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
from collections.abc import Iterable, Iterator
from pathlib import Path

from ..schema import Documento, anonimizar, eleicao_de

SESSAO = Path("data/eleicoes2026/_telegram.session")
SAL = os.environ.get("MIND_SALT", "mind-dev")

# Canais públicos de veículo e instituição. Semente conservadora: o resto vem
# das menções encontradas no que já foi coletado.
SEMENTES = [
    "g1", "poder360", "cnnbrasil", "metropoles", "agenciabrasil",
    "aosfatos", "agencialupa",
]


class SemCredencial(RuntimeError):
    pass


def _credenciais() -> tuple[int, str]:
    api_id = os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TELEGRAM_API_HASH")
    if not (api_id and api_hash):
        raise SemCredencial(
            "TELEGRAM_API_ID e TELEGRAM_API_HASH ausentes. Ver CREDENCIAIS.md."
        )
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


def coletar(canais: Iterable[str] | None = None, por_canal: int = 300,
            desde: str | None = None) -> Iterator[Documento]:
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
            except (ValueError, UsernameInvalidError, UsernameNotOccupiedError,
                    ChannelPrivateError):
                continue
            for m in c.iter_messages(ent, limit=por_canal):
                texto = (m.message or "").strip()
                if len(texto) < 40:
                    continue
                quando = m.date.isoformat() if m.date else None
                if desde and quando and quando < desde:
                    break
                yield Documento(
                    fonte="telegram",
                    url=f"https://t.me/{canal}/{m.id}",
                    texto=texto,
                    canal="telegram",
                    modalidade="texto",
                    eleicao=eleicao_de(quando),
                    veiculado_em=quando,
                    patrocinador=getattr(ent, "title", canal),
                    # Canal é público, mas quem encaminha não é figura pública:
                    # identificador de autor nunca em claro (LGPD, art. 5º, II).
                    autor_hash=anonimizar(str(m.sender_id), SAL) if m.sender_id else None,
                    metadados={
                        "canal": canal,
                        "mensagem_id": m.id,
                        "encaminhamentos": getattr(m, "forwards", None),
                        "visualizacoes": getattr(m, "views", None),
                        "tem_midia": bool(m.media),
                    },
                )
