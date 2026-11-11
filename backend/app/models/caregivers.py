"""Tablas ``caregiver_links`` y ``caregiver_audit_log``
(`docs/database/RELACIONES_CUIDADORES.md` §4–§5 y
`docs/database/MODELO_DATOS.md` §3.12–§3.13).

- ``caregiver_links``: el vinculo paciente–cuidador. Un paciente
  puede tener varios cuidadores y un cuidador varios pacientes,
  siempre con autorizacion explicita. La fila INVITADO lleva
  ``caregiver_user_id`` NULL: en el momento de invitar, el
  cuidador aun no esta identificado; se vincula su identidad
  cuando presenta el codigo.
- ``caregiver_audit_log``: auditoria de acciones del cuidador.
  Solo INSERT desde la aplicacion: nunca UPDATE ni DELETE.

Reglas criticas (auditoria 2026-11-11, decisiones D22–D27):

- Los permisos se verifican en el backend en cada operacion; la
  interfaz nunca es la unica barrera.
- El cuidador nunca escribe en ``treatment_medications`` (dosis),
  nunca edita ``medications.concentration`` ni ``unit``, nunca
  cambia indicaciones medicas y nunca cambia el estado de un
  tratamiento.
- Gestionar horarios es solo editar las horas (``times``) de
  horarios existentes: no crea horarios ni cambia frecuencia,
  dias o intervalos.
- No existe permiso para confirmar ni posponer tomas.
- Al revocar y volver a invitar se crea una fila nueva; la
  anterior queda REVOCADA con su historia intacta.
- ``details`` JSONB sigue la politica de minimizacion: nunca
  tokens, secretos, codigos de invitacion, dosis, concentraciones,
  nombres de medicamentos ni indicaciones innecesarias.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.users import User

# Estados de un vinculo de cuidador (RELACIONES §4.1).
CAREGIVER_LINK_STATUSES = ("INVITADO", "ACTIVO", "REVOCADO")

# Permisos independientes del cuidador (RF21). Todos empiezan en
# FALSE y se conceden explicitamente por el paciente, por separado.
CAREGIVER_PERMISSIONS = (
    "perm_view_medications",
    "perm_view_treatments",
    "perm_view_schedules",
    "perm_view_upcoming",
    "perm_view_history",
    "perm_receive_notifications",
    "perm_manage_medications",
    "perm_manage_schedules",
)

# Resultados de una accion auditada (RELACIONES §5).
AUDIT_RESULTS = ("OK", "DENEGADO")


class CaregiverLink(Base):
    """Vinculo entre un paciente y un cuidador autorizado."""

    __tablename__ = "caregiver_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INVITADO', 'ACTIVO', 'REVOCADO')",
            name="ck_caregiver_links_status",
        ),
        # Maquina de estados (RELACIONES §4.1).
        CheckConstraint(
            "status <> 'ACTIVO' OR "
            "(caregiver_user_id IS NOT NULL AND accepted_at IS NOT NULL "
            "AND invite_code_hash IS NULL AND invite_expires_at IS NULL)",
            name="ck_caregiver_links_activo",
        ),
        CheckConstraint(
            "status <> 'REVOCADO' OR "
            "(revoked_at IS NOT NULL AND invite_code_hash IS NULL "
            "AND invite_expires_at IS NULL)",
            name="ck_caregiver_links_revocado",
        ),
        CheckConstraint(
            "status <> 'INVITADO' OR "
            "(accepted_at IS NULL AND revoked_at IS NULL)",
            name="ck_caregiver_links_invitado",
        ),
        # Nadie es su propio cuidador (con caregiver NULL el CHECK
        # no se evalua en PostgreSQL: la fila INVITADO anonima no
        # necesita esta comprobacion).
        CheckConstraint(
            "patient_user_id <> caregiver_user_id",
            name="ck_caregiver_links_not_self",
        ),
        # Gestionar exige poder ver (RELACIONES §4.1).
        CheckConstraint(
            "perm_manage_medications = FALSE OR perm_view_medications = TRUE",
            name="ck_caregiver_links_manage_meds_needs_view",
        ),
        CheckConstraint(
            "perm_manage_schedules = FALSE OR perm_view_schedules = TRUE",
            name="ck_caregiver_links_manage_sched_needs_view",
        ),
        # Unicidad: como maximo una fila no revocada por pareja.
        # Al revincular se crea una fila nueva (decision 1).
        Index(
            "uq_caregiver_active_pair",
            "patient_user_id",
            "caregiver_user_id",
            unique=True,
            postgresql_where=text("status <> 'REVOCADO'"),
        ),
        # Como maximo una invitacion pendiente por pareja conocida.
        Index(
            "uq_caregiver_pending_pair",
            "patient_user_id",
            "caregiver_user_id",
            unique=True,
            postgresql_where=text(
                "status = 'INVITADO' AND caregiver_user_id IS NOT NULL"
            ),
        ),
        # Localizar la invitacion cuando el cuidador envia el codigo.
        Index(
            "idx_caregiver_invite_hash",
            "invite_code_hash",
            postgresql_where=text("status = 'INVITADO'"),
        ),
        Index("idx_caregiver_by_caregiver", "caregiver_user_id", "status"),
        Index("idx_caregiver_by_patient", "patient_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    patient_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    caregiver_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="INVITADO"
    )
    invite_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_attempts: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    perm_view_medications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_view_treatments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_view_schedules: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_view_upcoming: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_view_history: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_receive_notifications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_manage_medications: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    perm_manage_schedules: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    invited_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    patient: Mapped["User"] = relationship(
        "User",
        foreign_keys="CaregiverLink.patient_user_id",
        back_populates="caregiver_links_as_patient",
    )
    caregiver: Mapped["User | None"] = relationship(
        "User",
        foreign_keys="CaregiverLink.caregiver_user_id",
        back_populates="caregiver_links_as_caregiver",
    )
    invited_by_user: Mapped["User"] = relationship(
        "User", foreign_keys="CaregiverLink.invited_by"
    )
    revoked_by_user: Mapped["User | None"] = relationship(
        "User", foreign_keys="CaregiverLink.revoked_by"
    )


class CaregiverAuditLog(Base):
    """Auditoria de acciones de un cuidador sobre un paciente.

    Sin FK a ``caregiver_links``: si el vinculo se revoca, la
    auditoria debe conservarse. La pareja (cuidador, paciente)
    identifica el vinculo sin depender de su fila.
    """

    __tablename__ = "caregiver_audit_log"
    __table_args__ = (
        CheckConstraint(
            "result IN ('OK', 'DENEGADO')",
            name="ck_caregiver_audit_result",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    caregiver_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=True
    )
    patient_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    caregiver: Mapped["User | None"] = relationship(
        "User", foreign_keys="CaregiverAuditLog.caregiver_user_id"
    )
    patient: Mapped["User"] = relationship(
        "User", foreign_keys="CaregiverAuditLog.patient_user_id"
    )


# Indices (patient, created_at DESC) y (caregiver, created_at DESC)
# para la auditoria: se definen aqui porque __table_args__ no admite
# el orden DESC con nombres de columna en texto.
Index(
    "idx_caregiver_audit_patient",
    CaregiverAuditLog.__table__.c.patient_user_id,
    CaregiverAuditLog.__table__.c.created_at.desc(),
)
Index(
    "idx_caregiver_audit_caregiver",
    CaregiverAuditLog.__table__.c.caregiver_user_id,
    CaregiverAuditLog.__table__.c.created_at.desc(),
)
