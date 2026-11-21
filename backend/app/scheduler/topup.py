"""Top-up periódico de recordatorios (Fase 5, Etapa 6).

El motor solo genera recordatorios al crear un tratamiento, al
añadir un vínculo y al reanudar: sin una pasada periódica, la
ventana de 72 h se vacía y el paciente deja de recibir avisos en
silencio (diagnóstico de la Etapa 6: tratamientos ACTIVO sin
PENDIENTE futuros en la base local). El top-up ejecuta
``generate_reminders_for_schedule`` para cada horario activo y
nunca borra ni toca estados existentes: no usa las funciones de
regeneración (que borran los PENDIENTE futuros) y la inserción es
idempotente por el UNIQUE parcial + ``INSERT ... ON CONFLICT DO
NOTHING``.

Cada horario se procesa con su propia sesión y su propio commit,
y un horario que falla (zona horaria inválida, error de BD) se
salta y se registra: nunca interrumpe la pasada. Entre la
enumeración y la generación el tratamiento pudo pausarse, así
que cada horario recarga su cadena (horario → vínculo →
tratamiento → usuario) y revalida que siga activa antes de
generar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import (
    schedule_repository,
    treatment_medication_repository,
    treatment_repository,
    user_repository,
)
from app.services import schedule_service

__all__ = ["TopUpResult", "run_topup"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopUpResult:
    """Resultado de una pasada de top-up."""

    schedules_checked: int = 0
    reminders_created: int = 0
    skipped: int = 0
    errors: tuple[str, ...] = ()


async def run_topup(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    *,
    now: datetime | None = None,
    horizon_hours: int = schedule_service.GENERATION_HORIZON_HOURS,
) -> TopUpResult:
    """Genera los recordatorios que faltan en la ventana de 72 h.

    Enumera los horarios activos y genera por horario. Si la
    enumeración misma falla (la BD no responde), la pasada entera
    falla y el llamador decide si reintenta: un fallo de la BD no
    es un horario saltado.
    """
    current = now or datetime.now(timezone.utc)
    async with session_factory() as session:
        schedule_ids = await schedule_repository.list_active_for_topup(session)
    checked = created = skipped = 0
    errors: list[str] = []
    for schedule_id in schedule_ids:
        checked += 1
        try:
            created += await _topup_one(
                session_factory,
                schedule_id,
                now=current,
                horizon_hours=horizon_hours,
            )
        except Exception:
            skipped += 1
            errors.append(f"schedule_id={schedule_id}")
            logger.exception("Top-up: horario %s saltado", schedule_id)
    result = TopUpResult(
        schedules_checked=checked,
        reminders_created=created,
        skipped=skipped,
        errors=tuple(errors),
    )
    logger.info(
        "Top-up: %d horarios revisados, %d recordatorios creados, %d saltados",
        result.schedules_checked,
        result.reminders_created,
        result.skipped,
    )
    return result


async def _topup_one(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    schedule_id: int,
    *,
    now: datetime,
    horizon_hours: int,
) -> int:
    """Genera para un horario (0 si ya no está activo o no hay hueco).

    Recarga la cadena y revalida que siga activa; si algo cambió
    (horario o vínculo desactivado, tratamiento pausado, usuario
    borrado), no genera nada. El commit es de esta función: un
    fallo aquí no afecta a los horarios ya procesados.
    """
    async with session_factory() as session:
        schedule = await schedule_repository.get_by_id(session, schedule_id)
        if schedule is None or not schedule.is_active:
            return 0
        link = await treatment_medication_repository.get_by_id(
            session, schedule.treatment_medication_id, user_id=schedule.user_id
        )
        if link is None or not link.is_active:
            return 0
        treatment = await treatment_repository.get_by_id(
            session, link.treatment_id, user_id=schedule.user_id
        )
        if treatment is None or treatment.status != "ACTIVO":
            return 0
        user = await user_repository.get_by_id(session, schedule.user_id)
        if user is None:
            return 0
        created = await schedule_service.generate_reminders_for_schedule(
            session,
            schedule,
            treatment,
            user,
            horizon_hours=horizon_hours,
            now=now,
        )
        await session.commit()
        return created
