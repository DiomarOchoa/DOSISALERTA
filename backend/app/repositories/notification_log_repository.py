"""Insercion de intentos de envio en ``notification_logs``. Solo SQL, sin logica de negocio."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.logs import NotificationLog

__all__ = ["create_log"]


async def create_log(
    session: AsyncSession,
    *,
    reminder_id: int,
    user_id: int,
    attempt_id: UUID,
    status: str,
    telegram_message_id: int | None = None,
    sent_at: datetime | None = None,
    error: str | None = None,
) -> NotificationLog:
    """Inserta una fila por intento de envio (D18).

    Las restricciones del modelo imponen la coherencia: ENVIADA
    exige ``sent_at`` + ``telegram_message_id``; FALLIDA y AMBIGUA
    exigen ``sent_at`` NULL; AMBIGUA exige ``telegram_message_id``
    NULL. Quien llama hace el commit (normalmente junto al cambio
    de estado del recordatorio, en la misma transaccion).
    """
    log = NotificationLog(
        reminder_id=reminder_id,
        user_id=user_id,
        attempt_id=attempt_id,
        status=status,
        telegram_message_id=telegram_message_id,
        sent_at=sent_at,
        error=error,
    )
    session.add(log)
    return log
