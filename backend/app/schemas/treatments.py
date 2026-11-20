"""Esquemas Pydantic de tratamientos y vinculos (Fase 4, RF05/RF06/RF08).

Entrada y salida de los endpoints de `api/routers/treatments.py`.

Las restricciones por campo segun el actor NO viven aqui: el
schema no conoce al actor. Las aplica `treatment_service.py`
(diseno §4.4): crear/editar tratamientos, cambiar su estado y
anadir/quitar/cambiar la dosis de sus medicamentos son
operaciones de **solo paciente** (403 directo para el cuidador,
§4.6.7); la lectura con filtrado por seccion (D-1) tambien vive
en el servicio, que construye `TreatmentResponse` sin asignar
las secciones no autorizadas.

`ScheduleCreate` / `ScheduleResponse` se definen aqui porque la
creacion anidada de tratamientos los necesita como tipos; los
endpoints propios de horarios llegan con su modulo (Fase 4).
`ScheduleUpdate` pertenece a ese modulo y no se define aqui.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


def _validate_title_not_blank(title: str) -> str:
    """El titulo no puede ser solo espacios en blanco."""
    if not title.strip():
        raise ValueError("El título no puede estar vacío")
    return title


class ScheduleCreate(BaseModel):
    """Horario anidado en la creacion de un tratamiento."""

    frequency: Literal["DIARIO", "DIAS_SEMANA", "INTERVALO_DIAS"]
    days_of_week: list[int] | None = Field(default=None)
    interval_days: int | None = Field(default=None, ge=1)
    times: list[time] = Field(min_length=1)
    start_date: date
    end_date: date | None = None

    @field_validator("days_of_week")
    @classmethod
    def _check_days(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        for day in value:
            if day < 0 or day > 6:
                raise ValueError(
                    "Los días de semana van de 0 (lunes) a 6 (domingo)"
                )
        return value

    @model_validator(mode="after")
    def _check_frequency_fields(self) -> "ScheduleCreate":
        """Coherencia frecuencia <-> campos (diseno §4.4).

        DIAS_SEMANA exige `days_of_week`; INTERVALO_DIAS exige
        `interval_days`; si vienen con otra frecuencia -> 422.
        """
        if self.frequency == "DIAS_SEMANA":
            if not self.days_of_week:
                raise ValueError("DIAS_SEMANA exige days_of_week")
            if self.interval_days is not None:
                raise ValueError("interval_days no aplica con DIAS_SEMANA")
        elif self.frequency == "INTERVALO_DIAS":
            if self.interval_days is None:
                raise ValueError("INTERVALO_DIAS exige interval_days")
            if self.days_of_week is not None:
                raise ValueError("days_of_week no aplica con INTERVALO_DIAS")
        else:  # DIARIO
            if self.days_of_week is not None:
                raise ValueError("days_of_week no aplica con DIARIO")
            if self.interval_days is not None:
                raise ValueError("interval_days no aplica con DIARIO")
        return self


class ScheduleResponse(BaseModel):
    """Horario de un medicamento dentro de un tratamiento."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    treatment_medication_id: int
    frequency: str
    days_of_week: list[int] | None
    interval_days: int | None
    times: list[time]
    start_date: date
    end_date: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MedicationSummary(BaseModel):
    """Medicamento resumido, anidado en vinculos y recordatorios."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    presentation: str | None
    concentration: str | None


class TreatmentSummary(BaseModel):
    """Tratamiento resumido, anidado en recordatorios."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str


class TreatmentMedicationCreate(BaseModel):
    """Medicamento dentro de un tratamiento, con su dosis.

    `schedules` es obligatorio (>= 1) en la creacion anidada
    (lo exige `TreatmentCreate`); en el endpoint suelto
    (`POST /treatments/{id}/medications`) es opcional.
    """

    medication_id: int = Field(gt=0)
    dose_amount: Decimal = Field(max_digits=10, decimal_places=3, gt=0)
    dose_unit: str = Field(min_length=1, max_length=30)
    instructions: str | None = None
    schedules: list[ScheduleCreate] | None = Field(default=None, min_length=1)


