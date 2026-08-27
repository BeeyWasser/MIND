"""Deduplicação em três níveis.

Em escala de milhões, com meme e anúncio, isto deixa de ser refinamento e vira
requisito de validade. Anúncio se repete às centenas com variação mínima de
segmentação; meme circula como recodificação, recorte, recompressão e captura de
tela de captura de tela. Sem tratar, o corpus tem milhões de linhas e uma fração
disso em peças únicas — o modelo decora repetição em vez de aprender técnica, e
a métrica reportada fica inflada.

Níveis: sha256 para idêntico, MinHash/LSH para texto quase idêntico, hash
perceptual para imagem. Ver COLETA.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from datasketch import MinHash, MinHashLSH

NUM_PERM = 128
LIMIAR_TEXTO = 0.85   # calibrar contra lote conferido à mão antes do corpus todo
SHINGLE = 5           # palavras por shingle


def normalizar(texto: str) -> str:
    """Tira acento, caixa e pontuação. Variação de acentuação não é peça nova."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def shingles(texto: str, n: int = SHINGLE) -> set[str]:
    palavras = normalizar(texto).split()
    if len(palavras) < n:
        return {" ".join(palavras)} if palavras else set()
    return {" ".join(palavras[i:i + n]) for i in range(len(palavras) - n + 1)}


def assinatura(texto: str, num_perm: int = NUM_PERM) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for s in shingles(texto):
        m.update(s.encode())
    return m


class IndiceTexto:
    """LSH sobre MinHash. Diz se já existe algo quase igual no corpus."""

    def __init__(self, limiar: float = LIMIAR_TEXTO, num_perm: int = NUM_PERM):
        self.limiar = limiar
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=limiar, num_perm=num_perm)
        self._n = 0

    def parecidos(self, texto: str) -> list[str]:
        return list(self.lsh.query(assinatura(texto, self.num_perm)))

    def adicionar(self, chave: str, texto: str) -> bool:
        """Insere. Devolve False se já havia peça quase idêntica."""
        m = assinatura(texto, self.num_perm)
        if self.lsh.query(m):
            return False
        self.lsh.insert(chave, m)
        self._n += 1
        return True

    def __len__(self) -> int:
        return self._n


def phash_imagem(caminho) -> str:
    """Hash perceptual. Sobrevive a recompressão, recorte leve e redimensionamento."""
    import imagehash
    from PIL import Image

    with Image.open(caminho) as img:
        return str(imagehash.phash(img))


def distancia(a: str, b: str) -> int:
    """Hamming entre dois hashes perceptuais em hexadecimal."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def parecidas(alvo: str, conhecidos: Iterable[str], limite: int = 8) -> list[str]:
    """Imagens perceptualmente próximas. Limite 8 em 64 bits é o usual para
    'mesma imagem, outra codificação'."""
    return [h for h in conhecidos if distancia(alvo, h) <= limite]
