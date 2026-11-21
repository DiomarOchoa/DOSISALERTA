"""Endpoints de tomas: confirmar y posponer (Fase 5, Etapa 4).

``POST /api/v1/reminders/{id}/confirm`` y
``POST /api/v1/reminders/{id}/postpone``. Las rutas solo validan
la entrada, llaman al servicio y devuelven la respuesta; no
contienen logica de negocio ni SQL.

Sin `patient_id`: confirmar y posponer son solo del paciente.
Un cuidador que llama con el id del recordatorio de su paciente
recibe 403 con auditoria ACCESS_DENIED (el servicio lo decide);
un extrano recibe 403 sin auditoria.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.reminders import (
    IntakeResponse,
    PostponeRequest,
    PostponeResponse,
)
from app.services import intake_service

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
