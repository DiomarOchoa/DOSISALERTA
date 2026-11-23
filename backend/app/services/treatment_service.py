"""Logica de negocio de tratamientos y vinculos (Fase 4, RF05/RF06/RF08).

Crear (atomico), listar, ver, editar, pausar/reanudar/cancelar/
completar tratamientos; anadir, editar dosis y quitar
medicamentos de tratamientos. Llama a los repositorios y a
`caregiver_access`. Sin manejador generico de excepciones: los
errores controlados son `HTTPException` (400/401/403/404/409)
y la validacion de Pydantic (422) la hace FastAPI.

Reglas del cuidador (diseno §4.6.7, RELACIONES §6.2):
- Lectura: paciente o cuidador con `perm_view_treatments`;
  secciones anidadas por D-1 (`medications` solo con
  `perm_view_medications`, horarios solo con
  `perm_view_schedules`, proximos recordatorios solo con
  `perm_view_upcoming`). La seccion sin permiso se omite del
  JSON (ni `null` ni lista vacia).
- Mutaciones (crear/editar/cambiar estado/anadir/quitar/
  cambiar dosis): **solo paciente**. El cuidador recibe **403
  directo, sin cargar el vinculo**; la denegacion se audita
  (`ACCESS_DENIED`) cuando `patient_id` viene y es distinto del
  actor.

Maquina de estados (diseno §4.6.4): ACTIVO -> PAUSADO /
CANCELADO / COMPLETADO; PAUSADO -> ACTIVO / CANCELADO;
CANCELADO y COMPLETADO son terminales (cualquier transicion
-> 400). Pausar/cancelar/completar cancelan los recordatorios
PENDIENTE y ENVIANDO futuros y conservan el historial.
Reanudar regenera los recordatorios (§4.7, horizonte 72 horas).

Refresh tras UPDATE (leccion del modulo de medicamentos):
`updated_at` tiene `onupdate=func.now()`; tras el UPDATE la
base regenera el valor y SQLAlchemy lo marca expirado. Sin
`await session.refresh(...)` tras el commit, el `model_validate`
sincrono intentaria una carga perezosa y fallaria con
MissingGreenlet. Por eso cada operacion que hace UPDATE
recarga el objeto antes de construir la respuesta.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caregivers import CaregiverLink
from app.models.medications import (
    TREATMENT_STATUSES,
    Treatment,
    TreatmentMedication,
)
from app.models.users import User
from app.repositories import (
    medication_repository,
    reminder_repository,
    schedule_repository,
    treatment_medication_repository,
    treatment_repository,
)
from app.schemas.treatments import (
    MedicationSummary,
    ReminderResponse,
    ScheduleResponse,
    TreatmentCreate,
    TreatmentMedicationCreate,
    TreatmentMedicationResponse,
    TreatmentMedicationUpdate,
    TreatmentResponse,
    TreatmentSummary,
    TreatmentUpdate,
)
from app.services import caregiver_access, schedule_service

_NOT_FOUND_ERROR = "Tratamiento no encontrado"
_LINK_NOT_FOUND_ERROR = "Medicamento del tratamiento no encontrado"
_MEDICATION_NOT_FOUND_ERROR = "Medicamento no encontrado"
_FORBIDDEN_ERROR = "No tienes permiso para realizar esta acción"
_INVALID_DATE_RANGE_ERROR = (
    "La fecha de fin no puede ser anterior a la fecha de inicio"
)
_TREATMENT_NOT_ACTIVE_ERROR = "El tratamiento no está activo"
_DUPLICATE_LINK_ERROR = "El medicamento ya está en el tratamiento"
_DEACTIVATED_MEDICATION_ERROR = "El medicamento está desactivado"
_TERMINAL_STATE_ERROR = "El tratamiento ya está cancelado/completado"
_INVALID_TRANSITION_ERROR = (
    "Transición de estado no válida para el tratamiento"
)

# Transiciones permitidas (diseno §4.6.4). CANCELADO y
# COMPLETADO son terminales.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "ACTIVO": {"PAUSADO", "CANCELADO", "COMPLETADO"},
    "PAUSADO": {"ACTIVO", "CANCELADO"},
    "CANCELADO": set(),
    "COMPLETADO": set(),
}

# Horizonte de generacion vigente (escenario A, 2026-11-20).
_GENERATION_HORIZON_HOURS = schedule_service.GENERATION_HORIZON_HOURS

# Secciones de D-1: todas visibles (paciente propietario).
_ALL_SECTIONS = {"medications": True, "schedules": True, "upcoming": True}


def _is_caregiver(actor: User, effective_user_id: int) -> bool:
    """True si el actor actua sobre los datos de otro usuario."""
    return effective_user_id != actor.id


def _normalize_times(times: list) -> list:
    """`times` ordenadas y sin duplicados (diseno §4.4)."""
    return sorted(set(times))


async def _reject_caregiver_mutation(
    session: AsyncSession,
    actor: User,
    patient_id: int | None,
    *,
    attempted_action: str,
    target_type: str | None = None,
    target_id: int | None = None,
) -> None:
    """403 directo para el cuidador en mutaciones (§4.6.7).

    Sin cargar el vinculo. Si `patient_id` viene y es distinto
    del actor, la denegacion se audita (`ACCESS_DENIED`, con
    commit inmediato como hace el helper). Si no viene o es el
    propio actor, el actor es el dueno y no se rechaza.

    Si el paciente no existe no se puede auditar (la FK de
    `caregiver_audit_log.patient_user_id` daria 500): se deniega
    con 403 sin registro, igual que `resolve_actor`.
    """
    if patient_id is None or patient_id == actor.id:
        return
    patient = await session.get(User, patient_id)
    if patient is None:
        raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)
    await caregiver_access.audit_denied(
        session,
        caregiver_id=actor.id,
        patient_id=patient_id,
        attempted_action=attempted_action,
        target_type=target_type,
        target_id=target_id,
    )
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def _load_treatment_or_error(
    session: AsyncSession, treatment_id: int, effective_user_id: int
) -> Treatment:
    """Carga el tratamiento del usuario efectivo (404 o 403).

    404 si no existe en ninguna cuenta; 403 si existe pero es de
    otro usuario (diseno §4.6.1).
    """
    treatment = await treatment_repository.get_by_id(
        session, treatment_id, effective_user_id
    )
    if treatment is not None:
        return treatment
    any_treatment = await treatment_repository.get_by_id(session, treatment_id)
    if any_treatment is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def _load_link_or_error(
    session: AsyncSession,
    treatment_id: int,
    link_id: int,
    effective_user_id: int,
) -> TreatmentMedication:
    """Carga el vinculo de un tratamiento del usuario efectivo.

    404 si no existe o no pertenece a ese tratamiento; 403 si
    existe en ese tratamiento pero es de otro usuario.
    """
    link = await treatment_medication_repository.get_by_id(
        session, link_id, effective_user_id, treatment_id
    )
    if link is not None:
        return link
    any_link = await treatment_medication_repository.get_by_id(session, link_id)
    if any_link is None or any_link.treatment_id != treatment_id:
        raise HTTPException(status_code=404, detail=_LINK_NOT_FOUND_ERROR)
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def _load_medication_for_treatment(
    session: AsyncSession, medication_id: int, effective_user_id: int
):
    """Medicamento del usuario efectivo, listo para un tratamiento.

    404 si no existe; 403 si es de otro usuario; 409 si esta
    desactivado (un medicamento desactivado no se puede anadir a
    un tratamiento, diseno §4.6.2).
    """
    medication = await medication_repository.get_by_id(
        session, medication_id, effective_user_id
    )
    if medication is not None:
        if not medication.is_active:
            raise HTTPException(
                status_code=409, detail=_DEACTIVATED_MEDICATION_ERROR
            )
        return medication
    any_medication = await medication_repository.get_by_id(session, medication_id)
    if any_medication is None:
        raise HTTPException(status_code=404, detail=_MEDICATION_NOT_FOUND_ERROR)
    raise HTTPException(status_code=403, detail=_FORBIDDEN_ERROR)


async def _caregiver_section_permissions(
    session: AsyncSession, actor: User, effective_user_id: int
) -> dict[str, bool]:
    """Permisos de seccion D-1 del cuidador.

    Para el dueno, todo True. Para el cuidador, se lee su vinculo
    ACTIVO con el paciente: cada seccion exige su permiso
    concreto. (`resolve_actor` ya verifico el vinculo y
    `perm_view_treatments`; aqui solo se leen las demas columnas.)
    """
    if effective_user_id == actor.id:
        return dict(_ALL_SECTIONS)
    stmt = select(CaregiverLink).where(
        CaregiverLink.patient_user_id == effective_user_id,
        CaregiverLink.caregiver_user_id == actor.id,
        CaregiverLink.status == "ACTIVO",
    )
    result = await session.execute(stmt)
    link = result.scalar_one_or_none()
    if link is None:
        return {"medications": False, "schedules": False, "upcoming": False}
    return {
        "medications": bool(link.perm_view_medications),
        "schedules": bool(link.perm_view_schedules),
        "upcoming": bool(link.perm_view_upcoming),
    }


def _build_link_response(
    link: TreatmentMedication, *, include_schedules: bool
) -> TreatmentMedicationResponse:
    """Vinculo -> respuesta, con horarios solo si corresponde.

    `schedules` no se asigna cuando no corresponde (D-1): queda
    sin establecer y la ruta lo excluye del JSON con
    `response_model_exclude_unset=True`.
    """
    kwargs: dict = {
        "id": link.id,
        "medication_id": link.medication_id,
        "medication": MedicationSummary.model_validate(link.medication),
        "dose_amount": link.dose_amount,
        "dose_unit": link.dose_unit,
        "instructions": link.instructions,
        "is_active": link.is_active,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
    }
    if include_schedules:
        kwargs["schedules"] = [
            ScheduleResponse.model_validate(schedule)
            for schedule in link.schedules
        ]
    return TreatmentMedicationResponse(**kwargs)


def _build_reminder_response(reminder, treatment: Treatment) -> ReminderResponse:
    """Recordatorio -> respuesta, con medicamento, dosis y plan."""
    link = reminder.treatment_medication
    return ReminderResponse(
        id=reminder.id,
        scheduled_at=reminder.scheduled_at,
        status=reminder.status,
        medication=MedicationSummary.model_validate(link.medication),
        dose_amount=link.dose_amount,
        dose_unit=link.dose_unit,
        treatment=TreatmentSummary(id=treatment.id, title=treatment.title),
        schedule_id=reminder.schedule_id,
    )


async def _build_treatment_response(
    session: AsyncSession,
    treatment: Treatment,
    *,
    sections: dict[str, bool],
) -> TreatmentResponse:
    """Tratamiento -> respuesta, con filtrado por seccion (D-1).

    Las secciones sin permiso NO se asignan (ni se pasan al
    constructor ni se ponen en `None`): quedan sin establecer y
    la ruta las excluye del JSON.
    """
    kwargs: dict = {
        "id": treatment.id,
        "title": treatment.title,
        "notes": treatment.notes,
        "start_date": treatment.start_date,
        "end_date": treatment.end_date,
        "status": treatment.status,
        "created_at": treatment.created_at,
        "updated_at": treatment.updated_at,
    }
    if sections["medications"]:
        kwargs["medications"] = [
            _build_link_response(
                link, include_schedules=sections["schedules"]
            )
            for link in treatment.treatment_medications
        ]
    if sections["upcoming"]:
        now = datetime.now(timezone.utc)
        horizon_end = now + timedelta(hours=_GENERATION_HORIZON_HOURS)
        reminders = await reminder_repository.list_upcoming_for_treatment(
            session, treatment.id, treatment.user_id, now, horizon_end
        )
        kwargs["upcoming_reminders"] = [
            _build_reminder_response(reminder, treatment)
            for reminder in reminders
        ]
    return TreatmentResponse(**kwargs)


def _conflict_is_duplicate_link(exc: IntegrityError) -> bool:
    """True si el IntegrityError es el vinculo duplicado (409).

    Solo con la constraint exacta: `sqlstate == "23505"` Y
    `constraint_name == "uq_treatment_meds_active"` (patron de
    Fase 3). Cualquier otro IntegrityError se propaga (500).
    """
    orig = getattr(exc, "orig", None)
    return (
        getattr(orig, "sqlstate", None) == "23505"
        and getattr(orig, "constraint_name", None)
        == "uq_treatment_meds_active"
    )


async def create_treatment(
    session: AsyncSession,
    actor: User,
    data: TreatmentCreate,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Crea un tratamiento completo en una sola transaccion (201).

    Solo paciente (403 directo para el cuidador). Un solo commit:
    tratamiento -> flush -> vinculos -> flush -> horarios ->
    flush -> generar recordatorios -> commit. Cualquier error ->
    rollback: no queda tratamiento sin medicamentos ni
    medicamentos sin recordatorios (diseno §4.6.3).
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action="CREATE_TREATMENT",
            target_type="treatment",
        )
        effective_user_id = actor.id
        if data.end_date is not None and data.end_date < data.start_date:
            raise HTTPException(
                status_code=400, detail=_INVALID_DATE_RANGE_ERROR
            )
        seen_medications: set[int] = set()
        for item in data.medications:
            if item.medication_id in seen_medications:
                raise HTTPException(
                    status_code=409, detail=_DUPLICATE_LINK_ERROR
                )
            seen_medications.add(item.medication_id)
            await _load_medication_for_treatment(
                session, item.medication_id, effective_user_id
            )
        treatment = treatment_repository.create(
            session,
            user_id=effective_user_id,
            title=data.title,
            notes=data.notes,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        await session.flush()
        treatment_id = treatment.id
        for item in data.medications:
            link = treatment_medication_repository.create(
                session,
                user_id=effective_user_id,
                treatment_id=treatment_id,
                medication_id=item.medication_id,
                dose_amount=item.dose_amount,
                dose_unit=item.dose_unit,
                instructions=item.instructions,
            )
            await session.flush()
            for sched in item.schedules or []:
                if (
                    sched.end_date is not None
                    and sched.end_date < sched.start_date
                ):
                    raise HTTPException(
                        status_code=400, detail=_INVALID_DATE_RANGE_ERROR
                    )
                schedule = schedule_repository.create(
                    session,
                    user_id=effective_user_id,
                    treatment_medication_id=link.id,
                    frequency=sched.frequency,
                    days_of_week=sched.days_of_week,
                    interval_days=sched.interval_days,
                    times=_normalize_times(sched.times),
                    start_date=sched.start_date,
                    end_date=sched.end_date,
                )
                await session.flush()
                await schedule_service.generate_reminders_for_schedule(
                    session,
                    schedule,
                    treatment,
                    actor,
                    horizon_hours=_GENERATION_HORIZON_HOURS,
                )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        if _conflict_is_duplicate_link(exc):
            raise HTTPException(
                status_code=409, detail=_DUPLICATE_LINK_ERROR
            )
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_repository.get_by_id(
        session, treatment_id, effective_user_id
    )
    return await _build_treatment_response(
        session, reloaded, sections=dict(_ALL_SECTIONS)
    )


async def list_treatments(
    session: AsyncSession,
    actor: User,
    *,
    status: str | None = None,
    limit: int = 100,
    patient_id: int | None = None,
) -> list[TreatmentResponse]:
    """Lista los tratamientos del usuario efectivo (200).

    Paciente o cuidador con `perm_view_treatments`. Cada elemento
    lleva el filtrado por seccion de D-1 (aplicacion derivada).
    La accion del cuidador queda auditada (VIEW_TREATMENTS).
    """
    try:
        if status is not None and status not in TREATMENT_STATUSES:
            raise HTTPException(
                status_code=400, detail="Estado no válido"
            )
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_view_treatments",
            action="VIEW_TREATMENTS",
            target_type="treatment",
        )
        treatments = await treatment_repository.list_by_user(
            session, effective_user_id, status=status, limit=limit
        )
        sections = await _caregiver_section_permissions(
            session, actor, effective_user_id
        )
        responses = [
            await _build_treatment_response(
                session, treatment, sections=sections
            )
            for treatment in treatments
        ]
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="VIEW_TREATMENTS",
                target_type="treatment",
            )
            await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return responses


async def get_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Devuelve un tratamiento del usuario efectivo (200).

    Paciente: respuesta completa. Cuidador con
    `perm_view_treatments`: datos generales mas las secciones
    que sus permisos cubran (D-1). Sin `perm_view_treatments`
    -> 403 aunque tenga los demas permisos.
    """
    try:
        effective_user_id = await caregiver_access.resolve_actor(
            session,
            actor=actor,
            patient_id=patient_id,
            permission="perm_view_treatments",
            action="VIEW_TREATMENTS",
            target_type="treatment",
            target_id=treatment_id,
        )
        treatment = await _load_treatment_or_error(
            session, treatment_id, effective_user_id
        )
        sections = await _caregiver_section_permissions(
            session, actor, effective_user_id
        )
        response = await _build_treatment_response(
            session, treatment, sections=sections
        )
        if _is_caregiver(actor, effective_user_id):
            caregiver_access.audit_action(
                session,
                caregiver_id=actor.id,
                patient_id=effective_user_id,
                action="VIEW_TREATMENTS",
                target_type="treatment",
                target_id=treatment.id,
            )
            await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return response


