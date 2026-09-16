"""Rótulos de alta precisão publicados por agências de checagem.

O rótulo vem apenas do título: o corpo costuma citar várias alegações, inclusive
verdadeiras, e inferir o veredito dele criaria supervisão ruidosa. Padrões
ambíguos ficam sem rótulo para anotação humana posterior.
"""

from __future__ import annotations

import re

from ..schema import Documento

PADROES = (
    ("fora_de_contexto", re.compile(r"\b(fora|tirad[oa])\s+de\s+contexto\b", re.I)),
    ("ia_sintetica", re.compile(r"\b(deepfake|gerad[oa]s?\s+por\s+(?:uma\s+)?ia)\b", re.I)),
    ("sem_evidencia", re.compile(r"\b(sem\s+provas?|n[aã]o\s+h[aá]\s+ind[ií]cios?)\b", re.I)),
    ("enganoso", re.compile(r"\b(enganos[oa]s?|engana)\b", re.I)),
    ("falso", re.compile(r"\b([ée]\s+fals[oa]|s[aã]o\s+fals[oa]s|fake)\b", re.I)),
)


def inferir(documento: Documento) -> tuple[str, str] | None:
    if documento.fonte != "checagem" or not documento.titulo:
        return None
    for rotulo, padrao in PADROES:
        if padrao.search(documento.titulo):
            origem = str(documento.metadados.get("feed") or "checagem")
            return rotulo, origem
    return None
