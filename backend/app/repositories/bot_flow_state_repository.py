"""Consultas del estado persistente de los flujos del bot. Solo SQL, sin logica de negocio."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bot_flow_states import BotFlowState

__all__ = ["get_state", "upsert_state", "delete_state"]


async def get_state(
    session: AsyncSession, user_id: int, flow: str
) -> BotFlowState | None:
    """El estado guardado de un flujo de un usuario, o None si no hay ninguno."""
    stmt = select(BotFlowState).where(
        BotFlowState.user_id == user_id,
        BotFlowState.flow == flow,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_state(
    session: AsyncSession,
    user_id: int,
    flow: str,
    step: str,
    data: dict[str, Any],
) -> BotFlowState:
    """Crea el estado del flujo o actualiza el existente (un flujo por usuario).

    Un solo UPSERT atomico: dos pasos del mismo usuario no pueden
    dejar dos filas del mismo flujo.
    """
    stmt = pg_insert(BotFlowState).values(
        user_id=user_id, flow=flow, step=step, data=data
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "flow"],
        set_={
            "step": stmt.excluded.step,
            "data": stmt.excluded.data,
            "updated_at": func.now(),
        },
    ).returning(BotFlowState)
    result = await session.execute(stmt)
    return result.scalar_one()


async def delete_state(session: AsyncSession, user_id: int, flow: str) -> bool:
    """Borra el estado de un flujo. Devuelve True si habia algo que borrar."""
    stmt = delete(BotFlowState).where(
        BotFlowState.user_id == user_id,
        BotFlowState.flow == flow,
    )
    result = await session.execute(stmt)
    return result.rowcount > 0