async def update_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    data: TreatmentUpdate,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Edita parcialmente un tratamiento (200).

    Solo paciente: `title`, `notes`, `end_date`. El estado NO se
    edita aqui (`notes` es indicacion medica, §6.2). I-4: un
    tratamiento CANCELADO o COMPLETADO bloquea la edicion (400).
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action="UPDATE_TREATMENT",
            target_type="treatment",
            target_id=treatment_id,
        )
        treatment = await _load_treatment_or_error(
            session, treatment_id, actor.id
        )
        if treatment.status in ("CANCELADO", "COMPLETADO"):
            raise HTTPException(status_code=400, detail=_TERMINAL_STATE_ERROR)
        fields = data.model_dump(exclude_unset=True)
        new_end = fields.get("end_date", treatment.end_date)
        if new_end is not None and new_end < treatment.start_date:
            raise HTTPException(
                status_code=400, detail=_INVALID_DATE_RANGE_ERROR
            )
        treatment_repository.update(session, treatment, **fields)
        await session.commit()
        # `updated_at` con `onupdate`: refresh antes de validar.
        await session.refresh(treatment)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_repository.get_by_id(
        session, treatment.id, actor.id
    )
    return await _build_treatment_response(
        session, reloaded, sections=dict(_ALL_SECTIONS)
    )


