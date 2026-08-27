"""Descoberta de conteúdo social a partir do que já foi coletado.

Para TikTok e Instagram não há rota oficial de volume, e o gargalo não é buscar
— é descobrir quais URLs existem. Essa superfície de descoberta é justamente a
que as plataformas mais defendem: rastrear hashtag ou "para você" é bater de
frente com a única coisa protegida de verdade.

A saída é inverter. O corpus já contém cinco índices de conteúdo social:
checagem citando a peça que desmentiu, decisão do TSE apontando o que mandou
remover, Reddit e Telegram encaminhando link, e notícia embutindo post.

Efeito colateral, que precisa ir para as limitações do artigo: a amostra fica
enviesada para conteúdo que circulou o bastante para ser citado, checado,
processado ou compartilhado. Para este objeto o viés é na direção certa —
propaganda que ninguém viu não manipulou ninguém.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator

from ..schema import Documento

PADROES = {
    "tiktok": re.compile(
        r"https?://(?:www\.|vm\.|m\.)?tiktok\.com/[^\s\"'<>)\]]+", re.IGNORECASE),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+", re.IGNORECASE),
    "youtube": re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{11}",
        re.IGNORECASE),
    "facebook": re.compile(
        r"https?://(?:www\.|m\.)?facebook\.com/[^\s\"'<>)\]]*/(?:posts|videos|reel)/[^\s\"'<>)\]]+",
        re.IGNORECASE),
    "telegram": re.compile(r"https?://t\.me/[A-Za-z0-9_]+/\d+", re.IGNORECASE),
}

# Corta rastreamento e âncora: a mesma peça linkada de dois lugares vira duas
# URLs diferentes e a deduplicação por URL não pega.
SUJEIRA = re.compile(
    r"[?&](utm_[^=]+|fbclid|gclid|igshid|si|_r|is_from_webapp|sender_device)=[^&]*")


def limpar(url: str) -> str:
    url = SUJEIRA.sub("", url).rstrip(".,;:)]\"'")
    return url.split("#")[0].rstrip("?&")


def extrair(texto: str, plataformas: Iterable[str] | None = None) -> dict[str, set[str]]:
    alvos = plataformas or PADROES.keys()
    achados: dict[str, set[str]] = {}
    for plat in alvos:
        if urls := {limpar(u) for u in PADROES[plat].findall(texto)}:
            achados[plat] = urls
    return achados


def varrer(documentos: Iterator[Documento],
           plataformas: Iterable[str] | None = None) -> dict[str, Counter]:
    """Percorre o corpus e conta quantas vezes cada URL social foi citada.

    A contagem importa: URL citada por várias fontes independentes circulou mais,
    e é por onde começar quando não dá para buscar tudo.
    """
    saida: dict[str, Counter] = {}
    for doc in documentos:
        corpo = "\n".join([doc.texto, doc.titulo, str(doc.metadados.get("resumo", ""))])
        for plat, urls in extrair(corpo, plataformas).items():
            saida.setdefault(plat, Counter()).update(urls)
    return saida
