"""add TOMADA to partial unique index on reminders (Fase A, I-10)

Revision ID: fc387ec4f3db
Revises: bb68e39bf104
Create Date: 2026-11-21 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = 'fc387ec4f3db'
down_revision: str | None = 'bb68e39bf104'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # I-10: una franja TOMADA no debe admitir un segundo PENDIENTE.
    # Se anade TOMADA al predicado del indice parcial: las CANCELADA
    # siguen pudiendo rellenarse (decision B), las tomadas no.
    # Es mas restrictivo que el anterior: antes de aplicar, hay que
    # comprobar que no existan duplicados (TOMADA + activo) en el
    # mismo (schedule_id, scheduled_at).
    op.drop_index('uq_reminders_schedule_time', table_name='medication_reminders')
    op.create_index(
        'uq_reminders_schedule_time',
        'medication_reminders',
        ['schedule_id', 'scheduled_at'],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('PENDIENTE', 'ENVIANDO', 'ENVIADA', 'TOMADA')"
        ),
    )


def downgrade() -> None:
    op.drop_index('uq_reminders_schedule_time', table_name='medication_reminders')
    op.create_index(
        'uq_reminders_schedule_time',
        'medication_reminders',
        ['schedule_id', 'scheduled_at'],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('PENDIENTE', 'ENVIANDO', 'ENVIADA')"
        ),
    )
