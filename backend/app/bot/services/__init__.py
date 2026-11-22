"""Servicios del bot en modo demostracion.

En este esqueleto solo vive ``mock_data`` (datos ficticios). En
la Fase 6, los handlers llamaran a los servicios centrales del
backend (``app.services``), nunca a PostgreSQL directamente.
"""

from app.bot.services.mock_data import (
    CAREGIVER_DEMO,
    DEMO_NOTICE,
    DEMO_PATIENT_NAME,
    HISTORY,
    MEDICATIONS,
    TREATMENTS,
    UPCOMING_INTAKES,
    get_caregiver_demo,
    get_medication,
    get_treatment,
    list_history,
    list_medications,
    list_treatments,
    list_upcoming_intakes,
)

__all__ = [
    "CAREGIVER_DEMO",
    "DEMO_NOTICE",
    "DEMO_PATIENT_NAME",
    "HISTORY",
    "MEDICATIONS",
    "TREATMENTS",
    "UPCOMING_INTAKES",
    "get_caregiver_demo",
    "get_medication",
    "get_treatment",
    "list_history",
    "list_medications",
    "list_treatments",
    "list_upcoming_intakes",
]