async def _change_treatment_status(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    target_status: str,
    patient_id: int | None,
    attempted_action: str,
) -> TreatmentResponse:
    """Cambio de estado de un tratamiento (200).

    Solo paciente. Un UPDATE de estado + cancelacion o
    regeneracion de recordatorios en la misma transaccion.
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action=attempted_action,
            target_type="treatment",
            target_id=treatment_id,
        )
        treatment = await _load_treatment_or_error(
            session, treatment_id, actor.id
        )
        allowed = _ALLOWED_TRANSITIONS.get(treatment.status, set())
        if target_status not in allowed:
            if treatment.status in ("CANCELADO", "COMPLETADO"):
                raise HTTPException(
                    status_code=400, detail=_TERMINAL_STATE_ERROR
                )
            raise HTTPException(
                status_code=400, detail=_INVALID_TRANSITION_ERROR
            )
        treatment_repository.update_status(session, treatment, target_status)
        now = datetime.now(timezone.utc)
        if target_status == "ACTIVO":
            # Resume: regenerar los recordatorios de los horarios
            # activos de los vinculos activos (§4.7).
            links = await treatment_medication_repository.list_by_treatment(
                session, treatment.id, actor.id
            )
            for link in links:
                if not link.is_active:
                    continue
                schedules = (
                    await schedule_repository.list_by_treatment_medication(
                        session, link.id, actor.id
                    )
                )
                for schedule in schedules:
                    if not schedule.is_active:
                        continue
                    await schedule_service.regenerate_reminders_for_resume(
                        session,
                        schedule,
                        treatment,
                        actor,
                        horizon_hours=_GENERATION_HORIZON_HOURS,
                        now=now,
                    )
        else:
            # Pausar, cancelar o completar: cancelar los
            # recordatorios PENDIENTE y ENVIANDO futuros y
            # conservar el historial (diseno §4.6.4).
            # D-11: el motivo registra el primer evento de
            # cancelacion (la causa que cancelo la dosis).
            reason = {
                "CANCELADO": "TREATMENT_CANCELLED",
                "PAUSADO": "TREATMENT_PAUSED",
                "COMPLETADO": "TREATMENT_COMPLETED",
            }[target_status]
            await reminder_repository.cancel_pending_for_treatment(
                session, treatment.id, now, reason
            )
        await session.commit()
        # `updated_at` con `onupdate`: refresh antes de validar.
        await session.refresh(treatment)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_repository.get_by_id(
        session, treatment.id, actor.id
    )
    return await _build_treatment_response(
        session, reloaded, sections=dict(_ALL_SECTIONS)
    )


async def pause_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Pausa un tratamiento ACTIVO (200, status PAUSADO)."""
    return await _change_treatment_status(
        session, actor, treatment_id, "PAUSADO", patient_id, "PAUSE_TREATMENT"
    )


