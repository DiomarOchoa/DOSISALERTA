"""add caregiver_link_attempts table (Fase 6, tabla 14)

Revision ID: 8033addb5499
Revises: 6686a70821b5
Create Date: 2026-11-22

Tabla antifraude de las invitaciones de cuidador
(`docs/database/RELACIONES_CUIDADORES.md` §13, aprobada
2026-11-11). Espejo de `telegram_link_attempts`: cada intento de
codigo se registra por `chat_id` antes de validar, incluso
cuando el codigo no corresponde a ninguna invitacion. Sin esta
tabla, el limite de intentos por `chat_id` dependeria de memoria
que se pierde al reiniciar el bot.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '8033addb5499'
down_revision: str | None = '6686a70821b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "caregiver_link_attempts",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("attempted_code_hash", sa.String(length=64), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_caregiver_link_attempts_chat",
        "caregiver_link_attempts",
        ["chat_id", sa.text("attempted_at DESC")],
    )
    op.create_index(
        "idx_caregiver_link_attempts_hash",
        "caregiver_link_attempts",
        ["attempted_code_hash", sa.text("attempted_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_caregiver_link_attempts_hash", table_name="caregiver_link_attempts"
    )
    op.drop_index(
        "idx_caregiver_link_attempts_chat", table_name="caregiver_link_attempts"
    )
    op.drop_table("caregiver_link_attempts")
