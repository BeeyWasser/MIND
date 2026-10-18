"""Descoberta de conteúdo social a partir do que já foi coletado.

Sem acesso institucional, o gargalo de TikTok e Instagram é descobrir quais
URLs públicas existem. A fila combina busca web autorizada, autores, links e
marcações entre contas sem depender de rastrear feeds personalizados.

A saída é inverter. O corpus já contém cinco índices de conteúdo social:
checagem citando a peça que desmentiu, decisão do TSE apontando o que mandou
remover, Reddit e Telegram encaminhando link, e notícia embutindo post.

Efeito colateral, que precisa ir para as limitações do artigo: a amostra fica
enviesada para conteúdo que circulou o bastante para ser citado, checado,
processado ou compartilhado. Para este objeto o viés é na direção certa —
propaganda que ninguém viu não manipulou ninguém.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from urllib.parse import unquote, urlsplit

from ..schema import Documento

PADROES = {
    "tiktok": re.compile(
        r"https?://(?:(?:www\.|m\.)?tiktok\.com/@[^/\s]+/video/\d+|"
        r"vm\.tiktok\.com/[A-Za-z0-9]+)[^\s\"'<>)\]]*",
        re.IGNORECASE,
    ),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/(?:p|reel|tv)/[A-Za-z0-9_-]+", re.IGNORECASE
    ),
    "youtube": re.compile(
        r"https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[A-Za-z0-9_-]{11}", re.IGNORECASE
    ),
    "facebook": re.compile(
        r"https?://(?:www\.|m\.)?facebook\.com/(?:reel/|[^\s\"'<>)\]]*/(?:posts|videos|reel)/)"
        r"[^\s\"'<>)\]]+",
        re.IGNORECASE,
    ),
    "x": re.compile(
        r"https?://(?:(?:www\.|mobile\.)?twitter\.com|(?:www\.)?x\.com)/"
        r"[A-Za-z0-9_]+/status/\d+[^\s\"'<>)\]]*",
        re.IGNORECASE,
    ),
    "telegram": re.compile(r"https?://t\.me/[A-Za-z0-9_]+/\d+", re.IGNORECASE),
    "bluesky": re.compile(
        r"https?://bsky\.app/profile/[A-Za-z0-9._:-]+/post/[A-Za-z0-9]+", re.IGNORECASE
    ),
    "kwai": re.compile(r"https?://(?:www\.)?kwai\.com/[^\s\"'<>)\]]+", re.IGNORECASE),
}

URL_SOCIAL = re.compile(
    r"https?://(?:www\.|m\.|mobile\.)?"
    r"(?:tiktok\.com|instagram\.com|youtube\.com|youtu\.be|facebook\.com|fb\.com|"
    r"twitter\.com|x\.com|t\.me|bsky\.app|kwai\.com)/[^\s\"'<>)\]]+",
    re.IGNORECASE,
)

RESERVADOS = {
    "about",
    "accounts",
    "ads",
    "business",
    "channel",
    "directory",
    "events",
    "explore",
    "groups",
    "hashtag",
    "home",
    "login",
    "p",
    "photo",
    "photos",
    "reel",
    "reels",
    "search",
    "share",
    "shorts",
    "stories",
    "tv",
    "video",
    "videos",
    "watch",
}

# Corta rastreamento e âncora: a mesma peça linkada de dois lugares vira duas
# URLs diferentes e a deduplicação por URL não pega.
SUJEIRA = re.compile(
    r"[?&](utm_[^=]+|fbclid|gclid|igshid|si|_r|is_from_webapp|sender_device)=[^&]*"
)
HANDLE = re.compile(r"(?<![\w@])@([A-Za-z0-9][A-Za-z0-9._-]{2,63})")
URL_HANDLE = {
    "instagram": "https://www.instagram.com/{handle}",
    "tiktok": "https://www.tiktok.com/@{handle}",
    "youtube": "https://www.youtube.com/@{handle}",
    "x": "https://x.com/{handle}",
    "bluesky": "https://bsky.app/profile/{handle}",
}


def limpar(url: str) -> str:
    url = unquote(url).replace("\\", "")
    url = SUJEIRA.sub("", url).rstrip(".,;:)]\"'")
    url = re.sub(
        r"(instagram\.com/)(p|reel|tv)/",
        lambda achado: achado.group(1) + achado.group(2).lower() + "/",
        url,
        count=1,
        flags=re.IGNORECASE,
    )
    url = re.sub(
        r"(tiktok\.com/@[^/]+/)(video)/",
        lambda achado: achado.group(1) + "video/",
        url,
        count=1,
        flags=re.IGNORECASE,
    )
    return url.split("#")[0].rstrip("?&")


def extrair(texto: str, plataformas: Iterable[str] | None = None) -> dict[str, set[str]]:
    alvos = plataformas or PADROES.keys()
    achados: dict[str, set[str]] = {}
    for plat in alvos:
        if urls := {limpar(u) for u in PADROES[plat].findall(texto)}:
            achados[plat] = urls
    return achados


def perfil_de_url(url: str) -> tuple[str, str] | None:
    """Normaliza o perfil contido numa URL de perfil ou publicação conhecida."""
    url = limpar(url)
    partes_url = urlsplit(url)
    host = partes_url.netloc.lower()
    for prefixo in ("www.", "mobile.", "m."):
        host = host.removeprefix(prefixo)
    partes = [parte for parte in partes_url.path.split("/") if parte]
    if not partes:
        return None

    if host == "tiktok.com":
        if partes[0].startswith("@") and len(partes[0]) > 1:
            return "tiktok", f"https://www.tiktok.com/{partes[0]}"
        return None

    if host == "instagram.com":
        handle = partes[0]
        if handle.lower() not in RESERVADOS and re.fullmatch(r"[A-Za-z0-9._]+", handle):
            return "instagram", f"https://www.instagram.com/{handle.lower()}"
        return None

    if host == "youtube.com":
        primeiro = partes[0]
        if primeiro.startswith("@"):
            return "youtube", f"https://www.youtube.com/{primeiro}"
        if primeiro.lower() in {"channel", "c", "user"} and len(partes) > 1:
            return "youtube", f"https://www.youtube.com/{primeiro}/{partes[1]}"
        return None

    if host in {"twitter.com", "x.com"}:
        handle = partes[0]
        if handle.lower() not in RESERVADOS | {"i", "intent", "settings"}:
            return "x", f"https://x.com/{handle.lower()}"
        return None

    if host in {"facebook.com", "fb.com"}:
        handle = partes[0]
        if handle.lower() not in RESERVADOS and handle.lower() != "profile.php":
            return "facebook", f"https://www.facebook.com/{handle}"
        return None

    if host == "t.me":
        canal = partes[0].lstrip("+")
        if canal and canal.lower() not in {"joinchat", "share"}:
            return "telegram", f"https://t.me/{canal}"
        return None

    if host == "bsky.app" and len(partes) >= 2 and partes[0].lower() == "profile":
        return "bluesky", f"https://bsky.app/profile/{partes[1].lower()}"

    if host == "kwai.com" and partes[0].startswith("@"):
        return "kwai", f"https://www.kwai.com/{partes[0]}"
    return None


def extrair_perfis(texto: str) -> dict[str, set[str]]:
    saida: dict[str, set[str]] = {}
    for url in URL_SOCIAL.findall(texto):
        if perfil := perfil_de_url(url):
            plataforma, normalizada = perfil
            saida.setdefault(plataforma, set()).add(normalizada)
    return saida


def perfis_mencionados(doc: Documento) -> set[tuple[str, str]]:
    """Perfis marcados em posts raiz; comentários de usuários ficam de fora."""
    if doc.metadados.get("tipo") in {"comentario", "resposta"}:
        return set()
    plataforma = doc.canal if doc.canal in URL_HANDLE else doc.fonte
    molde = URL_HANDLE.get(plataforma)
    if not molde:
        return set()
    handles = set(HANDLE.findall("\n".join((doc.titulo, doc.texto))))
    mencoes_meta = doc.metadados.get("mencoes") or []
    if isinstance(mencoes_meta, str):
        mencoes_meta = [mencoes_meta]
    handles.update(str(handle).strip().lstrip("@") for handle in mencoes_meta if handle)
    return {
        (plataforma, molde.format(handle=handle))
        for handle in handles
        if handle and "@" not in handle
    }


def varrer(
    documentos: Iterator[Documento], plataformas: Iterable[str] | None = None
) -> dict[str, Counter]:
    """Percorre o corpus e conta quantas vezes cada URL social foi citada.

    A contagem importa: URL citada por várias fontes independentes circulou mais,
    e é por onde começar quando não dá para buscar tudo.
    """
    saida: dict[str, Counter] = {}
    for doc in documentos:
        meta = json.dumps(doc.metadados, ensure_ascii=False, default=str)
        corpo = "\n".join([doc.texto, doc.titulo, meta])
        for plat, urls in extrair(corpo, plataformas).items():
            saida.setdefault(plat, Counter()).update(urls)
    return saida


def varrer_perfis(documentos: Iterator[Documento]) -> dict[str, Counter]:
    """Perfis citados ou responsáveis por publicações citadas no corpus."""
    saida: dict[str, Counter] = {}
    for doc in documentos:
        meta = json.dumps(doc.metadados, ensure_ascii=False, default=str)
        corpo = "\n".join([doc.url, doc.texto, doc.titulo, meta])
        for plataforma, urls in extrair_perfis(corpo).items():
            saida.setdefault(plataforma, Counter()).update(urls)
        for plataforma, url in perfis_mencionados(doc):
            saida.setdefault(plataforma, Counter()).update([url])
    return saida
