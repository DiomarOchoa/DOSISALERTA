"""Tabla ``notification_logs`` (`docs/database/MODELO_DATOS.md` §3.10).

Una fila por intento de envio, antes o inmediatamente despues de
llamar a Telegram, nunca solo si el envio salio bien. Es la prueba
de que un aviso se envio (o fallo, o quedo ambiguo) y el freno
contra reenvios: si ya hay ``telegram_message_id``, no se vuelve
a enviar ese recordatorio.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reminders import MedicationReminder
    from app.models.users import User

# Estados de un intento de envio (MODELO_DATOS §3.10).
NOTIFICATION_LOG_STATUSES = ("ENVIADA", "FALLIDA", "AMBIGUA")


class NotificationLog(Base):
    """Intento de envio de un aviso a Telegram."""

    __tablename__ = "notification_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["reminder_id", "user_id"],
            ["medication_reminders.id", "medication_reminders.user_id"],
            name="fk_logs_reminder",
        ),
        CheckConstraint(
            "status IN ('ENVIADA', 'FALLIDA', 'AMBIGUA')",
            name="ck_logs_status",
        ),
        # ENVIADA exige confirmacion de Telegram; FALLIDA y AMBIGUA
        # exigen NO tenerla (MODELO_DATOS §3.10).
        CheckConstraint(
            "status <> 'ENVIADA' OR "
            "(sent_at IS NOT NULL AND telegram_message_id IS NOT NULL)",
            name="ck_logs_enviada_confirmed",
        ),
        CheckConstraint(
            "status NOT IN ('FALLIDA', 'AMBIGUA') OR sent_at IS NULL",
            name="ck_logs_fallida_ambigua_no_sent",
        ),
        CheckConstraint(
            "status <> 'AMBIGUA' OR telegram_message_id IS NULL",
            name="ck_logs_ambigua_no_message",
        ),
        Index(
            "idx_logs_reconciliation",
            "status",
            "attempted_at",
            postgresql_where=text("status = 'AMBIGUA'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reminder_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="TELEGRAM")
    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship()
    reminder: Mapped["MedicationReminder"] = relationship(
        back_populates="notification_logs", overlaps="user"
    )


# Indice (reminder_id, attempted_at DESC) para la reconciliacion:
# se define aqui porque __table_args__ no admite el orden DESC
# con nombres de columna en texto.
Index(
    "idx_logs_reminder",
    NotificationLog.__table__.c.reminder_id,
    NotificationLog.__table__.c.attempted_at.desc(),
)
