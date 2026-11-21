"""Consultas de recordatorios (Fase 4). Solo SQL, sin logica de negocio.

El repositorio solo consulta: el servicio decide (estados,
regeneracion). Los endpoints propios de recordatorios
(`GET /reminders/upcoming`, `GET /reminders/{id}`,
`POST /reminders/{id}/confirm`) llegan con su modulo (Fase 4);
aqui se necesitan la insercion masiva idempotente (UNIQUE
parcial sobre estados activos), la lectura de proximos por
tratamiento (seccion `upcoming_reminders` de D-1), la
cancelacion de futuros para los cambios de estado y el borrado
de PENDIENTE para la regeneracion. Las filas CANCELADA nunca
se borran (decision B).

La reclamacion atomica y el listado de pendientes llegan con
la Fase 5 (``claim_reminder``, ``mark_sent``, ``list_pending``):
el scheduler reclama un PENDIENTE y solo quien lo reclama puede
enviarlo y marcarlo ENVIADA (D18).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.medications import TreatmentMedication
from app.models.reminders import MedicationReminder


def _with_relations(stmt):
    """Carga ansiosa de horario y vinculo -> medicamento.

    La respuesta `ReminderResponse` necesita la dosis (del
    vinculo) y el medicamento; sin esto, construirla tocaria
    relaciones perezosas fuera del contexto asincrono.
    """
    return stmt.options(
        selectinload(MedicationReminder.schedule),
        selectinload(MedicationReminder.treatment_medication).selectinload(
            TreatmentMedication.medication
        ),
    )


async def create_many(session: AsyncSession, rows: list[dict]) -> int:
    """Insercion masiva de recordatorios, idempotente.

    `INSERT ... ON CONFLICT DO NOTHING` sobre la UNIQUE parcial
    `(schedule_id, scheduled_at)` (`uq_reminders_schedule_time`,
    solo estados activos): regenerar nunca duplica un
    recordatorio activo, y un hueco con una fila CANCELADA (u
    otra inactiva) si admite un PENDIENTE nuevo. Devuelve el
    numero de filas insertadas (0 si `rows` esta vacio).
    """
    if not rows:
        return 0
    stmt = pg_insert(MedicationReminder).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["schedule_id", "scheduled_at"],
        index_where=MedicationReminder.status.in_(
            ["PENDIENTE", "ENVIANDO", "ENVIADA"]
        ),
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def get_by_id(
    session: AsyncSession, reminder_id: int, user_id: int | None = None
) -> MedicationReminder | None:
    """Busca un recordatorio por id, con horario y vinculo.

    Con `user_id`, filtra por el dueno. Sin `user_id`, busca en
    cualquier cuenta: el servicio lo usa para distinguir 404 de
    403.
    """
    stmt = _with_relations(
        select(MedicationReminder).where(MedicationReminder.id == reminder_id)
    )
    if user_id is not None:
        stmt = stmt.where(MedicationReminder.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_upcoming(
    session: AsyncSession,
    user_id: int,
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 100,
) -> list[MedicationReminder]:
    """Proximos recordatorios del usuario (PENDIENTE y ENVIADA),
    ordenados por `scheduled_at`.

    Es la consulta de `GET /reminders/upcoming` (su endpoint
    llega con el modulo de recordatorios); ENVIANDO no aparece
    porque es un estado transitorio de reclamacion por el motor
    (diseno §4.6.8).
    """
    stmt = _with_relations(
        select(MedicationReminder)
        .where(
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA"]),
            MedicationReminder.scheduled_at >= from_dt,
            MedicationReminder.scheduled_at <= to_dt,
        )
        .order_by(MedicationReminder.scheduled_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_upcoming_for_treatment(
    session: AsyncSession,
    treatment_id: int,
    user_id: int,
    from_dt: datetime,
    to_dt: datetime,
    limit: int = 100,
) -> list[MedicationReminder]:
    """Proximos recordatorios de un tratamiento (PENDIENTE y
    ENVIADA), ordenados por `scheduled_at`.

    Es la consulta de la seccion `upcoming_reminders` del detalle
    y del listado de tratamientos (D-1): solo se ejecuta cuando
    el actor tiene `perm_view_upcoming` (o es el paciente).
    """
    stmt = _with_relations(
        select(MedicationReminder)
        .join(
            TreatmentMedication,
            TreatmentMedication.id
            == MedicationReminder.treatment_medication_id,
        )
        .where(
            TreatmentMedication.treatment_id == treatment_id,
            MedicationReminder.user_id == user_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIADA"]),
            MedicationReminder.scheduled_at >= from_dt,
            MedicationReminder.scheduled_at <= to_dt,
        )
        .order_by(MedicationReminder.scheduled_at)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def cancel_pending_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> int:
    """Cancela los recordatorios PENDIENTE y ENVIANDO futuros de
    un horario (status -> CANCELADA).

    Futuro = `scheduled_at >= now`. No toca TOMADA, POSPUESTA,
    PERDIDA, ENVIADA ni sus intakes: el historial se conserva
    (diseno §4.6.4).
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.schedule_id == schedule_id,
            MedicationReminder.status.in_(["PENDIENTE", "ENVIANDO"]),
            MedicationReminder.scheduled_at >= now,
        )
        .values(status="CANCELADA")
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def cancel_pending_for_treatment(
    session: AsyncSession, treatment_id: int, now: datetime
) -> int:
    """Cancela los recordatorios PENDIENTE y ENVIANDO futuros de
    todo un tratamiento (status -> CANCELADA).

    Lo usan pausar, cancelar y completar (diseno §4.6.4).
    """
    subquery = select(TreatmentMedication.id).where(
        TreatmentMedication.treatment_id == treatment_id
    )
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.treatment_medication_id.in_(subquery),
            MedicationReminder.status.in_(["PENDIENTE", "ENVIANDO"]),
            MedicationReminder.scheduled_at >= now,
        )
        .values(status="CANCELADA")
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def list_cancelled_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> list[MedicationReminder]:
    """Filas CANCELADA futuras de un horario, ordenadas por
    fecha e id.

    Las usa el resume para relacionar cada recordatorio nuevo
    con la fila cancelada que reemplaza (`parent_reminder_id`);
    si hay varias CANCELADA en el mismo hueco (varios ciclos
    pausa+resume), el servicio toma la mas reciente (mayor id).
    """
    stmt = (
        select(MedicationReminder)
        .where(
            MedicationReminder.schedule_id == schedule_id,
            MedicationReminder.status == "CANCELADA",
            MedicationReminder.scheduled_at >= now,
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def delete_pending_for_schedule(
    session: AsyncSession, schedule_id: int, now: datetime
) -> int:
    """Borrado fisico de los recordatorios PENDIENTE futuros de
    un horario.

    Solo PENDIENTE sin historial (sin intake ni logs): es el
    primer paso de la regeneracion (§4.7). Nunca borra TOMADA,
    POSPUESTA, PERDIDA, ENVIADA, ENVIANDO ni CANCELADA.
    """
    stmt = delete(MedicationReminder).where(
        MedicationReminder.schedule_id == schedule_id,
        MedicationReminder.status == "PENDIENTE",
        MedicationReminder.scheduled_at >= now,
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def claim_reminder(
    session: AsyncSession, reminder_id: int, *, attempt_id: UUID, now: datetime
) -> MedicationReminder | None:
    """Reclama un recordatorio PENDIENTE para enviarlo, de forma atomica (Fase 5, D18).

    Un solo UPDATE con WHERE de estado y RETURNING: PostgreSQL lo
    ejecuta como una operacion atomica, asi que de varias
    reclamaciones concurrentes del mismo recordatorio solo una
    puede ganar (las demas encuentran el estado ya en ENVIANDO y
    obtienen 0 filas). Quien reclama es el unico que puede enviar
    y marcar ENVIADA (con el mismo attempt_id). Devuelve la fila
    reclamada o None. Quien llama hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "PENDIENTE",
        )
        .values(
            status="ENVIANDO",
            current_attempt_id=attempt_id,
            claimed_at=now,
            attempt_count=MedicationReminder.attempt_count + 1,
        )
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def mark_sent(
    session: AsyncSession, reminder_id: int, *, attempt_id: UUID
) -> MedicationReminder | None:
    """Marca ENVIADA un recordatorio reclamado, solo si el intento coincide.

    El WHERE exige estado ENVIANDO y el mismo ``current_attempt_id``
    de la reclamacion: solo el reclamante puede marcarlo. Devuelve
    la fila marcada o None. Quien llama hace el commit.
    """
    stmt = (
        update(MedicationReminder)
        .where(
            MedicationReminder.id == reminder_id,
            MedicationReminder.status == "ENVIANDO",
            MedicationReminder.current_attempt_id == attempt_id,
        )
        .values(status="ENVIADA")
        .returning(MedicationReminder)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()




async def list_pending(
    session: AsyncSession, *, from_dt: datetime, limit: int = 500
) -> list[MedicationReminder]:
    """Recordatorios PENDIENTE listos para (re)cargar, ordenados.

    Lo usa el scheduler para (re)cargar la cola (Fase 5, Etapa
    2). El orden es el mismo de la cola: scheduled_at y despues
    id. Se cargan los PENDIENTE con ``scheduled_at`` dentro de la
    ventana [from_dt, ...) y sin un ``next_attempt_at`` futuro.
    """
    stmt = (
        select(MedicationReminder)
        .where(
            MedicationReminder.status == "PENDIENTE",
            MedicationReminder.next_attempt_at.is_(None),
            MedicationReminder.scheduled_at >= from_dt,
        )
        .order_by(MedicationReminder.scheduled_at, MedicationReminder.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
