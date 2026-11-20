"""Endpoints de tratamientos y vinculos (Fase 4, RF05/RF06/RF08).

``POST /api/v1/treatments``, ``GET /api/v1/treatments``,
``GET /api/v1/treatments/{id}``, ``PATCH``, pause/resume/cancel/
complete, y los tres de medicamentos dentro de un tratamiento
(anadir, editar dosis, quitar). Las rutas solo validan la
entrada, llaman al servicio y devuelven la respuesta; no
contienen logica de negocio ni SQL.

`patient_id` (query, opcional) es como el cuidador indica
sobre que paciente actua: si viene y no es el propio usuario,
el servicio exige el vinculo ACTIVO y el permiso concreto
(diseno §4.6.7). La web (Fase 8) no lo expone: es solo API.

Las rutas GET de tratamientos usan
`response_model_exclude_unset=True`: el servicio construye
`TreatmentResponse` sin asignar las secciones que el cuidador
no puede ver (D-1) y asi la seccion queda ausente del JSON (ni
`null` ni lista vacia).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.treatments import (
    TreatmentCreate,
    TreatmentMedicationCreate,
    TreatmentMedicationResponse,
    TreatmentMedicationUpdate,
    TreatmentResponse,
    TreatmentUpdate,
)
from app.services import treatment_service

router = APIRouter(prefix="/treatments", tags=["treatments"])


@router.post(
    "",
    response_model=TreatmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_treatment(
    data: TreatmentCreate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Crea un tratamiento completo (201). Solo paciente."""
    return await treatment_service.create_treatment(
        session, current_user, data, patient_id=patient_id
    )


@router.get(
    "",
    response_model=list[TreatmentResponse],
    response_model_exclude_unset=True,
)
async def list_treatments(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> list[TreatmentResponse]:
    """Lista los tratamientos propios (200), con filtrado D-1."""
    return await treatment_service.list_treatments(
        session,
        current_user,
        status=status,
        limit=limit,
        patient_id=patient_id,
    )


@router.get(
    "/{treatment_id}",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def get_treatment(
    treatment_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Devuelve un tratamiento propio por id (200), con D-1."""
    return await treatment_service.get_treatment(
        session, current_user, treatment_id, patient_id=patient_id
    )


@router.patch(
    "/{treatment_id}",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def update_treatment(
    treatment_id: int,
    data: TreatmentUpdate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Edita parcialmente un tratamiento propio (200)."""
    return await treatment_service.update_treatment(
        session, current_user, treatment_id, data, patient_id=patient_id
    )


@router.post(
    "/{treatment_id}/pause",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def pause_treatment(
    treatment_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Pausa un tratamiento ACTIVO (200, status PAUSADO)."""
    return await treatment_service.pause_treatment(
        session, current_user, treatment_id, patient_id=patient_id
    )


@router.post(
    "/{treatment_id}/resume",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def resume_treatment(
    treatment_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Reanuda un tratamiento PAUSADO (200, status ACTIVO)."""
    return await treatment_service.resume_treatment(
        session, current_user, treatment_id, patient_id=patient_id
    )


@router.post(
    "/{treatment_id}/cancel",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def cancel_treatment(
    treatment_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Cancela un tratamiento ACTIVO o PAUSADO (200)."""
    return await treatment_service.cancel_treatment(
        session, current_user, treatment_id, patient_id=patient_id
    )


@router.post(
    "/{treatment_id}/complete",
    response_model=TreatmentResponse,
    response_model_exclude_unset=True,
)
async def complete_treatment(
    treatment_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentResponse:
    """Completa un tratamiento ACTIVO (200)."""
    return await treatment_service.complete_treatment(
        session, current_user, treatment_id, patient_id=patient_id
    )


@router.post(
    "/{treatment_id}/medications",
    response_model=TreatmentMedicationResponse,
    response_model_exclude_unset=True,
    status_code=status.HTTP_201_CREATED,
)
async def add_medication_to_treatment(
    treatment_id: int,
    data: TreatmentMedicationCreate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentMedicationResponse:
    """Anade un medicamento a un tratamiento ACTIVO (201)."""
    return await treatment_service.add_medication_to_treatment(
        session, current_user, treatment_id, data, patient_id=patient_id
    )


@router.patch(
    "/{treatment_id}/medications/{link_id}",
    response_model=TreatmentMedicationResponse,
    response_model_exclude_unset=True,
)
async def update_treatment_medication(
    treatment_id: int,
    link_id: int,
    data: TreatmentMedicationUpdate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentMedicationResponse:
    """Cambia la dosis de un medicamento del tratamiento (200)."""
    return await treatment_service.update_treatment_medication(
        session,
        current_user,
        treatment_id,
        link_id,
        data,
        patient_id=patient_id,
    )


@router.delete(
    "/{treatment_id}/medications/{link_id}",
    response_model=TreatmentMedicationResponse,
    response_model_exclude_unset=True,
)
async def delete_treatment_medication(
    treatment_id: int,
    link_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TreatmentMedicationResponse:
    """Quita un medicamento de un tratamiento (200)."""
    return await treatment_service.delete_treatment_medication(
        session, current_user, treatment_id, link_id, patient_id=patient_id
    )
