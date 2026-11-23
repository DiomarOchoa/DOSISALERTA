"""Contexto del bot: sesion de BD y usuario vinculado (Fase 6).

El bot nunca toca PostgreSQL directamente: abre una sesion con
`AsyncSessionLocal` y llama a los mismos servicios que la web.
Todos los imports de `app.database`, `app.models`,
`app.repositories` y `app.services` son PEREZOSOS (dentro de las
funciones), para que importar `app.bot` no cargue SQLAlchemy ni
las capas de datos (lo exige
`test_bot_structure.test_importar_el_bot_no_carga_base_de_datos_ni_servicios`).

`linked_session` es el punto de entrada de cada handler: resuelve
el usuario a partir del `chat_id` (RF19) y, si no esta vinculado,
responde con el mensaje de vinculacion y no devuelve datos.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from telegram import Update

LINK_PROMPT = (
    "Para usar DosisAlerta, primero vincula tu cuenta de Telegram.\n\n"
    "1. Entra a la web de DosisAlerta y ve a tu Perfil.\n"
    "2. Pulsa «Vincular Telegram» y copia el código.\n"
    "3. Envíame aquí: /vincular CÓDIGO\n\n"
    "El código caduca en 15 minutos."
)

UNLINKED_MENU_TEXT = (
    "Aún no has vinculado tu cuenta de Telegram.\n\n" + LINK_PROMPT
)


def _chat_id_of(update: Update) -> int | None:
    """El chat_id del mensaje o del callback, o None."""
    if update.effective_chat is not None:
        return update.effective_chat.id
    if update.message is not None:
        return update.message.chat.id
    if update.callback_query is not None and update.callback_query.message is not None:
        return update.callback_query.message.chat.id
    return None


def _telegram_user_of(update: Update) -> tuple[int | None, str | None]:
    """(telegram_user_id, username) del remitente, o (None, None)."""
    user = update.effective_user
    if user is None:
        return None, None
    return user.id, user.username


async def _reply(update: Update, text: str) -> None:
    """Responde al mensaje o edita el mensaje del callback."""
    if update.callback_query is not None:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(text)
        except Exception:
            if update.effective_message is not None:
                await update.effective_message.reply_text(text)
        return
    if update.message is not None:
        await update.message.reply_text(text)


@asynccontextmanager
async def linked_session(update: Update) -> AsyncIterator[tuple[object | None, object | None]]:
    """Sesion + usuario vinculado del chat, o (None, None).

    Si el chat no esta vinculado (RF19), responde con el mensaje
    de vinculacion y no devuelve sesion ni usuario: el handler no
    debe consultar ni mostrar ningun dato.
    """
    from app.database import AsyncSessionLocal
    from app.repositories import telegram_account_repository

    chat_id = _chat_id_of(update)
    if chat_id is None:
        yield None, None
        return
    async with AsyncSessionLocal() as session:
        account = await telegram_account_repository.get_by_chat_id(session, chat_id)
        if account is None:
            await _reply(update, UNLINKED_MENU_TEXT)
            yield None, None
            return
        user = account.user
        yield session, user


async def resolve_chat_user(update: Update) -> tuple[object | None, object | None]:
    """Sesion + usuario vinculado, sin gestionar el cierre.

    Solo para los handlers que necesitan la sesion fuera de un
    `async with` (flujos con varios pasos). El llamador debe
    cerrar la sesion. Prefiere `linked_session` cuando puedas.
    """
    from app.database import AsyncSessionLocal
    from app.repositories import telegram_account_repository

    chat_id = _chat_id_of(update)
    if chat_id is None:
        return None, None
    session = AsyncSessionLocal()
    account = await telegram_account_repository.get_by_chat_id(session, chat_id)
    if account is None:
        await session.close()
        return None, None
    return session, account.user
