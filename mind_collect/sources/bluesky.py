"""Posts públicos do Bluesky pela API oficial do AT Protocol, sem credencial."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from datetime import date
from urllib.parse import urlsplit

import httpx

from ..schema import Documento, anonimizar, eleicao_de

API = "https://api.bsky.app/xrpc"
CABECALHO = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)"}
TERMOS = (
    "eleições 2026",
    "eleição 2026",
    "propaganda eleitoral",
    "campanha eleitoral",
    "candidato presidente",
    "horário eleitoral",
    "urna eletrônica",
    "TSE eleições",
)


def _url(uri: str, handle: str) -> str:
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def _midias(post: dict) -> list[dict]:
    embed = post.get("embed") or {}
    saida: list[dict] = []
    for imagem in embed.get("images") or []:
        saida.append(
            {
                "tipo": "imagem",
                "url": imagem.get("fullsize") or imagem.get("thumb"),
                "thumb": imagem.get("thumb"),
                "alt": imagem.get("alt") or "",
            }
        )
    if playlist := embed.get("playlist"):
        saida.append(
            {
                "tipo": "video",
                "url": playlist,
                "thumb": embed.get("thumbnail"),
                "alt": embed.get("alt") or "",
            }
        )
    return saida


def _links(post: dict) -> list[str]:
    links: list[str] = []
    record = post.get("record") or {}
    for facet in record.get("facets") or []:
        for feature in facet.get("features") or []:
            if uri := feature.get("uri"):
                links.append(uri)
    externo = (post.get("embed") or {}).get("external") or {}
    if uri := externo.get("uri"):
        links.append(uri)
    return sorted(set(links))


def para_documento(post: dict) -> Documento:
    autor = post.get("author") or {}
    record = post.get("record") or {}
    handle = autor.get("handle") or autor.get("did") or "desconhecido"
    criado = record.get("createdAt") or post.get("indexedAt")
    midias = _midias(post)
    alts = [midia["alt"] for midia in midias if midia.get("alt")]
    texto = "\n".join([record.get("text") or "", *alts]).strip()
    modalidade = (
        "video"
        if any(midia.get("tipo") == "video" for midia in midias)
        else "imagem"
        if midias
        else "texto"
    )
    return Documento(
        fonte="bluesky",
        url=_url(post.get("uri", ""), handle),
        texto=texto,
        canal="bluesky",
        modalidade=modalidade,
        eleicao=eleicao_de(criado),
        veiculado_em=criado,
        autor_hash=anonimizar(autor.get("did") or handle, os.environ.get("MIND_SALT", "mind-dev")),
        metadados={
            "uri": post.get("uri"),
            "cid": post.get("cid"),
            "idiomas": record.get("langs"),
            "respostas": post.get("replyCount"),
            "reposts": post.get("repostCount"),
            "curtidas": post.get("likeCount"),
            "citacoes": post.get("quoteCount"),
            "links": _links(post),
            "midias": midias,
            "perfil_url": f"https://bsky.app/profile/{handle}",
            "perfil_publico": {
                "handle": autor.get("handle"),
                "nome": autor.get("displayName"),
                "foto": autor.get("avatar"),
                "rotulos": autor.get("labels"),
            },
        },
    )


def _paginar(cliente: httpx.Client, metodo: str, params: dict, limite: int) -> Iterator[dict]:
    cursor = None
    entregues = 0
    while entregues < limite:
        restantes = limite - entregues
        atuais = {**params, "limit": max(10, min(100, restantes))}
        if cursor:
            atuais["cursor"] = cursor
        resposta = cliente.get(f"{API}/{metodo}", params=atuais, timeout=60)
        if cursor and resposta.status_code in {400, 403}:
            return
        resposta.raise_for_status()
        dados = resposta.json()
        itens = dados.get("posts") or [item.get("post") for item in dados.get("feed", [])]
        itens = [item for item in itens if item]
        if not itens:
            return
        selecionados = itens[:restantes]
        yield from selecionados
        entregues += len(selecionados)
        cursor = dados.get("cursor")
        if not cursor:
            return


def handle_de_url(url: str) -> str | None:
    partes = [parte for parte in urlsplit(url).path.split("/") if parte]
    handle = partes[1] if len(partes) >= 2 and partes[0].lower() == "profile" else None
    handle = (handle or (partes[0] if partes else "")).lower()
    if "." not in handle or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", handle):
        return None
    return handle


def coletar(
    termos: tuple[str, ...] = TERMOS,
    perfis: list[str] | None = None,
    de: str | None = None,
    limite_por_termo: int = 300,
    limite_por_perfil: int = 30,
) -> Iterator[Documento]:
    desde = de or f"{date.today().year}-01-01T00:00:00Z"
    vistos: set[str] = set()
    with httpx.Client(headers=CABECALHO, follow_redirects=True) as cliente:
        for termo in termos:
            params = {"q": termo, "lang": "pt", "sort": "latest", "since": desde}
            try:
                posts = _paginar(cliente, "app.bsky.feed.searchPosts", params, limite_por_termo)
                for post in posts:
                    uri = post.get("uri")
                    if not uri or uri in vistos:
                        continue
                    vistos.add(uri)
                    doc = para_documento(post)
                    if doc.conteudo:
                        yield doc
            except (httpx.HTTPError, ValueError):
                continue
        for perfil in perfis or []:
            handle = handle_de_url(perfil)
            if not handle:
                continue
            params = {"actor": handle, "filter": "posts_no_replies"}
            try:
                posts = _paginar(cliente, "app.bsky.feed.getAuthorFeed", params, limite_por_perfil)
                for post in posts:
                    uri = post.get("uri")
                    if not uri or uri in vistos:
                        continue
                    vistos.add(uri)
                    doc = para_documento(post)
                    if doc.conteudo:
                        yield doc
            except (httpx.HTTPError, ValueError):
                continue
