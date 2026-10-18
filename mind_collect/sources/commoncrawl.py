"""Common Crawl e Wayback — domínio inteiro sem tocar no servidor do veículo.

A rota de maior rendimento do plano. `cdx_toolkit --cc` extrai anos de conteúdo
de um portal sem emitir um único pedido para ele, o que resolve de uma vez rate
limit, anti-bot, Cloudflare e paginação. E se autopolicia: o Common Crawl
respeita robots.txt na coleta, então o que está no índice é o que o site liberou.

O mesmo módulo serve o Wayback (`fonte="ia"`), que é como se recupera conteúdo
que saiu do ar — o material das decisões de remoção do TSE.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import cdx_toolkit
import trafilatura

from ..schema import Documento, eleicao_de
from .rss import POLITICA

# O índice traz galeria de foto, tag, busca e paginação junto com matéria. Sem
# filtro, metade do que se baixa não é texto.
LIXO = re.compile(
    r"/(foto|fotos|galeria|video|videos|tag|tags|busca|search|page/\d+|feed|rss|amp)/|"
    r"\.(jpg|jpeg|png|gif|mp4|pdf|xml)$",
    re.IGNORECASE,
)

MINIMO_CHARS = 400

# O Common Crawl tem 127 índices mensais desde 2008. O cdx_toolkit só varre a
# janela pedida: sem `from_ts` ele usa um padrão estreito, e a coleta raspa uma
# fração do arquivo. Com 2018 entram 84 índices — cobre as eleições de 2018,
# 2020, 2022, 2024 e 2026.
DESDE_PADRAO = "201801"


@dataclass(frozen=True)
class Alvo:
    chave: str
    padrao: str  # ex.: "g1.globo.com/politica/*"
    fonte: str = "noticia"
    licenca: str = "referencia"
    eleicao: str | None = None
    somente_politica: bool = False


ALVOS: list[Alvo] = [
    # Jornalismo
    Alvo("cc-g1-politica", "g1.globo.com/politica/*"),
    Alvo("cc-oglobo", "oglobo.globo.com/politica/*"),
    Alvo("cc-poder360", "poder360.com.br/eleicoes/*"),
    Alvo("cc-ebc-politica", "agenciabrasil.ebc.com.br/politica/*"),
    Alvo("cc-folha-poder", "www1.folha.uol.com.br/poder/*"),
    Alvo("cc-estadao", "www.estadao.com.br/politica/*"),
    Alvo("cc-uol-eleicoes", "noticias.uol.com.br/eleicoes/*"),
    Alvo("cc-cnnbrasil", "www.cnnbrasil.com.br/politica/*"),
    Alvo("cc-metropoles", "www.metropoles.com/brasil/politica/*"),
    Alvo("cc-correio", "www.correiobraziliense.com.br/politica/*"),
    Alvo("cc-gazeta", "www.gazetadopovo.com.br/republica/*"),
    Alvo("cc-cartacapital", "www.cartacapital.com.br/politica/*"),
    Alvo("cc-veja", "veja.abril.com.br/politica/*"),
    Alvo("cc-r7", "noticias.r7.com/brasilia/*"),
    Alvo("cc-congressoemfoco", "congressoemfoco.uol.com.br/*"),
    Alvo("cc-jota", "www.jota.info/*"),
    Alvo("cc-brasildefato", "www.brasildefato.com.br/*"),
    Alvo("cc-intercept", "www.intercept.com.br/*"),
    Alvo("cc-apublica", "apublica.org/*"),
    Alvo("cc-icl", "iclnoticias.com.br/*"),
    Alvo("cc-istoe", "istoe.com.br/politica/*"),
    Alvo("cc-valor-politica", "valor.globo.com/politica/*"),
    Alvo("cc-correio24h", "www.correio24horas.com.br/*"),
    Alvo("cc-atarde", "atarde.com.br/politica/*"),
    Alvo("cc-nsctotal", "www.nsctotal.com.br/noticias/politica/*"),
    Alvo("cc-ndmais", "ndmais.com.br/politica-brasileira/*"),
    Alvo("cc-jornaldaparaiba", "jornaldaparaiba.com.br/politica/*"),
    Alvo("cc-campograndenews", "www.campograndenews.com.br/politica/*"),
    Alvo("cc-midianinja", "midianinja.org/*"),
    Alvo("cc-gazetaweb", "www.gazetaweb.com/noticias/politica/*"),
    Alvo("cc-dol", "dol.com.br/noticias/politica/*"),
    Alvo("cc-bemparana", "www.bemparana.com.br/noticias/politica/*"),
    Alvo("cc-aredacao", "aredacao.com.br/*"),
    Alvo("cc-diariogoias", "diariodegoias.com.br/*"),
    Alvo("cc-infomoney", "www.infomoney.com.br/politica/*"),
    Alvo("cc-moneytimes", "www.moneytimes.com.br/politica/*"),
    Alvo("cc-tribunadonorte", "tribunadonorte.com.br/politica/*"),
    Alvo("cc-jornaldebrasilia", "jornaldebrasilia.com.br/noticias/politica-e-poder/*"),
    Alvo("cc-tribunademinas", "tribunademinas.com.br/noticias/politica/*"),
    Alvo("cc-portalnorte", "portalnorte.com.br/politica/*"),
    Alvo("cc-folhabv", "www.folhabv.com.br/politica/*"),
    Alvo("cc-oantagonista", "oantagonista.com.br/*"),
    Alvo("cc-crusoe", "crusoe.com.br/*"),
    Alvo("cc-diariodopoder", "diariodopoder.com.br/*"),
    Alvo("cc-causaoperaria", "causaoperaria.org.br/*"),
    Alvo("cc-jornalopcao", "www.jornalopcao.com.br/*"),
    Alvo("cc-osul", "www.osul.com.br/*"),
    Alvo("cc-oimparcial", "oimparcial.com.br/*"),
    Alvo("cc-camara-noticias", "www.camara.leg.br/noticias/*"),
    Alvo("cc-senado-noticias", "www12.senado.leg.br/noticias/*"),
    Alvo("cc-tse-noticias", "www.tse.jus.br/comunicacao/noticias/*"),
    # Veículos nacionais e regionais com feed validado. O padrão é largo porque
    # vários não mantêm editoria estável; o filtro textual evita trazer esporte.
    Alvo("cc-bbc-brasil", "www.bbc.com/portuguese/*", somente_politica=True),
    Alvo("cc-agazeta-es", "www.agazeta.com.br/*", somente_politica=True),
    Alvo("cc-folhape", "www.folhape.com.br/*", somente_politica=True),
    Alvo("cc-cidadeverde", "cidadeverde.com/*", somente_politica=True),
    Alvo("cc-amazonasatual", "amazonasatual.com.br/*", somente_politica=True),
    Alvo("cc-jornalpequeno", "jornalpequeno.com.br/*", somente_politica=True),
    Alvo("cc-infonet", "infonet.com.br/*", somente_politica=True),
    Alvo("cc-gazetadocerrado", "gazetadocerrado.com.br/*", somente_politica=True),
    Alvo("cc-rondoniagora", "www.rondoniagora.com/*", somente_politica=True),
    Alvo("cc-sul21", "sul21.com.br/*", somente_politica=True),
    Alvo("cc-paranaportal", "www.paranaportal.com/*", somente_politica=True),
    Alvo("cc-pluralcuritiba", "www.plural.jor.br/*", somente_politica=True),
    Alvo("cc-agorarn", "agorarn.com.br/*", somente_politica=True),
    Alvo("cc-paraibaonline", "paraibaonline.com.br/*", somente_politica=True),
    Alvo("cc-politicaetc", "www.politicaetc.com.br/*", somente_politica=True),
    Alvo("cc-seculodiario", "www.seculodiario.com.br/*", somente_politica=True),
    Alvo("cc-diariodoacre", "diariodoacre.com.br/*", somente_politica=True),
    Alvo("cc-ac24horas", "ac24horas.com/*", somente_politica=True),
    Alvo("cc-diariodoamapa", "www.diariodoamapa.com.br/*", somente_politica=True),
    Alvo("cc-bncamazonas", "bncamazonas.com.br/*", somente_politica=True),
    Alvo("cc-nexojornal", "www.nexojornal.com.br/*", somente_politica=True),
    Alvo("cc-operamundi", "operamundi.uol.com.br/*", somente_politica=True),
    # Notícias oficiais dos 27 tribunais regionais eleitorais.
    *[
        Alvo(f"cc-tre-{uf}", f"www.tre-{uf}.jus.br/comunicacao/noticias/*")
        for uf in (
            "ac",
            "al",
            "ap",
            "am",
            "ba",
            "ce",
            "df",
            "es",
            "go",
            "ma",
            "mt",
            "ms",
            "mg",
            "pa",
            "pb",
            "pr",
            "pe",
            "pi",
            "rj",
            "rn",
            "rs",
            "ro",
            "rr",
            "sc",
            "sp",
            "se",
            "to",
        )
    ],
    # Comunicação oficial de partidos, mantida separada do jornalismo.
    Alvo("cc-partido-pt", "pt.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-psol", "psol50.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pdt", "pdt.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-mdb", "www.mdb.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-republicanos", "republicanos10.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-uniao", "uniaobrasil.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pcdob", "pcdob.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-psb", "psb40.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-avante", "avante70.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-solidariedade", "solidariedade.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pcb", "pcb.org.br/portal2/*", "partido", "referencia"),
    Alvo("cc-partido-pco", "pco.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pp", "progressistas.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pv", "pv.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pstu", "www.pstu.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-dc", "www.democraciacrista.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-rede", "www.redesustentabilidade.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pl", "partidoliberal.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-psd", "psd.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-novo", "novo.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-missao", "missao.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-psdb", "psdb.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-up", "unidadepopular.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-pmb", "www.pmb.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-prd", "prd.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-podemos", "podemos.org.br/*", "partido", "referencia"),
    Alvo("cc-partido-cidadania", "rede23.org/*", "partido", "referencia"),
    # Checagem — só referência, nunca treino
    Alvo("cc-aosfatos", "www.aosfatos.org/noticias/*", "checagem", "referencia"),
    Alvo("cc-lupa", "www.agencialupa.org/*", "checagem", "referencia"),
    Alvo("cc-comprova", "projetocomprova.com.br/publicacoes/*", "checagem", "referencia"),
    Alvo("cc-boatos", "www.boatos.org/*", "checagem", "referencia"),
    Alvo("cc-efarsas", "www.e-farsas.com/*", "checagem", "referencia"),
]

POR_CHAVE = {a.chave: a for a in ALVOS}

# Wayback: recupera o que saiu do ar. É a única rota para conteúdo removido —
# peça de propaganda apagada, matéria despublicada, decisão de remoção do TSE
# cumprida. O mesmo coletor serve, trocando origem="cc" por "ia".
ALVOS_WAYBACK: list[Alvo] = [
    Alvo("wb-g1-politica", "g1.globo.com/politica/*"),
    Alvo("wb-poder360", "poder360.com.br/eleicoes/*"),
    Alvo("wb-estadao", "www.estadao.com.br/politica/*"),
    Alvo("wb-uol-eleicoes", "noticias.uol.com.br/eleicoes/*"),
    Alvo("wb-oeste", "revistaoeste.com/*"),
    Alvo("wb-brasil247", "www.brasil247.com/*"),
    Alvo("wb-aosfatos", "www.aosfatos.org/noticias/*", "checagem", "referencia"),
    Alvo("wb-lupa", "www.agencialupa.org/*", "checagem", "referencia"),
]

POR_CHAVE_WAYBACK = {a.chave: a for a in ALVOS_WAYBACK}


def util(url: str) -> bool:
    return not LIXO.search(url)


def coletar(
    alvo: Alvo, de: str | None = None, ate: str | None = None, limite: int = 500, origem: str = "cc"
) -> Iterator[Documento]:
    """Varre o índice e extrai o texto de cada captura útil.

    `de` e `ate` no formato AAAAMM. `origem` é "cc" para Common Crawl ou "ia"
    para o Wayback.
    """
    cdx = cdx_toolkit.CDXFetcher(source=origem)
    opcoes: dict = {"limit": limite, "from_ts": de or DESDE_PADRAO}
    if ate:
        opcoes["to"] = ate

    for obj in cdx.iter(alvo.padrao, **opcoes):
        url = obj.get("url", "")
        if obj.get("status") != "200" or not util(url):
            continue
        if "html" not in (obj.get("mime-detected") or obj.get("mime") or ""):
            continue
        try:
            html = obj.content
        except Exception:
            continue
        if not html:
            continue
        if isinstance(html, bytes):
            html = html.decode("utf-8", "replace")
        texto = trafilatura.extract(html, include_comments=False, favor_precision=True)
        if not texto or len(texto) < MINIMO_CHARS:
            continue
        meta = trafilatura.extract_metadata(html)
        data = getattr(meta, "date", None)
        titulo = (getattr(meta, "title", "") or "").strip()
        if alvo.somente_politica and not POLITICA.search(f"{titulo}\n{texto}"):
            continue
        ts = obj.get("timestamp", "")
        yield Documento(
            fonte=alvo.fonte,
            url=url,
            titulo=titulo,
            texto=texto,
            canal="web",
            modalidade="texto",
            eleicao=alvo.eleicao or eleicao_de(data),
            veiculado_em=data,
            licenca_uso=alvo.licenca,
            url_arquivada=f"https://web.archive.org/web/{ts}/{url}" if origem == "ia" else None,
            metadados={
                "alvo": alvo.chave,
                "origem": origem,
                "captura": ts,
                "digest": obj.get("digest"),
            },
        )
