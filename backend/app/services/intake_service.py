"""Servicio de tomas: confirmar y posponer (Fase 5, Etapa 4).

Solo el paciente (dueno del recordatorio) puede confirmar o
posponer: no existe ningun permiso de cuidador que lo permita
(diseno 2026-11-11; el cuidador recibe 403 con auditoria
ACCESS_DENIED, un extrano recibe 403 sin auditoria). Las
transiciones las impone el servicio, no solo la BD: el estado
se cambia con un UPDATE atomico con WHERE de estados validos,
nunca leer-comprobar-escribir en dos pasos.

Idempotencia (spec §3.4):

- Confirmar dos veces devuelve la toma existente con 200, sin
  crear otra toma. La via rapida es el estado TOMADA; el
  respaldo es el UNIQUE de `medication_intakes.reminder_id`:
  si dos confirmaciones simultaneas chocan en el INSERT, se
  hace rollback y se devuelve la toma que ya existe.
- Posponer dos veces el mismo original es 409: la segunda
  llamada lo encuentra ya POSPUESTA y no crea un segundo hijo.

Las dos operaciones son una sola transaccion y un solo commit:
la toma y el TOMADA van juntos; el original POSPUESTA y el hijo
PENDIENTE van juntos; o queda todo, o nada.

Los servicios devuelven los esquemas de respuesta (convencion
del repo: `treatment_service` construye `TreatmentResponse`);
el router solo los devuelve.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caregivers import CaregiverLink
from app.models.reminders import MedicationReminder
from app.models.users import User
from app.repositories import intake_repository, reminder_repository
from app.schemas.reminders import (
    IntakeResponse,
    PostponeResponse,
    ReminderResponse,
)
from app.services import caregiver_access

__all__ = ["confirm", "postpone"]

_NOT_FOUND_ERROR = "Recordatorio no encontrado"
_FORBIDDEN_ERROR = "No tienes permiso para realizar esta acción"

# Estados desde los que se puede confirmar o posponer. ENVIANDO
# se admite: la confirmacion gana el estado y el `mark_sent` del
# scheduler no encuentra ENVIANDO y no cambia nada (Etapa 3).
CONFIRMABLE_STATUSES = ("PENDIENTE", "ENVIANDO", "ENVIADA", "FALLIDA")
POSTPONABLE_STATUSES = ("PENDIENTE", "ENVIANDO", "ENVIADA", "FALLIDA")

# I-5: maximo de posposiciones por cadena. El hijo hereda el
# contador del original (+1), asi que el tope se comprueba sobre
# el recordatorio que se intenta posponer: con 3 ya no se puede
# posponer mas (la cuarta posposicion es 409).
MAX_POSTPONEMENTS = 3
_POSTPONE_LIMIT_ERROR = "Límite de posposiciones alcanzado (máximo 3 por cadena)"

# Mensajes de 409 por estado (el estado actual no admite la operacion).
_STATE_MESSAGES = {
    "TOMADA": "La dosis ya fue tomada",
    "POSPUESTA": "El recordatorio ya fue pospuesto",
    "PERDIDA": "La dosis ya venció su ventana de gracia",
    "CANCELADA": "El recordatorio fue cancelado",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _conflict_message(status: str) -> str:
    return _STATE_MESSAGES.get(status, "El recordatorio no admite esta operación")


def _intake_response(intake, reminder_status: str) -> IntakeResponse:
    return IntakeResponse(
        id=intake.id,
        reminder_id=intake.reminder_id,
        user_id=intake.user_id,
        taken_at=intake.taken_at,
        source=intake.source,
        note=intake.note,
        created_at=intake.created_at,
        reminder_status=reminder_status,
    )


def _reminder_response(reminder: MedicationReminder) -> ReminderResponse:
    return ReminderResponse(
        id=reminder.id,
        schedule_id=reminder.schedule_id,
        treatment_medication_id=reminder.treatment_medication_id,
        user_id=reminder.user_id,
        scheduled_at=reminder.scheduled_at,
        status=reminder.status,
        parent_reminder_id=reminder.parent_reminder_id,
        postponed_count=reminder.postponed_count,
        version=reminder.version,
        created_at=reminder.created_at,
        updated_at=reminder.updated_at,
    )


async def _is_caregiver(
    session: AsyncSession, *, patient_id: int, caregiver_id: int
) -> bool:
    """True si hay un vinculo ACTIVO entre el paciente y el actor.

    Es la misma consulta que `caregiver_access._get_active_link`,
    repetida aqui para no modificar `caregiver_access.py` fuera
    de la lista de archivos de la Etapa 4: un helper compartido
    queda como limpieza posterior.
    """
    stmt = select(CaregiverLink.id).where(
        CaregiverLink.patient_user_id == patient_id,
        CaregiverLink.caregiver_user_id == caregiver_id,
        CaregiverLink.status == "ACTIVO",
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _require_owner(
    session: AsyncSession,
    actor: User,
    reminder: MedicationReminder,
    *,
    attempted_action: str,
) -> None:
    """Solo el dueno confirma o pospone.

    Cuidador (vinculo ACTIVO) -> 403 con auditoria ACCESS_DENIED
    (commit inmediato, sobrevive al rollback). Extrano (sin
    vinculo) -> 403 sin auditoria. Dueno -> sin auditoria.
    """
    if reminder.user_id == actor.id:
        return
    if await _is_caregiver(
        session, patient_id=reminder.user_id, caregiver_id=actor.id
    ):
        await caregiver_access.audit_denied(
            session,
            caregiver_id=actor.id,
            patient_id=reminder.user_id,
            attempted_action=attempted_action,
            target_type="reminder",
            target_id=reminder.id,
        )
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def _load_reminder_or_error(
    session: AsyncSession, reminder_id: int
) -> MedicationReminder:
    """El recordatorio, en cualquier cuenta (para distinguir 404 de 403)."""
    reminder = await reminder_repository.get_by_id(session, reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    return reminder


async def confirm(
    session: AsyncSession,
    actor: User,
    reminder_id: int,
    *,
    source: Literal["WEB", "TELEGRAM"],
) -> IntakeResponse:
    """Confirma una toma: crea la toma y marca TOMADA, en una transaccion.

    `taken_at` lo fija el servidor en el momento de la llamada:
    el cliente nunca envia una fecha. `source` es "WEB" desde el
    endpoint; la Fase 6 reutilizara esta funcion con "TELEGRAM".
    Confirmar dos veces devuelve la toma existente con 200.
    """
    reminder = await _load_reminder_or_error(session, reminder_id)
    await _require_owner(
        session, actor, reminder, attempted_action="CONFIRM_INTAKE"
    )

    # Via rapida de idempotencia: ya esta tomada.
    if reminder.status == "TOMADA":
        existing = await intake_repository.get_by_reminder_id(
            session, reminder_id
        )
        if existing is None:
            # Inconsistencia de datos: TOMADA sin toma. Falla alto.
            raise HTTPException(
                status_code=500,
                detail="La toma registrada no existe",
            )
        return _intake_response(existing, "TOMADA")

    transitioned = await reminder_repository.transition_to_taken(
        session,
        reminder_id,
        reminder.user_id,
        from_statuses=CONFIRMABLE_STATUSES,
    )
    if transitioned is None:
        # El estado cambio entre la lectura y el UPDATE (carrera).
        current = await _load_reminder_or_error(session, reminder_id)
        if current.status == "TOMADA":
            existing = await intake_repository.get_by_reminder_id(
                session, reminder_id
            )
            if existing is not None:
                return _intake_response(existing, "TOMADA")
        raise HTTPException(
            status_code=409, detail=_conflict_message(current.status)
        )

    intake = await intake_repository.create(
        session,
        reminder_id=reminder_id,
        user_id=reminder.user_id,
        taken_at=_utcnow(),
        source=source,
    )
    try:
        # El flush ejecuta el INSERT y asigna el id; si choca con
        # el UNIQUE (otra confirmacion simultanea), se resuelve
        # como "ya registrada" en lugar de fallar.
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await intake_repository.get_by_reminder_id(
            session, reminder_id
        )
        if existing is not None:
            return _intake_response(existing, "TOMADA")
        raise
    response = _intake_response(intake, "TOMADA")
    await session.commit()
    return response


async def postpone(
    session: AsyncSession,
    actor: User,
    reminder_id: int,
    *,
    delay_minutes: Literal[15, 30, 60],
    now: datetime | None = None,
) -> PostponeResponse:
    """Pospone una toma: el original queda POSPUESTA y nace un hijo.

    El hijo se programa en `now + delay_minutes` (por defecto,
    ahora UTC): "recuerdame en 15 minutos". Hereda horario,
    vinculo y usuario del original; `postponed_count` sube en uno.
    Todo en una sola transaccion. Si ya hay un recordatorio
    activo en ese instante para el mismo horario, es 409 y no
    cambia nada (rollback completo). I-5: si el recordatorio ya
    fue pospuesto `MAX_POSTPONEMENTS` veces (el contador de la
    cadena), es 409 y tampoco cambia nada.
    """
    reminder = await _load_reminder_or_error(session, reminder_id)
    await _require_owner(
        session, actor, reminder, attempted_action="POSTPONE_REMINDER"
    )

    if reminder.postponed_count >= MAX_POSTPONEMENTS:
        raise HTTPException(status_code=409, detail=_POSTPONE_LIMIT_ERROR)

    transitioned = await reminder_repository.transition_to_postponed(
        session,
        reminder_id,
        reminder.user_id,
        from_statuses=POSTPONABLE_STATUSES,
    )
    if transitioned is None:
        current = await _load_reminder_or_error(session, reminder_id)
        raise HTTPException(
            status_code=409, detail=_conflict_message(current.status)
        )

    at = now if now is not None else _utcnow()
    child = await reminder_repository.create_child(
        session,
        original=transitioned,
        scheduled_at=at + timedelta(minutes=delay_minutes),
    )
    try:
        await session.flush()
    except IntegrityError:
        # Colision con el indice unico parcial: ya hay un
        # recordatorio activo en ese instante para el horario.
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe un recordatorio activo en ese instante",
        )
    response = PostponeResponse(
        original=_reminder_response(transitioned),
        child=_reminder_response(child),
    )
    await session.commit()
    return response