async def resume_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Reanuda un tratamiento PAUSADO (200, status ACTIVO)."""
    return await _change_treatment_status(
        session, actor, treatment_id, "ACTIVO", patient_id, "RESUME_TREATMENT"
    )


async def cancel_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Cancela un tratamiento ACTIVO o PAUSADO (200)."""
    return await _change_treatment_status(
        session, actor, treatment_id, "CANCELADO", patient_id, "CANCEL_TREATMENT"
    )


async def complete_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    patient_id: int | None = None,
) -> TreatmentResponse:
    """Completa un tratamiento ACTIVO (200)."""
    return await _change_treatment_status(
        session,
        actor,
        treatment_id,
        "COMPLETADO",
        patient_id,
        "COMPLETE_TREATMENT",
    )


async def add_medication_to_treatment(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    data: TreatmentMedicationCreate,
    patient_id: int | None = None,
) -> TreatmentMedicationResponse:
    """Anade un medicamento a un tratamiento existente (201).

    Solo paciente. El tratamiento debe estar ACTIVO (400 si no).
    Mismas validaciones que en la creacion: medicamento existe
    (404), es propio (403), esta activo (409) y no esta ya en el
    tratamiento (409). Si trae horarios, se crean y se generan
    sus recordatorios en la misma transaccion.
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action="ADD_TREATMENT_MEDICATION",
            target_type="treatment",
            target_id=treatment_id,
        )
        treatment = await _load_treatment_or_error(
            session, treatment_id, actor.id
        )
        if treatment.status != "ACTIVO":
            raise HTTPException(
                status_code=400, detail=_TREATMENT_NOT_ACTIVE_ERROR
            )
        await _load_medication_for_treatment(
            session, data.medication_id, actor.id
        )
        existing = await treatment_medication_repository.get_active_by_treatment_and_medication(
            session, treatment.id, data.medication_id, actor.id
        )
        if existing is not None:
            raise HTTPException(
                status_code=409, detail=_DUPLICATE_LINK_ERROR
            )
        link = treatment_medication_repository.create(
            session,
            user_id=actor.id,
            treatment_id=treatment.id,
            medication_id=data.medication_id,
            dose_amount=data.dose_amount,
            dose_unit=data.dose_unit,
            instructions=data.instructions,
        )
        await session.flush()
        link_id = link.id
        for sched in data.schedules or []:
            if sched.end_date is not None and sched.end_date < sched.start_date:
                raise HTTPException(
                    status_code=400, detail=_INVALID_DATE_RANGE_ERROR
                )
            schedule = schedule_repository.create(
                session,
                user_id=actor.id,
                treatment_medication_id=link_id,
                frequency=sched.frequency,
                days_of_week=sched.days_of_week,
                interval_days=sched.interval_days,
                times=_normalize_times(sched.times),
                start_date=sched.start_date,
                end_date=sched.end_date,
            )
            await session.flush()
            await schedule_service.generate_reminders_for_schedule(
                session,
                schedule,
                treatment,
                actor,
                horizon_hours=_GENERATION_HORIZON_HOURS,
            )
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        if _conflict_is_duplicate_link(exc):
            raise HTTPException(
                status_code=409, detail=_DUPLICATE_LINK_ERROR
            )
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_medication_repository.get_by_id(
        session, link_id, actor.id, treatment.id
    )
    return _build_link_response(reloaded, include_schedules=True)


async def update_treatment_medication(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    link_id: int,
    data: TreatmentMedicationUpdate,
    patient_id: int | None = None,
) -> TreatmentMedicationResponse:
    """Cambia la dosis, la unidad o las instrucciones (200).

    Solo paciente: la dosis es prescripcion medica (§6.2). I-4:
    un tratamiento CANCELADO o COMPLETADO bloquea la edicion (400).
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action="UPDATE_TREATMENT_MEDICATION",
            target_type="treatment_medication",
            target_id=link_id,
        )
        treatment = await _load_treatment_or_error(session, treatment_id, actor.id)
        if treatment.status in ("CANCELADO", "COMPLETADO"):
            raise HTTPException(status_code=400, detail=_TERMINAL_STATE_ERROR)
        link = await _load_link_or_error(
            session, treatment_id, link_id, actor.id
        )
        fields = data.model_dump(exclude_unset=True)
        treatment_medication_repository.update(session, link, **fields)
        await session.commit()
        # `updated_at` con `onupdate`: refresh antes de validar.
        await session.refresh(link)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_medication_repository.get_by_id(
        session, link.id, actor.id, treatment_id
    )
    return _build_link_response(reloaded, include_schedules=True)


