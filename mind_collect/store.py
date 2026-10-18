"""Onde o corpus fica.

SQLite guarda estado, deduplicação e cobertura. O conteúdo vai para JSONL
comprimido, particionado por fonte e dia. Nada disso entra no git: `/data/*`
já está no .gitignore.

Parquet entra quando o volume justificar — o DuckDB lê JSONL direto, então a
troca não muda quem consulta. Ver COLETA.md.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import sqlite3
import threading
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .paths import CORPUS_ROOT, relative_to_corpus, resolve_corpus_reference
from .schema import Documento, Midia, Segmento

RAIZ = CORPUS_ROOT
SCHEMA_VERSION = 1

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
CREATE INDEX IF NOT EXISTS ix_doc_modalidade ON documentos(fonte, modalidade, coletado_em);

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

CREATE TABLE IF NOT EXISTS rotulos_externos (
    doc_id         TEXT PRIMARY KEY,
    rotulo         TEXT NOT NULL,
    fonte_rotulo   TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcricoes (
    doc_id         TEXT PRIMARY KEY,
    segmentos_json TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conteudos_enriquecidos (
    doc_id         TEXT PRIMARY KEY,
    titulo         TEXT NOT NULL,
    texto          TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cursores (
    fonte          TEXT PRIMARY KEY,
    valor          TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS falhas_coleta (
    fonte          TEXT NOT NULL,
    url            TEXT NOT NULL,
    tentativas     INTEGER NOT NULL,
    detalhe        TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL,
    PRIMARY KEY (fonte, url)
);

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

-- Fila operacional local. URLs de perfis podem identificar pessoas e ficam
-- apenas no SQLite ignorado pelo git; o corpus publicado continua anonimizado.
CREATE TABLE IF NOT EXISTS alvos_sociais (
    plataforma       TEXT NOT NULL,
    url              TEXT NOT NULL,
    tipo             TEXT NOT NULL,
    origem           TEXT NOT NULL,
    relevancia       INTEGER NOT NULL DEFAULT 1,
    primeira_vista   TEXT NOT NULL,
    ultima_vista     TEXT NOT NULL,
    ultima_tentativa TEXT,
    ultima_coleta    TEXT,
    tentativas       INTEGER NOT NULL DEFAULT 0,
    ultimo_erro      TEXT,
    ativo            INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (plataforma, url)
);
CREATE INDEX IF NOT EXISTS ix_alvo_social_fila
ON alvos_sociais(tipo, ativo, ultima_coleta, relevancia);

-- Uma etapa concluída pode não produzir linha em `midias` (vídeo sem texto na
-- tela, por exemplo). Sem este estado o worker baixaria o mesmo original para
-- sempre tentando encontrar um resultado que não existe.
CREATE TABLE IF NOT EXISTS processamentos_midia (
    doc_id        TEXT NOT NULL,
    etapa         TEXT NOT NULL,
    status        TEXT NOT NULL,
    tentativas    INTEGER NOT NULL DEFAULT 0,
    detalhe       TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL,
    PRIMARY KEY (doc_id, etapa)
);
CREATE INDEX IF NOT EXISTS ix_processamento_midia_status
ON processamentos_midia(etapa, status, tentativas, atualizado_em);

-- Snapshots locais de contas públicas observadas. O hash evita gravar a mesma
-- versão a cada ciclo, mas preserva mudanças de bio, verificação e métricas.
CREATE TABLE IF NOT EXISTS snapshots_perfis_sociais (
    plataforma   TEXT NOT NULL,
    url          TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    origem       TEXT NOT NULL,
    dados_json   TEXT NOT NULL,
    coletado_em  TEXT NOT NULL,
    PRIMARY KEY (plataforma, url, payload_hash)
);
CREATE INDEX IF NOT EXISTS ix_snapshot_perfil_url
ON snapshots_perfis_sociais(plataforma, url, coletado_em);
"""


@dataclass(frozen=True)
class AlvoSocial:
    plataforma: str
    url: str
    tipo: str
    origem: str
    relevancia: int
    ultima_coleta: str | None
    tentativas: int


