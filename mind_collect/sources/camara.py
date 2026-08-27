"""Discursos da Câmara dos Deputados.

Retórica política em português, com orador identificado, partido e data, em
transcrição integral. É persuasão deliberada de figura pública em contexto
público — o objeto do projeto, sem nenhuma restrição de licença ou acesso.

A API é aberta e sem autenticação. O endpoint de discurso exige janela de data:
sem `dataInicio` e `dataFim` devolve lista vazia sem erro, que foi o que me
enganou no primeiro teste.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import httpx

from ..schema import Documento, eleicao_de

API = "https://dadosabertos.camara.leg.br/api/v2"
CABECALHO = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)", "Accept": "application/json"}
MINIMO_CHARS = 300
PAUSA = 0.4


def deputados(cliente: httpx.Client, legislatura: int | None = None) -> list[dict]:
    saida, pagina = [], 1
    while True:
        p = {"itens": 100, "pagina": pagina, "ordem": "ASC", "ordenarPor": "nome"}
        if legislatura:
            p["idLegislatura"] = legislatura
        r = cliente.get(f"{API}/deputados", params=p, timeout=40)
        r.raise_for_status()
        dados = r.json().get("dados", [])
        if not dados:
            return saida
        saida += dados
        pagina += 1
        if pagina > 12:   # 513 deputados cabem folgados
            return saida


def discursos(cliente: httpx.Client, id_dep: int, de: str, ate: str) -> list[dict]:
    r = cliente.get(
        f"{API}/deputados/{id_dep}/discursos",
        params={"dataInicio": de, "dataFim": ate, "itens": 100,
                "ordem": "DESC", "ordenarPor": "dataHoraInicio"},
        timeout=40,
    )
    if r.status_code != 200:
        return []
    return r.json().get("dados", [])


def coletar(de: str | None = None, ate: str | None = None,
            limite_deputados: int | None = None) -> Iterator[Documento]:
    """Discursos na janela. Sem datas, os últimos 30 dias."""
    if not ate:
        ate = date.today().isoformat()
    if not de:
        de = (date.fromisoformat(ate) - timedelta(days=30)).isoformat()

    with httpx.Client(headers=CABECALHO, follow_redirects=True) as c:
        lista = deputados(c)
        if limite_deputados:
            lista = lista[:limite_deputados]
        for dep in lista:
            for d in discursos(c, dep["id"], de, ate):
                texto = (d.get("transcricao") or "").strip()
                if len(texto) < MINIMO_CHARS:
                    continue
                quando = d.get("dataHoraInicio") or ""
                yield Documento(
                    fonte="noticia",
                    url=(f"https://www.camara.leg.br/deputados/{dep['id']}"
                         f"/discursos?dataInicio={de}&dataFim={ate}"),
                    titulo=(d.get("sumario") or "").strip()[:200],
                    texto=texto,
                    canal="web",
                    modalidade="texto",
                    eleicao=eleicao_de(quando),
                    veiculado_em=quando[:19] or None,
                    patrocinador=dep.get("nome"),
                    partido=dep.get("siglaPartido"),
                    cargo="DEPUTADO FEDERAL",
                    metadados={
                        "origem": "camara_discurso",
                        "deputado_id": dep.get("id"),
                        "uf": dep.get("siglaUf"),
                        "tipo": d.get("tipoDiscurso"),
                        "fase": (d.get("faseEvento") or {}).get("titulo"),
                        "keywords": d.get("keywords"),
                    },
                )
