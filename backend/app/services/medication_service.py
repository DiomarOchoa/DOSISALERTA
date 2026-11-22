"""Logica de negocio de medicamentos (Fase 4, RF04).

Catalogo propio del usuario: crear, listar, ver, editar y
desactivar (logica, nunca borrado fisico). Llama a los
repositorios y a `caregiver_access`. Sin manejador generico de
excepciones: los errores controlados son `HTTPException`
(400/401/403/404/409) y la validacion de Pydantic (422) la hace
FastAPI.

Reglas del cuidador (diseno §4.6.2, RELACIONES §6.2, C3):
- Con `perm_manage_medications` puede CREAR medicamentos nuevos
  del paciente y editar solo `name`, `presentation` y `notes`.
- Editar `concentration` o `unit` -> 403 siempre (la
  concentracion es lo que se muestra como dosis).
- Desactivar solo si el medicamento NO esta en ningun
  `treatment_medication` activo de un tratamiento ACTIVO; si lo
  esta -> 403 (desactivarlo silenciaria sus recordatorios).
- Sin el permiso -> 403. Cada accion (concedida o denegada)
  queda en `caregiver_audit_log` (RF22).

404/403 (diseno §4.6.1): 404 si el recurso no existe; 403 si
existe pero pertenece a otro usuario.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import Medication
from app.models.users import User
from app.repositories import medication_repository, reminder_repository
from app.schemas.medications import (
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
)
from app.services import caregiver_access

_NOT_FOUND_ERROR = "Medicamento no encontrado"
_FORBIDDEN_ERROR = "No tienes permiso para realizar esta acción"

# Campos que el cuidador NO puede editar (C3). Si el payload
# trae alguno, se rechaza toda la peticion (403), no se ignora.
_CAREGIVER_FORBIDDEN_FIELDS = ("concentration", "unit")


def _is_caregiver(actor: User, effective_user_id: int) -> bool:
    """True si el actor actua sobre los datos de otro usuario."""
    return effective_user_id != actor.id


def _audit_details_for_update(fields: dict) -> dict | None:
    """`details` de auditoria para un PATCH (minimizacion, §5.3).

    Solo el nombre del campo que cambio; nunca los valores
    (nombre, presentacion y notas son datos del medicamento y
    estan prohibidos como valores en `details`).
    """
    names = sorted(fields.keys())
    if len(names) == 1:
        return {"field": names[0]}
    return {"fields": names}


async def _load_medication_or_error(
    session: AsyncSession, medication_id: int, effective_user_id: int
) -> Medication:
    """Carga el medicamento del usuario efectivo (404 o 403).

    404 si no existe en ninguna cuenta; 403 si existe pero es de
    otro usuario (diseno §4.6.1).
    """
    medication = await medication_repository.get_by_id(
        session, medication_id, effective_user_id
    )
    if medication is not None:
        return medication
    any_medication = await medication_repository.get_by_id(session, medication_id)
    if any_medication is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def create_medication(
    session: AsyncSession,
    actor: User,
    data: MedicationCreate,
    patient_id: int | None = None,
) -> MedicationResponse:
    """Crea un medicamento del usuario efectivo (201).

    Paciente o cuidador con `perm_manage_medications`. Una sola
    transaccion, un solo commit (medicamento + fila de auditoria
    del cuidador, si la hay).
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_manage_medications",
            action="MANAGE_MEDICATION_CREATE",
            target_type="medication",
        )
        medication = medication_repository.create(
            session,
            user_id=effective_user_id,
            name=data.name,
            presentation=data.presentation,
            concentration=data.concentration,
            unit=data.unit,
            notes=data.notes,
        )
        await session.flush()
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="MANAGE_MEDICATION_CREATE",
                target_type="medication",
                target_id=medication.id,
            )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return MedicationResponse.model_validate(medication)


async def list_medications(
    session: AsyncSession,
    actor: User,
    *,
    is_active: bool = True,
    limit: int = 100,
    patient_id: int | None = None,
) -> list[MedicationResponse]:
    """Lista los medicamentos del usuario efectivo (200).

    Solo propios (o del paciente, si actua un cuidador con
    `perm_view_medications`), ordenados por nombre. La accion
    del cuidador queda auditada (VIEW_MEDICATIONS).
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_view_medications",
            action="VIEW_MEDICATIONS",
            target_type="medication",
        )
        medications = await medication_repository.list_by_user(
            session, effective_user_id, is_active=is_active, limit=limit
        )
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="VIEW_MEDICATIONS",
                target_type="medication",
            )
            await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return [MedicationResponse.model_validate(m) for m in medications]


async def get_medication(
    session: AsyncSession,
    actor: User,
    medication_id: int,
    patient_id: int | None = None,
) -> MedicationResponse:
    """Devuelve un medicamento del usuario efectivo (200)."""
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_view_medications",
            action="VIEW_MEDICATIONS",
            target_type="medication",
            target_id=medication_id,
        )
        medication = await _load_medication_or_error(
            session, medication_id, effective_user_id
        )
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="VIEW_MEDICATIONS",
                target_type="medication",
                target_id=medication.id,
            )
            await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return MedicationResponse.model_validate(medication)


async def update_medication(
    session: AsyncSession,
    actor: User,
    medication_id: int,
    data: MedicationUpdate,
    patient_id: int | None = None,
) -> MedicationResponse:
    """Edita parcialmente un medicamento (200).

    Paciente: cualquier campo. Cuidador con
    `perm_manage_medications`: solo `name`, `presentation` y
    `notes`; si el payload trae `concentration` o `unit` -> 403
    y registro ACCESS_DENIED (toda la peticion se rechaza; los
    campos no se ignoran).
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_manage_medications",
            action="MANAGE_MEDICATION_UPDATE",
            target_type="medication",
            target_id=medication_id,
        )
        fields = data.model_dump(exclude_unset=True)
        if _is_caregiver(actor, effective_user_id) and any(
            field in fields for field in _CAREGIVER_FORBIDDEN_FIELDS
        ):
            forbidden = sorted(
                field for field in _CAREGIVER_FORBIDDEN_FIELDS if field in fields
            )
            await caregiver_access.audit_denied(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                attempted_action="MANAGE_MEDICATION_UPDATE",
                target_type="medication",
                target_id=medication_id,
                details={"fields": forbidden},
            )
            raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
        medication = await _load_medication_or_error(
            session, medication_id, effective_user_id
        )
        medication_repository.update(session, medication, **fields)
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="MANAGE_MEDICATION_UPDATE",
                target_type="medication",
                target_id=medication.id,
                details=_audit_details_for_update(fields),
            )
        await session.commit()
        # `updated_at` tiene `onupdate=func.now()`: tras el UPDATE
        # la base regenera el valor y SQLAlchemy lo marca expirado.
        # Sin este refresh, `model_validate` (sincrono) intentaria
        # una carga perezosa y fallaria con MissingGreenlet.
        await session.refresh(medication)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return MedicationResponse.model_validate(medication)


