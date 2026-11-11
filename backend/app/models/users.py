"""Tabla ``users`` (`docs/database/MODELO_DATOS.md` §3.1).

Un usuario es la persona que gestiona sus propios tratamientos.
Cada tabla de negocio lleva su ``user_id`` y filtra por el en
todas las consultas (aislamiento por usuario, MODELO_DATOS §7).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.caregivers import CaregiverLink
    from app.models.medications import Medication, Treatment
    from app.models.telegram import TelegramAccount
    from app.models.tokens import RefreshToken


class User(Base):
    """Usuario registrado de DosisAlerta."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, default="America/Bogota"
    )
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

    # Relaciones con sus propias tablas (1—* salvo Telegram, 1—1).
    medications: Mapped[list["Medication"]] = relationship(back_populates="user")
    treatments: Mapped[list["Treatment"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")
    telegram_account: Mapped["TelegramAccount | None"] = relationship(
        back_populates="user", uselist=False
    )

    # Vínculos de cuidador: como paciente y como cuidador.
    caregiver_links_as_patient: Mapped[list["CaregiverLink"]] = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.patient_user_id",
        back_populates="patient",
    )
    caregiver_links_as_caregiver: Mapped[list["CaregiverLink"]] = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.caregiver_user_id",
        back_populates="caregiver",
    )
