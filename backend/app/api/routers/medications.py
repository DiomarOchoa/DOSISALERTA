"""Endpoints de medicamentos (Fase 4, RF04).

``POST /api/v1/medications``, ``GET /api/v1/medications``,
``GET /api/v1/medications/{id}``, ``PATCH`` y ``DELETE``
(desactivacion logica), mas ``POST /{id}/reactivate``
(reactivacion logica, I-7). Las rutas solo validan la entrada,
llaman al servicio y devuelven la respuesta; no contienen
logica de negocio ni SQL.

`patient_id` (query, opcional) es como el cuidador indica
sobre que paciente actua: si viene y no es el propio usuario,
el servicio exige el vinculo ACTIVO y el permiso concreto
(diseno §4.6.7). La web (Fase 8) no lo expone: es solo API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.medications import (
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
)
from app.services import medication_service

router = APIRouter(prefix="/medications", tags=["medications"])


@router.post(
    "",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_medication(
    data: MedicationCreate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> MedicationResponse:
    """Crea un medicamento en el catalogo propio (201)."""
    return await medication_service.create_medication(
        session, current_user, data, patient_id=patient_id
    )


@router.get("", response_model=list[MedicationResponse])
async def list_medications(
    is_active: bool = True,
    limit: int = Query(default=100, ge=1, le=200),
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> list[MedicationResponse]:
    """Lista los medicamentos propios, ordenados por nombre (200)."""
    return await medication_service.list_medications(
        session,
        current_user,
        is_active=is_active,
        limit=limit,
        patient_id=patient_id,
    )


@router.get("/{medication_id}", response_model=MedicationResponse)
async def get_medication(
    medication_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> MedicationResponse:
    """Devuelve un medicamento propio por id (200)."""
    return await medication_service.get_medication(
        session, current_user, medication_id, patient_id=patient_id
    )


@router.patch("/{medication_id}", response_model=MedicationResponse)
async def update_medication(
    medication_id: int,
    data: MedicationUpdate,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> MedicationResponse:
    """Edita parcialmente un medicamento propio (200)."""
    return await medication_service.update_medication(
        session, current_user, medication_id, data, patient_id=patient_id
    )


@router.delete("/{medication_id}", response_model=MedicationResponse)
async def delete_medication(
    medication_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> MedicationResponse:
    """Desactiva un medicamento (`is_active=False`, 200)."""
    return await medication_service.deactivate_medication(
        session, current_user, medication_id, patient_id=patient_id
    )


@router.post("/{medication_id}/reactivate", response_model=MedicationResponse)
async def reactivate_medication(
    medication_id: int,
    patient_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> MedicationResponse:
    """Reactiva un medicamento (`is_active=True`, 200; I-7)."""
    return await medication_service.reactivate_medication(
        session, current_user, medication_id, patient_id=patient_id
    )
