"""Media Cloud — arquivo de notícia com curadoria por veículo.

Mais de 2 bilhões de matérias e 60 mil fontes, com suporte a português. É
infraestrutura pública de pesquisa, construída exatamente para este caso de uso,
e complementa o Common Crawl onde a cobertura dele for rala.

Entrega metadados e URL, não o texto integral — por questão de direito autoral,
como o GDELT. O corpo vem do coletor próprio ou do Common Crawl.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import date, timedelta

from ..schema import Documento, eleicao_de

# Coleção do Media Cloud para mídia nacional brasileira.
COLECAO_BRASIL = 34412118

CONSULTA = (
    "eleições OR eleitoral OR candidato OR campanha OR presidenciável "
    "OR urna OR TSE OR votação"
)


class SemChave(RuntimeError):
    pass


def _chave() -> str:
    k = os.environ.get("MEDIACLOUD_API_KEY")
    if not k:
        raise SemChave("MEDIACLOUD_API_KEY ausente. Ver CREDENCIAIS.md.")
    return k


def coletar(consulta: str = CONSULTA, de: str | None = None, ate: str | None = None,
            colecao: int = COLECAO_BRASIL, paginas: int = 20) -> Iterator[Documento]:
    import mediacloud.api

    busca = mediacloud.api.SearchApi(_chave())
    fim = date.fromisoformat(ate) if ate else date.today()
    ini = date.fromisoformat(de) if de else fim - timedelta(days=30)

    cursor = None
    for _ in range(paginas):
        pagina, cursor = busca.story_list(
            consulta, start_date=ini, end_date=fim,
            collection_ids=[colecao], pagination_token=cursor,
        )
        if not pagina:
            return
        for m in pagina:
            url = m.get("url")
            if not url:
                continue
            data = str(m.get("publish_date") or "")
            yield Documento(
                fonte="noticia",
                url=url,
                titulo=(m.get("title") or "").strip(),
                texto="",   # Media Cloud não entrega o corpo — só descoberta
                canal="web",
                modalidade="texto",
                eleicao=eleicao_de(data),
                veiculado_em=data or None,
                metadados={
                    "origem": "mediacloud",
                    "veiculo": m.get("media_name"),
                    "veiculo_id": m.get("media_id"),
                    "idioma": m.get("language"),
                    "story_id": m.get("id"),
                },
            )
        if not cursor:
            return
