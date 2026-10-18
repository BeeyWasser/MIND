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
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..media.download import baixar_audio, detalhar, listar
from ..media.transcribe import transcrever
from ..paths import corpus_path
from ..schema import Documento, eleicao_de

MIDIA = corpus_path("_midia")


@dataclass(frozen=True)
class Alvo:
    url: str
    candidato_id: str | None = None
    candidato: str | None = None
    partido: str | None = None
    cargo: str | None = None
    perfil: str | None = None


def _alvo(item: str | Alvo) -> Alvo:
    return item if isinstance(item, Alvo) else Alvo(item)


def _perfis_listaveis(url: str) -> tuple[str, ...]:
    base = url.rstrip("/")
    if "youtube.com/" not in base or base.endswith(("/videos", "/shorts", "/streams")):
        return (base,)
    return tuple(f"{base}/{aba}" for aba in ("videos", "shorts", "streams"))


def _perfil_listavel(url: str) -> str:
    return _perfis_listaveis(url)[0]


def descobrir_perfis(perfis: Iterable[Alvo], limite_perfil: int = 5) -> Iterator[Alvo]:
    """Enumera publicações de perfis declarados ao TSE."""
    vistos: set[str] = set()
    for perfil in perfis:
        for aba in _perfis_listaveis(perfil.url):
            try:
                pecas = listar(aba, limite=limite_perfil)
            except Exception:
                continue
            for peca in pecas:
                if not peca.id or not peca.url or peca.url in vistos:
                    continue
                vistos.add(peca.url)
                yield Alvo(
                    url=peca.url,
                    candidato_id=perfil.candidato_id,
                    candidato=perfil.candidato,
                    partido=perfil.partido,
                    cargo=perfil.cargo,
                    perfil=perfil.url,
                )


def coletar(
    urls: Iterable[str | Alvo],
    ja_tem,
    midia: Path = MIDIA,
    transcrever_audio: bool = True,
    limite: int = 100,
    max_tentativas: int | None = None,
    ao_falhar: Callable[[str, Exception], None] | None = None,
) -> Iterator[Documento]:
    n = 0
    tentativas = 0
    for item in urls:
        alvo = _alvo(item)
        if n >= limite or (max_tentativas is not None and tentativas >= max_tentativas):
            return
        if ja_tem(alvo.url):
            continue
        tentativas += 1
        try:
            peca = baixar_audio(alvo.url, midia) if transcrever_audio else detalhar(alvo.url)
        except Exception:
            try:
                peca = detalhar(alvo.url)
            except Exception as erro:
                if ao_falhar:
                    ao_falhar(alvo.url, erro)
                continue
        if not peca.id:
            continue
        n += 1

        segmentos = []
        if transcrever_audio and peca.audio:
            with contextlib.suppress(Exception):
                segmentos = transcrever(peca.audio)

        plataforma = next(
            (
                nome
                for nome in ("tiktok", "instagram", "facebook", "kwai", "youtube", "twitter")
                if nome in peca.plataforma or nome in alvo.url.lower()
            ),
            "x" if "x.com/" in alvo.url.lower() else "youtube",
        )
        if plataforma == "twitter":
            plataforma = "x"
        yield Documento(
            fonte=plataforma,
            url=peca.url or alvo.url,
            titulo=peca.titulo,
            texto=peca.descricao,
            canal=plataforma,
            modalidade="video",
            eleicao=eleicao_de(peca.publicado_em),
            veiculado_em=peca.publicado_em,
            transcricao=segmentos,
            duracao_seg=peca.duracao_seg,
            patrocinador=alvo.candidato or peca.canal or None,
            candidato_id=alvo.candidato_id,
            partido=alvo.partido,
            cargo=alvo.cargo,
            metadados={
                "video_id": peca.id,
                "conta": peca.canal_id,
                "visualizacoes": peca.visualizacoes,
                "descoberta": "tse_perfil" if alvo.perfil else "mencao",
                "perfil": alvo.perfil,
                **peca.extra,
            },
        )
