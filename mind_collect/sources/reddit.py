"""Reddit pelo arquivo público, via arctic_shift.

O plano previa o dump do Academic Torrents, que exige cliente de torrent e
baixa dezenas de GB. O arctic_shift — sucessor público do Pushshift — serve o
mesmo arquivo por HTTP, sem autenticação, sem torrent e com filtro por
subreddit e janela de data. É melhor por todos os critérios.

Duas naturezas de conteúdo, e as duas importam:
  - post costuma ser link, com o título carregando a carga retórica, e a URL
    alimentando a descoberta por menção;
  - comentário é discurso político espontâneo em português, que nenhuma outra
    fonte do projeto tem.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime

import httpx

from ..schema import Documento, anonimizar, eleicao_de

API = "https://arctic-shift.photon-reddit.com/api"
CABECALHO = {"User-Agent": "MINDResearchBot/0.1 (pesquisa academica)"}
SAL = os.environ.get("MIND_SALT", "mind-dev")
PAUSA = 1.0
MINIMO_CHARS = 60

# Conferidos em 25/08/2026 com `existe()`. r/PoliticaBrasil e r/conserva não
# retornam nada — subreddit inexistente devolve lista vazia sem erro, e a
# varredura gastaria a janela inteira em silêncio.
SUBREDDITS = [
    "brasil", "brasilivre", "BrasildoB", "politica",
    "esquerdaBR", "circojeca", "investimentos", "saopaulo",
]


def _quando(epoch) -> str | None:
    try:
        return datetime.fromtimestamp(float(epoch), tz=UTC).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _buscar(c: httpx.Client, rota: str, params: dict) -> list[dict]:
    for tentativa in range(3):
        r = c.get(f"{API}/{rota}", params=params, timeout=60)
        if r.status_code == 200:
            return r.json().get("data", [])
        if r.status_code in (429, 502, 503):
            time.sleep(2 ** tentativa * 3)
            continue
        return []
    return []


def existe(sub: str) -> bool:
    """Confere antes de varrer: subreddit inexistente devolve lista vazia sem
    erro, e a coleta gastaria a janela inteira em silêncio."""
    with httpx.Client(headers=CABECALHO, follow_redirects=True) as c:
        return bool(_buscar(c, "posts/search", {"subreddit": sub, "limit": 1}))


def coletar(subreddits: Iterable[str] | None = None, de: str | None = None,
            ate: str | None = None, por_sub: int = 500,
            comentarios: bool = True) -> Iterator[Documento]:
    subs = list(subreddits or SUBREDDITS)
    base = {"limit": 100, "sort": "desc"}
    if de:
        base["after"] = de
    if ate:
        base["before"] = ate

    with httpx.Client(headers=CABECALHO, follow_redirects=True) as c:
        for sub in subs:
            for rota, campo in (("posts/search", "selftext"),
                                ("comments/search", "body")):
                if rota.startswith("comments") and not comentarios:
                    continue
                vistos = 0
                cursor = None
                while vistos < por_sub:
                    p = {**base, "subreddit": sub}
                    if cursor:
                        p["before"] = cursor
                    itens = _buscar(c, rota, p)
                    if not itens:
                        break
                    for it in itens:
                        titulo = (it.get("title") or "").strip()
                        corpo = (it.get(campo) or "").strip()
                        texto = f"{titulo}\n{corpo}".strip() if titulo else corpo
                        if len(texto) < MINIMO_CHARS:
                            continue
                        quando = _quando(it.get("created_utc"))
                        vistos += 1
                        yield Documento(
                            fonte="reddit",
                            url=f"https://reddit.com{it.get('permalink', '')}",
                            titulo=titulo[:200],
                            texto=texto,
                            canal="reddit",
                            modalidade="texto",
                            eleicao=eleicao_de(quando),
                            veiculado_em=quando,
                            # Usuário de Reddit não é figura pública: identificador
                            # nunca em claro (LGPD, art. 5º, II).
                            autor_hash=anonimizar(str(it.get("author")), SAL)
                            if it.get("author") else None,
                            metadados={
                                "subreddit": sub,
                                "tipo": "post" if "posts" in rota else "comentario",
                                "score": it.get("score"),
                                "comentarios": it.get("num_comments"),
                                # URL do post alimenta a descoberta por menção
                                "link": it.get("url"),
                            },
                        )
                    cursor = itens[-1].get("created_utc")
                    if not cursor:
                        break
                    time.sleep(PAUSA)
