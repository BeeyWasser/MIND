"""Transcrição de áudio com Whisper.

mlx-whisper roda nativo em Metal no Apple Silicon, na casa de 10 a 20 vezes o
tempo real. Guarda timestamps por segmento e não só o texto corrido: o
alinhamento temporal é o que permite cruzar o que é dito com o que aparece
escrito na tela — ver COLETA.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..schema import Segmento

MODELO = "mlx-community/whisper-large-v3-turbo"

# HGPE é cheio de jingle e vinheta, e Whisper alucina em trecho sem fala:
# repete a última frase em janelas de exatos 30s, que é o chunk nativo dele.
# Desligar o condicionamento no texto anterior corta o laço na origem.
OPCOES = {
    "condition_on_previous_text": False,
    "hallucination_silence_threshold": 2.0,
}

# Piso de confiança. Conservador de propósito: -1.0 é a convenção do próprio
# Whisper e derruba o pior (jingle cantado sai perto de -1.4) sem tocar em fala
# de verdade (perto de -0.1). O valor fica no dado para recalibrar depois.
CONFIANCA_MINIMA = -1.0


# Alucinação de crédito de legenda: o Whisper foi treinado com muito legenda de
# vídeo e, em trecho só com música, produz a assinatura do legendador.
CREDITOS = re.compile(
    r"^\s*("
    r"legendas?\s+(pela|por|pelo)\b"
    r"|transcri[çc][ãa]o\s+e\s+legendas?\b"
    r"|legendado\s+por\b"
    r"|amara\.org"
    r"|inscreva-se\s+no\s+canal"
    r"|subtitles?\s+by\b"
    r")",
    re.IGNORECASE,
)


def _janela_cheia(s: Segmento) -> bool:
    """Segmento cobrindo exatamente uma janela de 30s do modelo.

    Fala real não se alinha a múltiplo exato de 30 — quando isso acontece, é o
    chunk inteiro devolvido sem transcrição de verdade.
    """
    return abs((s.fim_seg - s.inicio_seg) - 30.0) < 0.05 and abs(s.inicio_seg % 30.0) < 0.05


def _sem_repeticao(segmentos: list[Segmento]) -> list[Segmento]:
    """Tira repetição consecutiva — a assinatura da alucinação em silêncio.

    Vai junto com condition_on_previous_text=False, não no lugar: o parâmetro
    reduz o laço, este filtro pega o que escapa. Fala real não repete a mesma
    frase literal em segmentos seguidos.
    """
    limpos: list[Segmento] = []
    for s in segmentos:
        if CREDITOS.match(s.texto) or _janela_cheia(s):
            continue
        if s.confianca is not None and s.confianca < CONFIANCA_MINIMA:
            continue
        chave = " ".join(s.texto.lower().split())
        if limpos and chave == " ".join(limpos[-1].texto.lower().split()):
            continue
        limpos.append(s)
    return limpos


def transcrever(
    audio: Path, modelo: str = MODELO, idioma: str = "pt", cache: bool = True
) -> list[Segmento]:
    """Transcreve. Reaproveita o resultado em disco se já existir.

    Transcrever é caro e determinístico o bastante para valer cache: o .json ao
    lado do áudio evita refazer horas de trabalho quando a coleta roda de novo.
    """
    destino = audio.with_suffix(".json")
    if cache and destino.exists():
        return [Segmento(**s) for s in json.loads(destino.read_text())]

    import mlx_whisper

    r = mlx_whisper.transcribe(str(audio), path_or_hf_repo=modelo, language=idioma, **OPCOES)
    segmentos = _sem_repeticao(
        [
            Segmento(
                inicio_seg=round(s["start"], 2),
                fim_seg=round(s["end"], 2),
                texto=s["text"].strip(),
                confianca=round(s["avg_logprob"], 3) if "avg_logprob" in s else None,
            )
            for s in r.get("segments", [])
            if s.get("text", "").strip()
        ]
    )
    if cache:
        destino.write_text(json.dumps([s.__dict__ for s in segmentos], ensure_ascii=False))
    return segmentos


def texto(segmentos: list[Segmento]) -> str:
    return " ".join(s.texto for s in segmentos).strip()
