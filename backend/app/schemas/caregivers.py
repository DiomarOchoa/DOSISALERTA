"""Esquemas Pydantic de cuidadores (Etapa 5, RF20–RF22).

Entrada y salida de los endpoints de `api/routers/caregivers.py`.

El codigo de invitacion solo aparece en la respuesta de creacion
(`InviteCreateResponse.invite_code`): se muestra una sola vez al
paciente para que lo comparta con su cuidador, y nunca se guarda
en texto plano, nunca va en logs y ningun GET lo devuelve.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CaregiverPermissions(BaseModel):
    """Los 8 permisos independientes de un cuidador (RF21).

    Todos empiezan en False y se conceden explicitamente por el
    paciente, por separado. Gestionar exige poder ver (CHECK en
    la base de datos): el servicio rechaza con 422 un conjunto
    que ponga un permiso de gestion en True sin su permiso de
    lectura correspondiente.
    """

    perm_view_medications: bool = False
    perm_view_treatments: bool = False
    perm_view_schedules: bool = False
    perm_view_upcoming: bool = False
    perm_view_history: bool = False
    perm_receive_notifications: bool = False
    perm_manage_medications: bool = False
    perm_manage_schedules: bool = False


class CaregiverLinkResponse(BaseModel):
    """Un vinculo paciente–cuidador, como lo ve la web."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_user_id: int
    patient_name: str | None = None
    caregiver_user_id: int | None = None
    caregiver_name: str | None = None
    caregiver_email: str | None = None
    status: str
    perm_view_medications: bool
    perm_view_treatments: bool
    perm_view_schedules: bool
    perm_view_upcoming: bool
    perm_view_history: bool
    perm_receive_notifications: bool
    perm_manage_medications: bool
    perm_manage_schedules: bool
    invited_at: datetime
    invite_expires_at: datetime | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None


class InviteCreateResponse(CaregiverLinkResponse):
    """La invitacion recien creada, con el codigo (una sola vez)."""

    invite_code: str


class AcceptCodeRequest(BaseModel):
    """El cuidador presenta el codigo que le compartio el paciente."""

    code: str = Field(min_length=10, max_length=10)


class AcceptLinkRequest(BaseModel):
    """El paciente acepta la invitacion y fija los permisos iniciales."""

    permissions: CaregiverPermissions = CaregiverPermissions()


class PermissionsUpdateRequest(BaseModel):
    """El paciente cambia los permisos de un vinculo ACTIVO."""

    permissions: CaregiverPermissions


class CaregiverLinksResponse(BaseModel):
    """Mis vinculos: como paciente y como cuidador."""

    as_patient: list[CaregiverLinkResponse]
    as_caregiver: list[CaregiverLinkResponse]


class CaregiverAuditResponse(BaseModel):
    """Una fila de la auditoria de cuidadores (RF22)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    caregiver_user_id: int | None = None
    caregiver_name: str | None = None
    patient_user_id: int
    action: str
    target_type: str | None = None
    target_id: int | None = None
    details: dict | None = None
    result: str
    created_at: datetime


class CaregiverAuditPageResponse(BaseModel):
    """Pagina de auditoria, con total para la paginacion."""

    items: list[CaregiverAuditResponse]
    total: int
    limit: int
    offset: int
