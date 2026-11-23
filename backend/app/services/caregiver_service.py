"""Gestion de vinculos paciente–cuidador (Etapa 5, RF20–RF22).

Implementa el diseno de `docs/database/RELACIONES_CUIDADORES.md`:

- Invitacion con codigo de un solo uso (10 caracteres, alfabeto
  de 32 sin confusiones, `secrets`, HMAC-SHA256 con el secreto
  independiente `CAREGIVER_LINK_SECRET`, expiracion 15 minutos).
  Solo se guarda el HMAC; el codigo en texto plano nunca se
  guarda, nunca va en logs y solo se devuelve una vez, en la
  respuesta de creacion de la invitacion.
- El cuidador presenta el codigo (vincula su identidad) y el
  paciente acepta explicitamente fijando los permisos: solo
  entonces el vinculo queda ACTIVO. Que el cuidador tenga el
  codigo no basta.
- Los 8 permisos son independientes y empiezan en False.
  Gestionar exige poder ver (CHECK en la base de datos): el
  servicio rechaza con 422 un conjunto que lo viole.
- Revocar es inmediato y definitivo: el vinculo pasa a REVOCADO
  con fecha y autor, el hash se borra en la misma transaccion y
  la historia y la auditoria se conservan. Para volver a vincular
  hace falta una invitacion nueva, en una fila nueva.
- Auditoria (RF22): cada accion del ciclo de vida queda en
  `caregiver_audit_log` (solo INSERT). `details` sigue la
  politica de minimizacion: solo el nombre del permiso que cambio
  y sus valores anterior y nuevo; nunca codigos, secretos, dosis
  ni nombres de medicamentos.

Limites de intentos (RELACIONES §6.3 y §13): 5 fallos sobre el
codigo vigente lo invalidan (hash a NULL; el paciente genera
otro codigo). El limite por `chat_id` de la tabla 14
(`caregiver_link_attempts`) es de la Fase 6 (bot): la web no
recibe codigos por chat y el codigo tiene 50 bits con expiracion
de 15 minutos, asi que la fuerza bruta por la web no es viable
sin ese limite.

Los errores de codigo son genericos a proposito (404 "Codigo no
valido o expirado"): un codigo inexistente, vencido, ya usado o
bloqueado devuelven lo mismo, para no confirmar que codigos
existen.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.caregivers import (
    CAREGIVER_PERMISSIONS,
    CaregiverAuditLog,
    CaregiverLink,
    CaregiverLinkAttempt,
)
from app.models.users import User
from app.schemas.caregivers import (
    AcceptCodeRequest,
    CaregiverAuditPageResponse,
    CaregiverAuditResponse,
    CaregiverLinkResponse,
    CaregiverLinksResponse,
    CaregiverPermissions,
    InviteCreateResponse,
)

# Alfabeto de 32 caracteres sin confusiones (sin I, O, 0 ni 1):
# 24 letras + 8 digitos = 50 bits por codigo de 10 caracteres.
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 10
_CODE_TTL = timedelta(minutes=15)
_MAX_FAILED_ATTEMPTS = 5

_GENERIC_CODE_ERROR = "Código no válido o expirado"
_NOT_FOUND_ERROR = "Vínculo no encontrado"
_FORBIDDEN_ERROR = "No tienes permiso para realizar esta acción"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _generate_code() -> str:
    """Codigo de invitacion de 10 caracteres, con `secrets`."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _code_hash(code: str) -> str:
    """HMAC-SHA256 del codigo con el secreto de cuidadores."""
    secret = get_settings().caregiver_link_secret.encode("utf-8")
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _validate_permissions(permissions: CaregiverPermissions) -> None:
    """Gestionar exige poder ver (CHECK de la base de datos)."""
    if permissions.perm_manage_medications and not permissions.perm_view_medications:
        raise HTTPException(
            status_code=422,
            detail="Para gestionar medicamentos hay que poder verlos.",
        )
    if permissions.perm_manage_schedules and not permissions.perm_view_schedules:
        raise HTTPException(
            status_code=422,
            detail="Para gestionar horarios hay que poder verlos.",
        )