def conectar(raiz: Path = RAIZ) -> sqlite3.Connection:
    raiz.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(raiz / "mind.db", timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    current_version = con.execute("PRAGMA user_version").fetchone()[0]
    if current_version > SCHEMA_VERSION:
        con.close()
        raise RuntimeError(
            f"schema do corpus é mais novo ({current_version}) que este código ({SCHEMA_VERSION})"
        )
    con.executescript(ESQUEMA)
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    con.commit()
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

    def tem_url(self, url: str) -> bool:
        cur = self.con.execute("SELECT 1 FROM documentos WHERE url = ? LIMIT 1", (url,))
        return cur.fetchone() is not None

    def guardar(self, doc: Documento) -> bool:
        """Grava. Devolve False se já existia — dedup por conteúdo, não por URL,
        porque portal republica a mesma matéria em URLs diferentes o tempo todo."""
        with self._trava:
            if doc.rotulo_externo and doc.fonte_rotulo:
                self._guardar_rotulo(
                    doc.doc_id, doc.rotulo_externo, doc.fonte_rotulo, doc.coletado_em
                )
            if self.ja_tem(doc.doc_id):
                self.con.commit()
                return False
            arquivo = self.caminho(doc.fonte, doc.coletado_em[:10])
            with gzip.open(arquivo, "at", encoding="utf-8") as f:
                f.write(doc.to_json() + "\n")
            self.con.execute(
                "INSERT INTO documentos VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    doc.doc_id,
                    doc.fonte,
                    doc.url,
                    doc.modalidade,
                    doc.eleicao,
                    doc.licenca_uso,
                    doc.coletado_em,
                    doc.veiculado_em,
                    relative_to_corpus(arquivo, self.raiz),
                ),
            )
            if doc.transcricao:
                self._guardar_transcricao(doc.doc_id, doc.transcricao, doc.coletado_em)
            self.con.commit()
            return True

    def guardar_rotulo(self, doc_id: str, rotulo: str, fonte_rotulo: str) -> None:
        from .schema import _agora

        with self._trava:
            self._guardar_rotulo(doc_id, rotulo, fonte_rotulo, _agora())
            self.con.commit()

    def _guardar_rotulo(self, doc_id: str, rotulo: str, fonte_rotulo: str, agora: str) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO rotulos_externos VALUES (?,?,?,?)",
            (doc_id, rotulo, fonte_rotulo, agora),
        )

    def remover_rotulo(self, doc_id: str) -> None:
        with self._trava:
            self.con.execute("DELETE FROM rotulos_externos WHERE doc_id = ?", (doc_id,))
            self.con.commit()

    def guardar_transcricao(self, doc_id: str, segmentos: list[Segmento]) -> None:
        from .schema import _agora

        with self._trava:
            self._guardar_transcricao(doc_id, segmentos, _agora())
            self.con.commit()

    def _guardar_transcricao(self, doc_id: str, segmentos: list[Segmento], agora: str) -> None:
        from dataclasses import asdict

        bruto = json.dumps([asdict(segmento) for segmento in segmentos], ensure_ascii=False)
        self.con.execute(
            "INSERT OR REPLACE INTO transcricoes VALUES (?,?,?)",
            (doc_id, bruto, agora),
        )

    def transcritos(self) -> set[str]:
        return {r[0] for r in self.con.execute("SELECT doc_id FROM transcricoes")}

    def guardar_conteudo(self, doc_id: str, titulo: str, texto: str) -> None:
        from .schema import _agora

        with self._trava:
            self.con.execute(
                "INSERT OR REPLACE INTO conteudos_enriquecidos VALUES (?,?,?,?)",
                (doc_id, titulo, texto, _agora()),
            )
            self.con.commit()

    def registrar_alvo_social(
        self,
        plataforma: str,
        url: str,
        tipo: str,
        origem: str,
        relevancia: int = 1,
    ) -> None:
        self.registrar_alvos_sociais([(plataforma, url, tipo, origem, relevancia)])

    def registrar_alvos_sociais(self, alvos: Iterable[tuple[str, str, str, str, int]]) -> int:
        from .schema import _agora

        agora = _agora()
        linhas = []
        for plataforma, url, tipo, origem, relevancia in alvos:
            if tipo not in {"perfil", "publicacao"}:
                raise ValueError(f"tipo de alvo social inválido: {tipo!r}")
            linhas.append((plataforma, url, tipo, origem, max(1, relevancia), agora, agora))
        if not linhas:
            return 0
        with self._trava:
            self.con.executemany(
                """
                INSERT INTO alvos_sociais (
                    plataforma, url, tipo, origem, relevancia,
                    primeira_vista, ultima_vista
                ) VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(plataforma,url) DO UPDATE SET
                    tipo=excluded.tipo,
                    origem=excluded.origem,
                    relevancia=MAX(alvos_sociais.relevancia, excluded.relevancia),
                    ultima_vista=excluded.ultima_vista,
                    ativo=1
                """,
                linhas,
            )
            self.con.commit()
        return len(linhas)

    def listar_alvos_sociais(
        self,
        tipo: str,
        plataformas: tuple[str, ...],
        limite: int,
    ) -> list[AlvoSocial]:
        if not plataformas or limite <= 0:
            return []
        marcadores = ",".join("?" for _ in plataformas)
        linhas = self.con.execute(
            f"""
            SELECT plataforma, url, tipo, origem, relevancia, ultima_coleta, tentativas
            FROM alvos_sociais
            WHERE tipo = ? AND ativo = 1
              AND plataforma IN ({marcadores})
              AND (tipo != 'publicacao' OR ultima_coleta IS NULL)
              AND (
                    tentativas < 3
                    OR julianday(ultima_tentativa) < julianday('now', '-7 days')
                  )
            ORDER BY
                CASE WHEN ultima_coleta IS NULL THEN 0 ELSE 1 END,
                relevancia DESC,
                COALESCE(ultima_coleta, primeira_vista) ASC
            LIMIT ?
            """,
            (tipo, *plataformas, limite),
        ).fetchall()
        return [AlvoSocial(*linha) for linha in linhas]

    def marcar_alvo_social(self, plataforma: str, url: str, erro: str | None = None) -> None:
        from .schema import _agora

        agora = _agora()
        with self._trava:
            if erro:
                self.con.execute(
                    """
                    UPDATE alvos_sociais SET
                        ultima_tentativa=?, tentativas=tentativas+1, ultimo_erro=?
                    WHERE plataforma=? AND url=?
                    """,
                    (agora, erro[:500], plataforma, url),
                )
            else:
                self.con.execute(
                    """
                    UPDATE alvos_sociais SET
                        ultima_tentativa=?, ultima_coleta=?, tentativas=0, ultimo_erro=NULL
                    WHERE plataforma=? AND url=?
                    """,
                    (agora, agora, plataforma, url),
                )
            self.con.commit()

    def alvos_sociais_por_plataforma(self) -> list[tuple[str, str, int]]:
        return self.con.execute(
            """
            SELECT plataforma, tipo, COUNT(*)
            FROM alvos_sociais WHERE ativo=1
            GROUP BY plataforma, tipo ORDER BY COUNT(*) DESC
            """
        ).fetchall()

    def registrar_snapshot_perfil(
        self,
        plataforma: str,
        url: str,
        dados: dict,
        origem: str,
    ) -> bool:
        from .schema import _agora

        limpos = {chave: valor for chave, valor in dados.items() if valor not in (None, "", [], {})}
        if not limpos:
            return False
        bruto = json.dumps(limpos, ensure_ascii=False, sort_keys=True, default=str)
        payload_hash = hashlib.sha256(bruto.encode()).hexdigest()
        with self._trava:
            cursor = self.con.execute(
                "INSERT OR IGNORE INTO snapshots_perfis_sociais VALUES (?,?,?,?,?,?)",
                (plataforma, url, payload_hash, origem, bruto, _agora()),
            )
            self.con.commit()
        return bool(cursor.rowcount)

    def marcar_processamento_midia(
        self, doc_id: str, etapa: str, concluido: bool, detalhe: str = ""
    ) -> None:
        from .schema import _agora

        agora = _agora()
        status = "concluido" if concluido else "erro"
        with self._trava:
            self.con.execute(
                """
                INSERT INTO processamentos_midia VALUES (?,?,?,?,?,?)
                ON CONFLICT(doc_id,etapa) DO UPDATE SET
                    status=excluded.status,
                    tentativas=CASE
                        WHEN excluded.status='concluido' THEN 0
                        ELSE processamentos_midia.tentativas+1
                    END,
                    detalhe=excluded.detalhe,
                    atualizado_em=excluded.atualizado_em
                """,
                (doc_id, etapa, status, 0 if concluido else 1, detalhe[:500], agora),
            )
            self.con.commit()

    def processados_midia(self, etapa: str) -> set[str]:
        return {
            linha[0]
            for linha in self.con.execute(
                "SELECT doc_id FROM processamentos_midia WHERE etapa=? AND status='concluido'",
                (etapa,),
            )
        }

    def bloqueados_midia(self, etapa: str, max_tentativas: int = 3, dias: int = 7) -> set[str]:
        return {
            linha[0]
            for linha in self.con.execute(
                """
                SELECT doc_id FROM processamentos_midia
                WHERE etapa=? AND status='erro' AND tentativas>=?
                  AND julianday(atualizado_em) >= julianday('now', ?)
                """,
                (etapa, max_tentativas, f"-{dias} days"),
            )
        }

    def cursor(self, fonte: str, padrao: int = 0) -> int:
        linha = self.con.execute("SELECT valor FROM cursores WHERE fonte = ?", (fonte,)).fetchone()
        try:
            return int(linha[0]) if linha else padrao
        except (TypeError, ValueError):
            return padrao

    def salvar_cursor(self, fonte: str, valor: int) -> None:
        from .schema import _agora

        with self._trava:
            self.con.execute(
                "INSERT OR REPLACE INTO cursores VALUES (?,?,?)",
                (fonte, str(valor), _agora()),
            )
            self.con.commit()

    def registrar_falha(self, fonte: str, url: str, detalhe: str) -> None:
        from .schema import _agora

        with self._trava:
            self.con.execute(
                """
                INSERT INTO falhas_coleta VALUES (?,?,1,?,?)
                ON CONFLICT(fonte,url) DO UPDATE SET
                    tentativas=tentativas+1,
                    detalhe=excluded.detalhe,
                    atualizado_em=excluded.atualizado_em
                """,
                (fonte, url, detalhe[:500], _agora()),
            )
            self.con.commit()

    def limpar_falha(self, fonte: str, url: str) -> None:
        with self._trava:
            self.con.execute("DELETE FROM falhas_coleta WHERE fonte = ? AND url = ?", (fonte, url))
            self.con.commit()

    def bloqueadas(self, fonte: str, max_tentativas: int = 3, dias: int = 7) -> set[str]:
        return {
            linha[0]
            for linha in self.con.execute(
                """
                SELECT url FROM falhas_coleta
                WHERE fonte = ? AND tentativas >= ?
                  AND julianday(atualizado_em) >= julianday('now', ?)
                """,
                (fonte, max_tentativas, f"-{dias} days"),
            )
        }

    def guardar_midia(self, m: Midia) -> None:
        with self._trava:
            self._guardar_midia(m)

    def _guardar_midia(self, m: Midia) -> None:
        url_origem = self._referencia_local_portavel(m.url_origem)
        thumb_path = self._referencia_local_portavel(m.thumb_path, strict=True)
        self.con.execute(
            "INSERT OR REPLACE INTO midias VALUES (?,?,?,?,?,?,?,?,?)",
            (
                m.midia_id,
                m.doc_id,
                m.tipo,
                url_origem,
                m.t_seg,
                m.phash,
                m.dhash,
                m.ocr_texto,
                thumb_path,
            ),
        )
        self.con.commit()

    def _referencia_local_portavel(self, value: str | None, strict: bool = False) -> str | None:
        if not value:
            return value
        if strict:
            resolved = resolve_corpus_reference(value, self.raiz)
            return relative_to_corpus(resolved, self.raiz)
        path = Path(value)
        if path.is_absolute():
            try:
                return relative_to_corpus(path, self.raiz)
            except ValueError:
                if strict:
                    raise
                return value
        if path.parts[:2] == ("data", "eleicoes2026"):
            return Path(*path.parts[2:]).as_posix()
        return value

    # ---------- leitura ----------

    def ler(
        self, fonte: str | None = None, treinavel: bool | None = None, estrito: bool = False
    ) -> Iterator[Documento]:
        """Lê o corpus. Arquivo truncado devolve o que dá e segue.

        `estrito=True` propaga o erro, para o reparo saber onde parou.
        """
        rotulos = {
            doc_id: (rotulo, origem)
            for doc_id, rotulo, origem in self.con.execute(
                "SELECT doc_id, rotulo, fonte_rotulo FROM rotulos_externos"
            )
        }
        transcricoes = {
            doc_id: bruto
            for doc_id, bruto in self.con.execute("SELECT doc_id, segmentos_json FROM transcricoes")
        }
        conteudos = {
            doc_id: (titulo, texto)
            for doc_id, titulo, texto in self.con.execute(
                "SELECT doc_id, titulo, texto FROM conteudos_enriquecidos"
            )
        }
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
                        doc_id = doc.doc_id
                        if rotulo := rotulos.get(doc_id):
                            doc.rotulo_externo, doc.fonte_rotulo = rotulo
                        if bruto := transcricoes.get(doc_id):
                            try:
                                doc.transcricao = [Segmento(**s) for s in json.loads(bruto)]
                            except (json.JSONDecodeError, TypeError, KeyError):
                                if estrito:
                                    raise
                        if conteudo := conteudos.get(doc_id):
                            doc.titulo, doc.texto = conteudo
                        if treinavel is not None and doc.treinavel != treinavel:
                            continue
                        yield doc
            # zlib.error não herda de OSError: sem ele, arquivo truncado
            # derruba a leitura inteira do corpus.
            except (OSError, EOFError, ValueError, zlib.error):
                if estrito:
                    raise

    def ler_ids(self, doc_ids: Iterable[str], estrito: bool = False) -> Iterator[Documento]:
        """Lê somente documentos escolhidos, abrindo cada gzip no máximo uma vez."""
        alvos = set(doc_ids)
        if not alvos:
            return
        marcadores = ",".join("?" for _ in alvos)
        parametros = tuple(alvos)
        por_arquivo: dict[Path, set[str]] = {}
        for doc_id, arquivo in self.con.execute(
            f"SELECT doc_id, arquivo FROM documentos WHERE doc_id IN ({marcadores})",
            parametros,
        ):
            caminho = resolve_corpus_reference(arquivo, self.raiz)
            por_arquivo.setdefault(caminho, set()).add(doc_id)

        rotulos = {
            doc_id: (rotulo, origem)
            for doc_id, rotulo, origem in self.con.execute(
                f"""
                SELECT doc_id, rotulo, fonte_rotulo FROM rotulos_externos
                WHERE doc_id IN ({marcadores})
                """,
                parametros,
            )
        }
        transcricoes = {
            doc_id: bruto
            for doc_id, bruto in self.con.execute(
                f"SELECT doc_id, segmentos_json FROM transcricoes WHERE doc_id IN ({marcadores})",
                parametros,
            )
        }
        conteudos = {
            doc_id: (titulo, texto)
            for doc_id, titulo, texto in self.con.execute(
                f"""
                SELECT doc_id, titulo, texto FROM conteudos_enriquecidos
                WHERE doc_id IN ({marcadores})
                """,
                parametros,
            )
        }
        for arquivo, ids_arquivo in por_arquivo.items():
            try:
                with gzip.open(arquivo, "rt", encoding="utf-8") as fluxo:
                    for linha in fluxo:
                        if not linha.strip():
                            continue
                        try:
                            doc = Documento.from_json(linha)
                        except (ValueError, TypeError, KeyError):
                            if estrito:
                                raise
                            continue
                        if doc.doc_id not in ids_arquivo:
                            continue
                        if rotulo := rotulos.get(doc.doc_id):
                            doc.rotulo_externo, doc.fonte_rotulo = rotulo
                        if bruto := transcricoes.get(doc.doc_id):
                            try:
                                doc.transcricao = [Segmento(**item) for item in json.loads(bruto)]
                            except (json.JSONDecodeError, TypeError, KeyError):
                                if estrito:
                                    raise
                        if conteudo := conteudos.get(doc.doc_id):
                            doc.titulo, doc.texto = conteudo
                        yield doc
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

    def encerrar_execucao(
        self, id_: int, novos: int, repetidos: int, erros: int, detalhe: str = ""
    ) -> None:
        from .schema import _agora

        with self._trava:
            self._encerrar(id_, novos, repetidos, erros, detalhe, _agora())

    def _encerrar(self, id_, novos, repetidos, erros, detalhe, agora) -> None:
        self.con.execute(
            "UPDATE execucoes SET fim=?, novos=?, repetidos=?, erros=?, detalhe=? WHERE id=?",
            (agora, novos, repetidos, erros, detalhe, id_),
        )
        self.con.commit()
