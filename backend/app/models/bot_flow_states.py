"""Estado persistente de los flujos guiados del bot.

El flujo guiado de creacion de medicamentos (``handlers/medications.py``)
guardaba su estado en ``context.user_data``: memoria del proceso que se
pierde al reiniciar el bot (incidente 2026-11-23 23:41, el medicamento
que se estaba creando no se guardo). Esta tabla lo guarda en
PostgreSQL para que sobreviva a reinicios y redespliegues.

Un flujo por usuario (UNIQUE user_id, flow). Hoy solo existe el flujo
``med_create``; la columna ``flow`` deja la puerta abierta a otros
flujos guiados sin crear otra tabla.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BotFlowState(Base):
    """Un flujo guiado del bot en curso, de un usuario."""

    __tablename__ = "bot_flow_states"
    __table_args__ = (
        UniqueConstraint("user_id", "flow", name="uq_bot_flow_states_user_id_flow"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    flow: Mapped[str] = mapped_column(String(30), nullable=False)
    step: Mapped[str] = mapped_column(String(30), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
