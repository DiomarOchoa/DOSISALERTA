"""Consultas de refresh tokens (Fase 3). Solo SQL, sin logica de negocio."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tokens import RefreshToken


def create(
    session: AsyncSession,
    *,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
) -> RefreshToken:
    """Crea el objeto RefreshToken y lo anade a la sesion (sin commit)."""
    refresh = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        revoked_at=None,
    )
    session.add(refresh)
    return refresh


async def get_by_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    """Busca un refresh token por su hash SHA-256."""
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def claim_for_refresh(
    session: AsyncSession, token_hash: str, now: datetime
) -> RefreshToken | None:
    """Reclama un refresh token para renovar, de forma atomica.

    Un solo UPDATE con WHERE de validez y RETURNING: PostgreSQL lo
    ejecuta como una operacion atomica, asi que de varias solicitudes
    concurrentes con el mismo token solo una puede reclamarlo (las
    demas encuentran `revoked_at` ya fijado y obtienen 0 filas).
    Gracias a la restriccion UNIQUE de `token_hash`, el UPDATE afecta
    como maximo a una fila. Devuelve la fila reclamada o None.
    """
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshToken)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_all_for_user(
    session: AsyncSession, user_id: int, now: datetime
) -> None:
    """Revoca todos los refresh tokens activos de un usuario.

    No se expone endpoint en la Fase 3; queda disponible para la
    Fase 4+ (por ejemplo, "cerrar sesion en todos los dispositivos").
    """
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.execute(stmt)
