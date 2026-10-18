"""Discursos do plenário do Senado.

Mesmo valor dos discursos da Câmara — retórica política em português, com orador
e data, livre e sem autenticação. São 81 senadores contra 513 deputados, então o
volume é menor, mas a fonte é a mesma qualidade.

A API exige janela de datas em AAAAMMDD e devolve pouco para janela recente
(recesso, ou sessão ainda não indexada). Mês fechado funciona bem.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta

import httpx

from ..schema import Documento, eleicao_de

API = "https://legis.senado.leg.br/dadosabertos"
CABECALHO = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)", "Accept": "application/json"}
MINIMO_CHARS = 300


def _lista(v) -> list:
    """A API alterna entre objeto e lista quando há um só elemento."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _integral(c: httpx.Client, url: str | None) -> str:
    """Busca o corpo do discurso. Falha em silêncio: um discurso a menos não
    trava a coleta do mês inteiro."""
    if not url:
        return ""
    try:
        # Accept explícito: o cliente carrega application/json para a listagem,
        # e o endpoint de texto integral serve text/plain e devolve 406.
        r = c.get(url, timeout=60, headers={"Accept": "text/plain, */*"})
    except httpx.HTTPError:
        return ""
    return r.text.strip() if r.status_code == 200 else ""


def coletar(de: str | None = None, ate: str | None = None) -> Iterator[Documento]:
    if not ate:
        ate = date.today().isoformat()
    if not de:
        de = (date.fromisoformat(ate) - timedelta(days=60)).isoformat()
    d1, d2 = de.replace("-", ""), ate.replace("-", "")

    with httpx.Client(headers=CABECALHO, follow_redirects=True) as c:
        r = c.get(f"{API}/plenario/lista/discursos/{d1}/{d2}", timeout=90)
        if r.status_code != 200:
            return
        raiz = r.json().get("DiscursosSessao", {})
        for sessao in _lista((raiz.get("Sessoes") or {}).get("Sessao")):
            for p in _lista((sessao.get("Pronunciamentos") or {}).get("Pronunciamento")):
                # TextoIntegral e TextoIntegralTxt são URLs, não texto, e o
                # Resumo tem ~150 caracteres. O corpo exige uma segunda busca.
                texto = _integral(c, p.get("TextoIntegralTxt"))
                if len(texto) < MINIMO_CHARS:
                    continue
                data = p.get("Data") or sessao.get("DataSessao")
                tipo = p.get("TipoUsoPalavra") or {}
                yield Documento(
                    fonte="noticia",
                    url=p.get("TextoIntegral") or f"{API}/discurso/{p.get('id')}",
                    titulo=(p.get("Indexacao") or p.get("Resumo") or "")[:200],
                    texto=texto,
                    canal="web",
                    modalidade="texto",
                    eleicao=eleicao_de(data),
                    veiculado_em=data,
                    patrocinador=p.get("NomeAutor"),
                    partido=p.get("Partido"),
                    cargo="SENADOR",
                    metadados={
                        "origem": "senado_discurso",
                        "uf": p.get("UF"),
                        "tipo": tipo.get("Descricao") if isinstance(tipo, dict) else tipo,
                        "resumo": p.get("Resumo"),
                        "pronunciamento_id": p.get("id"),
                    },
                )
