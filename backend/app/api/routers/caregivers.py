"""Endpoints de cuidadores: invitacion, aceptacion, permisos,
revocacion y auditoria (Etapa 5, RF20–RF22).

Las rutas solo validan la entrada, llaman al servicio y devuelven
la respuesta; no contienen logica de negocio ni SQL. El servicio
decide cada 403/404/409 y registra la auditoria.

Flujo (RELACIONES_CUIDADORES.md §6.3):
1. El paciente crea la invitacion (POST /invite): recibe el codigo
   UNA SOLA VEZ para compartirlo con su cuidador. El codigo
   caduca en 15 minutos.
2. El cuidador, ya registrado, presenta el codigo
   (POST /accept-code): vincula su identidad a la invitacion.
   El vinculo sigue INVITADO.
3. El paciente acepta explicitamente y fija los permisos
   (POST /{id}/accept): el vinculo pasa a ACTIVO.
4. El paciente cambia permisos (PATCH /{id}/permissions) o
   revoca (POST /{id}/revoke, tambien lo puede hacer el cuidador).
5. El paciente consulta la auditoria (GET /audit): quien hizo
   que sobre sus datos.

Sin `patient_id`: la gestion de cuidadores es del propio usuario
(paciente o cuidador). Un cuidador nunca gestiona vinculos de
otro paciente: el servicio lo decide.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.caregivers import (
    AcceptCodeRequest,
    AcceptLinkRequest,
    CaregiverAuditPageResponse,
    CaregiverLinkResponse,
    CaregiverLinksResponse,
    InviteCreateResponse,
    PermissionsUpdateRequest,
)
from app.services import caregiver_service

router = APIRouter(prefix="/caregivers", tags=["caregivers"])


@router.post("/invite", response_model=InviteCreateResponse, status_code=201)
async def invite_caregiver(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> InviteCreateResponse:
    """Crea una invitacion y devuelve el codigo (una sola vez)."""
    return await caregiver_service.create_invite(session, current_user)


@router.post("/accept-code", response_model=CaregiverLinkResponse)
async def accept_code(
    data: AcceptCodeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverLinkResponse:
    """El cuidador presenta el codigo y vincula su identidad."""
    return await caregiver_service.accept_code(session, current_user, data)


@router.get("", response_model=CaregiverLinksResponse)
async def list_my_links(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverLinksResponse:
    """Mis vinculos: como paciente y como cuidador."""
    return await caregiver_service.list_links(session, current_user)


@router.post("/{link_id}/accept", response_model=CaregiverLinkResponse)
async def accept_link(
    link_id: int,
    data: AcceptLinkRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverLinkResponse:
    """El paciente acepta la invitacion y fija los permisos."""
    return await caregiver_service.accept_link(
        session, current_user, link_id, data.permissions
    )


@router.patch("/{link_id}/permissions", response_model=CaregiverLinkResponse)
async def update_permissions(
    link_id: int,
    data: PermissionsUpdateRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverLinkResponse:
    """El paciente cambia los permisos de un vinculo ACTIVO."""
    return await caregiver_service.update_permissions(
        session, current_user, link_id, data.permissions
    )


@router.post("/{link_id}/revoke", response_model=CaregiverLinkResponse)
async def revoke_link(
    link_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverLinkResponse:
    """Revoca un vinculo (paciente o cuidador)."""
    return await caregiver_service.revoke_link(session, current_user, link_id)


@router.get("/audit", response_model=CaregiverAuditPageResponse)
async def get_audit(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> CaregiverAuditPageResponse:
    """Auditoria del paciente: quien hizo que sobre sus datos."""
    return await caregiver_service.get_audit(
        session, current_user, limit=limit, offset=offset
    )
