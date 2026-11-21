"""Consultas de horarios (Fase 4). Solo SQL, sin logica de negocio.

El repositorio solo consulta: el servicio decide (404/403/400,
generacion de recordatorios). `create` y `deactivate` solo
anaden o modifican objetos en la sesion; el commit lo hace el
servicio, en una sola transaccion (patron de Fase 3).

Los endpoints propios de horarios (`POST .../schedules`,
`PATCH /schedules/{id}`, `DELETE /schedules/{id}`) llegan con
su modulo; aqui solo se necesita la creacion anidada dentro de
tratamientos y vinculos, mas la lectura para regenerar.
"""

from __future__ import annotations

from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import Treatment, TreatmentMedication
from app.models.schedules import MedicationSchedule


def create(
    session: AsyncSession,
    *,
    user_id: int,
    treatment_medication_id: int,
    frequency: str,
    days_of_week: list[int] | None = None,
    interval_days: int | None = None,
    times: list[time],
    start_date: date,
    end_date: date | None = None,
) -> MedicationSchedule:
    """Crea el objeto MedicationSchedule y lo anade a la sesion
    (sin commit).

    El servicio valida antes la coherencia frecuencia <-> campos
    (Pydantic) y `end_date >= start_date` (400), y normaliza
    `times` (ordenadas y sin duplicados).
    """
    schedule = MedicationSchedule(
        user_id=user_id,
        treatment_medication_id=treatment_medication_id,
        frequency=frequency,
        days_of_week=days_of_week,
        interval_days=interval_days,
        times=times,
        start_date=start_date,
        end_date=end_date,
        is_active=True,
    )
    session.add(schedule)
    return schedule


async def get_by_id(
    session: AsyncSession, schedule_id: int, user_id: int | None = None
) -> MedicationSchedule | None:
    """Busca un horario por id.

    Con `user_id`, filtra por el dueno. Sin `user_id`, busca en
    cualquier cuenta: el servicio lo usa para distinguir 404 de
    403.
    """
    stmt = select(MedicationSchedule).where(
        MedicationSchedule.id == schedule_id
    )
    if user_id is not None:
        stmt = stmt.where(MedicationSchedule.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_treatment_medication(
    session: AsyncSession, link_id: int, user_id: int
) -> list[MedicationSchedule]:
    """Horarios de un vinculo, en orden de creacion."""
    stmt = (
        select(MedicationSchedule)
        .where(
            MedicationSchedule.treatment_medication_id == link_id,
            MedicationSchedule.user_id == user_id,
        )
        .order_by(MedicationSchedule.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def deactivate(
    session: AsyncSession, schedule: MedicationSchedule
) -> MedicationSchedule:
    """Desactivacion logica (`is_active=False`, sin commit)."""
    schedule.is_active = False
    return schedule


async def list_active_for_topup(session: AsyncSession) -> list[int]:
    """Ids de los horarios que el top-up debe revisar (Fase 5, Etapa 6).

    Horario activo + vínculo activo + tratamiento ACTIVO. La
    consulta solo enumera: el top-up recarga cada cadena y
    revalida que siga activa antes de generar (entre la
    enumeración y la generación el tratamiento pudo pausarse).
    Las fechas de inicio/fin no se filtran aquí:
    `generate_reminders_for_schedule` ya recorta la ventana por
    ellas y devuelve 0 cuando no hay hueco. La FK compuesta
    (treatment_medication_id, user_id) garantiza que el vínculo
    es del mismo usuario que el horario.
    """
    stmt = (
        select(MedicationSchedule.id)
        .join(
            TreatmentMedication,
            TreatmentMedication.id
            == MedicationSchedule.treatment_medication_id,
        )
        .join(Treatment, Treatment.id == TreatmentMedication.treatment_id)
        .where(
            MedicationSchedule.is_active.is_(True),
            TreatmentMedication.is_active.is_(True),
            Treatment.status == "ACTIVO",
        )
        .order_by(MedicationSchedule.id)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