async def deactivate_medication(
    session: AsyncSession,
    actor: User,
    medication_id: int,
    patient_id: int | None = None,
) -> MedicationResponse:
    """Desactiva un medicamento (`is_active=False`, 200).

    Desactivacion logica, no borrado fisico. El paciente puede
    desactivar cualquiera de sus medicamentos. El cuidador con
    `perm_manage_medications` solo si el medicamento NO esta en
    ningun tratamiento activo; si lo esta -> 403 y registro
    ACCESS_DENIED (C3).
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_manage_medications",
            action="MANAGE_MEDICATION_DEACTIVATE",
            target_type="medication",
            target_id=medication_id,
        )
        medication = await _load_medication_or_error(
            session, medication_id, effective_user_id
        )
        if _is_caregiver(actor, effective_user_id) and (
            await medication_repository.is_in_active_treatment(
                session, medication_id, effective_user_id
            )
        ):
            await caregiver_access.audit_denied(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                attempted_action="MANAGE_MEDICATION_DEACTIVATE",
                target_type="medication",
                target_id=medication_id,
                details={"field": "is_active"},
            )
            raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
        medication_repository.deactivate(session, medication)
        # Fase A, I-3 (opcion A): desactivar cancela sus futuros
        # recordatorios PENDIENTE/ENVIANDO en la misma transaccion,
        # para que el paciente deje de recibir avisos de un farmaco
        # que ya no debe tomar. El historial no se toca.
        # D-11: el motivo es la desactivacion del medicamento.
        await reminder_repository.cancel_pending_for_medication(
            session,
            medication.id,
            effective_user_id,
            datetime.now(timezone.utc),
            "MEDICATION_DEACTIVATED",
        )
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="MANAGE_MEDICATION_DEACTIVATE",
                target_type="medication",
                target_id=medication.id,
                details={"field": "is_active"},
            )
        await session.commit()
        # `updated_at` tiene `onupdate=func.now()`: tras el UPDATE
        # la base regenera el valor y SQLAlchemy lo marca expirado.
        # Sin este refresh, `model_validate` (sincrono) intentaria
        # una carga perezosa y fallaria con MissingGreenlet.
        await session.refresh(medication)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return MedicationResponse.model_validate(medication)


async def reactivate_medication(
    session: AsyncSession,
    actor: User,
    medication_id: int,
    patient_id: int | None = None,
) -> MedicationResponse:
    """Reactiva un medicamento (`is_active=True`, 200).

    Reactivacion logica. El paciente puede reactivar cualquiera de
    sus medicamentos; el cuidador con `perm_manage_medications`
    tambien (mismo permiso y auditoria que la desactivacion).
    Idempotente: si ya esta activo, devuelve 200 sin modificarlo.

    No revive recordatorios: las filas CANCELADA conservan su motivo
    (decision B, D-11) y nunca vuelven a PENDIENTE. Los recordatorios
    futuros nuevos nacen por el top-up o la regeneracion normal de
    72 h (que solo genera para medicamentos activos, Fase A, I-3),
    no por esta funcion.

    A diferencia de la desactivacion, no hay restriccion por estar
    en un tratamiento activo: reactivar restaura el medicamento, no
    lo detiene, y es justo en un tratamiento activo donde se quiere
    volver a usarlo.
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_manage_medications",
            action="MANAGE_MEDICATION_REACTIVATE",
            target_type="medication",
            target_id=medication_id,
        )
        medication = await _load_medication_or_error(
            session, medication_id, effective_user_id
        )
        if medication.is_active:
            # Idempotente: ya esta activo, no hay nada que cambiar.
            return MedicationResponse.model_validate(medication)
        medication_repository.reactivate(session, medication)
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="MANAGE_MEDICATION_REACTIVATE",
                target_type="medication",
                target_id=medication.id,
                details={"field": "is_active"},
            )
        await session.commit()
        # `updated_at` tiene `onupdate=func.now()`: tras el UPDATE
        # la base regenera el valor y SQLAlchemy lo marca expirado.
        # Sin este refresh, `model_validate` (sincrono) intentaria
        # una carga perezosa y fallaria con MissingGreenlet.
        await session.refresh(medication)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return MedicationResponse.model_validate(medication)
