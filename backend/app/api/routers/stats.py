"""Endpoints de estadísticas de cumplimiento (Fase 7, RF14).

``GET /api/v1/stats/compliance``. El cumplimiento es un cálculo,
no un recurso, por eso vive en este router nuevo (D-5). Las
agrupaciones (`group_by`, D-7) llegan en el commit 4.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.stats import ComplianceResponse
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get(
    "/compliance",
    response_model=ComplianceResponse,
    response_model_exclude_unset=True,
)
async def get_compliance(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    medication_id: int | None = None,
    treatment_id: int | None = None,
    patient_id: int | None = None,
    group_by: Literal["day", "week", "month", "medication"] | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> ComplianceResponse:
    """Resumen de cumplimiento del periodo (200).

    `from`/`to` son fechas (`YYYY-MM-DD`) en la zona del
    paciente (D-4); sin ellas, los últimos 30 días. Sin
    `group_by`, solo el resumen y `groups: null`. Con `group_by`
    (D-7), el resumen del periodo completo más el desglose por
    grupo. Los campos de identidad que no corresponden al tipo
    de grupo se omiten (`response_model_exclude_unset=True`,
    plan §5.3).
    """
    return await stats_service.get_compliance(
        session,
        current_user,
        patient_id=patient_id,
        from_date=from_date,
        to_date=to_date,
        medication_id=medication_id,
        treatment_id=treatment_id,
        group_by=group_by,
    )
