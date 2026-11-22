"""Datos ficticios del modo demostracion del bot.

Todo lo que hay en este modulo es INVENTADO y esta marcado como
demostracion. No sale de PostgreSQL, no es un paciente real y
no se guarda en ningun sitio: solo sirve para probar la
navegacion, los teclados y los mensajes del bot sin depender de
los servicios que todavia no existen (Fases 3-5).

Reglas:

- Cada registro lleva un id de texto que empieza por ``demo-``.
  Nunca se usan ids numericos de base de datos.
- Cada pantalla que muestra estos datos incluye
  ``DEMO_NOTICE`` para que nadie confunda la demostracion con
  datos reales.
- Los valores de ejemplo (medicamentos, dosis, horarios) siguen
  el formato de la especificacion (``docs/ESPECIFICACION_BOT_
  TELEGRAM.md`` §3.1), pero el paciente es ficticio.
"""

from __future__ import annotations

from dataclasses import dataclass

DEMO_NOTICE = (
    "🔔 Modo demostración: los datos son ficticios "
    "y no se guarda nada."
)

DEMO_PATIENT_NAME = "Paciente de demostración"


@dataclass(frozen=True)
class MockMedication:
    """Un medicamento ficticio de la demostracion."""

    id: str
    name: str
    presentation: str
    concentration: str
    unit: str
    dose_text: str


@dataclass(frozen=True)
class MockTreatment:
    """Un tratamiento ficticio de la demostracion."""

    id: str
    name: str
    status: str
    start_date: str
    medications_text: str


@dataclass(frozen=True)
class MockUpcomingIntake:
    """Una proxima toma ficticia de la demostracion."""

    id: str
    medication_name: str
    dose_text: str
    time: str
    treatment_name: str


@dataclass(frozen=True)
class MockHistoryEntry:
    """Una toma pasada ficticia de la demostracion."""

    date: str
    time: str
    medication_name: str
    origin: str
    result: str


@dataclass(frozen=True)
class MockCaregiver:
    """Un cuidador ficticio de la demostracion."""

    name: str
    relation: str
    permissions_text: str


MEDICATIONS: tuple[MockMedication, ...] = (
    MockMedication(
        id="demo-med-1",
        name="Amoxicilina",
        presentation="cápsulas",
        concentration="500 mg",
        unit="cápsula",
        dose_text="1 cápsula cada 8 horas",
    ),
    MockMedication(
        id="demo-med-2",
        name="Paracetamol",
        presentation="tabletas",
        concentration="500 mg",
        unit="tableta",
        dose_text="1 tableta cada 8 horas",
    ),
    MockMedication(
        id="demo-med-3",
        name="Omeprazol",
        presentation="cápsulas",
        concentration="20 mg",
        unit="cápsula",
        dose_text="1 cápsula en ayunas",
    ),
    MockMedication(
        id="demo-med-4",
        name="Losartán",
        presentation="tabletas",
        concentration="50 mg",
        unit="tableta",
        dose_text="1 tableta al día",
    ),
)

TREATMENTS: tuple[MockTreatment, ...] = (
    MockTreatment(
        id="demo-treat-1",
        name="Infección respiratoria (demo)",
        status="ACTIVO",
        start_date="2026-11-10",
        medications_text="Amoxicilina 500 mg — 1 cápsula cada 8 horas",
    ),
    MockTreatment(
        id="demo-treat-2",
        name="Control de presión arterial (demo)",
        status="ACTIVO",
        start_date="2026-11-01",
        medications_text="Losartán 50 mg — 1 tableta al día",
    ),
)

UPCOMING_INTAKES: tuple[MockUpcomingIntake, ...] = (
    MockUpcomingIntake(
        id="demo-intake-1",
        medication_name="Amoxicilina 500 mg",
        dose_text="1 cápsula",
        time="08:00",
        treatment_name="Infección respiratoria (demo)",
    ),
    MockUpcomingIntake(
        id="demo-intake-2",
        medication_name="Paracetamol 500 mg",
        dose_text="1 tableta",
        time="14:00",
        treatment_name="Infección respiratoria (demo)",
    ),
    MockUpcomingIntake(
        id="demo-intake-3",
        medication_name="Omeprazol 20 mg",
        dose_text="1 cápsula",
        time="20:00",
        treatment_name="Control de presión arterial (demo)",
    ),
)

HISTORY: tuple[MockHistoryEntry, ...] = (
    MockHistoryEntry(
        date="2026-11-11",
        time="08:02",
        medication_name="Amoxicilina 500 mg",
        origin="TELEGRAM",
        result="Tomada",
    ),
    MockHistoryEntry(
        date="2026-11-10",
        time="20:05",
        medication_name="Omeprazol 20 mg",
        origin="WEB",
        result="Tomada",
    ),
    MockHistoryEntry(
        date="2026-11-10",
        time="14:30",
        medication_name="Paracetamol 500 mg",
        origin="TELEGRAM",
        result="Tomada",
    ),
    MockHistoryEntry(
        date="2026-11-10",
        time="08:00",
        medication_name="Amoxicilina 500 mg",
        origin="—",
        result="Perdida (no se confirmó a tiempo)",
    ),
)

CAREGIVER_DEMO = MockCaregiver(
    name="Ana Pérez (demo)",
    relation="Hija (demo)",
    permissions_text="Puede ver tus medicamentos y tus próximas tomas.",
)


def list_medications() -> tuple[MockMedication, ...]:
    """Devuelve los medicamentos ficticios de la demostracion."""
    return MEDICATIONS


def get_medication(medication_id: str) -> MockMedication | None:
    """Busca un medicamento ficticio por id, o None si no existe."""
    for medication in MEDICATIONS:
        if medication.id == medication_id:
            return medication
    return None


def list_treatments() -> tuple[MockTreatment, ...]:
    """Devuelve los tratamientos ficticios de la demostracion."""
    return TREATMENTS


def get_treatment(treatment_id: str) -> MockTreatment | None:
    """Busca un tratamiento ficticio por id, o None si no existe."""
    for treatment in TREATMENTS:
        if treatment.id == treatment_id:
            return treatment
    return None


def list_upcoming_intakes() -> tuple[MockUpcomingIntake, ...]:
    """Devuelve las proximas tomas ficticias, ordenadas por hora."""
    return tuple(sorted(UPCOMING_INTAKES, key=lambda item: item.time))


def list_history() -> tuple[MockHistoryEntry, ...]:
    """Devuelve el historial ficticio, el mas reciente primero."""
    return HISTORY


def get_caregiver_demo() -> MockCaregiver:
    """Devuelve el cuidador ficticio de la demostracion."""
    return CAREGIVER_DEMO
