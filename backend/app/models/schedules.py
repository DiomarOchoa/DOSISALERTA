"""Tabla ``medication_schedules`` (`docs/database/MODELO_DATOS.md` §3.5).

Un horario es la recurrencia de un medicamento dentro de un
tratamiento: frecuencia, dias o intervalo y horas de pared
(``TIME`` local del usuario; el instante UTC concreto se calcula
al generar cada recordatorio, MODELO_DATOS §8).
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.medications import TreatmentMedication
    from app.models.reminders import MedicationReminder
    from app.models.users import User

# Frecuencias de un horario (MODELO_DATOS §3.5).
SCHEDULE_FREQUENCIES = ("DIARIO", "DIAS_SEMANA", "INTERVALO_DIAS")


class MedicationSchedule(Base):
    """Recurrencia de un medicamento en un tratamiento."""

    __tablename__ = "medication_schedules"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_schedules_id_user"),
        ForeignKeyConstraint(
            ["treatment_medication_id", "user_id"],
            ["treatment_medications.id", "treatment_medications.user_id"],
            name="fk_schedules_treatment_medication",
        ),
        CheckConstraint(
            "frequency IN ('DIARIO', 'DIAS_SEMANA', 'INTERVALO_DIAS')",
            name="ck_schedules_frequency",
        ),
        CheckConstraint(
            "interval_days IS NULL OR interval_days >= 1",
            name="ck_schedules_interval_days",
        ),
        CheckConstraint(
            "frequency <> 'DIAS_SEMANA' OR days_of_week IS NOT NULL",
            name="ck_schedules_days_of_week",
        ),
        CheckConstraint(
            "frequency <> 'INTERVALO_DIAS' OR interval_days IS NOT NULL",
            name="ck_schedules_interval_required",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_schedules_end_date",
        ),
        CheckConstraint(
            "array_length(times, 1) >= 1",
            name="ck_schedules_times_not_empty",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    treatment_medication_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False)
    days_of_week: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer), nullable=True
    )
    interval_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    times: Mapped[list[time]] = mapped_column(ARRAY(Time), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(overlaps="schedules")
    treatment_medication: Mapped["TreatmentMedication"] = relationship(
        back_populates="schedules", overlaps="user"
    )
    reminders: Mapped[list["MedicationReminder"]] = relationship(
        back_populates="schedule",
        overlaps="reminders,treatment_medication,user",
    )
