"""Esquemas Pydantic de medicamentos (Fase 4, RF04).

Entrada y salida de los endpoints de `api/routers/medications.py`.

Las restricciones por campo segun el actor NO viven aqui: el
schema no conoce al actor. Las aplica `medication_service.py`
(diseno §4.4): el cuidador con `perm_manage_medications` solo
edita `name`/`presentation`/`notes`; si el payload trae
`concentration` o `unit` -> 403.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _validate_name_not_blank(name: str) -> str:
    """El nombre no puede ser solo espacios en blanco."""
    if not name.strip():
        raise ValueError("El nombre no puede estar vacío")
    return name


class MedicationCreate(BaseModel):
    """Entrada de `POST /api/v1/medications`."""

    name: str = Field(min_length=1, max_length=150)
    presentation: str | None = Field(default=None, max_length=100)
    concentration: str | None = Field(default=None, max_length=50)
    unit: str | None = Field(default=None, max_length=30)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _validate_name_not_blank(value)


class MedicationUpdate(BaseModel):
    """Entrada de `PATCH /api/v1/medications/{id}` (parcial).

    Todos los campos son opcionales; al menos uno debe venir
    (si no, 422). Si `name` viene, mismas reglas que en la
    creacion. Un campo con valor `None` lo borra (p. ej. quitar
    las notas); para distinguir "no viene" de "viene en null",
    el servicio usa `model_dump(exclude_unset=True)`.
    """

    name: str | None = Field(default=None, min_length=1, max_length=150)
    presentation: str | None = Field(default=None, max_length=100)
    concentration: str | None = Field(default=None, max_length=50)
    unit: str | None = Field(default=None, max_length=30)
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_name_not_blank(value)

    @model_validator(mode="after")
    def _check_at_least_one_field(self) -> "MedicationUpdate":
        if not self.model_fields_set:
            raise ValueError("Debe indicar al menos un campo para actualizar")
        return self


class MedicationResponse(BaseModel):
    """Medicamento del catalogo propio del usuario (RF04)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    presentation: str | None
    concentration: str | None
    unit: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
