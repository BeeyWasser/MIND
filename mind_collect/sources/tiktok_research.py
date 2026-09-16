"""TikTok Research API para descoberta temática em escala.

É a rota oficial que permite sair de perfis previamente conhecidos: consulta
vídeos públicos por palavra-chave, hashtag, região e janela de data, além de
comentários e respostas. O coletor só ativa após aprovação institucional.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import httpx

from ..schema import Documento, Segmento, anonimizar, eleicao_de

API = "https://open.tiktokapis.com/v2"
VIDEO_FIELDS = ",".join(
    (
        "id",
        "video_description",
        "create_time",
        "region_code",
        "share_count",
        "view_count",
        "like_count",
        "comment_count",
        "music_id",
        "hashtag_names",
        "username",
        "effect_ids",
        "playlist_id",
        "voice_to_text",
        "favorites_count",
        "video_duration",
        "video_mention_list",
        "video_label",
        "video_tag",
    )
)
COMMENT_FIELDS = "id,video_id,text,like_count,reply_count,parent_comment_id,create_time"


class SemCredencial(RuntimeError):
    pass


def configurado() -> bool:
    return bool(
        os.environ.get("TIKTOK_RESEARCH_CLIENT_KEY")
        and os.environ.get("TIKTOK_RESEARCH_CLIENT_SECRET")
    )


def obter_token(cliente: httpx.Client) -> str:
    chave = os.environ.get("TIKTOK_RESEARCH_CLIENT_KEY", "").strip()
    segredo = os.environ.get("TIKTOK_RESEARCH_CLIENT_SECRET", "").strip()
    if not (chave and segredo):
        raise SemCredencial("credenciais da TikTok Research API ausentes. Ver CREDENCIAIS.md.")
    resposta = cliente.post(
        f"{API}/oauth/token/",
        data={"client_key": chave, "client_secret": segredo, "grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get("access_token"):
        raise RuntimeError(dados.get("error_description") or "TikTok não devolveu access_token")
    return str(dados["access_token"])


def _verificar(dados: dict) -> dict:
    erro = dados.get("error") or {}
    if erro and erro.get("code") not in {None, "", "ok"}:
        raise RuntimeError(f"TikTok Research API: {erro.get('code')}: {erro.get('message')}")
    return dados.get("data") or {}


def _quando(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(int(epoch), UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return None


def _segmentos(legenda: str, duracao: float | None) -> list[Segmento]:
    legenda = legenda.strip()
    if not legenda:
        return []
    return [Segmento(0.0, float(duracao or 0), legenda)]


def para_documento(video: dict, consulta: str) -> Documento:
    video_id = str(video.get("id") or "")
    username = str(video.get("username") or "").strip().lstrip("@")
    publicado = _quando(video.get("create_time"))
    duracao = float(video.get("video_duration") or 0) or None
    descricao = str(video.get("video_description") or "").strip()
    legenda = str(video.get("voice_to_text") or "").strip()
    return Documento(
        fonte="tiktok",
        url=f"https://www.tiktok.com/@{username}/video/{video_id}",
        texto=descricao,
        canal="tiktok",
        modalidade="video",
        eleicao=eleicao_de(publicado),
        veiculado_em=publicado,
        transcricao=_segmentos(legenda, duracao),
        duracao_seg=duracao,
        autor_hash=anonimizar(username, os.environ.get("MIND_SALT", "mind-dev"))
        if username
        else None,
        metadados={
            "video_id": video_id,
            "conta": username,
            "perfil_url": f"https://www.tiktok.com/@{username}" if username else None,
            "perfil_publico": {"handle": username or None},
            "consulta": consulta,
            "descoberta": "tiktok_research_api",
            "regiao": video.get("region_code"),
            "visualizacoes": video.get("view_count"),
            "curtidas": video.get("like_count"),
            "comentarios": video.get("comment_count"),
            "compartilhamentos": video.get("share_count"),
            "favoritos": video.get("favorites_count"),
            "hashtags": video.get("hashtag_names"),
            "mencoes": video.get("video_mention_list"),
            "rotulo_plataforma": video.get("video_label"),
            "marcacao_video": video.get("video_tag"),
            "music_id": video.get("music_id"),
        },
    )


def para_comentario(comentario: dict, video_id: str) -> Documento | None:
    texto = str(comentario.get("text") or "").strip()
    identificador = str(comentario.get("id") or "")
    if not texto or not identificador:
        return None
    publicado = _quando(comentario.get("create_time"))
    pai = str(comentario.get("parent_comment_id") or "") or None
    return Documento(
        fonte="tiktok",
        url=f"https://www.tiktok.com/video/{video_id}?comment={identificador}",
        texto=texto,
        canal="tiktok",
        modalidade="texto",
        eleicao=eleicao_de(publicado),
        veiculado_em=publicado,
        metadados={
            "tipo": "resposta" if pai and pai != video_id else "comentario",
            "video_id": video_id,
            "comentario_id": identificador,
            "comentario_pai": pai,
            "curtidas": comentario.get("like_count"),
            "respostas": comentario.get("reply_count"),
            "descoberta": "tiktok_research_api",
        },
    )


def _janela(de: date | None, ate: date | None) -> tuple[str, str]:
    fim = ate or date.today()
    inicio = de or (fim - timedelta(days=29))
    if fim < inicio or (fim - inicio).days > 30:
        raise ValueError("a janela da TikTok Research API deve ter no máximo 30 dias")
    return inicio.strftime("%Y%m%d"), fim.strftime("%Y%m%d")


def buscar_videos(
    cliente: httpx.Client,
    token: str,
    consulta: str,
    de: date | None = None,
    ate: date | None = None,
    paginas: int = 5,
) -> Iterator[dict]:
    inicio, fim = _janela(de, ate)
    cursor = 0
    search_id = None
    for _ in range(max(1, paginas)):
        corpo = {
            "query": {
                "and": [
                    {"operation": "IN", "field_name": "region_code", "field_values": ["BR"]},
                    {"operation": "EQ", "field_name": "keyword", "field_values": [consulta]},
                ]
            },
            "start_date": inicio,
            "end_date": fim,
            "max_count": 100,
            "cursor": cursor,
        }
        if search_id:
            corpo["search_id"] = search_id
        resposta = cliente.post(
            f"{API}/research/video/query/",
            params={"fields": VIDEO_FIELDS},
            json=corpo,
            headers={"Authorization": f"Bearer {token}"},
        )
        resposta.raise_for_status()
        dados = _verificar(resposta.json())
        yield from dados.get("videos") or []
        if not dados.get("has_more"):
            return
        cursor = int(dados.get("cursor") or 0)
        search_id = dados.get("search_id") or search_id


def buscar_comentarios(
    cliente: httpx.Client,
    token: str,
    video_id: str,
    paginas: int = 2,
) -> Iterator[dict]:
    fila: list[tuple[str, bool]] = [(video_id, False)]
    while fila:
        identificador, eh_resposta = fila.pop(0)
        cursor = 0
        for _ in range(max(1, paginas)):
            corpo = {
                "comment_id" if eh_resposta else "video_id": int(identificador),
                "max_count": 100,
                "cursor": cursor,
            }
            resposta = cliente.post(
                f"{API}/research/video/comment/list/",
                params={"fields": COMMENT_FIELDS},
                json=corpo,
                headers={"Authorization": f"Bearer {token}"},
            )
            resposta.raise_for_status()
            dados = _verificar(resposta.json())
            comentarios = dados.get("comments") or []
            yield from comentarios
            if not eh_resposta:
                fila.extend(
                    (str(comentario["id"]), True)
                    for comentario in comentarios
                    if comentario.get("id") and int(comentario.get("reply_count") or 0) > 0
                )
            if not dados.get("has_more"):
                break
            cursor = int(dados.get("cursor") or 0)


def coletar(
    consulta: str,
    de: date | None = None,
    ate: date | None = None,
    paginas_videos: int = 5,
    paginas_comentarios: int = 1,
) -> Iterator[Documento]:
    with httpx.Client(timeout=90, follow_redirects=True) as cliente:
        token = obter_token(cliente)
        for video in buscar_videos(cliente, token, consulta, de, ate, paginas_videos):
            doc = para_documento(video, consulta)
            if doc.url and doc.metadados.get("video_id"):
                yield doc
            if paginas_comentarios <= 0:
                continue
            video_id = str(video.get("id") or "")
            for comentario in buscar_comentarios(
                cliente, token, video_id, paginas=paginas_comentarios
            ):
                if doc_comentario := para_comentario(comentario, video_id):
                    yield doc_comentario
