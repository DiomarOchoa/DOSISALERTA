"""Agregación de cumplimiento (Fase 7, RF14).

Una sola consulta con `COUNT(*) FILTER (WHERE ...)`; el
porcentaje y el denominador se calculan en el servicio
(plan §6.2 y §6.3). El JOIN a `medication_intakes` es
`LEFT JOIN` (solo las `TOMADA` tienen toma).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Date, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import Medication, TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.scheduler.reconciliation import GRACE_MINUTES

# Estados que NO cuentan en ningún conteo de cumplimiento
# (D-2, D-3, D-10): se excluyen con `NOT IN` para que un
# estado nuevo no entre en el denominador sin decisión
# expresa (plan §6.2).
_EXCLUDED_STATUSES = ["POSPUESTA", "FALLIDA", "PENDIENTE", "ENVIANDO", "ENVIADA"]


def _count_columns() -> list:
    """Las 10 columnas de conteo: 4 categorías + 6 desgloses (D-11).

    La gracia es la misma del motor (`GRACE_MINUTES`, 30 min,
    inclusiva, D-8): `taken_at <= scheduled_at + 30 min` es a
    tiempo. Una `TOMADA` sin toma cuenta como tardía (D-9): el
    filtro de tardía incluye explícitamente `taken_at IS NULL`,
    porque sin él la fila desaparecería de ambos conteos por la
    lógica de tres valores de SQL.
    """
    grace = timedelta(minutes=GRACE_MINUTES)
    on_time = MedicationReminder.scheduled_at + grace
    return [
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "TOMADA",
                MedicationIntake.taken_at <= on_time,
            )
        )
        .label("taken_on_time"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "TOMADA",
                or_(
                    MedicationIntake.taken_at.is_(None),
                    MedicationIntake.taken_at > on_time,
                ),
            )
        )
        .label("taken_late"),
        func.count()
        .filter(MedicationReminder.status == "PERDIDA")
        .label("lost"),
        func.count()
        .filter(MedicationReminder.status == "CANCELADA")
        .label("cancelled"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason
                == "TREATMENT_CANCELLED",
            )
        )
        .label("cancelled_treatment_cancelled"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason == "TREATMENT_PAUSED",
            )
        )
        .label("cancelled_treatment_paused"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason
                == "TREATMENT_COMPLETED",
            )
        )
        .label("cancelled_treatment_completed"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason
                == "MEDICATION_DEACTIVATED",
            )
        )
        .label("cancelled_medication_deactivated"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason == "LINK_REMOVED",
            )
        )
        .label("cancelled_link_removed"),
        func.count()
        .filter(
            and_(
                MedicationReminder.status == "CANCELADA",
                MedicationReminder.cancel_reason.is_(None),
            )
        )
        .label("cancelled_unknown"),
    ]


def _apply_filters(stmt, *, user_id, from_utc, to_utc, medication_id, treatment_id):
    """Filtros comunes: usuario, rango y medicamento/tratamiento."""
    stmt = stmt.where(
        MedicationReminder.user_id == user_id,
        MedicationReminder.scheduled_at >= from_utc,
        MedicationReminder.scheduled_at < to_utc,
        MedicationReminder.status.not_in(_EXCLUDED_STATUSES),
    )
    if medication_id is not None:
        stmt = stmt.where(
            TreatmentMedication.medication_id == medication_id
        )
    if treatment_id is not None:
        stmt = stmt.where(
            TreatmentMedication.treatment_id == treatment_id
        )
    return stmt


async def compliance_counts(
    session: AsyncSession,
    *,
    user_id: int,
    from_utc: datetime,
    to_utc: datetime,
    medication_id: int | None = None,
    treatment_id: int | None = None,
) -> dict[str, int]:
    """Conteos de cumplimiento de un periodo (RF14, sin agrupar).

    Devuelve los 4 conteos de categoría y el desglose de las
    canceladas por motivo (D-11). La suma de los seis desgloses
    debe ser igual a `cancelled` (el servicio lo verifica).
    """
    stmt = (
        select(*_count_columns())
        .select_from(MedicationReminder)
        .outerjoin(
            MedicationIntake,
            MedicationIntake.reminder_id == MedicationReminder.id,
        )
        .join(
            TreatmentMedication,
            TreatmentMedication.id
            == MedicationReminder.treatment_medication_id,
        )
    )
    stmt = _apply_filters(
        stmt,
        user_id=user_id,
        from_utc=from_utc,
        to_utc=to_utc,
        medication_id=medication_id,
        treatment_id=treatment_id,
    )
    result = await session.execute(stmt)
    row = result.one()
    return dict(row._mapping)


async def compliance_counts_grouped(
    session: AsyncSession,
    *,
    user_id: int,
    from_utc: datetime,
    to_utc: datetime,
    group_by: str,
    tz_name: str,
    medication_id: int | None = None,
    treatment_id: int | None = None,
) -> list[dict]:
    """Conteos de cumplimiento por grupo (D-7).

    Una fila por grupo PRESENTE en el periodo (la serie
    completa, con los grupos vacíos, la construye el servicio
    en Python; plan §6.2). Cada fila trae la clave del grupo
    (`period_start` para día/semana/mes; `medication_id` +
    `medication_name` para medicamento) y las mismas 10
    columnas de conteo que `compliance_counts`.

    La agrupación temporal usa la hora LOCAL del usuario
    (`scheduled_at AT TIME ZONE :tz`, plan §6.2): un
    recordatorio a las 23:30 hora de Bogotá pertenece al día
    local, aunque en UTC sea el día siguiente. Las semanas son
    ISO (lunes a domingo, `date_trunc('week')`); los meses, de
    calendario (`date_trunc('month')`).
    """
    # Hora local del usuario (timestamptz -> timestamp sin zona).
    local = func.timezone(tz_name, MedicationReminder.scheduled_at)
    if group_by == "medication":
        key_columns = [
            TreatmentMedication.medication_id.label("medication_id"),
            Medication.name.label("medication_name"),
        ]
        group_columns = [
            TreatmentMedication.medication_id,
            Medication.name,
        ]
        order_columns = [Medication.name.asc()]
        join_medication = True
    elif group_by == "day":
        key = local.cast(Date).label("period_start")
        key_columns = [key]
        group_columns = [key]
        order_columns = [key.asc()]
        join_medication = False
    elif group_by == "week":
        key = func.date_trunc("week", local).cast(Date).label("period_start")
        key_columns = [key]
        group_columns = [key]
        order_columns = [key.asc()]
        join_medication = False
    elif group_by == "month":
        key = func.date_trunc("month", local).cast(Date).label("period_start")
        key_columns = [key]
        group_columns = [key]
        order_columns = [key.asc()]
        join_medication = False
    else:
        raise ValueError(f"group_by no soportado: {group_by}")
    stmt = (
        select(*key_columns, *_count_columns())
        .select_from(MedicationReminder)
        .outerjoin(
            MedicationIntake,
            MedicationIntake.reminder_id == MedicationReminder.id,
        )
        .join(
            TreatmentMedication,
            TreatmentMedication.id
            == MedicationReminder.treatment_medication_id,
        )
    )
    if join_medication:
        stmt = stmt.join(
            Medication, Medication.id == TreatmentMedication.medication_id
        )
    stmt = _apply_filters(
        stmt,
        user_id=user_id,
        from_utc=from_utc,
        to_utc=to_utc,
        medication_id=medication_id,
        treatment_id=treatment_id,
    )
    stmt = stmt.group_by(*group_columns).order_by(*order_columns)
    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result.all()]
