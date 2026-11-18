"""Consultas de usuarios (Fase 3). Solo SQL, sin logica de negocio."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Busca un usuario por email (UNIQUE, `uq_users_email`)."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    """Busca un usuario por id (clave primaria)."""
    return await session.get(User, user_id)


def create(
    session: AsyncSession,
    *,
    name: str,
    email: str,
    password_hash: str,
    timezone: str,
) -> User:
    """Crea el objeto User y lo anade a la sesion (sin commit).

    El commit lo hace el servicio, junto con el refresh token, en
    una sola transaccion (registro atomico, ver `auth_service`).
    """
    user = User(
        name=name,
        email=email,
        password_hash=password_hash,
        timezone=timezone,
        is_active=True,
    )
    session.add(user)
    return user
