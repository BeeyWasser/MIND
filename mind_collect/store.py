"""Onde o corpus fica.

SQLite guarda estado, deduplicação e cobertura. O conteúdo vai para JSONL
comprimido, particionado por fonte e dia. Nada disso entra no git: `/data/*`
já está no .gitignore.

Parquet entra quando o volume justificar — o DuckDB lê JSONL direto, então a
troca não muda quem consulta. Ver COLETA.md.
"""

from __future__ import annotations

import gzip
import os
import sqlite3
import threading
import zlib
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

from .schema import Documento, Midia

RAIZ = Path("data/eleicoes2026")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS documentos (
    doc_id       TEXT PRIMARY KEY,
    fonte        TEXT NOT NULL,
    url          TEXT NOT NULL,
    modalidade   TEXT NOT NULL,
    eleicao      TEXT,
    licenca_uso  TEXT NOT NULL,
    coletado_em  TEXT NOT NULL,
    veiculado_em TEXT,
    arquivo      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_doc_fonte ON documentos(fonte, coletado_em);
CREATE INDEX IF NOT EXISTS ix_doc_url   ON documentos(url);

CREATE TABLE IF NOT EXISTS midias (
    midia_id   TEXT PRIMARY KEY,
    doc_id     TEXT NOT NULL,
    tipo       TEXT NOT NULL,
    url_origem TEXT NOT NULL,
    t_seg      REAL,
    phash      TEXT,
    dhash      TEXT,
    ocr_texto  TEXT,
    thumb_path TEXT
);
CREATE INDEX IF NOT EXISTS ix_midia_doc   ON midias(doc_id);
CREATE INDEX IF NOT EXISTS ix_midia_phash ON midias(phash);

-- Uma linha por execução de coletor. Buraco silencioso na série histórica é
-- pior que coleta interrompida, e é isso que permite enxergar.
CREATE TABLE IF NOT EXISTS execucoes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    fonte     TEXT NOT NULL,
    inicio    TEXT NOT NULL,
    fim       TEXT,
    novos     INTEGER DEFAULT 0,
    repetidos INTEGER DEFAULT 0,
    erros     INTEGER DEFAULT 0,
    detalhe   TEXT
);
CREATE INDEX IF NOT EXISTS ix_exec_fonte ON execucoes(fonte, inicio);
"""


def conectar(raiz: Path = RAIZ) -> sqlite3.Connection:
    raiz.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(raiz / "mind.db", timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(ESQUEMA)
    return con


class Store:
    def __init__(self, raiz: Path = RAIZ):
        self.raiz = raiz
        self.con = conectar(raiz)
        # O nome por PID separa processos, mas threads do mesmo processo
        # compartilham o arquivo — e gzip append concorrente corrompe igual.
        self._trava = threading.Lock()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def fechar(self) -> None:
        self.con.commit()
        self.con.close()

    # ---------- escrita ----------

    def caminho(self, fonte: str, dia: str | None = None) -> Path:
        """Um arquivo por fonte, por dia e **por processo**.

        Sem o PID, o ciclo do launchd, a varredura do Common Crawl e qualquer
        execução manual anexam ao mesmo .gz ao mesmo tempo. gzip em modo append
        com escritas intercaladas corrompe o arquivo do ponto da colisão em
        diante — e o estrago só aparece na leitura, muito depois.
        """
        dia = dia or date.today().isoformat()
        d = self.raiz / fonte
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{dia}-{os.getpid()}.jsonl.gz"

    def ja_tem(self, doc_id: str) -> bool:
        cur = self.con.execute("SELECT 1 FROM documentos WHERE doc_id = ?", (doc_id,))
        return cur.fetchone() is not None

    def guardar(self, doc: Documento) -> bool:
        """Grava. Devolve False se já existia — dedup por conteúdo, não por URL,
        porque portal republica a mesma matéria em URLs diferentes o tempo todo."""
        with self._trava:
            if self.ja_tem(doc.doc_id):
                return False
            arquivo = self.caminho(doc.fonte, doc.coletado_em[:10])
            with gzip.open(arquivo, "at", encoding="utf-8") as f:
                f.write(doc.to_json() + "\n")
            self.con.execute(
                "INSERT INTO documentos VALUES (?,?,?,?,?,?,?,?,?)",
                (doc.doc_id, doc.fonte, doc.url, doc.modalidade, doc.eleicao,
                 doc.licenca_uso, doc.coletado_em, doc.veiculado_em, str(arquivo)),
            )
            self.con.commit()
            return True

    def guardar_midia(self, m: Midia) -> None:
        with self._trava:
            self._guardar_midia(m)

    def _guardar_midia(self, m: Midia) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO midias VALUES (?,?,?,?,?,?,?,?,?)",
            (m.midia_id, m.doc_id, m.tipo, m.url_origem, m.t_seg,
             m.phash, m.dhash, m.ocr_texto, m.thumb_path),
        )
        self.con.commit()

    # ---------- leitura ----------

    def ler(self, fonte: str | None = None, treinavel: bool | None = None,
            estrito: bool = False) -> Iterator[Documento]:
        """Lê o corpus. Arquivo truncado devolve o que dá e segue.

        `estrito=True` propaga o erro, para o reparo saber onde parou.
        """
        padrao = f"{fonte}/*.jsonl.gz" if fonte else "*/*.jsonl.gz"
        for arq in sorted(self.raiz.glob(padrao)):
            try:
                with gzip.open(arq, "rt", encoding="utf-8") as f:
                    for linha in f:
                        if not linha.strip():
                            continue
                        # Por linha, não só por arquivo: uma linha malformada
                        # não pode derrubar a leitura das outras milhares.
                        try:
                            doc = Documento.from_json(linha)
                        except (ValueError, TypeError, KeyError):
                            if estrito:
                                raise
                            continue
                        if treinavel is not None and doc.treinavel != treinavel:
                            continue
                        yield doc
            # zlib.error não herda de OSError: sem ele, arquivo truncado
            # derruba a leitura inteira do corpus.
            except (OSError, EOFError, ValueError, zlib.error):
                if estrito:
                    raise

    def reparar(self) -> tuple[int, int]:
        """Reconstrói índice e arquivos a partir do que ainda é legível.

        Índice e conteúdo têm que concordar: doc_id no SQLite sem conteúdo
        legível faz a deduplicação pular a recoleta, e o documento some de vez.
        Devolve (documentos salvos, entradas de índice descartadas)."""
        salvos: dict[str, Documento] = {}
        for doc in self.ler():
            salvos[doc.doc_id] = doc

        for arq in self.raiz.glob("*/*.jsonl.gz"):
            arq.unlink()
        self.con.execute("DELETE FROM documentos")
        self.con.commit()

        antes = len(salvos)
        for doc in salvos.values():
            self.guardar(doc)
        return antes, 0

    def cobertura(self) -> list[tuple]:
        return self.con.execute("""
            SELECT fonte, modalidade, COUNT(*) n,
                   MIN(substr(coletado_em,1,10)) de,
                   MAX(substr(coletado_em,1,10)) ate
            FROM documentos GROUP BY fonte, modalidade ORDER BY n DESC
        """).fetchall()

    def buracos(self, fonte: str) -> list[str]:
        """Dias sem nenhum documento, entre a primeira e a última coleta."""
        linhas = self.con.execute(
            "SELECT DISTINCT substr(coletado_em,1,10) FROM documentos WHERE fonte = ? ORDER BY 1",
            (fonte,),
        ).fetchall()
        if len(linhas) < 2:
            return []
        dias = [date.fromisoformat(r[0]) for r in linhas]
        tudo = {dias[0] + timedelta(days=i) for i in range((dias[-1] - dias[0]).days + 1)}
        return sorted(d.isoformat() for d in tudo - set(dias))

    # ---------- execuções ----------

    def iniciar_execucao(self, fonte: str) -> int:
        from .schema import _agora
        with self._trava:
            cur = self.con.execute(
                "INSERT INTO execucoes (fonte, inicio) VALUES (?,?)", (fonte, _agora())
            )
            self.con.commit()
            return cur.lastrowid

    def encerrar_execucao(self, id_: int, novos: int, repetidos: int,
                          erros: int, detalhe: str = "") -> None:
        from .schema import _agora
        with self._trava:
            self._encerrar(id_, novos, repetidos, erros, detalhe, _agora())

    def _encerrar(self, id_, novos, repetidos, erros, detalhe, agora) -> None:
        self.con.execute(
            "UPDATE execucoes SET fim=?, novos=?, repetidos=?, erros=?, detalhe=? WHERE id=?",
            (agora, novos, repetidos, erros, detalhe, id_),
        )
        self.con.commit()