async def delete_treatment_medication(
    session: AsyncSession,
    actor: User,
    treatment_id: int,
    link_id: int,
    patient_id: int | None = None,
) -> TreatmentMedicationResponse:
    """Quita un medicamento de un tratamiento (200).

    Solo paciente. Desactivacion logica (`is_active=False`) +
    cancelacion de sus recordatorios PENDIENTE y ENVIANDO
    futuros. El indice parcial permite volver a anadir el mismo
    medicamento despues. I-4: un tratamiento CANCELADO o
    COMPLETADO bloquea la eliminacion del vinculo (400).
    """
    try:
        await _reject_caregiver_mutation(
            session,
            actor,
            patient_id,
            attempted_action="DELETE_TREATMENT_MEDICATION",
            target_type="treatment_medication",
            target_id=link_id,
        )
        treatment = await _load_treatment_or_error(session, treatment_id, actor.id)
        if treatment.status in ("CANCELADO", "COMPLETADO"):
            raise HTTPException(status_code=400, detail=_TERMINAL_STATE_ERROR)
        link = await _load_link_or_error(
            session, treatment_id, link_id, actor.id
        )
        link_id_value = link.id
        treatment_medication_repository.deactivate(session, link)
        now = datetime.now(timezone.utc)
        schedules = await schedule_repository.list_by_treatment_medication(
            session, link.id, actor.id
        )
        for schedule in schedules:
            # D-11: el motivo es el retiro del vinculo.
            await reminder_repository.cancel_pending_for_schedule(
                session, schedule.id, now, "LINK_REMOVED"
            )
        await session.commit()
        # `updated_at` con `onupdate`: refresh antes de validar.
        await session.refresh(link)
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    reloaded = await treatment_medication_repository.get_by_id(
        session, link_id_value, actor.id, treatment_id
    )
    return _build_link_response(reloaded, include_schedules=True)
