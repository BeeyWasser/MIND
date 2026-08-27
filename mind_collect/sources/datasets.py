"""Corpora já publicados por outros pesquisadores.

É a única rota viável para X/Twitter, cuja API hoje é cara e limitada — mas quem
coletou em 2022, quando ela era aberta, publicou. Dado já extraído legalmente e
publicado para reúso é melhor que dado raspado: vem citável, com artigo
descrevendo a metodologia de coleta, e sobrevive a qualquer questionamento de
procedência.

Cuidado com dataset de reidratação: por exigência de termos de uso, muitos
publicam só os IDs das mensagens, e o texto precisa ser buscado na plataforma
depois — o que reintroduz a dependência de credencial.
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..schema import Documento, anonimizar, eleicao_de

DIR = Path("data/eleicoes2026/_datasets")
ZENODO = "https://zenodo.org/api/records/{rec}/files/{arq}/content"
SAL = os.environ.get("MIND_SALT", "mind-dev")   # ver .env.exemplo


@dataclass(frozen=True)
class Fonte:
    chave: str
    registro: str          # id do registro no Zenodo
    arquivo: str
    licenca_dado: str      # licença declarada pelo autor
    eleicao: str
    canal: str
    reidratacao: bool = False   # traz só IDs, precisa buscar o texto depois
    doi: str = ""


FONTES: list[Fonte] = [
    # Conferido em 25/08/2026: as colunas são conversation_id,
    # Created_at_convert, author_id e referenced_tweets. Não há texto — é
    # reidratação, e reidratar exige a API do X, que hoje é paga e limitada.
    # Os 201 MB são identificador e timestamp.
    Fonte("tweets-eleicoes-2022", "11206577", "tweets_eleicoes_2022.zip",
          "cc-by-4.0", "2022", "twitter", reidratacao=True,
          doi="10.5281/zenodo.11206577"),
    Fonte("telegram-bolsonarista-2022", "10287589", "id_chats_agosto_telegram.csv",
          "cc-by-4.0", "2022", "telegram", reidratacao=True,
          doi="10.5281/zenodo.10287589"),
]

POR_CHAVE = {f.chave: f for f in FONTES}


def baixar(fonte: Fonte, destino: Path = DIR) -> Path:
    """Baixa uma vez e reaproveita. Arquivo grande não se rebaixa à toa."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{fonte.chave}-{fonte.arquivo}"
    if caminho.exists() and caminho.stat().st_size > 0:
        return caminho
    url = ZENODO.format(rec=fonte.registro, arq=fonte.arquivo)
    with httpx.stream("GET", url, timeout=600, follow_redirects=True,
                      headers={"User-Agent": "MINDResearchBot/0.1"}) as r:
        r.raise_for_status()
        with open(caminho, "wb") as f:
            for pedaco in r.iter_bytes(1 << 20):
                f.write(pedaco)
    return caminho


def _linhas(caminho: Path) -> Iterator[dict]:
    """Lê CSV ou JSONL, solto ou dentro de zip."""
    if caminho.suffix == ".zip":
        with zipfile.ZipFile(caminho) as z:
            for nome in z.namelist():
                if nome.endswith("/"):
                    continue
                with z.open(nome) as f:
                    fluxo = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                    yield from _de_stream(fluxo, nome)
    else:
        with open(caminho, encoding="utf-8", errors="replace", newline="") as f:
            yield from _de_stream(f, caminho.name)


def _de_stream(f, nome: str) -> Iterator[dict]:
    if nome.endswith(".jsonl") or nome.endswith(".ndjson"):
        for linha in f:
            if linha.strip():
                try:
                    yield json.loads(linha)
                except json.JSONDecodeError:
                    continue
    elif nome.endswith(".csv"):
        amostra = f.read(8192)
        f.seek(0)
        try:
            sep = csv.Sniffer().sniff(amostra, delimiters=",;\t").delimiter
        except csv.Error:
            sep = ","
        yield from csv.DictReader(f, delimiter=sep)


# Nomes de campo variam por dataset; procura-se pelo mais provável.
CAMPOS_TEXTO = ("text", "texto", "content", "conteudo", "message", "mensagem", "tweet", "full_text")
CAMPOS_DATA = ("created_at", "date", "data", "datetime", "timestamp", "dt")
CAMPOS_AUTOR = ("user", "username", "author", "autor", "screen_name", "user_id", "from_id")


def _pega(linha: dict, chaves: tuple[str, ...]) -> str | None:
    for k in chaves:
        for real in (k, k.upper(), k.capitalize()):
            if v := linha.get(real):
                return str(v).strip()
    return None


def coletar(fonte: Fonte, limite: int | None = None) -> Iterator[Documento]:
    if fonte.reidratacao:
        # Sem texto no arquivo. Reidratar significa buscar cada mensagem na
        # plataforma de origem — o que reintroduz a dependência de credencial
        # que o dataset publicado deveria ter evitado.
        return
    caminho = baixar(fonte)
    n = 0
    for linha in _linhas(caminho):
        texto = _pega(linha, CAMPOS_TEXTO)
        if not texto or len(texto) < 40:
            continue
        data = _pega(linha, CAMPOS_DATA)
        autor = _pega(linha, CAMPOS_AUTOR)
        n += 1
        if limite and n > limite:
            return
        yield Documento(
            fonte="noticia" if fonte.canal == "web" else "telegram"
            if fonte.canal == "telegram" else "reddit",
            url=f"https://doi.org/{fonte.doi}#{n}",
            texto=texto,
            canal=fonte.canal,
            modalidade="texto",
            eleicao=eleicao_de(data) or fonte.eleicao,
            veiculado_em=data,
            # Opinião política é dado sensível pela LGPD: o identificador do
            # autor nunca entra em claro.
            autor_hash=anonimizar(autor, SAL) if autor else None,
            metadados={"dataset": fonte.chave, "doi": fonte.doi,
                       "licenca_dado": fonte.licenca_dado},
        )
