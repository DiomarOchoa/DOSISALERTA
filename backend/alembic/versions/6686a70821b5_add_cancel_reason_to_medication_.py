"""add cancel_reason to medication_reminders

Revision ID: 6686a70821b5
Revises: fc387ec4f3db
Create Date: 2026-11-21 19:35:37.710550
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '6686a70821b5'
down_revision: str | None = 'fc387ec4f3db'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "medication_reminders",
        sa.Column("cancel_reason", sa.String(length=30), nullable=True),
    )
    # CHECK de dominio: garantiza que el desglose por motivo sea exhaustivo.
    # cancel_reason solo puede ser NULL o uno de los cinco motivos.
    # Sin el, un valor ajeno se contaria en `cancelled` pero en ninguna
    # categoria del desglose, y la identidad sum(desglose) = cancelled
    # se romperia (ver PLAN_TECNICO_FASE_7.md §6.2).
    op.create_check_constraint(
        "ck_reminders_cancel_reason",
        "medication_reminders",
        sa.text(
            "cancel_reason IS NULL OR cancel_reason IN "
            "('TREATMENT_CANCELLED', 'TREATMENT_PAUSED', "
            "'TREATMENT_COMPLETED', 'MEDICATION_DEACTIVATED', "
            "'LINK_REMOVED')"
        ),
    )
    # CHECK de coherencia estado-motivo (D-11, aprobada):
    # una fila solo puede tener un motivo si esta en CANCELADA.
    # No exige que toda CANCELADA tenga motivo (las historicas son NULL).
    op.create_check_constraint(
        "ck_reminders_cancel_reason_status",
        "medication_reminders",
        sa.text("cancel_reason IS NULL OR status = 'CANCELADA'"),
    )
    # Trigger de integridad (D-11, aclaracion aprobada 2026-11-21, ver
    # PLAN_TECNICO_FASE_7.md §12.11 punto 2): el parametro obligatorio
    # protege los llamadores actualizados, pero no impide que una
    # escritura SQL manual u otro codigo inserte una cancelacion con
    # NULL. El trigger rechaza toda transicion nueva hacia CANCELADA
    # sin motivo y todo borrado del motivo de una fila que ya lo tenia,
    # sin tocar las filas historicas (que ya son CANCELADA con NULL).
    # No hay precedente de triggers en el codigo revisado; se crea
    # con op.execute (SQL estandar Alembic).
    op.execute(
        sa.text(
            "CREATE OR REPLACE FUNCTION fn_reminders_require_cancel_reason() "
            "RETURNS trigger AS $$ "
            "BEGIN "
            "IF NEW.status = 'CANCELADA' "
            "AND NEW.cancel_reason IS NULL "
            "AND (TG_OP = 'INSERT' OR OLD.status <> 'CANCELADA') THEN "
            "RAISE EXCEPTION 'CANCELADA sin cancel_reason: toda cancelación "
            "nueva debe registrar su motivo'; "
            "END IF; "
            "IF OLD.status = 'CANCELADA' "
            "AND OLD.cancel_reason IS NOT NULL "
            "AND NEW.cancel_reason IS NULL THEN "
            "RAISE EXCEPTION 'cancel_reason registrado no puede borrarse'; "
            "END IF; "
            "RETURN NEW; "
            "END; "
            "$$ LANGUAGE plpgsql"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_reminders_cancel_reason "
            "BEFORE INSERT OR UPDATE ON medication_reminders "
            "FOR EACH ROW EXECUTE FUNCTION fn_reminders_require_cancel_reason()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_reminders_cancel_reason ON medication_reminders"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_reminders_require_cancel_reason()"))
    op.drop_constraint(
        "ck_reminders_cancel_reason_status",
        "medication_reminders",
        type_="check",
    )
    op.drop_constraint(
        "ck_reminders_cancel_reason",
        "medication_reminders",
        type_="check",
    )
    op.drop_column("medication_reminders", "cancel_reason")
