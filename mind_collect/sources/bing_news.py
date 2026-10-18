"""Descoberta transversal de notícias eleitorais pelo RSS público do Bing."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit

import feedparser
import httpx
import trafilatura

from ..http import Bloqueado, Cliente
from ..schema import Documento, eleicao_de
from .rss import MINIMO_CHARS, _sem_html

TERMOS = (
    "eleições 2026 Brasil",
    "propaganda eleitoral 2026",
    "campanha presidencial 2026",
    "vídeo candidato eleições 2026",
    "anúncio político eleições 2026",
    "desinformação eleições 2026",
    "TSE propaganda internet 2026",
    "horário eleitoral gratuito 2026",
)


def url_original(url_bing: str) -> str | None:
    valores = parse_qs(urlsplit(url_bing).query).get("url") or []
    return valores[0] if valores else None


def _publicado(entrada) -> str | None:
    valor = entrada.get("published_parsed")
    return datetime(*valor[:6], tzinfo=UTC).isoformat(timespec="seconds") if valor else None


def coletar(cliente: Cliente, termos: tuple[str, ...] = TERMOS, ja_tem=None) -> Iterator[Documento]:
    vistos: set[str] = set()
    for termo in termos:
        consulta = urlencode({"q": termo, "format": "RSS", "setlang": "pt-br"})
        try:
            resposta = cliente.buscar(f"https://www.bing.com/news/search?{consulta}")
        except (Bloqueado, httpx.HTTPError):
            return
        if resposta.inalterado or not resposta.ok:
            continue
        feed = feedparser.parse(resposta.conteudo)
        for entrada in feed.entries:
            url = url_original(entrada.get("link", ""))
            if not url or url in vistos or (ja_tem and ja_tem(url)):
                continue
            vistos.add(url)
            resumo = _sem_html(entrada.get("summary", ""))
            corpo = ""
            try:
                pagina = cliente.buscar(url, condicional=False)
                if pagina.ok:
                    corpo = (
                        trafilatura.extract(
                            pagina.texto, include_comments=False, favor_precision=True
                        )
                        or ""
                    )
            except (Bloqueado, OSError, httpx.HTTPError):
                pass
            texto = corpo or resumo
            if len(texto) < MINIMO_CHARS:
                continue
            publicado = _publicado(entrada)
            yield Documento(
                fonte="noticia",
                url=url,
                titulo=entrada.get("title", "").strip(),
                texto=texto,
                canal="web",
                modalidade="texto",
                veiculado_em=publicado,
                eleicao=eleicao_de(publicado),
                metadados={
                    "descoberta": "bing_news_rss",
                    "consulta": termo,
                    "veiculo": entrada.get("news_source"),
                    "imagem": entrada.get("news_image"),
                    "resumo": resumo,
                },
            )
