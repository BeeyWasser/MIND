"""Comentários e respostas pela API oficial YouTube Data v3."""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx

from ..http import UA
from ..schema import Documento, anonimizar, eleicao_de
from .rss import _sem_html

API_THREADS = "https://www.googleapis.com/youtube/v3/commentThreads"
API_COMENTARIOS = "https://www.googleapis.com/youtube/v3/comments"
MINIMO_CHARS = 20


class SemChave(RuntimeError):
    pass


def _chave() -> str:
    chave = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not chave:
        raise SemChave("YOUTUBE_API_KEY ausente. Ver CREDENCIAIS.md.")
    return chave


def _documento(comentario: dict, video_id: str, pai: str | None = None) -> Documento | None:
    identificador = comentario.get("id")
    trecho = comentario.get("snippet") or {}
    texto = _sem_html(trecho.get("textDisplay") or trecho.get("textOriginal") or "")
    if not identificador or len(texto) < MINIMO_CHARS:
        return None
    publicado = trecho.get("publishedAt")
    autor = (trecho.get("authorChannelId") or {}).get("value")
    return Documento(
        fonte="youtube",
        url=f"https://www.youtube.com/watch?v={video_id}&lc={identificador}",
        texto=texto,
        canal="youtube",
        modalidade="texto",
        eleicao=eleicao_de(publicado),
        veiculado_em=publicado,
        autor_hash=anonimizar(autor, os.environ.get("MIND_SALT", "mind-dev")) if autor else None,
        metadados={
            "tipo": "resposta" if pai else "comentario",
            "video_id": video_id,
            "comentario_id": identificador,
            "comentario_pai": pai,
            "likes": trecho.get("likeCount"),
            "atualizado_em": trecho.get("updatedAt"),
            "origem": "youtube_data_api_v3",
        },
    )


def _respostas(
    cliente: httpx.Client,
    video_id: str,
    pai: str,
    ignorar: set[str],
) -> Iterator[Documento]:
    token = None
    while True:
        parametros = {
            "key": _chave(),
            "part": "snippet",
            "parentId": pai,
            "maxResults": 100,
            "textFormat": "plainText",
        }
        if token:
            parametros["pageToken"] = token
        resposta = cliente.get(API_COMENTARIOS, params=parametros)
        resposta.raise_for_status()
        dados = resposta.json()
        for item in dados.get("items", []):
            identificador = str(item.get("id") or "")
            if not identificador or identificador in ignorar:
                continue
            ignorar.add(identificador)
            if doc := _documento(item, video_id, pai=pai):
                yield doc
        token = dados.get("nextPageToken")
        if not token:
            return


def coletar(video_id: str, paginas: int = 5) -> Iterator[Documento]:
    token = None
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60) as cliente:
        for _pagina in range(paginas):
            parametros = {
                "key": _chave(),
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": 100,
                "order": "time",
                "textFormat": "plainText",
            }
            if token:
                parametros["pageToken"] = token
            resposta = cliente.get(API_THREADS, params=parametros)
            if resposta.status_code == 403 and "commentsDisabled" in resposta.text:
                return
            resposta.raise_for_status()
            dados = resposta.json()
            for item in dados.get("items", []):
                principal = (item.get("snippet") or {}).get("topLevelComment") or {}
                if doc := _documento(principal, video_id):
                    yield doc
                pai = principal.get("id")
                respostas_vistas: set[str] = set()
                for resposta_item in (item.get("replies") or {}).get("comments", []):
                    if identificador := resposta_item.get("id"):
                        respostas_vistas.add(str(identificador))
                    if doc := _documento(resposta_item, video_id, pai=pai):
                        yield doc
                total = int((item.get("snippet") or {}).get("totalReplyCount") or 0)
                if pai and total > len(respostas_vistas):
                    yield from _respostas(cliente, video_id, pai, respostas_vistas)
            token = dados.get("nextPageToken")
            if not token:
                return
