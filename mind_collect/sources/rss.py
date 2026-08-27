"""Jornalismo e checagem ao vivo, por RSS.

Cobre a janela de 2026 — o que o Common Crawl ainda não indexou. O histórico
vem de Common Crawl e Media Cloud, não daqui.

Feeds conferidos em 24/08/2026; o rendimento de cada um está em COLETA.md.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC
from html.parser import HTMLParser

import feedparser
import trafilatura

from ..http import Bloqueado, Cliente
from ..schema import Documento, eleicao_de


@dataclass(frozen=True)
class Feed:
    chave: str
    url: str
    fonte: str = "noticia"
    # Perfil editorial, descritivo e não ideológico: serve para comparar
    # prevalência de técnica entre tipos de veículo. Corpus só de imprensa de
    # referência enviesa o modelo para texto neutro, e é na imprensa partidária
    # e popular que a técnica de manipulação se concentra.
    perfil: str = "referencia"   # referencia | partidario | popular | institucional
    # As agências de checagem restringem uso para treino: a Lupa publica
    # Content-Signal ai-train=no e o Aos Fatos bloqueia bots de IA. Entram como
    # avaliação e referência. O campo garante que o treino nunca as veja.
    licenca: str = "livre"


FEEDS: list[Feed] = [
    Feed("g1-politica",   "https://g1.globo.com/rss/g1/politica/"),
    Feed("g1-brasil",     "https://g1.globo.com/rss/g1/brasil/"),
    Feed("oglobo-politica", "https://oglobo.globo.com/rss/oglobo/politica/"),
    Feed("gazeta-republica", "https://www.gazetadopovo.com.br/feed/rss/republica.xml"),
    Feed("metropoles",    "https://www.metropoles.com/feed"),
    Feed("senado",        "https://www12.senado.leg.br/noticias/rss"),
    Feed("poder360",      "https://www.poder360.com.br/feed/"),
    Feed("ebc-politica",  "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"),
    Feed("ebc-geral",     "https://agenciabrasil.ebc.com.br/rss/geral/feed.xml"),
    # Paywall: o trafilatura extrai só a chamada. Mediana de 280 caracteres
    # contra 2 a 4 mil dos outros. Serve como índice de pauta, não como texto —
    # o corpo tem que vir de Common Crawl.
    Feed("folha-poder",   "https://feeds.folha.uol.com.br/poder/rss091.xml"),
    Feed("estadao-politica",
         "https://www.estadao.com.br/arc/outboundfeeds/feeds/rss/sections/politica/"),
    Feed("cnnbrasil", "https://www.cnnbrasil.com.br/feed/"),

    # Imprensa partidária, dos dois lados. É onde a técnica se concentra.
    Feed("brasil247",   "https://www.brasil247.com/feed", perfil="partidario"),
    Feed("dcm",         "https://www.diariodocentrodomundo.com.br/feed/", perfil="partidario"),
    Feed("forum",       "https://revistaforum.com.br/feed", perfil="partidario"),
    Feed("oeste",       "https://revistaoeste.com/feed/", perfil="partidario"),
    Feed("plenonews",   "https://pleno.news/feed", perfil="partidario"),
    Feed("conexaopol",  "https://www.conexaopolitica.com.br/feed/", perfil="partidario"),
    Feed("jovempan",    "https://jovempan.com.br/feed", perfil="partidario"),

    # Popular e agregador: volume alto, título chamativo.
    Feed("noticiasaominuto", "https://www.noticiasaominuto.com.br/rss/ultima-hora",
         perfil="popular"),

    # Checagem — só referência, nunca treino
    Feed("lupa", "https://www.agencialupa.org/feed/",
         "checagem", "referencia", "referencia"),
    Feed("comprova", "https://projetocomprova.com.br/feed/",
         "checagem", "referencia", "referencia"),
    Feed("boatos", "https://www.boatos.org/feed",
         "checagem", "referencia", "referencia"),
    Feed("efarsas", "https://www.e-farsas.com/feed",
         "checagem", "referencia", "referencia"),
]

POR_CHAVE = {f.chave: f for f in FEEDS}

# Piso de conteúdo. O feed do Comprova, por exemplo, ainda serve "Hello world!"
# e lorem ipsum de 2019 junto com as checagens reais.
MINIMO_CHARS = 200


def _publicado(entrada) -> str | None:
    t = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if not t:
        return None
    from datetime import datetime
    return datetime(*t[:6], tzinfo=UTC).isoformat(timespec="seconds")


class _Despir(HTMLParser):
    """Tira tags de fragmento de feed.

    O trafilatura não serve aqui: `extract` e `html2txt` devolvem vazio para
    fragmento solto, e `sanitize` só normaliza espaço em branco.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pedacos: list[str] = []

    def handle_data(self, d: str) -> None:
        self.pedacos.append(d)

    def handle_starttag(self, tag: str, attrs) -> None:
        self.pedacos.append(" ")   # senão blocos adjacentes colam: "fim.Começo"

    def handle_endtag(self, tag: str) -> None:
        self.pedacos.append(" ")

    def texto(self) -> str:
        return re.sub(r"\s+", " ", "".join(self.pedacos)).strip()


def _sem_html(fragmento: str) -> str:
    p = _Despir()
    p.feed(fragmento)
    p.close()
    return p.texto()


def _do_feed(entrada) -> str:
    """O melhor texto que o próprio feed entrega, sem custo de rede.

    Vários feeds trazem `content` bem mais completo que `summary` — o Poder360 e
    o Metrópoles dão 56 a 140 caracteres em summary e o corpo em content.
    """
    bruto = ""
    if c := entrada.get("content"):
        bruto = max((i.get("value", "") for i in c), key=len, default="")
    return _sem_html(bruto or entrada.get("summary", ""))


def _texto_completo(cliente: Cliente, url: str) -> str:
    """Corpo da matéria sem boilerplate. Falha em silêncio: o resumo do feed
    já é conteúdo utilizável, e uma matéria a menos não trava a coleta."""
    try:
        r = cliente.buscar(url, condicional=False)
    except Exception:
        return ""
    if not r.ok:
        return ""
    return trafilatura.extract(r.texto, include_comments=False, favor_precision=True) or ""


def coletar(cliente: Cliente, feed: Feed, completo: bool = True,
            descartados: list | None = None) -> Iterator[Documento]:
    try:
        r = cliente.buscar(feed.url)
    except Bloqueado:
        return
    if r.inalterado or not r.ok:
        return

    # feedparser resolve sozinho RSS 0.91 em ISO-8859-1, que é o caso da Folha.
    d = feedparser.parse(r.conteudo)
    for e in d.entries:
        url = e.get("link")
        if not url:
            continue
        resumo = _do_feed(e)
        texto = _texto_completo(cliente, url) if completo else ""
        # O texto extraído da matéria ganha sempre que existir: o do feed é
        # truncado ou vem com marcação. Só se não houver, cai para o do feed.
        corpo = texto or resumo
        if len(corpo) < MINIMO_CHARS:
            # Nunca descartar em silêncio: buraco invisível é pior que coleta
            # interrompida. O runner reporta a contagem.
            if descartados is not None:
                descartados.append((url, len(corpo)))
            continue
        yield Documento(
            fonte=feed.fonte,
            url=url,
            titulo=e.get("title", "").strip(),
            texto=corpo,
            canal="web",
            modalidade="texto",
            veiculado_em=(pub := _publicado(e)),
            eleicao=eleicao_de(pub),
            licenca_uso=feed.licenca,
            metadados={"feed": feed.chave, "perfil": feed.perfil, "resumo": resumo},
        )
