"""Publicações públicas do Instagram pela página oficial de incorporação.

O endpoint de embed funciona sem login para posts públicos e expõe o contexto
que a própria página usa para renderizar imagem, vídeo, legenda e métricas. A
imagem original é processada em memória de trabalho e descartada; ficam URL,
miniatura, OCR e hashes perceptuais.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ..media.images import processar as processar_imagens
from ..paths import corpus_path
from ..schema import Documento, Midia, anonimizar, eleicao_de

MIDIA = corpus_path("_midia")
CABECALHO = {
    "User-Agent": "Mozilla/5.0 (compatible; MINDResearchBot/0.1; pesquisa academica)",
    "Accept-Language": "pt-BR,pt;q=0.9",
}
CONTEXTO = re.compile(r'"contextJSON":"((?:\\.|[^"\\])*)"')


def _contexto(html: str) -> dict:
    achado = CONTEXTO.search(html)
    if not achado:
        raise ValueError("embed do Instagram sem contextJSON")
    texto_json = json.loads('"' + achado.group(1) + '"')
    contexto = json.loads(texto_json)
    media = (contexto.get("gql_data") or {}).get("shortcode_media")
    if not media:
        raise ValueError("publicação indisponível no embed do Instagram")
    return media


def _itens(media: dict) -> list[dict]:
    filhos = (media.get("edge_sidecar_to_children") or {}).get("edges") or []
    return [filho.get("node") or {} for filho in filhos] or [media]


def _legenda(media: dict) -> str:
    arestas = (media.get("edge_media_to_caption") or {}).get("edges") or []
    return "\n".join(
        aresta.get("node", {}).get("text", "").strip()
        for aresta in arestas
        if aresta.get("node", {}).get("text", "").strip()
    )


def para_documento(media: dict, url: str) -> Documento:
    itens = _itens(media)
    acessibilidade = [
        str(item.get("accessibility_caption") or "").strip()
        for item in itens
        if str(item.get("accessibility_caption") or "").strip()
    ]
    legenda = _legenda(media)
    timestamp = media.get("taken_at_timestamp")
    publicado = (
        datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")
        if isinstance(timestamp, (int, float))
        else None
    )
    dono = media.get("owner") or {}
    usuario = str(dono.get("username") or "").strip()
    midias = [
        {
            "tipo": "video" if item.get("is_video") else "imagem",
            "url": item.get("video_url") if item.get("is_video") else item.get("display_url"),
            "thumb": item.get("display_url"),
            "alt": item.get("accessibility_caption") or "",
        }
        for item in itens
        if item.get("display_url") or item.get("video_url")
    ]
    videos = [item for item in itens if item.get("is_video")]
    return Documento(
        fonte="instagram",
        url=url,
        texto="\n".join([legenda, *acessibilidade]).strip(),
        canal="instagram",
        modalidade="video" if videos else "imagem",
        eleicao=eleicao_de(publicado),
        veiculado_em=publicado,
        duracao_seg=max((float(item.get("video_duration") or 0) for item in videos), default=0)
        or None,
        licenca_uso="referencia",
        robots_ok=False,
        autor_hash=anonimizar(
            str(dono.get("id") or dono.get("username") or media.get("id")),
            os.environ.get("MIND_SALT", "mind-dev"),
        ),
        metadados={
            "shortcode": media.get("shortcode"),
            "media_id": media.get("id"),
            "tipo_instagram": media.get("__typename"),
            "curtidas": (media.get("edge_liked_by") or {}).get("count"),
            "comentarios": (media.get("edge_media_to_comment") or {}).get("count"),
            "visualizacoes": media.get("video_view_count"),
            "perfil_url": f"https://www.instagram.com/{usuario}/" if usuario else None,
            "perfil_publico": {
                "handle": usuario or None,
                "nome": dono.get("full_name"),
                "verificado": dono.get("is_verified"),
                "foto": dono.get("profile_pic_url"),
            },
            "midias": midias,
            "descoberta": "mencao",
            "aviso_coleta": "embed público; robots.txt geral da plataforma bloqueia automação",
        },
    )


def coletar(
    urls: Iterable[str], ja_tem, limite: int = 100, destino: Path = MIDIA
) -> Iterator[tuple[Documento, list[Midia]]]:
    entregues = 0
    with httpx.Client(headers=CABECALHO, follow_redirects=True, timeout=40) as cliente:
        for url in urls:
            if entregues >= limite:
                return
            if ja_tem(url):
                continue
            try:
                embed = url.rstrip("/") + "/embed/captioned/"
                resposta = cliente.get(embed)
                resposta.raise_for_status()
                media = _contexto(resposta.text)
                doc = para_documento(media, url)
                imagens = processar_imagens(
                    doc.doc_id,
                    doc.metadados["midias"],
                    destino,
                    cliente,
                    referer="https://www.instagram.com/",
                )
            except (httpx.HTTPError, json.JSONDecodeError, ValueError):
                continue
            entregues += 1
            yield doc, imagens