def _audit(
    session: AsyncSession,
    *,
    caregiver_id: int | None,
    patient_id: int,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Anade una fila de auditoria OK a la sesion (sin commit).

    La confirma el commit unico de la operacion que la origina.
    `caregiver_id` puede ser None en eventos del ciclo de
    invitacion sin cuidador identificado (C4).
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


def _permissions_dict(permissions: CaregiverPermissions) -> dict[str, bool]:
    return {name: getattr(permissions, name) for name in CAREGIVER_PERMISSIONS}


async def _users_by_id(
    session: AsyncSession, user_ids: set[int]
) -> dict[int, User]:
    """Carga los usuarios indicados, en una sola consulta."""
    if not user_ids:
        return {}
    result = await session.execute(
        select(User).where(User.id.in_(sorted(user_ids)))
    )
    return {user.id: user for user in result.scalars().all()}


def _to_response(
    link: CaregiverLink, users: dict[int, User]
) -> CaregiverLinkResponse:
    patient = users.get(link.patient_user_id)
    caregiver = (
        users.get(link.caregiver_user_id)
        if link.caregiver_user_id is not None
        else None
    )
    return CaregiverLinkResponse(
        id=link.id,
        patient_user_id=link.patient_user_id,
        patient_name=patient.name if patient else None,
        caregiver_user_id=link.caregiver_user_id,
        caregiver_name=caregiver.name if caregiver else None,
        caregiver_email=caregiver.email if caregiver else None,
        status=link.status,
        perm_view_medications=link.perm_view_medications,
        perm_view_treatments=link.perm_view_treatments,
        perm_view_schedules=link.perm_view_schedules,
        perm_view_upcoming=link.perm_view_upcoming,
        perm_view_history=link.perm_view_history,
        perm_receive_notifications=link.perm_receive_notifications,
        perm_manage_medications=link.perm_manage_medications,
        perm_manage_schedules=link.perm_manage_schedules,
        invited_at=link.invited_at,
        invite_expires_at=link.invite_expires_at,
        accepted_at=link.accepted_at,
        revoked_at=link.revoked_at,
    )


async def create_invite(
    session: AsyncSession, patient: User
) -> InviteCreateResponse:
    """Crea una invitacion y devuelve el codigo (una sola vez).

    Si el paciente ya tiene una fila INVITADO anonima (sin
    cuidador identificado), se actualiza con el codigo nuevo, la
    expiracion nueva y `failed_attempts = 0` (RELACIONES §4.2):
    no se crea otra fila. En cualquier otro caso se crea una
    fila nueva.
    """
    code = _generate_code()
    code_hash = _code_hash(code)
    expires_at = _utcnow() + _CODE_TTL

    existing = await session.execute(
        select(CaregiverLink).where(
            CaregiverLink.patient_user_id == patient.id,
            CaregiverLink.status == "INVITADO",
            CaregiverLink.caregiver_user_id.is_(None),
        )
    )
    link = existing.scalar_one_or_none()
    if link is not None:
        link.invite_code_hash = code_hash
        link.invite_expires_at = expires_at
        link.failed_attempts = 0
        link.last_failed_at = None
    else:
        link = CaregiverLink(
            patient_user_id=patient.id,
            caregiver_user_id=None,
            status="INVITADO",
            invite_code_hash=code_hash,
            invite_expires_at=expires_at,
            failed_attempts=0,
            invited_by=patient.id,
        )
        session.add(link)
    await session.flush()
    _audit(
        session,
        caregiver_id=None,
        patient_id=patient.id,
        action="INVITE_CREATED",
        target_type="caregiver_link",
        target_id=link.id,
    )
    await session.commit()
    await session.refresh(link)
    users = await _users_by_id(session, {patient.id})
    response = _to_response(link, users)
    return InviteCreateResponse(**response.model_dump(), invite_code=code)


async def _record_failed_attempt(
    session: AsyncSession, link: CaregiverLink
) -> None:
    """Incrementa `failed_attempts` de forma atomica.

    Al llegar a 5 fallos sobre el codigo vigente, el codigo se
    invalida (hash a NULL) y queda en auditoria. El paciente
    genera otro codigo con una invitacion nueva.
    """
    result = await session.execute(
        update(CaregiverLink)
        .where(CaregiverLink.id == link.id)
        .values(
            failed_attempts=CaregiverLink.failed_attempts + 1,
            last_failed_at=_utcnow(),
        )
        .returning(CaregiverLink.failed_attempts)
    )
    attempts = result.scalar_one()
    if attempts >= _MAX_FAILED_ATTEMPTS:
        await session.execute(
            update(CaregiverLink)
            .where(CaregiverLink.id == link.id)
            .values(invite_code_hash=None, invite_expires_at=None)
        )
        _audit(
            session,
            caregiver_id=None,
            patient_id=link.patient_user_id,
            action="INVITE_CODE_INVALIDATED",
            target_type="caregiver_link",
            target_id=link.id,
        )
    await session.commit()


async def _record_caregiver_attempt(
    session: AsyncSession,
    *,
    chat_id: int,
    telegram_user_id: int | None,
    attempted_code_hash: str | None,
    success: bool,
    reason: str | None,
) -> None:
    """Registra un intento de codigo de cuidador (tabla 14, Fase 6).

    Solo la usa el bot (recibe codigos por `chat_id`); la web no
    recibe codigos por chat y no escribe aqui. El intento queda
    guardado aunque la vinculacion falle: es una fila de seguridad.
    El commit inmediato hace que sobreviva al error generico.
    """
    session.add(
        CaregiverLinkAttempt(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=attempted_code_hash,
            success=success,
            reason=reason,
        )
    )
    await session.commit()


async def _recent_caregiver_failures(session: AsyncSession, chat_id: int) -> int:
    """Fallos de codigo de cuidador de este chat en 15 minutos."""
    since = _utcnow() - timedelta(minutes=15)
    result = await session.execute(
        select(func.count())
        .select_from(CaregiverLinkAttempt)
        .where(
            CaregiverLinkAttempt.chat_id == chat_id,
            CaregiverLinkAttempt.success.is_(False),
            CaregiverLinkAttempt.attempted_at >= since,
        )
    )
    return int(result.scalar_one())


async def accept_code(
    session: AsyncSession,
    caregiver: User,
    data: AcceptCodeRequest,
    *,
    chat_id: int | None = None,
    telegram_user_id: int | None = None,
) -> CaregiverLinkResponse:
    """El cuidador presenta el codigo y vincula su identidad.

    La identidad queda vinculada a la invitacion, pero el vinculo
    NO queda ACTIVO: falta la aceptacion explicita del paciente
    con los permisos (`accept_link`). El codigo es de un solo uso
    en la practica: una vez vinculado, la fila ya tiene cuidador
    y un segundo intento con el mismo codigo es un fallo generico.

    Con `chat_id` (bot, `/vincular_cuidador`): cada intento queda
    en `caregiver_link_attempts` y 5 fallos en 15 minutos bloquean
    el chat (RELACIONES §13). Sin `chat_id` (web): el limite por
    chat no aplica y solo cuenta `failed_attempts` del vinculo.
    """
    code_hash = _code_hash(data.code)

    # Limite por chat (solo bot): 5 fallos en 15 minutos bloquean.
    if chat_id is not None and await _recent_caregiver_failures(session, chat_id) >= _MAX_FAILED_ATTEMPTS:
        await _record_caregiver_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=code_hash,
            success=False,
            reason="LIMITADO",
        )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    result = await session.execute(
        select(CaregiverLink).where(
            CaregiverLink.invite_code_hash == code_hash,
            CaregiverLink.status == "INVITADO",
        )
    )
    link = result.scalar_one_or_none()
    if link is None:
        if chat_id is not None:
            await _record_caregiver_attempt(
                session,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                attempted_code_hash=code_hash,
                success=False,
                reason="INVALIDO",
            )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    now = _utcnow()
    wrong_state = (
        link.caregiver_user_id is not None
        or link.invite_expires_at is None
        or link.invite_expires_at <= now
    )
    if wrong_state:
        # Codigo correcto pero vencido, ya usado o revocado: el
        # fallo se atribuye al vinculo y cuenta para invalidarlo.
        if chat_id is not None:
            reason = (
                "VENCIDO"
                if link.invite_expires_at is not None
                and link.invite_expires_at <= now
                else "INVALIDO"
            )
            await _record_caregiver_attempt(
                session,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                attempted_code_hash=code_hash,
                success=False,
                reason=reason,
            )
        await _record_failed_attempt(session, link)
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    if link.patient_user_id == caregiver.id:
        if chat_id is not None:
            await _record_caregiver_attempt(
                session,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                attempted_code_hash=code_hash,
                success=False,
                reason="INVALIDO",
            )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    existing = await session.execute(
        select(CaregiverLink).where(
            CaregiverLink.patient_user_id == link.patient_user_id,
            CaregiverLink.caregiver_user_id == caregiver.id,
            CaregiverLink.status != "REVOCADO",
        )
    )
    if existing.scalar_one_or_none() is not None:
        if chat_id is not None:
            await _record_caregiver_attempt(
                session,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                attempted_code_hash=code_hash,
                success=False,
                reason="INVALIDO",
            )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)

    # Reclamo atomico: solo una fila puede ganar la carrera, y
    # solo si sigue INVITADO, sin cuidador y sin expirar.
    claimed = await session.execute(
        update(CaregiverLink)
        .where(
            CaregiverLink.id == link.id,
            CaregiverLink.status == "INVITADO",
            CaregiverLink.caregiver_user_id.is_(None),
            CaregiverLink.invite_expires_at > now,
        )
        .values(caregiver_user_id=caregiver.id)
        .returning(CaregiverLink.id)
    )
    if claimed.scalar_one_or_none() is None:
        if chat_id is not None:
            await _record_caregiver_attempt(
                session,
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
                attempted_code_hash=code_hash,
                success=False,
                reason="INVALIDO",
            )
        raise HTTPException(status_code=404, detail=_GENERIC_CODE_ERROR)
    if chat_id is not None:
        await _record_caregiver_attempt(
            session,
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            attempted_code_hash=None,
            success=True,
            reason=None,
        )
    else:
        await session.commit()
    await session.refresh(link)
    users = await _users_by_id(
        session, {link.patient_user_id, caregiver.id}
    )
    return _to_response(link, users)


