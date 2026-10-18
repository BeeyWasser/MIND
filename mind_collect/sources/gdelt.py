"""GDELT — descoberta em massa pelos arquivos brutos, não pela DOC API.

A DOC API impõe uma requisição a cada cinco segundos e, na prática, devolve 429
mesmo respeitando isso. Os arquivos brutos são a rota feita para volume: o GDELT
publica um pacote a cada 15 minutos, sem chave e sem limite.

Duas trilhas: a padrão é só inglês; o conteúdo brasileiro está na translingual
(`lastupdate-translation.txt`), que traz cerca de 54 registros de domínio .br por
janela — algo como 5 mil por dia.

O GDELT não entrega texto, por questão de direito autoral. Entrega URL, tema,
entidade, localização e tom. Serve para descobrir o que existe; o texto vem do
Common Crawl ou do coletor próprio.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta

import httpx

from ..schema import Documento, eleicao_de

BASE = "http://data.gdeltproject.org/gdeltv2"
ULTIMO = f"{BASE}/lastupdate-translation.txt"

# Colunas do GKG 2.1 confirmadas contra um registro brasileiro real.
COL_DATA, COL_DOMINIO, COL_URL = 1, 3, 4
COL_TEMAS, COL_LOCAIS, COL_PESSOAS, COL_ORGS, COL_TOM = 7, 9, 11, 13, 15

DOMINIO_BR = re.compile(r"\.br$|\.br/|\.com\.br")

# Temas eleitorais do GDELT. Estreito de propósito: GOVERNMENT, LEGISLATION e
# POLICY aparecem em quase tudo — no primeiro teste o filtro largo trouxe vagas
# de emprego em Cuiabá e IPO da Shein junto com matéria de campanha.
TEMAS_ELEITORAIS = re.compile(
    r"ELECTION|ELECTORAL|VOTE|VOTING|BALLOT|CAMPAIGN_FINANCE|DEMOCRACY|"
    r"POLITICAL_PARTY|PROPAGANDA|DISINFORMATION|FAKE_NEWS|CORRUPTION",
    re.IGNORECASE,
)

# O caminho da URL costuma ser sinal mais confiável que o tema: veículo põe a
# matéria em /eleicoes/ ou /politica/ quando ela é disso.
URL_POLITICA = re.compile(r"/(eleico|eleic|politica|poder|campanha)", re.IGNORECASE)


def janelas(de: datetime, ate: datetime) -> Iterator[str]:
    """URLs dos pacotes de 15 em 15 minutos, para varrer histórico."""
    t = de.replace(minute=(de.minute // 15) * 15, second=0, microsecond=0)
    while t <= ate:
        yield f"{BASE}/{t:%Y%m%d%H%M%S}.translation.gkg.csv.zip"
        t += timedelta(minutes=15)


def _atual() -> str | None:
    r = httpx.get(ULTIMO, timeout=30, follow_redirects=True)
    r.raise_for_status()
    for linha in r.text.strip().split("\n"):
        if "gkg" in linha:
            return linha.split()[-1]
    return None


def _registros(url: str) -> Iterator[list[str]]:
    try:
        r = httpx.get(url, timeout=180, follow_redirects=True)
        if r.status_code != 200:
            return
        z = zipfile.ZipFile(io.BytesIO(r.content))
    except (httpx.HTTPError, zipfile.BadZipFile):
        return
    bruto = z.read(z.namelist()[0]).decode("utf-8", "replace")
    for linha in bruto.split("\n"):
        campos = linha.split("\t")
        if len(campos) > COL_TOM:
            yield campos


def coletar(pacotes: list[str] | None = None, so_politico: bool = True) -> Iterator[Documento]:
    """Descobre URLs brasileiras. Sem `pacotes`, usa o mais recente."""
    if pacotes is None:
        atual = _atual()
        pacotes = [atual] if atual else []

    for pacote in pacotes:
        for c in _registros(pacote):
            dominio, url, temas = c[COL_DOMINIO], c[COL_URL], c[COL_TEMAS]
            if not DOMINIO_BR.search(dominio) or not url.startswith("http"):
                continue
            if so_politico and not (TEMAS_ELEITORAIS.search(temas) or URL_POLITICA.search(url)):
                continue
            data = c[COL_DATA]
            iso = f"{data[:4]}-{data[4:6]}-{data[6:8]}" if len(data) >= 8 else None
            yield Documento(
                fonte="noticia",
                url=url,
                titulo="",
                texto="",  # GDELT não entrega texto — só descoberta
                canal="web",
                modalidade="texto",
                eleicao=eleicao_de(iso),
                veiculado_em=iso,
                metadados={
                    "origem": "gdelt",
                    "dominio": dominio,
                    "temas": temas.split(";")[:12],
                    "pessoas": c[COL_PESSOAS].split(";")[:10],
                    "organizacoes": c[COL_ORGS].split(";")[:10],
                    "locais": c[COL_LOCAIS][:300],
                    "tom": c[COL_TOM].split(",")[0] if c[COL_TOM] else None,
                },
            )
