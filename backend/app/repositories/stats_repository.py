"""Agregación de cumplimiento (Fase 7, RF14).

Una sola consulta con `COUNT(*) FILTER (WHERE ...)`; el
porcentaje y el denominador se calculan en el servicio
(plan §6.2 y §6.3). El JOIN a `medication_intakes` es
`LEFT JOIN` (solo las `TOMADA` tienen toma).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import TreatmentMedication
from app.models.reminders import MedicationIntake, MedicationReminder
from app.scheduler.reconciliation import GRACE_MINUTES


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

    Los estados `POSPUESTA`, `FALLIDA`, `PENDIENTE`, `ENVIANDO`
    y `ENVIADA` no cuentan: se excluyen con `NOT IN` para que
    un estado nuevo no entre en el denominador sin decisión
    expresa (plan §6.2).

    La gracia es la misma del motor (`GRACE_MINUTES`, 30 min,
    inclusiva, D-8): `taken_at <= scheduled_at + 30 min` es a
    tiempo. Una `TOMADA` sin toma cuenta como tardía (D-9): el
    filtro de tardía incluye explícitamente `taken_at IS NULL`,
    porque sin él la fila desaparecería de ambos conteos por la
    lógica de tres valores de SQL.
    """
    grace = timedelta(minutes=GRACE_MINUTES)
    on_time = MedicationReminder.scheduled_at + grace
    stmt = (
        select(
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
        )
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
        .where(
            MedicationReminder.user_id == user_id,
            MedicationReminder.scheduled_at >= from_utc,
            MedicationReminder.scheduled_at < to_utc,
            MedicationReminder.status.not_in(
                ["POSPUESTA", "FALLIDA", "PENDIENTE", "ENVIANDO", "ENVIADA"]
            ),
        )
    )
    if medication_id is not None:
        stmt = stmt.where(
            TreatmentMedication.medication_id == medication_id
        )
    if treatment_id is not None:
        stmt = stmt.where(
            TreatmentMedication.treatment_id == treatment_id
        )
    result = await session.execute(stmt)
    row = result.one()
    return dict(row._mapping)
