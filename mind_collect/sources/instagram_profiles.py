"""Enumeração opcional de perfis públicos do Instagram com sessão do usuário.

O Instagram não oferece enumeração pública de perfil sem autenticação. Quando o
pesquisador fornece cookies de uma sessão própria, `gallery-dl` lista somente
posts públicos visíveis para essa sessão; o conteúdo continua sendo processado
pelo adaptador de embed e nenhum cookie entra no corpus.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Descoberta:
    urls: list[str]
    perfil: dict


def configurado() -> bool:
    return bool(
        os.environ.get("INSTAGRAM_COOKIES_FILE") or os.environ.get("INSTAGRAM_COOKIES_FROM_BROWSER")
    )


def _argumentos_cookies() -> list[str]:
    if arquivo := os.environ.get("INSTAGRAM_COOKIES_FILE", "").strip():
        return ["--cookies", arquivo]
    if navegador := os.environ.get("INSTAGRAM_COOKIES_FROM_BROWSER", "").strip():
        return ["--cookies-from-browser", navegador]
    return []


def dados_do_dump(bruto: str) -> Descoberta:
    eventos = json.loads(bruto)
    urls: list[str] = []
    perfil: dict = {}
    for evento in eventos:
        if not isinstance(evento, list) or len(evento) < 3 or evento[0] != 2:
            continue
        metadados = evento[2] if isinstance(evento[2], dict) else {}
        url = str(metadados.get("post_url") or "").strip()
        if url and url not in urls:
            urls.append(url)
        usuario = metadados.get("user") if isinstance(metadados.get("user"), dict) else {}
        candidato = {
            "handle": usuario.get("username") or metadados.get("username"),
            "nome": usuario.get("full_name") or metadados.get("fullname"),
            "bio": usuario.get("biography"),
            "url_externa": usuario.get("external_url"),
            "seguidores": usuario.get("follower_count") or usuario.get("count_followed"),
            "seguindo": usuario.get("following_count") or usuario.get("count_follow"),
            "publicacoes": usuario.get("media_count") or usuario.get("count_media"),
            "verificado": usuario.get("is_verified"),
            "privado": usuario.get("is_private"),
            "foto": usuario.get("profile_pic_url_hd") or usuario.get("profile_pic_url"),
        }
        perfil.update(
            {chave: valor for chave, valor in candidato.items() if valor not in (None, "", [], {})}
        )
    return Descoberta(urls, perfil)


def urls_do_dump(bruto: str) -> list[str]:
    return dados_do_dump(bruto).urls


def descobrir_detalhado(perfil: str, limite: int = 10) -> Descoberta:
    if not configurado():
        raise RuntimeError("cookies do Instagram ausentes. Ver CREDENCIAIS.md.")
    alvo = perfil.rstrip("/") + "/posts/"
    comando = [
        sys.executable,
        "-m",
        "gallery_dl",
        "--dump-json",
        "--post-range",
        f"1-{max(1, limite)}",
        *_argumentos_cookies(),
        alvo,
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True, timeout=300)
    if resultado.returncode:
        detalhe = resultado.stderr.strip().splitlines()[-1:] or ["falha desconhecida"]
        raise RuntimeError(detalhe[0][:500])
    return dados_do_dump(resultado.stdout)


def descobrir(perfil: str, limite: int = 10) -> list[str]:
    return descobrir_detalhado(perfil, limite).urls
