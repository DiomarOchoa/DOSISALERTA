"""Estado persistente de los flujos guiados del bot.

El flujo guiado de creacion de medicamentos guardaba su estado en
``context.user_data`` (memoria del proceso del bot): al reiniciar el
bot a mitad de la creacion, el medicamento se perdia (incidente
2026-11-23 23:41). Este servicio guarda ese estado en PostgreSQL, en
la misma base que ya usa el bot, para que sobreviva a reinicios y
redespliegues.

El servicio hace commit: los handlers lo llaman con la sesion de
``linked_session`` y no confirman por si mismos.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import bot_flow_state_repository

__all__ = ["load_flow", "save_flow", "clear_flow"]


async def load_flow(
    session: AsyncSession, user_id: int, flow: str
) -> dict[str, Any] | None:
    """El flujo guardado ({"step", "data"}) o None si el usuario no tiene ninguno en curso."""
    state = await bot_flow_state_repository.get_state(session, user_id, flow)
    if state is None:
        return None
    return {"step": state.step, "data": dict(state.data)}


async def save_flow(
    session: AsyncSession,
    user_id: int,
    flow: str,
    step: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Guarda (o actualiza) el paso actual de un flujo. Hace commit."""
    if not step:
        raise ValueError("El paso del flujo no puede estar vacio")
    if not isinstance(data, dict):
        raise ValueError("Los datos del flujo deben ser un diccionario")
    state = await bot_flow_state_repository.upsert_state(
        session, user_id, flow, step, data
    )
    await session.commit()
    return {"step": state.step, "data": dict(state.data)}


async def clear_flow(session: AsyncSession, user_id: int, flow: str) -> bool:
    """Borra el flujo guardado (al confirmar o cancelar). Hace commit.

    Devuelve True si habia algo que borrar.
    """
    deleted = await bot_flow_state_repository.delete_state(session, user_id, flow)
    await session.commit()
    return deleted
