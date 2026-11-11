"""Tablas ``medication_reminders`` y ``medication_intakes``
(`docs/database/MODELO_DATOS.md` §3.6–§3.7).

- ``medication_reminders`` es la tabla del motor: cada fila es una
  toma concreta programada, no un horario generico. El hijo de una
  posposicion apunta al original con ``parent_reminder_id``.
- ``medication_intakes`` es la toma confirmada: el historial de lo
  que paso realmente (cuando y desde donde). Una toma por
  recordatorio, como maximo (``reminder_id`` UNIQUE).

Las transiciones de estado las impone el servicio (Fase 5), no
solo la BD; el CHECK solo fija los valores validos.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.logs import NotificationLog
    from app.models.medications import TreatmentMedication
    from app.models.schedules import MedicationSchedule
    from app.models.users import User

# Estados de un recordatorio (MODELO_DATOS §3.6).
REMINDER_STATUSES = (
    "PENDIENTE",
    "ENVIANDO",
    "ENVIADA",
    "TOMADA",
    "POSPUESTA",
    "PERDIDA",
    "CANCELADA",
    "FALLIDA",
)

# Origenes de una toma confirmada (MODELO_DATOS §3.7).
INTAKE_SOURCES = ("WEB", "TELEGRAM")


class MedicationReminder(Base):
    """Una toma concreta programada."""

    __tablename__ = "medication_reminders"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_reminders_id_user"),
        ForeignKeyConstraint(
            ["schedule_id", "user_id"],
            ["medication_schedules.id", "medication_schedules.user_id"],
            name="fk_reminders_schedule",
        ),
        ForeignKeyConstraint(
            ["treatment_medication_id", "user_id"],
            ["treatment_medications.id", "treatment_medications.user_id"],
            name="fk_reminders_treatment_medication",
        ),
        CheckConstraint(
            "status IN ('PENDIENTE', 'ENVIANDO', 'ENVIADA', 'TOMADA',"
            " 'POSPUESTA', 'PERDIDA', 'CANCELADA', 'FALLIDA')",
            name="ck_reminders_status",
        ),
        Index("ix_reminders_user_scheduled", "user_id", "scheduled_at"),
        Index(
            "ix_reminders_status_scheduled",
            "status",
            "scheduled_at",
            postgresql_where=text("status IN ('PENDIENTE', 'ENVIANDO')"),
        ),
        Index(
            "uq_reminders_schedule_time",
            "schedule_id",
            "scheduled_at",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    treatment_medication_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDIENTE"
    )
    parent_reminder_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("medication_reminders.id"),
        nullable=True,
    )
    postponed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(overlaps="reminders")
    schedule: Mapped["MedicationSchedule"] = relationship(
        back_populates="reminders", overlaps="reminders,user"
    )
    treatment_medication: Mapped["TreatmentMedication"] = relationship(
        back_populates="reminders", overlaps="schedule,user"
    )
    parent: Mapped["MedicationReminder | None"] = relationship(
        "MedicationReminder",
        remote_side="MedicationReminder.id",
        back_populates="children",
    )
    children: Mapped[list["MedicationReminder"]] = relationship(
        "MedicationReminder", back_populates="parent"
    )
    intake: Mapped["MedicationIntake | None"] = relationship(
        back_populates="reminder", uselist=False
    )
    notification_logs: Mapped[list["NotificationLog"]] = relationship(
        back_populates="reminder", overlaps="user"
    )


class MedicationIntake(Base):
    """Una toma confirmada por el usuario."""

    __tablename__ = "medication_intakes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["reminder_id", "user_id"],
            ["medication_reminders.id", "medication_reminders.user_id"],
            name="fk_intakes_reminder",
        ),
        CheckConstraint(
            "source IN ('WEB', 'TELEGRAM')",
            name="ck_intakes_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    reminder_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship(overlaps="intake")
    reminder: Mapped["MedicationReminder"] = relationship(
        back_populates="intake", overlaps="user"
    )


# Indice (user_id, taken_at DESC) para el historial y las
# estadisticas: se define aqui porque __table_args__ no admite
# el orden DESC con nombres de columna en texto.
Index(
    "ix_intakes_user_taken",
    MedicationIntake.__table__.c.user_id,
    MedicationIntake.__table__.c.taken_at.desc(),
)
