"""Migracion: tabla bot_flow_states (estado persistente de los flujos del bot).

El flujo guiado de creacion de medicamentos del bot guardaba su
estado en ``context.user_data`` (memoria del proceso): al reiniciar
el bot a mitad de la creacion, el medicamento se perdia (incidente
2026-11-23 23:41). Esta tabla guarda ese estado en PostgreSQL, en
la misma base que ya usa el bot, para que sobreviva a reinicios y
redespliegues. Un flujo por usuario (UNIQUE user_id, flow).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '6f2f8d6b22d1'
down_revision: str | None = '8033addb5499'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_flow_states",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("flow", sa.String(length=30), nullable=False),
        sa.Column("step", sa.String(length=30), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_bot_flow_states_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "flow", name=op.f("uq_bot_flow_states_user_id_flow")
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_flow_states")
