"""Logica de negocio de autenticacion (Fase 3).

Registro, login, renovacion con rotacion atomica, cierre de sesion
y resolucion de `current_user`. Llama a los repositorios y a
`core/security.py`. No hay manejador generico de excepciones:
los errores controlados son `HTTPException` (401/409) y la
validacion de Pydantic (422) la hace FastAPI.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.models.users import User
from app.repositories import refresh_token_repository, user_repository
from app.schemas.auth import (
    TokenRefresh,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserRegisterResponse,
    UserResponse,
)

_GENERIC_LOGIN_ERROR = "Correo o contraseña incorrectos"
_GENERIC_TOKEN_ERROR = "No se pudo validar la sesión"
_REFRESH_ERROR = "Sesión no válida o expirada"
_EMAIL_TAKEN_ERROR = "El correo ya está registrado"


def _new_refresh_token_row(session: AsyncSession, user_id: int) -> str:
    """Genera un refresh token y lo anade a la sesion (sin commit).

    Devuelve el token en claro (solo se entrega una vez al cliente);
    en la base de datos solo queda su hash SHA-256.
    """
    settings = get_settings()
    raw = security.generate_refresh_token()
    refresh_token_repository.create(
        session,
        user_id=user_id,
        token_hash=security.hash_refresh_token(raw),
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.jwt_refresh_expiration_days),
    )
    return raw


def _token_response(user: User, refresh_raw: str) -> TokenResponse:
    """Construye la respuesta con tokens para un usuario."""
    return TokenResponse(
        access_token=security.create_access_token(user),
        refresh_token=refresh_raw,
        token_type="bearer",
    )


async def register(session: AsyncSession, data: UserRegister) -> UserRegisterResponse:
    """Registra un usuario y su primera sesion, en una sola transaccion.

    Usuario y refresh token se crean con un unico `commit` al final
    (con `flush` intermedio para obtener el id). Ante cualquier
    error, `rollback`: no queda ningun estado parcial.
    """
    try:
        existing = await user_repository.get_by_email(session, data.email)
        if existing is not None:
            raise HTTPException(status_code=409, detail=_EMAIL_TAKEN_ERROR)
        password_hash = security.hash_password(data.password)
        user = user_repository.create(
            session,
            name=data.name,
            email=data.email,
            password_hash=password_hash,
            timezone=data.timezone,
        )
        await session.flush()
        refresh_raw = _new_refresh_token_row(session, user.id)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except IntegrityError as exc:
        await session.rollback()
        # Solo la violacion exacta de la UNIQUE de users.email se
        # convierte en 409 (SQLSTATE 23505 + restriccion
        # uq_users_email, verificada en vivo). Cualquier otro
        # IntegrityError se propaga como 500 generico.
        orig = exc.orig
        sqlstate = getattr(orig, "sqlstate", None)
        constraint = getattr(orig, "constraint_name", None)
        if sqlstate == "23505" and constraint == "uq_users_email":
            raise HTTPException(
                status_code=409, detail=_EMAIL_TAKEN_ERROR
            ) from exc
        raise
    except Exception:
        await session.rollback()
        raise
    return UserRegisterResponse(
        user=UserResponse.model_validate(user),
        access_token=security.create_access_token(user),
        refresh_token=refresh_raw,
        token_type="bearer",
    )


async def login(session: AsyncSession, data: UserLogin) -> TokenResponse:
    """Autentica por email y contrasena (JSON).

    401 con el mismo mensaje generico si el email no existe, la
    contrasena es incorrecta o el usuario esta inactivo (sin
    enumeracion de usuarios).
    """
    user = await user_repository.get_by_email(session, data.email)
    if user is None or not security.verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)
    if not user.is_active:
        raise HTTPException(status_code=401, detail=_GENERIC_LOGIN_ERROR)
    try:
        refresh_raw = _new_refresh_token_row(session, user.id)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return _token_response(user, refresh_raw)


async def refresh(session: AsyncSession, data: TokenRefresh) -> TokenResponse:
    """Renueva la sesion con rotacion atomica del refresh token.

    Reclama el token con un UPDATE atomico (una sola solicitud gana
    la carrera). Si no se reclama, si el usuario no existe o esta
    inactivo -> 401 (y se revierte la reclamacion con rollback).
    """
    now = datetime.now(timezone.utc)
    token_hash = security.hash_refresh_token(data.refresh_token)
    try:
        claimed = await refresh_token_repository.claim_for_refresh(
            session, token_hash, now
        )
        if claimed is None:
            raise HTTPException(status_code=401, detail=_REFRESH_ERROR)
        user = await user_repository.get_by_id(session, claimed.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail=_REFRESH_ERROR)
        refresh_raw = _new_refresh_token_row(session, user.id)
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    return _token_response(user, refresh_raw)


async def logout(session: AsyncSession, data: TokenRefresh) -> None:
    """Revoca el refresh token.

    Si existe y no esta revocado, fija `revoked_at` y hace commit.
    Si no existe o ya esta revocado, no se revela: se devuelve 200
    igualmente (el router no distingue). El access token emitido
    antes sigue valido hasta su expiracion (limitacion de §7.5).
    """
    now = datetime.now(timezone.utc)
    token_hash = security.hash_refresh_token(data.refresh_token)
    try:
        token = await refresh_token_repository.get_by_hash(session, token_hash)
        if token is not None and token.revoked_at is None:
            token.revoked_at = now
            await session.commit()
    except Exception:
        await session.rollback()
        raise


async def resolve_current_user(session: AsyncSession, payload: dict) -> User:
    """Resuelve el usuario autenticado desde el payload del JWT.

    Extrae `sub`, lo convierte a entero, carga el usuario y comprueba
    que exista y este activo. Cualquier fallo -> 401 generico.
    """
    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401, detail=_GENERIC_TOKEN_ERROR
        ) from None
    user = await user_repository.get_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail=_GENERIC_TOKEN_ERROR)
    return user
