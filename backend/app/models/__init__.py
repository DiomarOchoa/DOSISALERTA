"""Tablas SQLAlchemy de DosisAlerta (Fase 2).

Una clase = una tabla, segun `docs/database/MODELO_DATOS.md` (11
tablas originales) y `docs/database/RELACIONES_CUIDADORES.md`
(2 tablas de cuidadores). La tabla 14, `caregiver_link_attempts`,
NO se implementa en esta fase: su migracion corresponde a la
Fase 6.

Importar este paquete registra todos los modelos en
``Base.metadata``, que es lo que usa Alembic para generar la
migracion inicial.
"""

from __future__ import annotations

from app.models.base import Base
from app.models.caregivers import (
    AUDIT_RESULTS,
    CAREGIVER_LINK_STATUSES,
    CAREGIVER_PERMISSIONS,
    CaregiverAuditLog,
    CaregiverLink,
)
from app.models.logs import NOTIFICATION_LOG_STATUSES, NotificationLog
from app.models.medications import (
    TREATMENT_STATUSES,
    Medication,
    Treatment,
    TreatmentMedication,
)
from app.models.reminders import (
    INTAKE_SOURCES,
    REMINDER_STATUSES,
    MedicationIntake,
    MedicationReminder,
)
from app.models.schedules import SCHEDULE_FREQUENCIES, MedicationSchedule
from app.models.telegram import (
    TELEGRAM_ACCOUNT_STATUSES,
    TelegramAccount,
    TelegramLinkAttempt,
)
from app.models.tokens import RefreshToken
from app.models.users import User

__all__ = [
    "AUDIT_RESULTS",
    "CAREGIVER_LINK_STATUSES",
    "CAREGIVER_PERMISSIONS",
    "INTAKE_SOURCES",
    "NOTIFICATION_LOG_STATUSES",
    "REMINDER_STATUSES",
    "SCHEDULE_FREQUENCIES",
    "TELEGRAM_ACCOUNT_STATUSES",
    "TREATMENT_STATUSES",
    "Base",
    "CaregiverAuditLog",
    "CaregiverLink",
    "Medication",
    "MedicationIntake",
    "MedicationReminder",
    "MedicationSchedule",
    "NotificationLog",
    "RefreshToken",
    "TelegramAccount",
    "TelegramLinkAttempt",
    "Treatment",
    "TreatmentMedication",
    "User",
]
