"""TikTok e Instagram, a partir de URL pública descoberta por menção.

Não há rota oficial: a Commercial Content Library do TikTok só cobre a Europa e
a Research API só aceita pesquisador brasileiro para estudo de segurança de
menores; a Meta Content Library está barrada por custo e prazo.

O que resta é buscar URL pública com `yt-dlp` — mesma ferramenta e mesmo regime
do YouTube, sem autenticação e sem contornar bloqueio. As URLs vêm do
`mencoes.py`, não de rastrear a superfície de descoberta das plataformas.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..media.download import baixar_audio, detalhar
from ..media.transcribe import transcrever
from ..schema import Documento, eleicao_de

MIDIA = Path("data/eleicoes2026/_midia")


def coletar(urls: Iterable[str], ja_tem, midia: Path = MIDIA,
            transcrever_audio: bool = True, limite: int = 100) -> Iterator[Documento]:
    n = 0
    for url in urls:
        if n >= limite or ja_tem(url):
            continue
        try:
            peca = detalhar(url)
        except Exception:
            continue
        if not peca.id:
            continue
        n += 1

        segmentos = []
        if transcrever_audio:
            with contextlib.suppress(Exception):
                baixada = baixar_audio(url, midia)
                if baixada.audio:
                    segmentos = transcrever(baixada.audio)

        plataforma = "tiktok" if "tiktok" in peca.plataforma else (
            "instagram" if "instagram" in peca.plataforma else peca.plataforma)
        yield Documento(
            fonte=plataforma if plataforma in ("tiktok", "instagram") else "youtube",
            url=peca.url or url,
            titulo=peca.titulo,
            texto=peca.descricao,
            canal=plataforma,
            modalidade="video",
            eleicao=eleicao_de(peca.publicado_em),
            veiculado_em=peca.publicado_em,
            transcricao=segmentos,
            duracao_seg=peca.duracao_seg,
            patrocinador=peca.canal or None,
            metadados={
                "video_id": peca.id,
                "conta": peca.canal_id,
                "visualizacoes": peca.visualizacoes,
                "descoberta": "mencao",
                **peca.extra,
            },
        )
