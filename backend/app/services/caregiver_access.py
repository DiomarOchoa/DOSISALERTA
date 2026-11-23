"""Resolucion de actor: dueno o cuidador (Fase 4, diseno §4.6.7).

Helper compartido por los servicios de Fase 4. Centraliza la
decision de acceso del cuidador en un solo lugar: si el actor
pide actuar sobre los datos de otro usuario (`patient_id`),
exige un vinculo ACTIVO y el permiso concreto de esa operacion;
si no lo hay, 403 con auditoria ACCESS_DENIED.

Auditoria (RELACIONES_CUIDADORES.md §5 y §8, RF22):
- Accion concedida: el servicio la registra con `audit_action`
  (resultado OK), junto con la operacion, en un solo commit.
- Denegacion: `audit_denied` la registra con `ACCESS_DENIED` y
  la confirma de inmediato, para que sobreviva al rollback de
  la peticion. En ese momento no hay cambios pendientes en la
  sesion (la denegacion ocurre antes de modificar nada).
- `details` sigue la politica de minimizacion (§5.3): solo el
  nombre del campo que cambio; nunca dosis, concentraciones,
  nombres de medicamentos ni indicaciones medicas.

Acciones auditadas (lista de RELACIONES §5): `VIEW_MEDICATIONS`,
`VIEW_TREATMENTS`, `VIEW_SCHEDULES`, `VIEW_UPCOMING`,
`VIEW_HISTORY`, `MANAGE_MEDICATION_CREATE`,
`MANAGE_MEDICATION_UPDATE`, `MANAGE_MEDICATION_DEACTIVATE`,
`MANAGE_SCHEDULE_CREATE`, `MANAGE_SCHEDULE_UPDATE`,
`ACCESS_DENIED`.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caregivers import CaregiverAuditLog, CaregiverLink
from app.models.users import User

_FORBIDDEN_ERROR = "No tienes permiso para realizar esta acción"


async def _get_active_link(
    session: AsyncSession, *, patient_id: int, caregiver_id: int
) -> CaregiverLink | None:
    """Vinculo ACTIVO entre paciente y cuidador, si existe."""
    stmt = select(CaregiverLink).where(
        CaregiverLink.patient_user_id == patient_id,
        CaregiverLink.caregiver_user_id == caregiver_id,
        CaregiverLink.status == "ACTIVO",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def audit_action(
    session: AsyncSession,
    *,
    caregiver_id: int,
    patient_id: int,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Anade una fila de auditoria OK a la sesion (sin commit).

    La confirma el commit unico de la operacion que la origina.
    Solo la llama el servicio cuando el actor es un cuidador;
    el dueno no se audita (actua sobre sus propios datos).
    """
    session.add(
        CaregiverAuditLog(
            caregiver_user_id=caregiver_id,
            patient_user_id=patient_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            result="OK",
        )
    )


async def audit_denied(
    session: AsyncSession,
    *,
    caregiver_id: int,
    patient_id: int,
    attempted_action: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Registra una denegacion y la confirma de inmediato.

    La fila lleva `action="ACCESS_DENIED"` y `result="DENEGADO"`
    (RELACIONES §5 y §8: "403 y registro `ACCESS_DENIED` en
    auditoria"). La operacion intentada queda en `details`
    (`attempted_action`), para saber que se denego sin perder
    el registro uniforme de denegaciones.

    El commit inmediato es necesario: la denegacion se registra
    antes de lanzar el 403, y el rollback del servicio no debe
    borrarla. Solo se llama antes de modificar nada, asi que el
    commit no arrastra ningun otro cambio pendiente.
    """
    row_details: dict[str, Any] = dict(details) if details else {}
    if attempted_action is not None:
        row_details["attempted_action"] = attempted_action
    session.add(
        CaregiverAuditLog(
            caregiver_user_id=caregiver_id,
            patient_user_id=patient_id,
            action="ACCESS_DENIED",
            target_type=target_type,
            target_id=target_id,
            details=row_details or None,
            result="DENEGADO",
        )
    )
    await session.commit()


async def resolve_actor(
    session: AsyncSession,
    *,
    actor: User,
    patient_id: int | None,
    permission: str | None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
) -> int:
    """Devuelve el id del usuario efectivo (dueno o paciente).

    - `patient_id` None o igual a `actor.id`: el actor es el
      dueno; devuelve `actor.id`, sin auditoria y sin consultar
      ningun vinculo.
    - En otro caso: exige un vinculo ACTIVO entre el paciente y
      el actor y, si `permission` no es None, que el vinculo
      tenga ese permiso en True (`permission` recibe el nombre
      de columna real, `perm_*`). Si falta el vinculo o el
      permiso -> 403 y registro `ACCESS_DENIED` en auditoria
      (con la operacion intentada en `details`).
    - Si pasa, devuelve `patient_id`. La accion concedida la
      audita el servicio con `audit_action`: el helper no conoce
      la operacion (solo la denegacion, que si registra aqui).
    """
    if patient_id is None or patient_id == actor.id:
        return actor.id
    # El paciente debe existir para poder auditar la denegacion
    # (`caregiver_audit_log.patient_user_id` tiene FK a `users`):
    # un id inexistente daria 500 al insertar el registro
    # ACCESS_DENIED. El contrato documentado es 403 (no 404, para
    # no revelar si el usuario existe): se deniega sin intentar
    # el registro, igual que con un paciente real sin vinculo.
    patient = await session.get(User, patient_id)
    if patient is None:
        raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
    link = await _get_active_link(
        session, patient_id=patient_id, caregiver_id=actor.id
    )
    if link is None:
        await audit_denied(
            session,
            caregiver_id=actor.id,
            patient_id=patient_id,
            attempted_action=action,
            target_type=target_type,
            target_id=target_id,
        )
        raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
    if permission is not None and not getattr(link, permission, False):
        await audit_denied(
            session,
            caregiver_id=actor.id,
            patient_id=patient_id,
            attempted_action=action,
            target_type=target_type,
            target_id=target_id,
        )
        raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
    return patient_id
