"""Sitemap — o arquivo de 2026 que o RSS não alcança.

O RSS de portal entrega só os itens mais recentes: cem no melhor caso, dez no
comum. O Common Crawl tem profundidade histórica mas ainda não indexou o que
saiu esta semana. O sitemap fecha o vão — é a lista que o próprio veículo
publica de tudo que ele quer que seja indexado.

Passa pelo Cliente, então robots.txt e Crawl-delay valem aqui como em todo o
resto.
"""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import trafilatura

from ..http import Bloqueado, Cliente
from ..schema import Documento, eleicao_de

NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
MINIMO_CHARS = 400

# Mesmo filtro do Common Crawl: sitemap de portal lista galeria, tag e vídeo
# junto com matéria.
LIXO = re.compile(
    r"/(foto|fotos|galeria|video|videos|tag|tags|busca|search|autor|author)/|"
    r"\.(jpg|jpeg|png|gif|mp4|pdf)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Mapa:
    chave: str
    url: str
    fonte: str = "noticia"
    licenca: str = "livre"
    padrao: str | None = None   # regex que a URL da matéria precisa casar


MAPAS: list[Mapa] = [
    Mapa("sm-g1", "https://g1.globo.com/sitemap/g1/sitemap.xml",
         padrao=r"/politica/|/eleicoes/"),
    Mapa("sm-poder360", "https://www.poder360.com.br/sitemap_index.xml",
         padrao=r"/eleicoes|/poder"),
    Mapa("sm-lupa",
         "https://www.agencialupa.org/wp-content/sitemaps/posts/post-sitemap-index.xml",
         "checagem", "referencia"),
]

POR_CHAVE = {m.chave: m for m in MAPAS}


def _xml(cliente: Cliente, url: str) -> ET.Element | None:
    try:
        r = cliente.buscar(url, condicional=False)
    except (Bloqueado, Exception):
        return None
    if not r.ok:
        return None
    dados = r.conteudo
    if url.endswith(".gz") or dados[:2] == b"\x1f\x8b":
        try:
            dados = gzip.decompress(dados)
        except OSError:
            return None
    try:
        return ET.fromstring(dados)
    except ET.ParseError:
        return None


def urls(cliente: Cliente, raiz: str, limite: int = 2000,
         profundidade: int = 2) -> Iterator[str]:
    """Percorre índice de sitemap até as URLs finais."""
    raiz_xml = _xml(cliente, raiz)
    if raiz_xml is None:
        return
    filhos = [e.text for e in raiz_xml.findall(".//s:sitemap/s:loc", NS) if e.text]
    if filhos and profundidade > 0:
        vistos = 0
        for filho in filhos:
            for u in urls(cliente, filho, limite - vistos, profundidade - 1):
                yield u
                vistos += 1
                if vistos >= limite:
                    return
        return
    n = 0
    for e in raiz_xml.findall(".//s:url/s:loc", NS):
        if e.text:
            yield e.text
            n += 1
            if n >= limite:
                return


def coletar(cliente: Cliente, mapa: Mapa, limite: int = 500) -> Iterator[Documento]:
    padrao = re.compile(mapa.padrao) if mapa.padrao else None
    n = 0
    for url in urls(cliente, mapa.url, limite=limite * 4):
        if n >= limite:
            return
        if LIXO.search(url) or (padrao and not padrao.search(url)):
            continue
        try:
            r = cliente.buscar(url, condicional=False)
        except (Bloqueado, Exception):
            continue
        if not r.ok:
            continue
        texto = trafilatura.extract(r.texto, include_comments=False, favor_precision=True)
        if not texto or len(texto) < MINIMO_CHARS:
            continue
        meta = trafilatura.extract_metadata(r.texto)
        data = getattr(meta, "date", None)
        n += 1
        yield Documento(
            fonte=mapa.fonte,
            url=url,
            titulo=(getattr(meta, "title", "") or "").strip(),
            texto=texto,
            canal="web",
            modalidade="texto",
            eleicao=eleicao_de(data),
            veiculado_em=data,
            licenca_uso=mapa.licenca,
            metadados={"mapa": mapa.chave},
        )
