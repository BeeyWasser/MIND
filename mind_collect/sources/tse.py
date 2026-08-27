"""Registro de candidaturas do TSE — a semente de todo o resto.

Define quais canais monitorar no YouTube, quais páginas enumerar na Biblioteca
de Anúncios e contra que lista casar entidades no texto coletado.

O download automático não é possível: o Akamai do TSE devolve 403 para esta
faixa de IP, e o bloqueio é de rede, não de cliente — Playwright com Chromium
real recebe o mesmo 403. Contornar exigiria proxy, que está fora do escopo do
projeto por decisão registrada em COLETA.md.

Então o arquivo entra à mão, uma vez:

    1. https://dadosabertos.tse.jus.br/dataset/candidatos-2026
    2. Baixar `consulta_cand_2026.zip` e `rede_social_candidato_2026.zip`
    3. Deixar os dois em data/eleicoes2026/_tse/

Daqui para a frente é automático.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

DIR = Path("data/eleicoes2026/_tse")

PLATAFORMAS = {
    "youtube.com": "youtube", "youtu.be": "youtube",
    "instagram.com": "instagram", "tiktok.com": "tiktok",
    "facebook.com": "facebook", "fb.com": "facebook",
    "twitter.com": "twitter", "x.com": "twitter",
    "t.me": "telegram", "kwai": "kwai",
}


@dataclass
class Candidato:
    sq: str                      # SQ_CANDIDATO, chave do TSE
    nome: str
    nome_urna: str
    partido: str
    cargo: str
    uf: str
    situacao: str = ""
    redes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def apto(self) -> bool:
        # Igualdade, não substring: "INAPTO" contém "APTO" e o teste pegou
        # candidatura inapta entrando na lista de sementes.
        return self.situacao.strip().upper() == "APTO"


def _tabela(zip_path: Path) -> Iterator[dict]:
    """Lê o CSV de dentro do ZIP do TSE: separador ponto-e-vírgula, latin-1."""
    with zipfile.ZipFile(zip_path) as z:
        alvos = [n for n in z.namelist() if n.upper().endswith(".CSV") and "BRASIL" in n.upper()]
        if not alvos:
            alvos = [n for n in z.namelist() if n.upper().endswith(".CSV")]
        for nome in alvos:
            with z.open(nome) as f:
                texto = io.TextIOWrapper(f, encoding="latin-1", newline="")
                yield from csv.DictReader(texto, delimiter=";")


def _plataforma(url: str) -> str | None:
    u = url.lower()
    for chave, nome in PLATAFORMAS.items():
        if chave in u:
            return nome
    return None


def carregar(diretorio: Path = DIR) -> dict[str, Candidato]:
    """Monta o registro. Devolve vazio, sem erro, se os ZIPs não estiverem lá."""
    cand_zip = next(diretorio.glob("consulta_cand*.zip"), None)
    if not cand_zip:
        return {}

    registro: dict[str, Candidato] = {}
    for linha in _tabela(cand_zip):
        sq = (linha.get("SQ_CANDIDATO") or "").strip()
        if not sq:
            continue
        registro[sq] = Candidato(
            sq=sq,
            nome=(linha.get("NM_CANDIDATO") or "").strip(),
            nome_urna=(linha.get("NM_URNA_CANDIDATO") or "").strip(),
            partido=(linha.get("SG_PARTIDO") or "").strip(),
            cargo=(linha.get("DS_CARGO") or "").strip(),
            uf=(linha.get("SG_UF") or "").strip(),
            situacao=(linha.get("DS_SITUACAO_CANDIDATURA") or "").strip(),
        )

    redes_zip = next(diretorio.glob("rede_social*.zip"), None)
    if redes_zip:
        for linha in _tabela(redes_zip):
            sq = (linha.get("SQ_CANDIDATO") or "").strip()
            url = (linha.get("DS_URL") or "").strip()
            if not (sq in registro and url):
                continue
            if plat := _plataforma(url):
                registro[sq].redes.setdefault(plat, []).append(url)
    return registro


def contas(registro: dict[str, Candidato], plataforma: str,
           cargos: tuple[str, ...] = ("PRESIDENTE", "GOVERNADOR", "SENADOR")) -> list[str]:
    """URLs declaradas numa plataforma, filtradas por cargo.

    Deputado é a maior parte das candidaturas e estoura qualquer orçamento de
    coleta; presidente, governador e senador cabem e concentram a propaganda.
    """
    saida: list[str] = []
    for c in registro.values():
        if not c.apto or not any(k in c.cargo.upper() for k in cargos):
            continue
        saida += c.redes.get(plataforma, [])
    return sorted(set(saida))


def resumo(registro: dict[str, Candidato]) -> str:
    if not registro:
        return (f"registro vazio — ver instruções no topo de {__file__.split('/')[-1]}; "
                f"deixe os ZIPs em {DIR}")
    aptos = sum(1 for c in registro.values() if c.apto)
    com_rede = sum(1 for c in registro.values() if c.redes)
    por_plat: dict[str, int] = {}
    for c in registro.values():
        for p in c.redes:
            por_plat[p] = por_plat.get(p, 0) + 1
    plats = ", ".join(f"{p}={n}" for p, n in sorted(por_plat.items(), key=lambda x: -x[1]))
    return (f"{len(registro)} candidaturas, {aptos} aptas, {com_rede} com rede declarada\n"
            f"  {plats}")
