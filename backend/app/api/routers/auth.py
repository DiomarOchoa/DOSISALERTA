"""Endpoints de autenticacion (Fase 3).

``POST /api/v1/auth/register``, ``/login``, ``/refresh``,
``/logout`` y ``GET /api/v1/auth/me``. Las rutas solo validan la
entrada, llaman al servicio y devuelven la respuesta; no contienen
logica de negocio ni SQL.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.auth import (
    TokenRefresh,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserRegisterResponse,
    UserResponse,
    UserUpdate,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    data: UserRegister,
    session: AsyncSession = Depends(get_session),
) -> UserRegisterResponse:
    """Registra un usuario y devuelve su perfil con sus tokens (201)."""
    return await auth_service.register(session, data)


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Inicia sesion con JSON (email + contrasena) y devuelve tokens (200)."""
    return await auth_service.login(session, data)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    data: TokenRefresh,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Renueva la sesion con rotacion atomica del refresh token (200)."""
    return await auth_service.refresh(session, data)


@router.post("/logout")
async def logout(
    data: TokenRefresh,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Cierra la sesion revocando el refresh token (200 siempre)."""
    await auth_service.logout(session, data)
    return {"detail": "Sesión cerrada"}


@router.get("/me", response_model=UserResponse)
async def me(
    current_user: User = Depends(deps.get_current_user),
) -> UserResponse:
    """Devuelve el perfil del usuario autenticado (200)."""
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    data: UserUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> UserResponse:
    """Actualiza el perfil del usuario autenticado (200).

    RF03: cambia la zona horaria. Un cambio de zona regenera
    unicamente los recordatorios PENDIENTE futuros (RNF04).
    """
    return await auth_service.update_profile(session, current_user, data)
