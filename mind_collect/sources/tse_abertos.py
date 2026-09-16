"""Conjuntos abertos do TSE relevantes para propaganda eleitoral em 2026.

Baixa os ZIPs oficiais e aceita um espelho explícito quando o CDN do TSE
bloqueia a rede local. Os arquivos brutos são preservados; CSVs analíticos são
convertidos em documentos de referência, nunca em exemplos de treino.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ..http import UA
from ..paths import corpus_path
from ..schema import Documento

DIR = corpus_path("_tse_abertos")
ATUALIZAR_APOS_HORAS = 20


@dataclass(frozen=True)
class Recurso:
    chave: str
    conjunto: str
    nome: str
    url: str
    fonte: str
    importar: bool = True

    @property
    def arquivo(self) -> str:
        return Path(urlsplit(self.url).path).name


def _recurso(
    chave: str, conjunto: str, nome: str, caminho: str, fonte: str, importar: bool = True
) -> Recurso:
    return Recurso(
        chave,
        conjunto,
        nome,
        f"https://cdn.tse.jus.br/estatistica/sead/odsele/{caminho}",
        fonte,
        importar,
    )


RECURSOS_ESTRUTURADOS = (
    _recurso(
        "processos",
        "processual-2026",
        "Processo Eleitoral",
        "processual/processo_eleitoral_2026.zip",
        "tse_decisao",
    ),
    _recurso(
        "assuntos",
        "processual-2026",
        "Assuntos",
        "processual/processos_eleitorais_assuntos_2026.zip",
        "tse_decisao",
    ),
    _recurso(
        "decisoes",
        "processual-2026",
        "Decisões",
        "processual/processos_eleitorais_decisoes_2026.zip",
        "tse_decisao",
    ),
    _recurso(
        "partes",
        "processual-2026",
        "Partes",
        "processual/processos_eleitorais_partes_2026.zip",
        "tse_decisao",
    ),
    _recurso(
        "pardal",
        "denuncias-eleitorais",
        "Denúncias do Pardal",
        "denuncia/denuncia_2026.zip",
        "tse_denuncia",
    ),
    _recurso(
        "pesquisas",
        "pesquisas-eleitorais-2026",
        "Pesquisas eleitorais",
        "pesquisa_eleitoral/pesquisa_eleitoral_2026.zip",
        "tse_pesquisa",
    ),
    _recurso(
        "pesquisas-contratantes",
        "pesquisas-eleitorais-2026",
        "Contratantes",
        "pesquisa_eleitoral/pesquisa_contratante_2026.zip",
        "tse_pesquisa",
    ),
    _recurso(
        "pesquisas-pagantes",
        "pesquisas-eleitorais-2026",
        "Pagantes",
        "pesquisa_eleitoral/pesquisa_pagante_2026.zip",
        "tse_pesquisa",
    ),
    _recurso(
        "pesquisas-notas",
        "pesquisas-eleitorais-2026",
        "Notas fiscais",
        "pesquisa_eleitoral/nota_fiscal_2026.zip",
        "tse_pesquisa",
        False,
    ),
    _recurso(
        "pesquisas-questionarios",
        "pesquisas-eleitorais-2026",
        "Questionários",
        "pesquisa_eleitoral/questionario_pesquisa_2026.zip",
        "tse_pesquisa",
        False,
    ),
    _recurso(
        "pesquisas-localidades",
        "pesquisas-eleitorais-2026",
        "Localidades",
        "pesquisa_eleitoral/bairro_municipio_2026.zip",
        "tse_pesquisa",
        False,
    ),
    _recurso(
        "contas-cnpj",
        "prestacao-de-contas-eleitorais-2026",
        "CNPJ de campanha",
        "prestacao_contas/CNPJ_campanha_2026.zip",
        "tse_financas",
        False,
    ),
    _recurso(
        "contas-partidos",
        "prestacao-de-contas-eleitorais-2026",
        "Contas partidárias",
        "prestacao_contas/prestacao_de_contas_eleitorais_orgaos_partidarios_2026.zip",
        "tse_financas",
    ),
    _recurso(
        "contas-candidatos",
        "prestacao-de-contas-eleitorais-2026",
        "Contas de candidatos",
        "prestacao_contas/prestacao_de_contas_eleitorais_candidatos_2026.zip",
        "tse_financas",
    ),
    _recurso(
        "extratos-partidos",
        "prestacao-de-contas-eleitorais-2026",
        "Extratos de partidos",
        "prestacao_contas_anual_partidaria/extrato_bancario_partido_2026.zip",
        "tse_financas",
        False,
    ),
    _recurso(
        "extratos-candidatos",
        "prestacao-de-contas-eleitorais-2026",
        "Extratos de candidatos",
        "prestacao_contas_anual_candidato/extrato_bancario_candidato_2026.zip",
        "tse_financas",
        False,
    ),
)

UFS = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "BR",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
)

RECURSOS_PROPOSTAS = tuple(
    _recurso(
        f"propostas-{uf.lower()}",
        "candidatos-2026",
        f"{uf} - Propostas de governo",
        f"proposta_governo/proposta_governo_2026_{uf}.zip",
        "tse_proposta",
        False,
    )
    for uf in UFS
)

RECURSOS_FOTOS = tuple(
    Recurso(
        f"fotos-{uf.lower()}",
        "candidatos-2026",
        f"{uf} - Fotos de candidatos",
        (
            "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/"
            f"fotos/foto_cand2026_{uf}_div.zip"
        ),
        "tse_registro",
        False,
    )
    for uf in UFS
)

RECURSOS = RECURSOS_ESTRUTURADOS + RECURSOS_PROPOSTAS + RECURSOS_FOTOS


def _fresco(diretorio: Path) -> bool:
    manifesto = diretorio / "_origem.json"
    if not manifesto.exists():
        return False
    try:
        dados = json.loads(manifesto.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    chaves = {item.get("chave") for item in dados.get("recursos", [])}
    return chaves == {recurso.chave for recurso in RECURSOS} and (
        time.time() - manifesto.stat().st_mtime < ATUALIZAR_APOS_HORAS * 3600
    )


def _espelho(recurso: Recurso) -> str | None:
    base = os.environ.get("MIND_TSE_MIRROR_BASE", "").strip().rstrip("/")
    return f"{base}/{recurso.arquivo}" if base else None


def atualizar(diretorio: Path = DIR, forcar: bool = False) -> dict:
    if not forcar and _fresco(diretorio):
        return json.loads((diretorio / "_origem.json").read_text())
    diretorio.mkdir(parents=True, exist_ok=True)
    resultados: list[dict] = []
    cdn_bloqueado = False
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True, timeout=30) as cliente:
        for recurso in RECURSOS:
            destino = diretorio / recurso.arquivo
            candidatos = (None if cdn_bloqueado else recurso.url), _espelho(recurso)
            urls = [url for url in candidatos if url]
            estado = "mantido" if destino.exists() else "indisponivel"
            origem = None
            erro = ""
            for url in urls:
                try:
                    resposta = cliente.get(url)
                    if resposta.status_code == 403 and "cdn.tse.jus.br" in url:
                        cdn_bloqueado = True
                    resposta.raise_for_status()
                    if not zipfile.is_zipfile(io.BytesIO(resposta.content)):
                        raise ValueError("conteúdo não é ZIP")
                    anterior = destino.read_bytes() if destino.exists() else None
                    if anterior != resposta.content:
                        temporario = destino.with_suffix(".zip.tmp")
                        temporario.write_bytes(resposta.content)
                        temporario.replace(destino)
                        estado = "baixado"
                    else:
                        estado = "inalterado"
                    origem = url
                    erro = ""
                    break
                except (httpx.HTTPError, OSError, ValueError) as excecao:
                    erro = f"{type(excecao).__name__}: {excecao}"[:240]
            resultados.append(
                {
                    "chave": recurso.chave,
                    "arquivo": recurso.arquivo,
                    "estado": estado,
                    "origem": origem,
                    "erro": erro,
                }
            )
    manifesto = {
        "atualizado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "licenca": "CC-BY",
        "cdn_bloqueado": cdn_bloqueado,
        "espelho_configurado": bool(os.environ.get("MIND_TSE_MIRROR_BASE")),
        "recursos": resultados,
    }
    (diretorio / "_origem.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifesto


def arquivos(diretorio: Path = DIR) -> Iterator[tuple[Recurso, Path]]:
    for recurso in RECURSOS:
        caminho = diretorio / recurso.arquivo
        if recurso.importar and caminho.exists():
            yield recurso, caminho


def arquivos_propostas(diretorio: Path = DIR) -> Iterator[tuple[Recurso, Path]]:
    for recurso in RECURSOS_PROPOSTAS:
        caminho = diretorio / recurso.arquivo
        if caminho.exists():
            yield recurso, caminho


def _linhas(caminho: Path) -> Iterator[dict[str, str]]:
    with zipfile.ZipFile(caminho) as compactado:
        for nome in compactado.namelist():
            if not nome.lower().endswith(".csv"):
                continue
            with compactado.open(nome) as bruto:
                texto = io.TextIOWrapper(bruto, encoding="latin-1", errors="replace", newline="")
                amostra = texto.read(8192)
                texto.seek(0)
                try:
                    separador = csv.Sniffer().sniff(amostra, delimiters=";,\t").delimiter
                except csv.Error:
                    separador = ";"
                yield from csv.DictReader(texto, delimiter=separador)


def _primeiro(linha: dict[str, str], *nomes: str) -> str | None:
    for nome in nomes:
        if valor := linha.get(nome):
            return valor.strip()
    return None


def _documento(recurso: Recurso, linha: dict[str, str]) -> Documento | None:
    campos = {chave: (valor or "").strip() for chave, valor in linha.items() if chave}
    valores = [f"{chave}: {valor}" for chave, valor in campos.items() if valor]
    if not valores:
        return None
    resumo = "\n".join(valores)
    identificador = hashlib.sha256(resumo.encode()).hexdigest()[:20]
    return Documento(
        fonte=recurso.fonte,
        url=f"{recurso.url}#{identificador}",
        titulo=f"{recurso.nome} — registro {identificador}",
        texto=resumo,
        canal="tse",
        modalidade="texto",
        eleicao="2026",
        candidato_id=_primeiro(campos, "SQ_CANDIDATO"),
        partido=_primeiro(campos, "SG_PARTIDO", "SG_PARTIDO_DENUNCIADO"),
        cargo=_primeiro(campos, "DS_CARGO", "DS_CARGO_DENUNCIADO"),
        licenca_uso="referencia",
        metadados={
            "conjunto": recurso.conjunto,
            "recurso": recurso.chave,
            "registro": campos,
            "fonte_oficial": f"https://dadosabertos.tse.jus.br/dataset/{recurso.conjunto}",
            "aviso": "denúncia ou registro não implica irregularidade confirmada"
            if recurso.fonte == "tse_denuncia"
            else None,
        },
    )


def lote(recurso: Recurso, caminho: Path, inicio: int, limite: int) -> tuple[list[Documento], int]:
    documentos: list[Documento] = []
    proximo = inicio
    for indice, linha in enumerate(_linhas(caminho)):
        if indice < inicio:
            continue
        if len(documentos) >= limite:
            break
        proximo = indice + 1
        if doc := _documento(recurso, linha):
            documentos.append(doc)
    return documentos, proximo


def _texto_pdf(conteudo: bytes) -> str:
    if not shutil.which("pdftotext"):
        raise RuntimeError(
            "pdftotext não encontrado; instale o Poppler para coletar propostas do TSE"
        )
    with tempfile.TemporaryDirectory(prefix="mind-tse-pdf-") as temporario:
        arquivo = Path(temporario) / "proposta.pdf"
        arquivo.write_bytes(conteudo)
        try:
            resultado = subprocess.run(
                ["pdftotext", "-layout", str(arquivo), "-"],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
    return resultado.stdout.decode("utf-8", "replace").strip()


def lote_propostas(
    recurso: Recurso, caminho: Path, inicio: int, limite: int
) -> tuple[list[Documento], int]:
    documentos: list[Documento] = []
    proximo = inicio
    with zipfile.ZipFile(caminho) as compactado:
        nomes = sorted(nome for nome in compactado.namelist() if nome.lower().endswith(".pdf"))
        for indice, nome in enumerate(nomes):
            if indice < inicio:
                continue
            if len(documentos) >= limite:
                break
            proximo = indice + 1
            texto = _texto_pdf(compactado.read(nome))
            if len(texto) < 100:
                continue
            numeros = [parte for parte in Path(nome).stem.split("_") if parte.isdigit()]
            candidato_id = max(numeros, key=len, default=None)
            documentos.append(
                Documento(
                    fonte="tse_proposta",
                    url=f"{recurso.url}#{nome}",
                    titulo=f"Proposta de governo — {Path(nome).stem}",
                    texto=texto,
                    canal="tse",
                    modalidade="texto",
                    eleicao="2026",
                    candidato_id=candidato_id,
                    licenca_uso="referencia",
                    metadados={
                        "conjunto": recurso.conjunto,
                        "recurso": recurso.chave,
                        "arquivo_pdf": nome,
                        "fonte_oficial": (
                            "https://dadosabertos.tse.jus.br/dataset/candidatos-2026"
                        ),
                    },
                )
            )
    return documentos, proximo
