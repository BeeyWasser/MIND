"""Spots oficiais de rádio publicados pelo TSE para as Eleições 2026."""

from __future__ import annotations

import contextlib
import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..media.transcribe import transcrever
from ..paths import corpus_path
from ..schema import Documento, Segmento

PAGINA = (
    "https://www.tse.jus.br/eleicoes/eleicoes-2026-content/"
    "propaganda-eleitoral-gratuita-eleicoes-2026/mapas-de-midia-e-spots-de-radio"
)
PAGINA_TEXTO = "https://r.jina.ai/http://" + PAGINA.removeprefix("https://")
MIDIA = corpus_path("_midia", "tse-radio")
LINK = re.compile(r"\[([^\]]+)\]\((https://www\.tse\.jus\.br/[^)]+)\)", re.I)
PECA = re.compile(r"\b(spot|bio|fb[-_ ]?\d+)\b", re.I)
EXCLUIR = re.compile(r"\b(mapa|claquete)\b", re.I)

PARTIDOS = {
    "avante": "AVANTE",
    "psd": "PSD",
    "pl-partido-liberal": "PL",
    "pt-prontos-pra-mais": "Brasil Pronto pra Mais",
}


def descobrir(markdown: str) -> list[tuple[str, str, str]]:
    saida: list[tuple[str, str, str]] = []
    vistos: set[str] = set()
    for titulo, url in LINK.findall(markdown):
        if "/arquivos-partidos/" not in url or url in vistos:
            continue
        if not PECA.search(titulo) or EXCLUIR.search(titulo):
            continue
        partes = [parte for parte in urlsplit(url).path.split("/") if parte]
        try:
            slug = partes[partes.index("arquivos-partidos") + 1]
        except (ValueError, IndexError):
            slug = "desconhecido"
        vistos.add(url)
        saida.append((titulo.strip(), url, PARTIDOS.get(slug, slug)))
    return saida


def _data(url: str) -> str | None:
    if achado := re.search(r"/(\d{2})-(\d{2})/", url):
        dia, mes = achado.groups()
        return f"2026-{mes}-{dia}T00:00:00+00:00"
    return None


def _baixar(cliente: httpx.Client, url: str, destino: Path) -> Path | None:
    resposta = cliente.get(url, timeout=60)
    if not resposta.is_success:
        return None
    conteudo = resposta.content
    tipo = resposta.headers.get("content-type", "").lower()
    if "audio" not in tipo and not conteudo.startswith((b"ID3", b"\xff\xfb", b"\xff\xf3")):
        return None
    destino.mkdir(parents=True, exist_ok=True)
    nome = hashlib.sha256(url.encode()).hexdigest()[:24] + ".mp3"
    caminho = destino / nome
    temporario = caminho.with_suffix(".tmp")
    temporario.write_bytes(conteudo)
    temporario.replace(caminho)
    return caminho


def coletar(destino: Path = MIDIA) -> Iterator[tuple[Documento, list[Segmento]]]:
    cabecalho = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)"}
    with httpx.Client(headers=cabecalho, follow_redirects=True) as cliente:
        pagina = cliente.get(PAGINA_TEXTO, timeout=60)
        pagina.raise_for_status()
        for titulo, url, partido in descobrir(pagina.text):
            audio = None
            with contextlib.suppress(httpx.HTTPError, OSError):
                audio = _baixar(cliente, url, destino)
            segmentos: list[Segmento] = []
            if audio:
                with contextlib.suppress(Exception):
                    segmentos = transcrever(audio)
            publicado = _data(url)
            yield (
                Documento(
                    fonte="hgpe_insercao",
                    url=url,
                    titulo=titulo,
                    canal="radio",
                    modalidade="audio",
                    eleicao="2026",
                    veiculado_em=publicado,
                    patrocinador=partido,
                    licenca_uso="referencia",
                    metadados={
                        "origem": "tse_spots_radio_2026",
                        "pagina_oficial": PAGINA,
                        "audio_local": str(audio) if audio else None,
                        "descoberto_em": datetime.now(UTC).isoformat(timespec="seconds"),
                    },
                ),
                segmentos,
            )
