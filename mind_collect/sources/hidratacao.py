"""Transforma URLs de descoberta em notícias com corpo integral."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator

import httpx
import trafilatura

from ..http import Bloqueado, Cliente
from ..schema import Documento
from .rss import MINIMO_CHARS


def coletar(
    cliente: Cliente,
    documentos: Iterable[Documento],
    bloqueadas: set[str],
    limite: int,
    ao_falhar: Callable[[str, Exception], None] | None = None,
) -> Iterator[tuple[str, str, str]]:
    tentativas = 0
    for doc in documentos:
        if tentativas >= limite:
            return
        if doc.conteudo or doc.url in bloqueadas:
            continue
        if doc.metadados.get("origem") not in {"gdelt", "mediacloud"}:
            continue
        tentativas += 1
        try:
            resposta = cliente.buscar(doc.url, condicional=False)
            if not resposta.ok:
                raise httpx.HTTPStatusError(
                    f"HTTP {resposta.status}",
                    request=httpx.Request("GET", doc.url),
                    response=httpx.Response(resposta.status),
                )
            texto = (
                trafilatura.extract(resposta.texto, include_comments=False, favor_precision=True)
                or ""
            )
            if len(texto) < MINIMO_CHARS:
                raise ValueError(f"conteúdo curto: {len(texto)} caracteres")
            metadados = trafilatura.extract_metadata(resposta.texto)
            titulo = (getattr(metadados, "title", "") or doc.titulo).strip()
            yield doc.doc_id, titulo, texto
        except (Bloqueado, OSError, ValueError, httpx.HTTPError) as erro:
            if ao_falhar:
                ao_falhar(doc.url, erro)
