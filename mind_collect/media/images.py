"""Persistência compacta de imagens remotas para análise multimodal."""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path

import httpx

from ..paths import corpus_path
from ..schema import Midia
from .ocr import ler
from .ocr import texto as texto_ocr
from .thumbs import hashes, miniatura

DESTINO = corpus_path("_midia")


def processar_arquivo(
    doc_id: str,
    origem: Path,
    url_origem: str,
    indice: int = 0,
    destino: Path = DESTINO,
    alt: str | None = None,
) -> Midia:
    destino.mkdir(parents=True, exist_ok=True)
    phash, dhash = hashes(origem)
    ocr = ""
    with contextlib.suppress(Exception):
        ocr = texto_ocr(ler(origem))
    thumb = miniatura(
        origem,
        destino / "thumbs" / f"imagem-{doc_id[:16]}-{indice}.jpg",
    )
    return Midia(
        doc_id=doc_id,
        tipo="imagem",
        url_origem=url_origem,
        phash=phash,
        dhash=dhash,
        ocr_texto=ocr or alt or None,
        thumb_path=str(thumb) if thumb else None,
    )


def processar(
    doc_id: str,
    midias: list[dict],
    destino: Path = DESTINO,
    cliente: httpx.Client | None = None,
    referer: str | None = None,
) -> list[Midia]:
    proprio = cliente is None
    cliente = cliente or httpx.Client(follow_redirects=True, timeout=40)
    saida: list[Midia] = []
    try:
        for indice, item in enumerate(midias):
            if item.get("tipo") not in {None, "imagem"}:
                continue
            url = item.get("url") or item.get("thumb")
            if not url:
                continue
            temporario: Path | None = None
            try:
                cabecalho = {"Referer": referer} if referer else None
                resposta = cliente.get(url, headers=cabecalho)
                resposta.raise_for_status()
                destino.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=destino, suffix=".jpg", delete=False
                ) as arquivo:
                    arquivo.write(resposta.content)
                    temporario = Path(arquivo.name)
                saida.append(
                    processar_arquivo(
                        doc_id,
                        temporario,
                        url,
                        indice=indice,
                        destino=destino,
                        alt=item.get("alt"),
                    )
                )
            except (httpx.HTTPError, OSError):
                continue
            finally:
                if temporario:
                    temporario.unlink(missing_ok=True)
    finally:
        if proprio:
            cliente.close()
    return saida