class TreatmentMedicationUpdate(BaseModel):
    """Entrada de `PATCH .../medications/{link_id}` (parcial).

    Solo dosis, unidad e instrucciones: la dosis es prescripcion
    medica y solo el paciente puede cambiarla (diseno §4.6.5).
    """

    dose_amount: Decimal | None = Field(
        default=None, max_digits=10, decimal_places=3, gt=0
    )
    dose_unit: str | None = Field(default=None, min_length=1, max_length=30)
    instructions: str | None = None

    @model_validator(mode="after")
    def _check_at_least_one_field(self) -> "TreatmentMedicationUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar")
        return self


class TreatmentMedicationResponse(BaseModel):
    """Vinculo tratamiento x medicamento, con su dosis prescrita.

    `schedules` se omite si el actor es un cuidador sin
    `perm_view_schedules` (D-1): el servicio no lo asigna y la
    ruta serializa con `response_model_exclude_unset=True`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    medication_id: int
    medication: MedicationSummary
    dose_amount: Decimal
    dose_unit: str
    instructions: str | None
    is_active: bool
    schedules: list[ScheduleResponse] | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("dose_amount")
    def _serialize_dose_amount(self, value: Decimal) -> float:
        """`dose_amount` como numero JSON, no como cadena.

        Pydantic v2 serializa `Decimal` como cadena por defecto
        para no perder precision. La dosis tiene como maximo 3
        decimales (`Numeric(10,3)`), y `float()` de un decimal de
        <= 3 cifras conserva el valor exacto al volver a JSON
        (p. ej. `Decimal("2.500")` -> `2.5`, `Decimal("0.001")` ->
        `0.001`): solo cambia la representacion, no el valor.
        """
        return float(value)


class TreatmentCreate(BaseModel):
    """Entrada de `POST /api/v1/treatments`."""

    title: str = Field(min_length=1, max_length=150)
    notes: str | None = None
    start_date: date
    end_date: date | None = None
    medications: list[TreatmentMedicationCreate] = Field(min_length=1)

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str) -> str:
        return _validate_title_not_blank(value)

    @model_validator(mode="after")
    def _check_nested_schedules(self) -> "TreatmentCreate":
        """En la creacion anidada cada medicamento trae >= 1 horario."""
        for item in self.medications:
            if not item.schedules:
                raise ValueError(
                    "Cada medicamento necesita al menos un horario"
                )
        return self


class TreatmentUpdate(BaseModel):
    """Entrada de `PATCH /api/v1/treatments/{id}` (parcial).

    Solo `title`, `notes` y `end_date`: el estado NO se edita
    aqui, solo cambia por pause/resume/cancel/complete.
    """

    title: str | None = Field(default=None, min_length=1, max_length=150)
    notes: str | None = None
    end_date: date | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_title_not_blank(value)

    @model_validator(mode="after")
    def _check_at_least_one_field(self) -> "TreatmentUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar")
        return self


class ReminderResponse(BaseModel):
    """Un recordatorio proximo, con medicamento, dosis y tratamiento."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    scheduled_at: datetime
    status: str
    medication: MedicationSummary
    dose_amount: Decimal
    dose_unit: str
    treatment: TreatmentSummary
    schedule_id: int

    @field_serializer("dose_amount")
    def _serialize_dose_amount(self, value: Decimal) -> float:
        """`dose_amount` como numero JSON (ver
        `TreatmentMedicationResponse`)."""
        return float(value)


class TreatmentResponse(BaseModel):
    """Tratamiento con sus secciones anidadas (D-1).

    `medications` y `upcoming_reminders` son opcionales: el
    servicio NO los asigna cuando el actor no tiene el permiso
    de esa seccion, y la ruta serializa con
    `response_model_exclude_unset=True`, asi que la seccion queda
    ausente del JSON (ni `null` ni lista vacia).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    notes: str | None
    start_date: date
    end_date: date | None
    status: str
    medications: list[TreatmentMedicationResponse] | None = None
    upcoming_reminders: list[ReminderResponse] | None = None
    created_at: datetime
    updated_at: datetime
