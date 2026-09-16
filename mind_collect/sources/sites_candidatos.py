"""Sites de campanha declarados por candidaturas ao TSE."""

from __future__ import annotations

import html
import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

from ..http import Bloqueado, Cliente
from ..schema import Documento

RELEVANTE = re.compile(
    r"\b(propost|plano|programa|noticia|agenda|biografia|sobre|ideia|compromisso|"
    r"governo|campanha|elei[cç]|artigo|imprensa)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Alvo:
    url: str
    candidato_id: str
    candidato: str
    partido: str
    cargo: str


class _Pagina(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self._titulo = False
        self._pedacos_titulo: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        atributos = dict(attrs)
        if tag == "a" and (href := atributos.get("href")):
            self.links.append(href)
        if tag == "title":
            self._titulo = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._titulo = False

    def handle_data(self, data: str) -> None:
        if self._titulo:
            self._pedacos_titulo.append(data)

    @property
    def titulo(self) -> str:
        return " ".join("".join(self._pedacos_titulo).split())


def _pagina(html_bruto: str, base: str) -> tuple[str, list[str]]:
    parser = _Pagina()
    parser.feed(html_bruto)
    parser.close()
    links = sorted(
        {
            urljoin(base, href).split("#", 1)[0]
            for href in parser.links
            if href and not href.startswith(("mailto:", "tel:", "javascript:"))
        }
    )
    return html.unescape(parser.titulo), links


def coletar(
    cliente: Cliente,
    alvos: list[Alvo],
    ja_tem,
    paginas_por_site: int = 5,
) -> Iterator[Documento]:
    for alvo in alvos:
        host = urlsplit(alvo.url).netloc.lower()
        fila = deque([alvo.url])
        enfileiradas = {alvo.url}
        visitadas = 0
        while fila and visitadas < paginas_por_site:
            url = fila.popleft()
            if ja_tem(url):
                continue
            visitadas += 1
            try:
                resposta = cliente.buscar(url, condicional=False)
            except (Bloqueado, OSError, httpx.HTTPError):
                continue
            if not resposta.ok or not resposta.texto:
                continue
            titulo, links = _pagina(resposta.texto, resposta.url)
            texto = (
                trafilatura.extract(resposta.texto, include_comments=False, favor_precision=True)
                or ""
            )
            if len(texto) >= 100:
                yield Documento(
                    fonte="site_candidato",
                    url=resposta.url,
                    titulo=titulo,
                    texto=texto,
                    canal="web",
                    modalidade="texto",
                    eleicao="2026",
                    patrocinador=alvo.candidato,
                    candidato_id=alvo.candidato_id,
                    partido=alvo.partido,
                    cargo=alvo.cargo,
                    licenca_uso="referencia",
                    metadados={
                        "origem": "site_declarado_ao_tse",
                        "site_raiz": alvo.url,
                        "links": links[:200],
                    },
                )
            internos = [
                link
                for link in links
                if urlsplit(link).netloc.lower() == host
                and RELEVANTE.search(urlsplit(link).path)
                and link not in enfileiradas
            ]
            for link in internos[:paginas_por_site]:
                enfileiradas.add(link)
                fila.append(link)
