"""Tablas ``medications``, ``treatments`` y ``treatment_medications``
(`docs/database/MODELO_DATOS.md` §3.2–§3.4).

- ``medications`` es el catalogo propio del usuario: existe aunque
  no este en ningun tratamiento activo.
- ``treatments`` es el plan (inicio, fin, estado).
- ``treatment_medications`` es el vinculo tratamiento x medicamento
  y es donde vive la dosis (``dose_amount`` / ``dose_unit``): la
  misma amoxicilina puede tomarse 1 capsula cada 8 horas en un
  tratamiento y 1 cada 12 horas en otro.

Las claves foraneas compuestas ``(padre_id, user_id)`` y los
UNIQUE ``(id, user_id)`` de los padres son la segunda capa de
defensa contra cruces entre cuentas (MODELO_DATOS §7): un error
del servicio que intentara mezclar el tratamiento de A con el
medicamento de B fallaria en la transaccion con error de FK.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.reminders import MedicationReminder
    from app.models.schedules import MedicationSchedule
    from app.models.users import User

# Estados de un tratamiento (MODELO_DATOS §3.3).
TREATMENT_STATUSES = ("ACTIVO", "PAUSADO", "COMPLETADO", "CANCELADO")


class Medication(Base):
    """Medicamento del catalogo propio del usuario."""

    __tablename__ = "medications"
    __table_args__ = (
        # UNIQUE (id, user_id): permite las FK compuestas de
        # treatment_medications hacia (medication_id, user_id).
        UniqueConstraint("id", "user_id", name="uq_medications_id_user"),
        Index("ix_medications_user", "user_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    presentation: Mapped[str | None] = mapped_column(String(100), nullable=True)
    concentration: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    user: Mapped["User"] = relationship(back_populates="medications")
    treatment_medications: Mapped[list["TreatmentMedication"]] = relationship(
        back_populates="medication"
    )


class Treatment(Base):
    """Plan de tratamiento de un usuario."""

    __tablename__ = "treatments"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_treatments_id_user"),
        CheckConstraint(
            "status IN ('ACTIVO', 'PAUSADO', 'COMPLETADO', 'CANCELADO')",
            name="ck_treatments_status",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_treatments_end_date",
        ),
        Index("ix_treatments_user", "user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVO")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="treatments")
    treatment_medications: Mapped[list["TreatmentMedication"]] = relationship(
        back_populates="treatment", overlaps="treatment_medications"
    )


class TreatmentMedication(Base):
    """Medicamento dentro de un tratamiento, con su dosis prescrita.

    La dosis pertenece al vinculo, no al catalogo ni al plan: aqui
    viven ``dose_amount``, ``dose_unit`` e ``instructions``.
    """

    __tablename__ = "treatment_medications"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_treatment_meds_id_user"),
        ForeignKeyConstraint(
            ["treatment_id", "user_id"],
            ["treatments.id", "treatments.user_id"],
            name="fk_treatment_meds_treatment",
        ),
        ForeignKeyConstraint(
            ["medication_id", "user_id"],
            ["medications.id", "medications.user_id"],
            name="fk_treatment_meds_medication",
        ),
        CheckConstraint("dose_amount > 0", name="ck_treatment_meds_dose_amount"),
        # Un mismo medicamento activo, una sola vez por tratamiento.
        # Si se necesitan dos dosis distintas, se usan dos horarios,
        # no dos vinculos (MODELO_DATOS §3.4).
        Index(
            "uq_treatment_meds_active",
            "treatment_id",
            "medication_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index("ix_treatment_meds_treatment", "treatment_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    treatment_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    medication_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    dose_amount: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    dose_unit: Mapped[str] = mapped_column(String(30), nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
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

    user: Mapped["User"] = relationship(
        overlaps="treatment_medications,treatment_medications"
    )
    treatment: Mapped["Treatment"] = relationship(
        back_populates="treatment_medications",
        overlaps="treatment_medications,user",
    )
    medication: Mapped["Medication"] = relationship(
        back_populates="treatment_medications",
        overlaps="treatment,treatment_medications,user",
    )
    schedules: Mapped[list["MedicationSchedule"]] = relationship(
        back_populates="treatment_medication"
    )
    reminders: Mapped[list["MedicationReminder"]] = relationship(
        back_populates="treatment_medication"
    )