async def list_links(
    session: AsyncSession, user: User
) -> CaregiverLinksResponse:
    """Mis vinculos: como paciente y como cuidador."""
    result = await session.execute(
        select(CaregiverLink)
        .where(
            (CaregiverLink.patient_user_id == user.id)
            | (CaregiverLink.caregiver_user_id == user.id)
        )
        .order_by(CaregiverLink.created_at.desc())
    )
    links = result.scalars().all()
    user_ids = {link.patient_user_id for link in links}
    user_ids |= {
        link.caregiver_user_id
        for link in links
        if link.caregiver_user_id is not None
    }
    users = await _users_by_id(session, user_ids)
    return CaregiverLinksResponse(
        as_patient=[
            _to_response(link, users)
            for link in links
            if link.patient_user_id == user.id
        ],
        as_caregiver=[
            _to_response(link, users)
            for link in links
            if link.caregiver_user_id == user.id
        ],
    )


async def accept_link(
    session: AsyncSession,
    patient: User,
    link_id: int,
    permissions: CaregiverPermissions,
) -> CaregiverLinkResponse:
    """El paciente acepta la invitacion y fija los permisos.

    El vinculo pasa a ACTIVO, con el hash borrado en la misma
    transaccion. La invitacion debe estar INVITADO y con la
    identidad del cuidador ya vinculada (haber presentado el
    codigo): sin cuidador identificado no se puede aceptar.
    """
    _validate_permissions(permissions)
    result = await session.execute(
        select(CaregiverLink).where(CaregiverLink.id == link_id)
    )
    link = result.scalar_one_or_none()
    if link is None or link.patient_user_id != patient.id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    if link.status != "INVITADO":
        raise HTTPException(
            status_code=409,
            detail="La invitación no está pendiente de aceptación.",
        )
    if link.caregiver_user_id is None:
        raise HTTPException(
            status_code=409,
            detail="El cuidador aún no ha presentado el código.",
        )

    values = _permissions_dict(permissions)
    updated = await session.execute(
        update(CaregiverLink)
        .where(
            CaregiverLink.id == link.id,
            CaregiverLink.status == "INVITADO",
        )
        .values(
            status="ACTIVO",
            accepted_at=_utcnow(),
            invite_code_hash=None,
            invite_expires_at=None,
            **values,
        )
        .returning(CaregiverLink.id)
    )
    if updated.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=409,
            detail="La invitación no está pendiente de aceptación.",
        )
    _audit(
        session,
        caregiver_id=link.caregiver_user_id,
        patient_id=patient.id,
        action="INVITE_ACCEPTED",
        target_type="caregiver_link",
        target_id=link.id,
    )
    for name, granted in values.items():
        if granted:
            _audit(
                session,
                caregiver_id=link.caregiver_user_id,
                patient_id=patient.id,
                action="PERMISSION_GRANTED",
                target_type="caregiver_link",
                target_id=link.id,
                details={"permission": name, "old": False, "new": True},
            )
    await session.commit()
    await session.refresh(link)
    users = await _users_by_id(
        session, {patient.id, link.caregiver_user_id}
    )
    return _to_response(link, users)


