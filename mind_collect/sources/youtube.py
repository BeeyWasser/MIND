"""Vídeo político no YouTube: HGPE, canais de partido e de candidato.

O HGPE de 2026 vai ao ar de 28/08 a 01/10 e é o único material perecível do
projeto — partidos, coligações, candidatos e veículos sobem os blocos e as
inserções, e é de lá que se busca.

A descoberta ideal viria das contas declaradas no registro do TSE, mas o domínio
do TSE responde 403 do Akamai (ver COLETA.md). Enquanto isso, sementes de busca.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from ..media.download import Peca, baixar_audio, baixar_video, keyframes, listar
from ..media.ocr import divergente, ler
from ..media.thumbs import hashes, miniatura
from ..media.transcribe import texto as texto_transcricao
from ..media.transcribe import transcrever
from ..schema import Documento, Midia

MIDIA = Path("data/eleicoes2026/_midia")

# Inserção é peça de 30 ou 60 segundos; bloco em rede passa de 5 minutos. A
# fronteira em 150s separa os dois com folga para vinheta e variação de corte.
LIMITE_INSERCAO_SEG = 150


@dataclass(frozen=True)
class Semente:
    chave: str
    alvo: str          # URL de canal/playlist ou "ytsearch30:termo"
    eleicao: str
    limite: int = 30


SEMENTES: list[Semente] = [
    Semente("hgpe-2026-tv",  "ytsearch30:horário eleitoral gratuito 2026 presidente", "2026"),
    Semente("hgpe-2026-ins", "ytsearch30:inserção eleitoral 2026", "2026"),
    Semente("hgpe-2022",     "ytsearch30:horário eleitoral gratuito 2022 presidente", "2022"),
    Semente("hgpe-2018",     "ytsearch20:horário eleitoral gratuito 2018 presidente", "2018"),
]

POR_CHAVE = {s.chave: s for s in SEMENTES}


def classificar(peca: Peca) -> str:
    if peca.duracao_seg and peca.duracao_seg <= LIMITE_INSERCAO_SEG:
        return "hgpe_insercao"
    return "hgpe_bloco"


def para_documento(peca: Peca, eleicao: str, transcricao) -> Documento:
    return Documento(
        fonte=classificar(peca),
        url=peca.url,
        titulo=peca.titulo,
        texto=peca.descricao,
        canal="youtube",
        modalidade="video",
        eleicao=eleicao,
        veiculado_em=peca.publicado_em,
        transcricao=transcricao,
        duracao_seg=peca.duracao_seg,
        patrocinador=peca.canal or None,
        metadados={
            "video_id": peca.id,
            "canal_id": peca.canal_id,
            "visualizacoes": peca.visualizacoes,
            "plataforma": peca.plataforma,
            **peca.extra,
        },
    )


def frames_de(video: Path, doc_id: str, fala: str, midia: Path,
              maximo: int = 40) -> list[Midia]:
    """Keyframes, OCR e hash perceptual de uma peça.

    Só o que diverge da fala entra: em HGPE boa parte do que o OCR lê é legenda
    queimada, que repete o áudio. Sem separar, a análise multimodal fica
    dominada por texto dizendo exatamente o que foi dito.
    """
    saida: list[Midia] = []
    for t, frame in keyframes(video, midia / "frames", maximo=maximo):
        achados = divergente(ler(frame), fala)
        if not achados:
            continue
        ph, dh = hashes(frame)
        thumb = miniatura(frame, midia / "thumbs" / f"{frame.stem}.jpg")
        saida.append(Midia(
            doc_id=doc_id, tipo="frame", url_origem=str(frame), t_seg=t,
            phash=ph, dhash=dh,
            ocr_texto="\n".join(a.texto for a in achados),
            thumb_path=str(thumb) if thumb else None,
        ))
    return saida


def coletar(semente: Semente, ja_tem, midia: Path = MIDIA,
            transcrever_audio: bool = True,
            com_frames: bool = False) -> Iterator[tuple[Documento, list[Midia]]]:
    """Descobre, baixa o áudio e transcreve. Com `com_frames`, também extrai
    keyframes e faz OCR — o que exige baixar o vídeo inteiro, ~150 MB por peça
    contra ~12 MB do áudio.

    `ja_tem(video_id)` evita rebaixar e retranscrever — transcrever é a parte
    cara e a coleta roda de novo todo dia.
    """
    for achada in listar(semente.alvo, limite=semente.limite):
        if not achada.id or ja_tem(achada.id):
            continue
        try:
            peca = baixar_audio(achada.url, midia)
        except Exception:
            continue
        segmentos = []
        if transcrever_audio and peca.audio:
            # Transcrição que falha não descarta a peça: título, descrição e
            # metadados de veiculação já são documento utilizável.
            with contextlib.suppress(Exception):
                segmentos = transcrever(peca.audio)

        doc = para_documento(peca, semente.eleicao, segmentos)
        frames: list[Midia] = []
        if com_frames:
            with contextlib.suppress(Exception):
                if v := baixar_video(achada.url, midia):
                    frames = frames_de(v, doc.doc_id,
                                       texto_transcricao(segmentos), midia)
        yield doc, frames
