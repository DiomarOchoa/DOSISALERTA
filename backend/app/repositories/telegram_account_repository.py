"""Consultas de cuentas de Telegram vinculadas. Solo SQL, sin logica de negocio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.telegram import TelegramAccount

__all__ = ["get_linked_chat_id", "get_by_chat_id"]


async def get_linked_chat_id(session: AsyncSession, user_id: int) -> int | None:
    """El ``chat_id`` de la cuenta VINCULADA del usuario, o None.

    Sin cuenta vinculada (o sin ``chat_id``) no hay aviso: el
    spec §3.1 prohibe inventar otro canal.
    """
    stmt = select(TelegramAccount.chat_id).where(
        TelegramAccount.user_id == user_id,
        TelegramAccount.status == "VINCULADA",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_chat_id(
    session: AsyncSession, chat_id: int
) -> TelegramAccount | None:
    """La cuenta VINCULADA de un `chat_id`, con su usuario, o None.

    Es la resolucion de identidad del bot (RF19): cada comando o
    callback exige vinculo activo; sin el, el bot no revela datos.
    Un `chat_id` revocado o pendiente no resuelve a ningun usuario.
    """
    stmt = (
        select(TelegramAccount)
        .where(
            TelegramAccount.chat_id == chat_id,
            TelegramAccount.status == "VINCULADA",
        )
        .options(selectinload(TelegramAccount.user))
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
