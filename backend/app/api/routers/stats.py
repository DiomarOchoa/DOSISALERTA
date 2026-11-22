"""Endpoints de estadísticas de cumplimiento (Fase 7, RF14).

``GET /api/v1/stats/compliance``. El cumplimiento es un cálculo,
no un recurso, por eso vive en este router nuevo (D-5). Las
agrupaciones (`group_by`) llegan en el commit 4.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.stats import ComplianceResponse
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/compliance", response_model=ComplianceResponse)
async def get_compliance(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    medication_id: int | None = None,
    treatment_id: int | None = None,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> ComplianceResponse:
    """Resumen de cumplimiento del periodo (200).

    `from`/`to` son fechas (`YYYY-MM-DD`) en la zona del
    paciente (D-4); sin ellas, los últimos 30 días. Sin
    `group_by`, solo el resumen y `groups: null`.
    """
    return await stats_service.get_compliance(
        session,
        current_user,
        patient_id=patient_id,
        from_date=from_date,
        to_date=to_date,
        medication_id=medication_id,
        treatment_id=treatment_id,
    )
