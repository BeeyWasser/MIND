"""Diário Oficial da União pelo portal oficial de dados abertos INLABS.

O INLABS entrega uma edição diária como ZIP de artigos XML. A autenticação e a
URL seguem o cliente de referência publicado pela própria Imprensa Nacional em
``github.com/Imprensa-Nacional/inlabs``. Todas as seis seções são consultadas;
somente atos relacionados à eleição e à propaganda entram no corpus.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import httpx

from ..http import UA
from ..paths import corpus_path
from ..schema import Documento
from .rss import _sem_html

DIR = corpus_path("_dou")
LOGIN_URL = "https://inlabs.in.gov.br/logar.php"
DOWNLOAD_URL = "https://inlabs.in.gov.br/index.php"
SECOES = ("DO1", "DO1E", "DO2", "DO2E", "DO3", "DO3E")
FONTE_OFICIAL = "https://inlabs.in.gov.br/"

ELEITORAL = re.compile(
    r"\b(elei(?:ç|c)[a-zá-ú]* (?:gerais|municipais|presidenciais|de 2026|2026)|"
    r"eleitorado|urna eletrônica|título eleitoral|alistamento eleitoral|tse|"
    r"tribunal superior eleitoral|tribunal regional eleitoral|tre-[a-z]{2}|"
    r"propaganda eleitoral|"
    r"hor[aá]rio eleitoral|prestação de contas eleitorais?|financiamento de campanha|"
    r"partido político|federação partidária|pardal|justiça eleitoral|"
    r"campanha (?:presidencial|eleitoral))\b",
    re.IGNORECASE,
)

ORGAO_ELEITORAL = re.compile(
    r"tribunal (?:superior|regional) eleitoral|justiça eleitoral", re.IGNORECASE
)


def pertinente(titulo: str, orgao: str, texto: str) -> bool:
    return bool(ORGAO_ELEITORAL.search(orgao) or ELEITORAL.search(f"{titulo}\n{texto}"))


class SemCredencial(RuntimeError):
    pass


def _credenciais() -> tuple[str, str]:
    email = os.environ.get("INLABS_EMAIL", "").strip()
    senha = os.environ.get("INLABS_PASSWORD", "").strip()
    if not email or not senha:
        raise SemCredencial("INLABS_EMAIL/INLABS_PASSWORD ausentes. Ver CREDENCIAIS.md.")
    return email, senha


def _data(valor: str | None, padrao: date) -> date:
    if not valor:
        return padrao
    if len(valor) == 6:
        return datetime.strptime(valor, "%Y%m").date()
    return date.fromisoformat(valor)


def datas(de: str | None, ate: str | None) -> Iterator[date]:
    fim = _data(ate, date.today())
    inicio = _data(de, fim)
    if len(ate or "") == 6:
        proximo_mes = (fim.replace(day=28) + timedelta(days=4)).replace(day=1)
        fim = proximo_mes - timedelta(days=1)
    if fim < inicio:
        raise ValueError("intervalo do DOU invertido")
    atual = inicio
    while atual <= fim:
        yield atual
        atual += timedelta(days=1)


class Inlabs:
    def __init__(self) -> None:
        self.http = httpx.Client(
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=True,
            timeout=httpx.Timeout(120, connect=20),
        )

    def __enter__(self) -> Inlabs:
        email, senha = _credenciais()
        resposta = self.http.post(LOGIN_URL, data={"email": email, "password": senha})
        resposta.raise_for_status()
        if not self.http.cookies.get("inlabs_session_cookie"):
            raise SemCredencial("INLABS recusou o login; confira e-mail e senha")
        return self

    def __exit__(self, *_) -> None:
        self.http.close()

    def baixar(self, dia: date, secao: str, diretorio: Path = DIR) -> Path | None:
        nome = f"{dia.isoformat()}-{secao}.zip"
        caminho = diretorio / nome
        if caminho.exists() and caminho.stat().st_size > 0:
            return caminho
        resposta = self.http.get(
            DOWNLOAD_URL,
            params={"p": dia.isoformat(), "dl": nome},
            headers={"origem": "736372697074"},
        )
        if resposta.status_code == 404:
            return None
        resposta.raise_for_status()
        if not zipfile.is_zipfile(io.BytesIO(resposta.content)):
            raise ValueError(f"INLABS não devolveu ZIP válido para {nome}")
        diretorio.mkdir(parents=True, exist_ok=True)
        temporario = caminho.with_suffix(".zip.tmp")
        temporario.write_bytes(resposta.content)
        temporario.replace(caminho)
        return caminho


def _texto(elemento: ElementTree.Element | None) -> str:
    if elemento is None:
        return ""
    bruto = " ".join(elemento.itertext()).strip()
    return _sem_html(bruto) if "<" in bruto else re.sub(r"\s+", " ", bruto).strip()


def para_documento(xml: bytes, arquivo: str = "") -> Documento | None:
    try:
        raiz = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return None
    artigo = raiz if raiz.tag == "article" else raiz.find(".//article")
    if artigo is None:
        return None
    corpo = artigo.find("body")
    identifica = _texto(corpo.find("Identifica") if corpo is not None else None)
    ementa = _texto(corpo.find("Ementa") if corpo is not None else None)
    texto = _texto(corpo.find("Texto") if corpo is not None else None)
    titulo = identifica or artigo.get("name", "").strip() or artigo.get("artType", "").strip()
    orgao = artigo.get("artCategory", "").strip()
    conteudo = "\n".join(parte for parte in (ementa, texto) if parte).strip()
    if len(conteudo) < 80 or not pertinente(titulo, orgao, conteudo):
        return None
    data_br = artigo.get("pubDate", "")
    try:
        publicado = datetime.strptime(data_br, "%d/%m/%Y").date().isoformat()
    except ValueError:
        publicado = None
    identificador = artigo.get("id") or artigo.get("idMateria") or arquivo
    url = artigo.get("pdfPage") or f"{FONTE_OFICIAL}#{identificador}"
    return Documento(
        fonte="dou",
        url=url,
        titulo=titulo,
        texto=conteudo,
        canal="dou",
        modalidade="texto",
        eleicao="2026" if publicado and publicado.startswith("2026") else None,
        veiculado_em=publicado,
        licenca_uso="livre",
        metadados={
            "origem": "inlabs_xml",
            "arquivo": arquivo,
            "id": artigo.get("id"),
            "id_materia": artigo.get("idMateria"),
            "secao": artigo.get("pubName"),
            "edicao": artigo.get("editionNumber"),
            "pagina": artigo.get("numberPage"),
            "orgao": orgao,
            "tipo_ato": artigo.get("artType"),
            "fonte_oficial": FONTE_OFICIAL,
        },
    )


def documentos(caminho: Path) -> Iterator[Documento]:
    with zipfile.ZipFile(caminho) as compactado:
        for nome in compactado.namelist():
            if not nome.lower().endswith(".xml"):
                continue
            if doc := para_documento(compactado.read(nome), nome):
                yield doc


def coletar(
    de: str | None = None,
    ate: str | None = None,
    secoes: tuple[str, ...] = SECOES,
) -> Iterator[Documento]:
    with Inlabs() as cliente:
        for dia in datas(de, ate):
            for secao in secoes:
                if caminho := cliente.baixar(dia, secao):
                    yield from documentos(caminho)
