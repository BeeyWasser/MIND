"""Snapshot público do DOU 2025–2026, derivado do INLABS e publicado em CC0."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import httpx

from ..http import UA
from ..paths import corpus_path
from ..schema import Documento
from .dou import FONTE_OFICIAL, pertinente

API = "https://datasets-server.huggingface.co/rows"
DATASET = "dataseek/ptbr-dou"
PAGINA = 100
FONTE_DATASET = "https://huggingface.co/datasets/dataseek/ptbr-dou"
PARQUET_URL = f"{FONTE_DATASET}/resolve/main/data/data_0.parquet"
PARQUET = corpus_path("_datasets", "ptbr-dou.parquet")


def para_documento(linha: dict) -> Documento | None:
    texto = str(linha.get("text") or "").strip()
    titulo = str(linha.get("titulo") or linha.get("identifica") or "").strip()
    orgao = str(linha.get("art_category") or "").strip()
    if len(texto) < 80 or not pertinente(titulo, orgao, texto):
        return None
    publicado = str(linha.get("pub_date") or "")
    try:
        publicado = datetime.fromisoformat(publicado).date().isoformat()
    except ValueError:
        publicado = None
    id_materia = str(linha.get("id_materia") or linha.get("article_id") or "")
    return Documento(
        fonte="dou",
        url=str(linha.get("pdf_url") or f"{FONTE_DATASET}#{id_materia}"),
        titulo=titulo,
        texto=texto,
        canal="dou",
        modalidade="texto",
        eleicao="2026",
        veiculado_em=publicado,
        licenca_uso="livre",
        metadados={
            "origem": "dataseek_ptbr_dou",
            "id_materia": id_materia,
            "article_id": linha.get("article_id"),
            "secao": linha.get("pub_name"),
            "edicao": linha.get("edition_number"),
            "pagina": linha.get("page_number"),
            "orgao": orgao,
            "tipo_ato": linha.get("art_type"),
            "ementa": linha.get("ementa"),
            "fonte_dataset": FONTE_DATASET,
            "fonte_oficial": FONTE_OFICIAL,
            "licenca_dataset": "CC0-1.0",
        },
    )


def _baixar_parquet(caminho: Path = PARQUET) -> Path:
    if caminho.exists() and caminho.stat().st_size > 0:
        return caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(".parquet.tmp")
    with httpx.stream(
        "GET", PARQUET_URL, headers={"User-Agent": UA}, follow_redirects=True, timeout=300
    ) as resposta:
        resposta.raise_for_status()
        with open(temporario, "wb") as arquivo:
            for pedaco in resposta.iter_bytes(1 << 20):
                arquivo.write(pedaco)
    temporario.replace(caminho)
    return caminho


def _lote_parquet(inicio: int, limite: int) -> tuple[list[Documento], int, int]:
    import pyarrow.parquet as parquet

    caminho = _baixar_parquet()
    arquivo = parquet.ParquetFile(caminho)
    total = arquivo.metadata.num_rows
    quantidade = min(limite, max(0, total - inicio))
    if not quantidade:
        return [], inicio, total
    linhas = parquet.read_table(caminho).slice(inicio, quantidade).to_pylist()
    documentos = [doc for linha in linhas if (doc := para_documento(linha)) is not None]
    return documentos, inicio + len(linhas), total


def _lote_api(inicio: int, limite: int) -> tuple[list[Documento], int, int]:
    documentos: list[Documento] = []
    cursor = inicio
    total = inicio
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=60) as cliente:
        while cursor - inicio < limite:
            tamanho = min(PAGINA, limite - (cursor - inicio))
            for _tentativa in range(3):
                resposta = cliente.get(
                    API,
                    params={
                        "dataset": DATASET,
                        "config": "default",
                        "split": "train",
                        "offset": cursor,
                        "length": tamanho,
                    },
                )
                if resposta.status_code != 429:
                    resposta.raise_for_status()
                    break
                time.sleep(min(float(resposta.headers.get("Retry-After", 10)), 60))
            else:
                return documentos, cursor, total
            dados = resposta.json()
            total = int(dados["num_rows_total"])
            linhas = [item["row"] for item in dados.get("rows", [])]
            if not linhas:
                break
            documentos.extend(doc for linha in linhas if (doc := para_documento(linha)) is not None)
            cursor += len(linhas)
            if cursor >= total:
                break
            time.sleep(1.5)
    return documentos, cursor, total


def lote(inicio: int, limite: int) -> tuple[list[Documento], int, int]:
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return _lote_api(inicio, limite)
    return _lote_parquet(inicio, limite)