async def update_permissions(
    session: AsyncSession,
    patient: User,
    link_id: int,
    permissions: CaregiverPermissions,
) -> CaregiverLinkResponse:
    """El paciente cambia los permisos de un vinculo ACTIVO.

    Cada permiso que cambia queda en auditoria (PERMISSION_GRANTED
    o PERMISSION_REVOKED, con el nombre del permiso y los valores
    anterior y nuevo). La revocacion es inmediata: la siguiente
    operacion del cuidador ya ve el permiso denegado.
    """
    _validate_permissions(permissions)
    result = await session.execute(
        select(CaregiverLink).where(CaregiverLink.id == link_id)
    )
    link = result.scalar_one_or_none()
    if link is None or link.patient_user_id != patient.id:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    if link.status != "ACTIVO":
        raise HTTPException(
            status_code=409,
            detail="Solo se pueden cambiar los permisos de un vínculo activo.",
        )
    values = _permissions_dict(permissions)
    for name, new_value in values.items():
        old_value = getattr(link, name)
        if old_value == new_value:
            continue
        _audit(
            session,
            caregiver_id=link.caregiver_user_id,
            patient_id=patient.id,
            action="PERMISSION_GRANTED" if new_value else "PERMISSION_REVOKED",
            target_type="caregiver_link",
            target_id=link.id,
            details={
                "permission": name,
                "old": old_value,
                "new": new_value,
            },
        )
    await session.execute(
        update(CaregiverLink)
        .where(CaregiverLink.id == link.id)
        .values(**values)
    )
    await session.commit()
    await session.refresh(link)
    users = await _users_by_id(
        session, {patient.id, link.caregiver_user_id}
    )
    return _to_response(link, users)


