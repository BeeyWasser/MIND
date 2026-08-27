"""Miniatura e hash perceptual.

O original nunca é guardado: um milhão de imagens a 200 KB dá 200 GB e não cabe
junto do resto. Por imagem ficam o hash perceptual, o texto do OCR, uma miniatura
de 256 px para revisão humana durante a anotação e a URL de origem para rebuscar
sob demanda — cerca de 20 KB, ou 20 GB por milhão.
"""

from __future__ import annotations

from pathlib import Path

LADO = 256


def miniatura(origem: Path, destino: Path, lado: int = LADO) -> Path | None:
    from PIL import Image

    destino.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(origem) as img:
            img = img.convert("RGB")
            img.thumbnail((lado, lado))
            img.save(destino, "JPEG", quality=72, optimize=True)
    except Exception:
        return None
    return destino


def hashes(origem: Path) -> tuple[str | None, str | None]:
    """pHash e dHash. Sobrevivem a recompressão, recorte leve e redimensionamento."""
    import imagehash
    from PIL import Image

    try:
        with Image.open(origem) as img:
            return str(imagehash.phash(img)), str(imagehash.dhash(img))
    except Exception:
        return None, None
