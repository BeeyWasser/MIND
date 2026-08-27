"""Cliente único de rede. Todo coletor que fala HTTP passa por aqui.

Educação aqui é requisito, não gentileza: a seção de método do artigo descreve
como os dados foram coletados e cinco avaliadores com doutorado a leem. Então
robots.txt é conferido e respeitado, Crawl-delay é honrado, o User-Agent se
identifica com contato, e nada tenta contornar paywall, login ou anti-bot.
Fonte que bloqueia fica de fora e é registrada como bloqueada.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from protego import Protego

UA = (
    "MINDResearchBot/0.1 (+pesquisa academica; deteccao de tecnicas de manipulacao; "
    "contato: daviabreudasilveira@gmail.com)"
)

PAUSA_PADRAO = 1.0   # segundos entre pedidos ao mesmo host
TENTATIVAS = 3


@dataclass
class Resposta:
    url: str
    status: int
    texto: str = ""
    conteudo: bytes = b""
    etag: str | None = None
    modificado_em: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def inalterado(self) -> bool:
        return self.status == 304


class Bloqueado(Exception):
    """robots.txt não permite. Não é erro de rede — é resposta."""


class Cliente:
    def __init__(self, pausa: float = PAUSA_PADRAO, cache: Path | None = None,
                 respeitar_robots: bool = True):
        self.pausa = pausa
        self.respeitar_robots = respeitar_robots
        self._ultimo: dict[str, float] = {}
        self._robots: dict[str, Protego | None] = {}
        self._atraso: dict[str, float] = {}
        self._cache_path = cache
        self._cache: dict[str, dict] = {}
        if cache and cache.exists():
            self._cache = json.loads(cache.read_text())
        self._http = httpx.Client(
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def __enter__(self) -> Cliente:
        return self

    def __exit__(self, *_) -> None:
        self.fechar()

    def fechar(self) -> None:
        if self._cache_path:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(self._cache))
        self._http.close()

    # ---------- robots ----------

    def _carregar_robots(self, host: str) -> None:
        # protego, e não urllib.robotparser: a stdlib não suporta curinga e
        # percent-encoda o `*`, então `Disallow: /busca/*` vira `/busca/%2A` e
        # nunca casa. Sub-bloquear em silêncio é pior que não checar.
        try:
            r = self._http.get(f"https://{host}/robots.txt", timeout=15)
            if r.status_code == 200:
                rp = Protego.parse(r.text)
                self._robots[host] = rp
                d = rp.crawl_delay(UA)
                if d:
                    self._atraso[host] = float(d)
                return
        except (httpx.HTTPError, ValueError):
            pass
        # Sem robots.txt legível: não se assume proibição, mas também não se
        # acelera. Fica no ritmo padrão.
        self._robots[host] = None

    def permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        host = urlparse(url).netloc
        if host not in self._robots:
            self._carregar_robots(host)
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(url, UA)

    # ---------- ritmo ----------

    def _esperar(self, host: str) -> None:
        pausa = max(self.pausa, self._atraso.get(host, 0.0))
        ultimo = self._ultimo.get(host)
        if ultimo is not None:
            resta = pausa - (time.monotonic() - ultimo)
            if resta > 0:
                time.sleep(resta)
        self._ultimo[host] = time.monotonic()

    # ---------- busca ----------

    def buscar(self, url: str, condicional: bool = True) -> Resposta:
        if not self.permitido(url):
            raise Bloqueado(url)

        host = urlparse(url).netloc
        cabecalhos = {}
        if condicional and (c := self._cache.get(url)):
            if c.get("etag"):
                cabecalhos["If-None-Match"] = c["etag"]
            if c.get("modificado_em"):
                cabecalhos["If-Modified-Since"] = c["modificado_em"]

        erro: Exception | None = None
        for tentativa in range(TENTATIVAS):
            self._esperar(host)
            try:
                r = self._http.get(url, headers=cabecalhos)
            except httpx.HTTPError as e:
                erro = e
                time.sleep(2**tentativa)
                continue

            if r.status_code in (429, 502, 503, 504):
                espera = float(r.headers.get("Retry-After", 2**tentativa))
                time.sleep(min(espera, 60))
                continue

            if r.status_code == 304:
                return Resposta(url=url, status=304)

            if 200 <= r.status_code < 300 and condicional:
                self._cache[url] = {
                    "etag": r.headers.get("ETag"),
                    "modificado_em": r.headers.get("Last-Modified"),
                }
            return Resposta(
                url=str(r.url), status=r.status_code, texto=r.text, conteudo=r.content,
                etag=r.headers.get("ETag"), modificado_em=r.headers.get("Last-Modified"),
            )

        if erro:
            raise erro
        return Resposta(url=url, status=599)
