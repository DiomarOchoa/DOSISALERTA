"""Consultas de tomas confirmadas (`medication_intakes`). Solo SQL, sin logica de negocio."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reminders import MedicationIntake

__all__ = ["get_by_reminder_id", "create"]


async def get_by_reminder_id(
    session: AsyncSession, reminder_id: int
) -> MedicationIntake | None:
    """La toma de un recordatorio, o None si no se confirmo."""
    stmt = select(MedicationIntake).where(
        MedicationIntake.reminder_id == reminder_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    reminder_id: int,
    user_id: int,
    taken_at: datetime,
    source: Literal["WEB", "TELEGRAM"],
) -> MedicationIntake:
    """Inserta una toma (una por recordatorio, como maximo).

    El UNIQUE de `reminder_id` es el respaldo de la idempotencia:
    si dos confirmaciones simultaneas llegan al INSERT, una
    choca con IntegrityError y el servicio la resuelve como "ya
    registrada". Quien llama hace el commit.
    """
    intake = MedicationIntake(
        reminder_id=reminder_id,
        user_id=user_id,
        taken_at=taken_at,
        source=source,
    )
    session.add(intake)
    return intake
