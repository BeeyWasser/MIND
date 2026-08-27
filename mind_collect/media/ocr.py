"""OCR de frame e de imagem.

Em peça de propaganda e em meme político, o texto na tela é a carga útil e quase
nunca coincide com a fala: é onde entram o número grande sem fonte, a estatística
com asterisco e a letra miúda que qualifica a afirmação por dois segundos.
Transcrever pega um canal; isto pega o segundo.

Usa o framework Vision da Apple via `ocrmac` — lê português bem, roda local e não
exige baixar modelo. `tesseract` com `por` fica como alternativa portável.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Abaixo disto o Vision costuma estar lendo textura, não texto.
CONFIANCA_MINIMA = 0.4


@dataclass
class Achado:
    texto: str
    confianca: float
    caixa: tuple[float, float, float, float]   # x, y, largura, altura, normalizado


def ler(imagem: Path, idiomas: tuple[str, ...] = ("pt-BR", "en-US"),
        minimo: float = CONFIANCA_MINIMA) -> list[Achado]:
    from ocrmac import ocrmac

    bruto = ocrmac.OCR(str(imagem), language_preference=list(idiomas)).recognize()
    achados = []
    for texto, conf, caixa in bruto:
        t = texto.strip()
        if t and conf >= minimo:
            achados.append(Achado(t, round(float(conf), 3), tuple(caixa)))
    return achados


def texto(achados: list[Achado]) -> str:
    """Junta na ordem de leitura: de cima para baixo, da esquerda para a direita.

    O Vision devolve por região, e a ordem bruta não é a de leitura. Em meme, com
    manchete em cima e ressalva embaixo, a ordem muda o sentido.
    """
    def chave(a: Achado):
        x, y, _, _ = a.caixa
        return (-round(y, 2), round(x, 2))   # y cresce para cima no Vision

    return "\n".join(a.texto for a in sorted(achados, key=chave))


def divergente(achados: list[Achado], transcricao_texto: str,
               minimo_palavras: int = 3, sobreposicao: float = 0.6) -> list[Achado]:
    """Separa grafismo de tela da legenda queimada.

    Em HGPE boa parte do que o OCR lê é legenda, que repete o áudio palavra por
    palavra. Isso importa: a hipótese multimodal do projeto é que a tela afirma
    o que a fala não afirma, e sem separar os dois a análise fica dominada por
    legenda dizendo exatamente o que foi dito.

    Devolve só o que não aparece na transcrição — nome, cargo, número de
    partido, estatística sobreposta, ressalva em letra miúda.

    Limitação declarada: depende da transcrição estar completa. Onde o Whisper
    perde fala, a legenda correspondente é classificada como grafismo.
    """
    # Comparação sem acento nem pontuação: o OCR lê "Dourados," e o Whisper
    # produz "Dourados." — com casamento literal, legenda idêntica escapava do
    # filtro e 96% do que era legenda passava como grafismo.
    from ..dedup import normalizar

    fala = set(normalizar(transcricao_texto).split())
    saida = []
    for a in achados:
        palavras = normalizar(a.texto).split()
        if len(palavras) < minimo_palavras:
            saida.append(a)          # curto demais para ser legenda
            continue
        # Sobreposição de palavras, não casamento literal: onde o Whisper perde
        # ou parafraseia um trecho, a legenda correspondente pareceria grafismo
        # e viraria falso positivo para a hipótese multimodal.
        fracao = sum(1 for w in palavras if w in fala) / len(palavras)
        if fracao < sobreposicao:
            saida.append(a)
    return saida