async def revoke_link(
    session: AsyncSession, user: User, link_id: int
) -> CaregiverLinkResponse:
    """Revoca un vinculo (lo puede hacer el paciente o el cuidador).

    El vinculo pasa a REVOCADO con fecha y autor, y el hash se
    borra en la misma transaccion. No borra el historial ni la
    auditoria, y no hay vuelta de REVOCADO a ACTIVO.
    """
    result = await session.execute(
        select(CaregiverLink).where(CaregiverLink.id == link_id)
    )
    link = result.scalar_one_or_none()
    if link is None or (
        link.patient_user_id != user.id
        and link.caregiver_user_id != user.id
    ):
        raise HTTPException(status_code=404, detail=_NOT_FOUND_ERROR)
    if link.status == "REVOCADO":
        raise HTTPException(
            status_code=409, detail="El vínculo ya está revocado."
        )
    revoked = await session.execute(
        update(CaregiverLink)
        .where(
            CaregiverLink.id == link.id,
            CaregiverLink.status.in_(("INVITADO", "ACTIVO")),
        )
        .values(
            status="REVOCADO",
            revoked_at=_utcnow(),
            revoked_by=user.id,
            invite_code_hash=None,
            invite_expires_at=None,
        )
        .returning(CaregiverLink.id)
    )
    if revoked.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=409, detail="El vínculo ya está revocado."
        )
    _audit(
        session,
        caregiver_id=link.caregiver_user_id,
        patient_id=link.patient_user_id,
        action="REVOKED",
        target_type="caregiver_link",
        target_id=link.id,
    )
    await session.commit()
    await session.refresh(link)
    user_ids = {link.patient_user_id}
    if link.caregiver_user_id is not None:
        user_ids.add(link.caregiver_user_id)
    users = await _users_by_id(session, user_ids)
    return _to_response(link, users)


async def get_audit(
    session: AsyncSession,
    patient: User,
    limit: int = 50,
    offset: int = 0,
) -> CaregiverAuditPageResponse:
    """Auditoria del paciente: quien hizo que sobre sus datos (RF22)."""
    total = await session.execute(
        select(func.count())
        .select_from(CaregiverAuditLog)
        .where(CaregiverAuditLog.patient_user_id == patient.id)
    )
    result = await session.execute(
        select(CaregiverAuditLog)
        .where(CaregiverAuditLog.patient_user_id == patient.id)
        .order_by(CaregiverAuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = result.scalars().all()
    caregiver_ids = {
        row.caregiver_user_id
        for row in rows
        if row.caregiver_user_id is not None
    }
    users = await _users_by_id(session, caregiver_ids)
    return CaregiverAuditPageResponse(
        items=[
            CaregiverAuditResponse(
                id=row.id,
                caregiver_user_id=row.caregiver_user_id,
                caregiver_name=(
                    users[row.caregiver_user_id].name
                    if row.caregiver_user_id is not None
                    and row.caregiver_user_id in users
                    else None
                ),
                patient_user_id=row.patient_user_id,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                details=row.details,
                result=row.result,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total.scalar_one(),
        limit=limit,
        offset=offset,
    )
