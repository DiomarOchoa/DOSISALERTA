"""Endpoints de tomas: confirmar, posponer e historial.

``POST /api/v1/reminders/{id}/confirm`` y
``POST /api/v1/reminders/{id}/postpone`` (Fase 5, Etapa 4) y
``GET /api/v1/reminders/history`` (Fase 7, RF13). Las rutas solo
validan la entrada, llaman al servicio y devuelven la respuesta;
no contienen logica de negocio ni SQL.

Sin `patient_id`: confirmar y posponer son solo del paciente.
Un cuidador que llama con el id del recordatorio de su paciente
recibe 403 con auditoria ACCESS_DENIED (el servicio lo decide);
un extrano recibe 403 sin auditoria.

El historial SÍ admite cuidadores con `perm_view_history`
(`patient_id`): el servicio resuelve el usuario efectivo y
audita la lectura concedida (`VIEW_HISTORY`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.reminders import (
    IntakeResponse,
    PostponeRequest,
    PostponeResponse,
)
from app.schemas.stats import HistoryPageResponse
from app.services import intake_service, stats_service

router = APIRouter(prefix="/reminders", tags=["reminders"])


@router.post(
    "/{reminder_id}/confirm",
    response_model=IntakeResponse,
)
async def confirm_reminder(
    reminder_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> IntakeResponse:
    """Confirma una toma (200). Solo paciente. Sin cuerpo."""
    return await intake_service.confirm(
        session, current_user, reminder_id, source="WEB"
    )


@router.post(
    "/{reminder_id}/postpone",
    response_model=PostponeResponse,
)
async def postpone_reminder(
    reminder_id: int,
    data: PostponeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> PostponeResponse:
    """Pospone una toma 15, 30 o 60 minutos (200). Solo paciente."""
    return await intake_service.postpone(
        session,
        current_user,
        reminder_id,
        delay_minutes=data.delay_minutes,
    )


@router.get("/history", response_model=HistoryPageResponse)
async def get_history(
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    medication_id: int | None = None,
    treatment_id: int | None = None,
    status: (
        Literal[
            "PENDIENTE",
            "ENVIANDO",
            "ENVIADA",
            "TOMADA",
            "POSPUESTA",
            "PERDIDA",
            "CANCELADA",
            "FALLIDA",
        ]
        | None
    ) = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> HistoryPageResponse:
    """Historial de tomas del usuario efectivo (200, RF13, D-6).

    Sin filtro de fecha no hay filtro implícito. Admite
    cuidadores con `perm_view_history` (`patient_id`).
    """
    return await stats_service.get_history(
        session,
        current_user,
        patient_id=patient_id,
        from_dt=from_dt,
        to_dt=to_dt,
        medication_id=medication_id,
        treatment_id=treatment_id,
        status=status,
        limit=limit,
        offset=offset,
    )
