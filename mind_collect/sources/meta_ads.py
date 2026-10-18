"""Biblioteca de Anúncios da Meta — anúncios políticos no Facebook e Instagram.

Cliente próprio em vez de dependência: a Meta publica scripts de exemplo em
`facebookresearch/Ad-Library-API-Script-Repository`, não um pacote, e o endpoint
é REST com paginação por cursor. Cem linhas previsíveis valem mais que um fork
de terceiro no meio da campanha.

É a rota legal para conteúdo pago de Instagram e Facebook, e entrega o que post
orgânico não tem: quem pagou, quanto, para quem e por quanto tempo. Cerca de 3
milhões de anúncios de períodos eleitorais brasileiros — ver COLETA.md.

Exige verificação de identidade com documento (leva dias) e token com escopo
`ads_archive`. Token de system user não expira e é o certo para varredura longa.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator

import httpx

from ..schema import Documento

# Só o que o projeto usa. Pedir campo demais estoura o custo interno da Meta e
# derruba o limite de chamadas antes das 200/hora nominais.
CAMPOS = [
    "id",
    "ad_creation_time",
    "ad_creative_bodies",
    "ad_creative_link_titles",
    "ad_creative_link_descriptions",
    "ad_creative_link_captions",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_snapshot_url",
    "page_id",
    "page_name",
    "bylines",
    "currency",
    "spend",
    "impressions",
    "publisher_platforms",
    "languages",
    "demographic_distribution",
    "delivery_by_region",
    "estimated_audience_size",
    "target_ages",
    "target_gender",
    "br_total_reach",
    "age_country_gender_reach_breakdown",
    "target_locations",
    "total_reach_by_location",
]

PAUSA = 18.0  # 200 chamadas/hora = uma a cada 18s


class SemToken(RuntimeError):
    pass


def token() -> str:
    t = os.environ.get("META_ADS_TOKEN")
    if not t:
        raise SemToken(
            "META_ADS_TOKEN não definido. Requer verificação de identidade com "
            "documento na Meta (leva dias) e app de desenvolvedor com escopo "
            "ads_archive. Ver COLETA.md."
        )
    return t


def api() -> str:
    versao = os.environ.get("META_GRAPH_API_VERSION", "v26.0").strip()
    if not versao.startswith("v"):
        versao = "v" + versao
    return f"https://graph.facebook.com/{versao}/ads_archive"


def _pagina(cliente: httpx.Client, params: dict) -> tuple[list[dict], str | None]:
    r = cliente.get(api(), params=params, timeout=60)
    if r.status_code == 400:
        raise RuntimeError(f"Ad Library recusou: {r.json().get('error', {}).get('message')}")
    r.raise_for_status()
    d = r.json()
    return d.get("data", []), d.get("paging", {}).get("next")


def buscar(
    termos: str | None = None,
    paginas: list[str] | None = None,
    de: str | None = None,
    ate: str | None = None,
    pais: str = "BR",
    limite_paginas: int = 100,
) -> Iterator[dict]:
    """Varre a Ad Library. `paginas` são search_page_ids do registro de candidaturas.

    Enumerar por página é melhor que buscar por palavra-chave: cobre tudo que o
    anunciante veiculou, sem depender de acertar o termo.
    """
    params = {
        "access_token": token(),
        "ad_reached_countries": f'["{pais}"]',
        "ad_type": "POLITICAL_AND_ISSUE_ADS",
        "ad_active_status": "ALL",
        "fields": ",".join(CAMPOS),
        "limit": 250,
    }
    if termos:
        params["search_terms"] = termos
    if paginas:
        params["search_page_ids"] = ",".join(paginas)
    if de:
        params["ad_delivery_date_min"] = de
    if ate:
        params["ad_delivery_date_max"] = ate

    with httpx.Client() as cliente:
        dados, proxima = _pagina(cliente, params)
        yield from dados
        for _ in range(limite_paginas - 1):
            if not proxima:
                return
            time.sleep(PAUSA)
            r = cliente.get(proxima, timeout=60)
            r.raise_for_status()
            d = r.json()
            yield from d.get("data", [])
            proxima = d.get("paging", {}).get("next")


def _texto(anuncio: dict) -> str:
    """Junta os campos de criativo. A API devolve listas — um anúncio pode ter
    várias variações de texto no mesmo id."""
    partes: list[str] = []
    for campo in (
        "ad_creative_link_titles",
        "ad_creative_bodies",
        "ad_creative_link_descriptions",
        "ad_creative_link_captions",
    ):
        partes += [p for p in (anuncio.get(campo) or []) if p]
    vistos, saida = set(), []
    for p in partes:
        if p not in vistos:
            vistos.add(p)
            saida.append(p)
    return "\n".join(saida).strip()


def _numero(v) -> float | None:
    """spend e impressions vêm como faixa {'lower_bound','upper_bound'}."""
    if isinstance(v, dict):
        lo = float(v.get("lower_bound") or 0)
        hi = float(v.get("upper_bound") or lo)
        return (lo + hi) / 2 if hi else lo
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def para_documento(anuncio: dict, eleicao: str | None = None) -> Documento:
    inicio = anuncio.get("ad_delivery_start_time")
    return Documento(
        fonte="meta_ads",
        url=anuncio.get("ad_snapshot_url", ""),
        titulo=(anuncio.get("ad_creative_link_titles") or [""])[0],
        texto=_texto(anuncio),
        canal="facebook",
        modalidade="texto",
        eleicao=eleicao or (inicio[:4] if inicio else None),
        veiculado_em=inicio,
        veiculado_ate=anuncio.get("ad_delivery_stop_time"),
        patrocinador=anuncio.get("bylines") or anuncio.get("page_name"),
        gasto=_numero(anuncio.get("spend")),
        alcance=int(
            _numero(anuncio.get("br_total_reach")) or _numero(anuncio.get("impressions")) or 0
        )
        or None,
        segmentacao={
            "demografia": anuncio.get("demographic_distribution"),
            "regiao": anuncio.get("delivery_by_region"),
            "idades": anuncio.get("target_ages"),
            "genero": anuncio.get("target_gender"),
            "localizacoes_alvo": anuncio.get("target_locations"),
            "alcance_por_localizacao": anuncio.get("total_reach_by_location"),
            "alcance_idade_pais_genero": anuncio.get("age_country_gender_reach_breakdown"),
        },
        metadados={
            "ad_id": anuncio.get("id"),
            "page_id": anuncio.get("page_id"),
            "page_name": anuncio.get("page_name"),
            "plataformas": anuncio.get("publisher_platforms"),
            "moeda": anuncio.get("currency"),
            "publico_estimado": anuncio.get("estimated_audience_size"),
        },
    )
