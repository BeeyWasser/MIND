"""Canais públicos do Telegram.

Vetor central de circulação política no Brasil e, para este projeto, também a
maior fonte de menção a TikTok e Instagram — é de mensagem encaminhada que sai
boa parte das URLs que a descoberta por menção consegue buscar depois.

Lê canal público pela API oficial, sem entrar no canal e sem contornar nada. A
primeira execução exige login interativo uma vez; a sessão fica em disco e as
seguintes rodam sozinhas.

Descoberta em duas frentes: uma lista-semente e os links t.me já citados no
corpus (ver `mencoes.py`).
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..paths import LOCAL_STATE_ROOT
from ..schema import Documento, anonimizar, eleicao_de
from .rss import POLITICA

SESSAO = LOCAL_STATE_ROOT / "telegram.session"
TERMOS = (
    "eleições 2026",
    "propaganda eleitoral",
    "campanha eleitoral",
    "urna eletrônica",
    "TSE eleições",
    "candidato presidente",
    "governo federal",
    "Congresso Nacional",
)

# Canais públicos de veículo e instituição. Semente conservadora: o resto vem
# das menções encontradas no que já foi coletado.
SEMENTES = [
    "g1",
    "poder360",
    "cnnbrasil",
    "metropoles",
    "agenciabrasil",
    "aosfatos",
    "agencialupa",
]


class SemCredencial(RuntimeError):
    pass


def _credenciais() -> tuple[int, str]:
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
        raise SemCredencial("TELEGRAM_API_ID e TELEGRAM_API_HASH ausentes. Ver CREDENCIAIS.md.")
    return int(api_id), api_hash


def cliente():
    from telethon.sync import TelegramClient

    api_id, api_hash = _credenciais()
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSAO), api_id, api_hash)


def estado() -> str:
    """`pronto`, `sem_login` ou `sem_credencial`.

    Distinguir importa: sem credencial é problema de .env, sem login é problema
    de sessão, e cada um tem uma correção diferente. Colapsar os dois em False
    faz o ciclo pular o Telegram sem dizer por quê.
    """
    try:
        _credenciais()
    except SemCredencial:
        return "sem_credencial"
    if not SESSAO.exists():
        return "sem_login"
    try:
        with cliente() as c:
            return "pronto" if c.is_user_authorized() else "sem_login"
    except Exception:
        return "sem_login"


def autenticado() -> bool:
    """Sessão pronta para coletar sem pedir nada. O ciclo checa antes de tentar:
    senão o coletor pediria código no meio de uma passada automática e travaria."""
    return estado() == "pronto"


def _canal(link: str) -> str:
    """Aceita 'g1', 't.me/g1' ou 'https://t.me/g1/123'."""
    nome = link.rstrip("/").split("/")
    for parte in reversed(nome):
        if parte and not parte.isdigit() and "t.me" not in parte and "http" not in parte:
            return parte.lstrip("@")
    return link


def _tipo_midia(mensagem) -> str | None:
    if getattr(mensagem, "photo", None):
        return "imagem"
    if getattr(mensagem, "video", None):
        return "video"
    if getattr(mensagem, "audio", None) or getattr(mensagem, "voice", None):
        return "audio"
    if getattr(mensagem, "media", None):
        return "arquivo"
    return None


def _documento(mensagem, entidade, canal: str, descoberta: str) -> Documento | None:
    texto = (mensagem.message or "").strip()
    tipo_midia = _tipo_midia(mensagem)
    if len(texto) < 40 and not tipo_midia:
        return None
    quando = mensagem.date.isoformat() if mensagem.date else None
    return Documento(
        fonte="telegram",
        url=f"https://t.me/{canal}/{mensagem.id}",
        texto=texto,
        canal="telegram",
        modalidade=tipo_midia if tipo_midia in {"imagem", "video", "audio"} else "texto",
        eleicao=eleicao_de(quando),
        veiculado_em=quando,
        patrocinador=getattr(entidade, "title", canal),
        autor_hash=anonimizar(str(mensagem.sender_id), os.environ.get("MIND_SALT", "mind-dev"))
        if mensagem.sender_id
        else None,
        metadados={
            "canal": canal,
            "perfil_url": f"https://t.me/{canal}",
            "perfil_publico": {
                "handle": canal,
                "nome": getattr(entidade, "title", None),
                "verificado": getattr(entidade, "verified", None),
                "participantes": getattr(entidade, "participants_count", None),
            },
            "mensagem_id": mensagem.id,
            "encaminhamentos": getattr(mensagem, "forwards", None),
            "visualizacoes": getattr(mensagem, "views", None),
            "tem_midia": bool(mensagem.media),
            "midia_tipo": tipo_midia,
            "descoberta": descoberta,
        },
    )


def coletar(
    canais: Iterable[str] | None = None, por_canal: int = 300, desde: str | None = None
) -> Iterator[Documento]:
    from telethon.errors import (
        ChannelPrivateError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )

    alvos = [_canal(c) for c in (canais or SEMENTES)]
    with cliente() as c:
        if not c.is_user_authorized():
            raise SemCredencial(
                "sessão do Telegram não autenticada. Rode uma vez:\n"
                "  uv run python -m mind_collect.run --telegram-login"
            )
        for canal in dict.fromkeys(alvos):
            try:
                ent = c.get_entity(canal)
            except (
                ValueError,
                UsernameInvalidError,
                UsernameNotOccupiedError,
                ChannelPrivateError,
            ):
                continue
            for m in c.iter_messages(ent, limit=por_canal):
                quando = m.date.isoformat() if m.date else None
                if desde and quando and quando < desde:
                    break
                if doc := _documento(m, ent, canal, "canal_semente"):
                    yield doc


def buscar_global(termos: Iterable[str], por_termo: int = 100) -> Iterator[Documento]:
    """Busca mensagens públicas e descobre canais além das listas conhecidas."""
    vistos: set[str] = set()
    with cliente() as c:
        if not c.is_user_authorized():
            raise SemCredencial("sessão do Telegram não autenticada")
        for termo in termos:
            palavras = {
                palavra.lower()
                for palavra in re.findall(r"[\wÀ-ÿ]+", termo)
                if len(palavra) >= 5 and not palavra.isdigit()
            }
            for mensagem in c.iter_messages(None, search=termo, limit=por_termo):
                entidade = getattr(mensagem, "chat", None)
                canal = str(getattr(entidade, "username", "") or "").strip()
                texto = (mensagem.message or "").strip()
                if not canal or not POLITICA.search(texto):
                    continue
                texto_normalizado = texto.lower()
                if palavras and not any(palavra in texto_normalizado for palavra in palavras):
                    continue
                url = f"https://t.me/{canal}/{mensagem.id}"
                if url in vistos:
                    continue
                vistos.add(url)
                if doc := _documento(mensagem, entidade, canal, "busca_global"):
                    doc.metadados["consulta"] = termo
                    yield doc


def baixar_midias(
    documentos: Iterable[Documento],
    limite: int,
    ao_falhar=None,
) -> Iterator[tuple[Documento, Path]]:
    """Baixa uma mídia por vez; o original é apagado ao retomar o gerador."""
    SESSAO.parent.mkdir(parents=True, exist_ok=True)
    processados = 0
    entidades: dict[str, object] = {}
    with cliente() as c:
        for doc in documentos:
            if processados >= limite:
                return
            canal = str(doc.metadados.get("canal") or "")
            mensagem_id = doc.metadados.get("mensagem_id")
            if not canal or not mensagem_id:
                continue
            try:
                entidade = entidades.get(canal)
                if entidade is None:
                    entidade = c.get_entity(canal)
                    entidades[canal] = entidade
                mensagem = c.get_messages(entidade, ids=int(mensagem_id))
                if not mensagem or not mensagem.media:
                    if ao_falhar:
                        ao_falhar(doc.url, RuntimeError("mensagem ou mídia indisponível"))
                    continue
                processados += 1
                with tempfile.TemporaryDirectory(dir=SESSAO.parent) as temporario:
                    baixado = c.download_media(mensagem, file=temporario)
                    if baixado:
                        yield doc, Path(baixado)
            except Exception as erro:
                if ao_falhar:
                    ao_falhar(doc.url, erro)
