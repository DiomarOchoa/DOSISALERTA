"""Historial y estadísticas de cumplimiento (Fase 7, RF13/RF14).

El servicio resuelve el usuario efectivo (dueño o paciente de
un cuidador autorizado con `perm_view_history`), valida el
periodo y calcula el porcentaje en Python a partir de los
conteos del repositorio (plan §6.3). El denominador y el
desglose viven en un solo lugar, para que un cambio de D-11
sea una modificación puntual.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User
from app.repositories import reminder_repository, stats_repository
from app.schemas.stats import (
    ComplianceResponse,
    ComplianceSummary,
    HistoryItemResponse,
    HistoryPageResponse,
)
from app.services import caregiver_access

logger = logging.getLogger(__name__)

# Claves del desglose por motivo (D-11), siempre presentes (0
# cuando no hay ninguna). La correspondencia con el valor de la
# columna es un simple `.lower()`; `unknown` cuenta las filas
# con `cancel_reason = NULL` (históricas, anteriores a la
# migración).
_REASON_KEYS = (
    "treatment_cancelled",
    "treatment_paused",
    "treatment_completed",
    "medication_deactivated",
    "link_removed",
    "unknown",
)

_RANGE_ERROR = "from debe ser anterior a to"


async def _resolve_effective_user(
    session: AsyncSession, actor: User, patient_id: int | None
) -> tuple[int, bool]:
    """Id del usuario efectivo y si el actor es cuidador.

    `patient_id` None o igual al propio id → dueño, sin
    auditoría. Otro `patient_id` → exige vínculo ACTIVO +
    `perm_view_history`; si falta, 403 + `ACCESS_DENIED`
    (lo decide `resolve_actor`).
    """
    effective_user_id = await caregiver_access.resolve_actor(
        session,
        actor=actor,
        patient_id=patient_id,
        permission="perm_view_history",
        action="VIEW_HISTORY",
    )
    return effective_user_id, effective_user_id != actor.id


async def _audit_caregiver_read(
    session: AsyncSession, actor: User, effective_user_id: int
) -> None:
    """Audita la lectura concedida a un cuidador (`VIEW_HISTORY` OK).

    El dueño no se audita. Se confirma de inmediato: la lectura
    no tiene otros cambios que arrastrar (patrón de
    `medication_service.list_medications`).
    """
    caregiver_access.audit_action(
        session,
        caregiver_id=actor.id,
        patient_id=effective_user_id,
        action="VIEW_HISTORY",
    )
    await session.commit()


def _as_utc(value: datetime) -> datetime:
    """Un datetime sin zona se asume UTC (plan §3.6)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def get_history(
    session: AsyncSession,
    actor: User,
    *,
    patient_id: int | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    medication_id: int | None = None,
    treatment_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> HistoryPageResponse:
    """Historial de tomas del usuario efectivo (RF13).

    Sin filtro de fecha no hay filtro implícito: se devuelven
    todas las tomas, ordenadas de más reciente a más antigua.
    El historial incluye todos los estados, también los no
    resueltos y los futuros (D-10).
    """
    try:
        effective_user_id, is_caregiver = await _resolve_effective_user(
            session, actor, patient_id
        )
        if is_caregiver:
            await _audit_caregiver_read(session, actor, effective_user_id)
        from_utc = _as_utc(from_dt) if from_dt is not None else None
        to_utc = _as_utc(to_dt) if to_dt is not None else None
        if from_utc is not None and to_utc is not None and from_utc >= to_utc:
            raise HTTPException(status_code=422, detail=_RANGE_ERROR)
        rows = await reminder_repository.list_history(
            session,
            user_id=effective_user_id,
            from_dt=from_utc,
            to_dt=to_utc,
            medication_id=medication_id,
            treatment_id=treatment_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        total = await reminder_repository.count_history(
            session,
            user_id=effective_user_id,
            from_dt=from_utc,
            to_dt=to_utc,
            medication_id=medication_id,
            treatment_id=treatment_id,
            status=status,
        )
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return HistoryPageResponse(
        items=[HistoryItemResponse(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _effective_period(
    from_date: date | None, to_date: date | None, tz: ZoneInfo
) -> tuple[date, date]:
    """Periodo efectivo (D-4): fechas en la zona del paciente.

    Sin parámetros: últimos 30 días (`hoy − 29`, `hoy + 1`).
    Solo `from`: `to = hoy + 1`. Solo `to`: `from = to − 30`.
    """
    today = datetime.now(tz).date()
    if from_date is None and to_date is None:
        from_date, to_date = today - timedelta(days=29), today + timedelta(days=1)
    elif from_date is not None and to_date is None:
        to_date = today + timedelta(days=1)
    elif from_date is None and to_date is not None:
        from_date = to_date - timedelta(days=30)
    return from_date, to_date


def _local_date_to_utc(day: date, tz: ZoneInfo) -> datetime:
    """Inicio del día local como instante UTC (el `to` es exclusive)."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)


def _build_summary(
    from_date: date, to_date: date, counts: dict[str, int]
) -> ComplianceSummary:
    """Resumen a partir de los conteos del repositorio.

    Denominador (D-1 opción 2; D-11 Alt 3, aprobada):
    `scheduled − cancelled + unknown`. Si el denominador es 0,
    el porcentaje es `null` (sin datos, no 0 %).
    """
    taken_on_time = counts["taken_on_time"]
    taken_late = counts["taken_late"]
    lost = counts["lost"]
    cancelled = counts["cancelled"]
    cancelled_by_reason = {
        key: counts[f"cancelled_{key}"] for key in _REASON_KEYS
    }
    scheduled = taken_on_time + taken_late + lost + cancelled
    denominator = scheduled - cancelled + cancelled_by_reason["unknown"]
    if (
        taken_on_time + taken_late + lost + cancelled != scheduled
        or sum(cancelled_by_reason.values()) != cancelled
    ):
        # Error de programación, no un dato del usuario: no se
        # devuelve un porcentaje con totales incoherentes.
        logger.error(
            "Totales de cumplimiento incoherentes: scheduled=%s, "
            "cancelled=%s, desglose=%s",
            scheduled,
            cancelled,
            cancelled_by_reason,
        )
        raise HTTPException(
            status_code=500, detail="Totales de cumplimiento incoherentes"
        )
    percentage = (
        round(taken_on_time / denominator * 100, 1)
        if denominator > 0
        else None
    )
    return ComplianceSummary(
        from_=from_date,
        to=to_date,
        scheduled=scheduled,
        taken_on_time=taken_on_time,
        taken_late=taken_late,
        lost=lost,
        cancelled=cancelled,
        cancelled_by_reason=cancelled_by_reason,
        compliance_percentage=percentage,
    )


async def get_compliance(
    session: AsyncSession,
    actor: User,
    *,
    patient_id: int | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    medication_id: int | None = None,
    treatment_id: int | None = None,
) -> ComplianceResponse:
    """Resumen de cumplimiento del periodo (RF14, sin `group_by`).

    `from`/`to` son fechas en la zona del paciente (D-4); el
    `group_by` y los grupos llegan en el commit 4, así que
    `groups` es `null`.
    """
    try:
        effective_user_id, is_caregiver = await _resolve_effective_user(
            session, actor, patient_id
        )
        if is_caregiver:
            await _audit_caregiver_read(session, actor, effective_user_id)
        # Zona del usuario efectivo (el paciente), no del cuidador.
        if effective_user_id == actor.id:
            tz = ZoneInfo(actor.timezone)
        else:
            patient = await session.get(User, effective_user_id)
            tz = ZoneInfo(patient.timezone)
        from_date, to_date = _effective_period(from_date, to_date, tz)
        if from_date >= to_date:
            raise HTTPException(status_code=422, detail=_RANGE_ERROR)
        from_utc = _local_date_to_utc(from_date, tz)
        to_utc = _local_date_to_utc(to_date, tz)
        counts = await stats_repository.compliance_counts(
            session,
            user_id=effective_user_id,
            from_utc=from_utc,
            to_utc=to_utc,
            medication_id=medication_id,
            treatment_id=treatment_id,
        )
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    summary = _build_summary(from_date, to_date, counts)
    return ComplianceResponse(summary=summary, groups=None)
