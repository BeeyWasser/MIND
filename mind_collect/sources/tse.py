"""Candidaturas e redes declaradas ao TSE em 2026.

O CDN oficial é tentado primeiro. Como o Akamai do TSE bloqueia a faixa de IP
desta máquina, há um fallback explícito para um espelho Git versionado dos CSVs
oficiais. A procedência usada em cada atualização fica em ``_origem.json``.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..paths import corpus_path
from ..schema import Documento

DIR = corpus_path("_tse")
OFICIAL = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ESPELHO = "https://raw.githubusercontent.com/leofn/tse-candidatos-2026/main/dados"
ATUALIZAR_APOS_HORAS = 20

RECURSOS = {
    "consulta_cand_2026_BRASIL.csv": (
        f"{OFICIAL}/consulta_cand/consulta_cand_2026.zip",
        f"{ESPELHO}/consulta_cand_2026_BRASIL.csv",
    ),
    "rede_social_candidato_2026_BRASIL.csv": (
        f"{OFICIAL}/consulta_cand/rede_social_candidato_2026.zip",
        f"{ESPELHO}/rede_social_candidato_2026_BRASIL.csv",
    ),
}

PLATAFORMAS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "t.me": "telegram",
    "kwai": "kwai",
    "bsky.app": "bluesky",
    "threads.com": "threads",
    "threads.net": "threads",
    "linkedin.com": "linkedin",
    "wa.me": "whatsapp",
    "whatsapp.com": "whatsapp",
    "linktr.ee": "linkhub",
    "tr.ee": "linkhub",
    "lnk.bio": "linkhub",
    "bio.site": "linkhub",
    "abre.bio": "linkhub",
    "bit.ly": "linkhub",
    "giphy.com": "giphy",
    "open.spotify.com": "spotify",
    "flickr.com": "flickr",
    "pinterest.com": "pinterest",
    "gettr.com": "gettr",
    "truthsocial.com": "truthsocial",
    "twitch.tv": "twitch",
    "soundcloud.com": "soundcloud",
}

SITUACOES_EXCLUIDAS = (
    "INAPTO",
    "INDEFERIDO",
    "CANCELADO",
    "CASSADO",
    "RENÚNCIA",
    "RENUNCIA",
    "FALECIDO",
    "NÃO CONHECIDO",
    "NAO CONHECIDO",
)


@dataclass
class Candidato:
    sq: str
    nome: str
    nome_urna: str
    partido: str
    cargo: str
    uf: str
    situacao: str = ""
    redes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def apto(self) -> bool:
        situacao = self.situacao.strip().upper()
        return not any(marca in situacao for marca in SITUACOES_EXCLUIDAS)


def precisa_atualizar(diretorio: Path = DIR) -> bool:
    agora = time.time()
    for nome in RECURSOS:
        caminho = diretorio / nome
        if not caminho.exists() or agora - caminho.stat().st_mtime > ATUALIZAR_APOS_HORAS * 3600:
            return True
    return False


def _csv_de_resposta(conteudo: bytes, nome: str) -> bytes:
    if conteudo[:2] != b"PK":
        return conteudo
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        candidatos = [
            item
            for item in z.namelist()
            if item.upper().endswith(".CSV") and "BRASIL" in item.upper()
        ]
        if not candidatos:
            candidatos = [item for item in z.namelist() if item.upper().endswith(".CSV")]
        if not candidatos:
            raise ValueError(f"ZIP sem CSV: {nome}")
        return z.read(candidatos[0])


def _valido(conteudo: bytes, nome: str) -> bool:
    cabecalho = conteudo[:1000].decode("latin-1", "replace")
    esperado = "SQ_CANDIDATO" if nome.startswith("consulta_cand") else "DS_URL"
    return esperado in cabecalho and conteudo.count(b"\n") > 100


def atualizar(diretorio: Path = DIR, forcar: bool = False) -> tuple[bool, dict[str, str]]:
    """Atualiza os dois CSVs. Devolve ``(mudou, origem_por_arquivo)``."""
    if not forcar and not precisa_atualizar(diretorio):
        return False, {}
    diretorio.mkdir(parents=True, exist_ok=True)
    mudou = False
    origens: dict[str, str] = {}
    cabecalho = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)"}
    with httpx.Client(headers=cabecalho, follow_redirects=True, timeout=180) as cliente:
        for nome, urls in RECURSOS.items():
            ultimo_erro: Exception | None = None
            for url in urls:
                try:
                    resposta = cliente.get(url)
                    resposta.raise_for_status()
                    conteudo = _csv_de_resposta(resposta.content, nome)
                    if not _valido(conteudo, nome):
                        raise ValueError(f"conteúdo inválido para {nome}")
                    destino = diretorio / nome
                    anterior = destino.read_bytes() if destino.exists() else None
                    if anterior != conteudo:
                        temporario = destino.with_suffix(destino.suffix + ".tmp")
                        temporario.write_bytes(conteudo)
                        temporario.replace(destino)
                        mudou = True
                    else:
                        destino.touch()
                    origens[nome] = url
                    break
                except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as erro:
                    ultimo_erro = erro
            else:
                if not (diretorio / nome).exists() and ultimo_erro:
                    raise ultimo_erro

    manifesto = {
        "atualizado_em": datetime.now(UTC).isoformat(timespec="seconds"),
        "fonte_oficial": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
        "licenca": "CC-BY",
        "origens": origens,
    }
    (diretorio / "_origem.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return mudou, origens


def _tabela(caminho: Path) -> Iterator[dict]:
    if caminho.suffix.lower() == ".csv":
        with open(caminho, encoding="latin-1", newline="") as arquivo:
            yield from csv.DictReader(arquivo, delimiter=";")
        return
    with zipfile.ZipFile(caminho) as z:
        alvos = [n for n in z.namelist() if n.upper().endswith(".CSV") and "BRASIL" in n.upper()]
        if not alvos:
            alvos = [n for n in z.namelist() if n.upper().endswith(".CSV")]
        for nome in alvos:
            with z.open(nome) as arquivo:
                texto = io.TextIOWrapper(arquivo, encoding="latin-1", newline="")
                yield from csv.DictReader(texto, delimiter=";")


def _plataforma(url: str) -> str | None:
    url = url.lower()
    for trecho, plataforma in PLATAFORMAS.items():
        if trecho in url:
            return plataforma
    host = urlsplit(url).netloc.removeprefix("www.")
    return "site" if "." in host and "@" not in host else None


def normalizar_url(url: str) -> str:
    url = url.strip().strip("\"'")
    if not url:
        return ""
    if achada := re.search(r"https?://[^\s\]]+", url, re.IGNORECASE):
        url = achada.group(0)
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    try:
        partes = urlsplit(url.rstrip(".,;:)]"))
    except ValueError:
        return ""
    if "@" in partes.netloc:
        return ""
    host = partes.netloc.lower()
    esquema = "https" if partes.scheme.lower() in {"http", "https"} else partes.scheme
    return urlunsplit((esquema, host, partes.path.rstrip("/"), "", ""))


def _achar(diretorio: Path, prefixo: str) -> Path | None:
    return next(diretorio.glob(f"{prefixo}*BRASIL.csv"), None) or next(
        diretorio.glob(f"{prefixo}*.zip"), None
    )


def carregar(diretorio: Path = DIR) -> dict[str, Candidato]:
    cand = _achar(diretorio, "consulta_cand_2026") or _achar(diretorio, "consulta_cand")
    if not cand:
        return {}
    registro: dict[str, Candidato] = {}
    for linha in _tabela(cand):
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

    redes = _achar(diretorio, "rede_social_candidato_2026") or _achar(diretorio, "rede_social")
    if redes:
        for linha in _tabela(redes):
            sq = (linha.get("SQ_CANDIDATO") or "").strip()
            url = normalizar_url(linha.get("DS_URL") or "")
            if not (sq in registro and url):
                continue
            if plataforma := _plataforma(url):
                registro[sq].redes.setdefault(plataforma, []).append(url)
    return registro


def candidatos_com_conta(
    registro: dict[str, Candidato],
    plataforma: str,
    cargos: tuple[str, ...] = ("PRESIDENTE", "GOVERNADOR", "SENADOR"),
) -> list[tuple[Candidato, str]]:
    saida: list[tuple[Candidato, str]] = []
    vistos: set[str] = set()
    for candidato in registro.values():
        if not candidato.apto or (
            cargos and not any(cargo in candidato.cargo.upper() for cargo in cargos)
        ):
            continue
        for url in candidato.redes.get(plataforma, []):
            if url not in vistos:
                vistos.add(url)
                saida.append((candidato, url))
    return sorted(saida, key=lambda item: (item[0].cargo, item[0].uf, item[0].sq, item[1]))


def contas(
    registro: dict[str, Candidato],
    plataforma: str,
    cargos: tuple[str, ...] = ("PRESIDENTE", "GOVERNADOR", "SENADOR"),
) -> list[str]:
    return [url for _, url in candidatos_com_conta(registro, plataforma, cargos)]


def documentos(registro: dict[str, Candidato]) -> Iterator[Documento]:
    for candidato in registro.values():
        redes = [url for urls in candidato.redes.values() for url in urls]
        yield Documento(
            fonte="tse_registro",
            url=f"https://divulgacandcontas.tse.jus.br/divulga/#/candidato/{candidato.sq}/2026",
            titulo=f"{candidato.nome_urna} — {candidato.cargo}",
            texto="\n".join(
                [candidato.nome, candidato.nome_urna, candidato.partido, candidato.cargo, *redes]
            ),
            canal="tse",
            modalidade="texto",
            eleicao="2026",
            candidato_id=candidato.sq,
            partido=candidato.partido,
            cargo=candidato.cargo,
            patrocinador=candidato.nome_urna,
            licenca_uso="referencia",
            metadados={
                "origem": "tse_candidaturas",
                "uf": candidato.uf,
                "situacao": candidato.situacao,
                "redes": candidato.redes,
                "fonte_oficial": "https://dadosabertos.tse.jus.br/dataset/candidatos-2026",
            },
        )


def resumo(registro: dict[str, Candidato]) -> str:
    if not registro:
        return f"registro vazio — rode --tse para baixar em {DIR}"
    aptos = sum(1 for candidato in registro.values() if candidato.apto)
    com_rede = sum(1 for candidato in registro.values() if candidato.redes)
    por_plataforma: dict[str, int] = {}
    for candidato in registro.values():
        for plataforma in candidato.redes:
            por_plataforma[plataforma] = por_plataforma.get(plataforma, 0) + 1
    plataformas = ", ".join(
        f"{plataforma}={quantidade}"
        for plataforma, quantidade in sorted(por_plataforma.items(), key=lambda item: -item[1])
    )
    return (
        f"{len(registro)} candidaturas, {aptos} coletáveis, {com_rede} com rede declarada\n"
        f"  {plataformas}"
    )
