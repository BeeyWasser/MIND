"""Common Crawl e Wayback — domínio inteiro sem tocar no servidor do veículo.

A rota de maior rendimento do plano. `cdx_toolkit --cc` extrai anos de conteúdo
de um portal sem emitir um único pedido para ele, o que resolve de uma vez rate
limit, anti-bot, Cloudflare e paginação. E se autopolicia: o Common Crawl
respeita robots.txt na coleta, então o que está no índice é o que o site liberou.

O mesmo módulo serve o Wayback (`fonte="ia"`), que é como se recupera conteúdo
que saiu do ar — o material das decisões de remoção do TSE.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import cdx_toolkit
import trafilatura

from ..schema import Documento, eleicao_de

# O índice traz galeria de foto, tag, busca e paginação junto com matéria. Sem
# filtro, metade do que se baixa não é texto.
LIXO = re.compile(
    r"/(foto|fotos|galeria|video|videos|tag|tags|busca|search|page/\d+|feed|rss|amp)/|"
    r"\.(jpg|jpeg|png|gif|mp4|pdf|xml)$",
    re.IGNORECASE,
)

MINIMO_CHARS = 400

# O Common Crawl tem 127 índices mensais desde 2008. O cdx_toolkit só varre a
# janela pedida: sem `from_ts` ele usa um padrão estreito, e a coleta raspa uma
# fração do arquivo. Com 2018 entram 84 índices — cobre as eleições de 2018,
# 2020, 2022, 2024 e 2026.
DESDE_PADRAO = "201801"


@dataclass(frozen=True)
class Alvo:
    chave: str
    padrao: str          # ex.: "g1.globo.com/politica/*"
    fonte: str = "noticia"
    licenca: str = "livre"
    eleicao: str | None = None


ALVOS: list[Alvo] = [
    # Jornalismo
    Alvo("cc-g1-politica",     "g1.globo.com/politica/*"),
    Alvo("cc-oglobo",          "oglobo.globo.com/politica/*"),
    Alvo("cc-poder360",        "poder360.com.br/eleicoes/*"),
    Alvo("cc-ebc-politica",    "agenciabrasil.ebc.com.br/politica/*"),
    Alvo("cc-folha-poder",     "www1.folha.uol.com.br/poder/*"),
    Alvo("cc-estadao",         "www.estadao.com.br/politica/*"),
    Alvo("cc-uol-eleicoes",    "noticias.uol.com.br/eleicoes/*"),
    Alvo("cc-cnnbrasil",       "www.cnnbrasil.com.br/politica/*"),
    Alvo("cc-metropoles",      "www.metropoles.com/brasil/politica/*"),
    Alvo("cc-correio",         "www.correiobraziliense.com.br/politica/*"),
    Alvo("cc-gazeta",          "www.gazetadopovo.com.br/republica/*"),
    Alvo("cc-cartacapital",    "www.cartacapital.com.br/politica/*"),
    Alvo("cc-veja",            "veja.abril.com.br/politica/*"),
    Alvo("cc-r7",              "noticias.r7.com/brasilia/*"),
    Alvo("cc-congressoemfoco", "congressoemfoco.uol.com.br/*"),
    Alvo("cc-jota",            "www.jota.info/*"),
    Alvo("cc-brasildefato",    "www.brasildefato.com.br/*"),
    Alvo("cc-camara-noticias", "www.camara.leg.br/noticias/*"),
    Alvo("cc-senado-noticias", "www12.senado.leg.br/noticias/*"),
    Alvo("cc-tse-noticias",    "www.tse.jus.br/comunicacao/noticias/*"),

    # Checagem — só referência, nunca treino
    Alvo("cc-aosfatos",  "www.aosfatos.org/noticias/*",        "checagem", "referencia"),
    Alvo("cc-lupa",      "www.agencialupa.org/*",              "checagem", "referencia"),
    Alvo("cc-comprova",  "projetocomprova.com.br/publicacoes/*", "checagem", "referencia"),
    Alvo("cc-boatos",    "www.boatos.org/*",                   "checagem", "referencia"),
    Alvo("cc-efarsas",   "www.e-farsas.com/*",                 "checagem", "referencia"),
]

POR_CHAVE = {a.chave: a for a in ALVOS}

# Wayback: recupera o que saiu do ar. É a única rota para conteúdo removido —
# peça de propaganda apagada, matéria despublicada, decisão de remoção do TSE
# cumprida. O mesmo coletor serve, trocando origem="cc" por "ia".
ALVOS_WAYBACK: list[Alvo] = [
    Alvo("wb-g1-politica",  "g1.globo.com/politica/*"),
    Alvo("wb-poder360",     "poder360.com.br/eleicoes/*"),
    Alvo("wb-estadao",      "www.estadao.com.br/politica/*"),
    Alvo("wb-uol-eleicoes", "noticias.uol.com.br/eleicoes/*"),
    Alvo("wb-oeste",        "revistaoeste.com/*"),
    Alvo("wb-brasil247",    "www.brasil247.com/*"),
    Alvo("wb-aosfatos", "www.aosfatos.org/noticias/*", "checagem", "referencia"),
    Alvo("wb-lupa",     "www.agencialupa.org/*",       "checagem", "referencia"),
]

POR_CHAVE_WAYBACK = {a.chave: a for a in ALVOS_WAYBACK}


def util(url: str) -> bool:
    return not LIXO.search(url)


def coletar(alvo: Alvo, de: str | None = None, ate: str | None = None,
            limite: int = 500, origem: str = "cc") -> Iterator[Documento]:
    """Varre o índice e extrai o texto de cada captura útil.

    `de` e `ate` no formato AAAAMM. `origem` é "cc" para Common Crawl ou "ia"
    para o Wayback.
    """
    cdx = cdx_toolkit.CDXFetcher(source=origem)
    opcoes: dict = {"limit": limite, "from_ts": de or DESDE_PADRAO}
    if ate:
        opcoes["to"] = ate

    for obj in cdx.iter(alvo.padrao, **opcoes):
        url = obj.get("url", "")
        if obj.get("status") != "200" or not util(url):
            continue
        if "html" not in (obj.get("mime-detected") or obj.get("mime") or ""):
            continue
        try:
            html = obj.content
        except Exception:
            continue
        if not html:
            continue
        if isinstance(html, bytes):
            html = html.decode("utf-8", "replace")
        texto = trafilatura.extract(html, include_comments=False, favor_precision=True)
        if not texto or len(texto) < MINIMO_CHARS:
            continue
        meta = trafilatura.extract_metadata(html)
        data = getattr(meta, "date", None)
        ts = obj.get("timestamp", "")
        yield Documento(
            fonte=alvo.fonte,
            url=url,
            titulo=(getattr(meta, "title", "") or "").strip(),
            texto=texto,
            canal="web",
            modalidade="texto",
            eleicao=alvo.eleicao or eleicao_de(data),
            veiculado_em=data,
            licenca_uso=alvo.licenca,
            url_arquivada=f"https://web.archive.org/web/{ts}/{url}" if origem == "ia" else None,
            metadados={
                "alvo": alvo.chave,
                "origem": origem,
                "captura": ts,
                "digest": obj.get("digest"),
            },
        )
