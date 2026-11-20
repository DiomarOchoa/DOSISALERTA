"""partial unique index on active reminders (Fase 4, decision B)

Revision ID: bb68e39bf104
Revises: 6ea5249ec805
Create Date: 2026-11-20 16:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = 'bb68e39bf104'
down_revision: str | None = '6ea5249ec805'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # La UNIQUE total (schedule_id, scheduled_at) impedia reanudar
    # sin borrar: un hueco con fila CANCELADA no admitia un
    # PENDIENTE nuevo y el resume tenia que borrar la fila
    # historica. El indice parcial solo cubre los estados activos
    # (PENDIENTE, ENVIANDO, ENVIADA): las CANCELADA quedan como
    # historial y el resume inserta PENDIENTE nuevos en esos
    # huecos. Es menos restrictivo que el anterior, asi que
    # cualquier dato valido antes lo sigue siendo ahora: no hay
    # conflicto de datos al aplicar la migracion.
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


def downgrade() -> None:
    op.drop_index('uq_reminders_schedule_time', table_name='medication_reminders')
    op.create_index(
        'uq_reminders_schedule_time',
        'medication_reminders',
        ['schedule_id', 'scheduled_at'],
        unique=True,
    )
