"""Download de vídeo público via yt-dlp.

Só áudio por padrão: `bestaudio` custa cerca de 1 MB por minuto contra 50 MB do
vídeo completo, e a transcrição é o que alimenta o modelo. Vídeo inteiro só
quando o OCR de frame precisar dele.

Busca URL pública, sem autenticação e sem contornar bloqueio. Mesma ferramenta e
mesmo regime para YouTube, TikTok e Instagram — ver COLETA.md.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

# Silencia o yt-dlp: quem reporta progresso é o runner.
QUIETO = {"quiet": True, "no_warnings": True, "noprogress": True}

EXT_AUDIO = {".m4a", ".mp3", ".opus", ".ogg", ".wav", ".aac", ".webm"}
EXT_VIDEO = {".mp4", ".mkv", ".webm", ".mov"}


def _achar(destino: Path, id_: str, extensoes: set[str]) -> Path | None:
    """O arquivo de mídia da peça, e só ele.

    O diretório também guarda o .json da transcrição; um glob solto por `id.*`
    devolve o cache em vez do mídia, dependendo da ordem do sistema de arquivos.
    """
    for p in sorted(destino.glob(f"{id_}.*")):
        if p.suffix.lower() in extensoes:
            return p
    return None


@dataclass
class Peca:
    """O que se sabe de um vídeo antes de decidir baixá-lo."""

    id: str
    url: str
    titulo: str
    duracao_seg: float | None = None
    canal: str = ""
    canal_id: str = ""
    publicado_em: str | None = None   # AAAA-MM-DD
    descricao: str = ""
    visualizacoes: int | None = None
    plataforma: str = "youtube"
    audio: Path | None = None
    extra: dict = field(default_factory=dict)


def _url(info: dict) -> str:
    """A URL da peça, qualquer que seja a forma da extração.

    Extração completa devolve `webpage_url`; a plana (`extract_flat`, usada na
    descoberta) devolve só `url`. Sem este fallback a descoberta enumera peças
    com URL vazia e o download falha uma a uma.
    """
    for chave in ("webpage_url", "original_url", "url"):
        if v := info.get(chave):
            return v
    vid = info.get("id")
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""


def _para_peca(info: dict) -> Peca:
    d = info.get("upload_date")  # yt-dlp devolve AAAAMMDD
    return Peca(
        id=info.get("id", ""),
        url=_url(info),
        titulo=(info.get("title") or "").strip(),
        duracao_seg=info.get("duration"),
        canal=info.get("uploader") or info.get("channel") or "",
        canal_id=info.get("channel_id") or info.get("uploader_id") or "",
        publicado_em=f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else None,
        descricao=(info.get("description") or "").strip(),
        visualizacoes=info.get("view_count"),
        plataforma=info.get("extractor_key", "youtube").lower(),
        extra={"like_count": info.get("like_count"), "tags": info.get("tags")},
    )


def listar(alvo: str, limite: int = 50) -> list[Peca]:
    """Enumera vídeos de um canal, playlist ou busca, sem baixar nada.

    `alvo` aceita URL de canal/playlist ou `ytsearch20:termo`.
    """
    opcoes = {**QUIETO, "extract_flat": "in_playlist", "playlistend": limite}
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(alvo, download=False)
    entradas = info.get("entries") or [info]
    return [_para_peca(e) for e in entradas if e]


def detalhar(url: str) -> Peca:
    """Metadados completos de uma peça, sem baixar o mídia."""
    with yt_dlp.YoutubeDL(QUIETO) as ydl:
        return _para_peca(ydl.extract_info(url, download=False))


def baixar_audio(url: str, destino: Path) -> Peca:
    """Baixa só a trilha de áudio, em m4a. Pula se o arquivo já existe."""
    destino.mkdir(parents=True, exist_ok=True)
    opcoes = {
        **QUIETO,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(destino / "%(id)s.%(ext)s"),
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "128"}
        ],
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)
    peca = _para_peca(info)
    peca.audio = _achar(destino, peca.id, EXT_AUDIO)
    return peca


def baixar_video(url: str, destino: Path) -> Path | None:
    """Vídeo completo. Só quando o OCR de frame precisar — custa ~50 MB/min
    contra ~1 MB/min do áudio."""
    destino.mkdir(parents=True, exist_ok=True)
    opcoes = {
        **QUIETO,
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
        "outtmpl": str(destino / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
    }
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        info = ydl.extract_info(url, download=True)
    return _achar(destino, info.get("id", ""), EXT_VIDEO)


def keyframes(video: Path, destino: Path, limiar: float = 0.30,
              maximo: int = 60) -> list[tuple[float, Path]]:
    """Extrai frames por mudança de cena, não por amostragem cega.

    Propaganda tem corte rápido e cena estável entre cortes, então mudança de
    cena é bom proxy para "apareceu texto novo" — e evita gerar sessenta frames
    idênticos de um plano parado.
    """
    destino.mkdir(parents=True, exist_ok=True)
    padrao = destino / f"{video.stem}_%04d.jpg"
    # loglevel "info", e não "error": o filtro showinfo loga em info, e é dele
    # que sai o pts_time de cada frame. Com "error" os frames são escritos e os
    # tempos somem — o resultado vinha vazio mesmo com o disco cheio de imagem.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "info", "-y", "-i", str(video),
        "-vf", f"select='gt(scene,{limiar})',showinfo,scale=1280:-1",
        "-fps_mode", "vfr", "-frames:v", str(maximo), "-q:v", "3", str(padrao),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    tempos = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    achados = sorted(destino.glob(f"{video.stem}_*.jpg"))
    if not achados:
        return []
    # O frame no disco manda: se o tempo não veio, devolve-se o frame mesmo
    # assim, com tempo nulo, em vez de perder tudo.
    tempos += [None] * (len(achados) - len(tempos))
    return list(zip(tempos[:len(achados)], achados, strict=True))
