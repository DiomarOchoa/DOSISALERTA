"""Esquemas Pydantic de recordatorios y tomas (Fase 5, Etapa 4).

Entrada y salida de los endpoints de `api/routers/reminders.py`.

Las restricciones por actor NO viven aqui: el schema no conoce
al actor. Las aplica `intake_service.py`: confirmar y posponer
son operaciones de **solo paciente** (403 directo para el
cuidador, con auditoria ACCESS_DENIED).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PostponeRequest(BaseModel):
    """Retraso elegido al posponer una toma (15, 30 o 60 minutos)."""

    delay_minutes: Literal[15, 30, 60]


class IntakeResponse(BaseModel):
    """Una toma confirmada (200 de POST /confirm)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: int
    user_id: int
    taken_at: datetime
    source: str
    note: str | None = None
    created_at: datetime
    # Campo calculado por el servicio, no una columna: la web
    # necesita saber que el recordatorio quedo TOMADA.
    reminder_status: str = "TOMADA"


class ReminderResponse(BaseModel):
    """Un recordatorio (original o hijo en POST /postpone)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    schedule_id: int
    treatment_medication_id: int
    user_id: int
    scheduled_at: datetime
    status: str
    parent_reminder_id: int | None = None
    postponed_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class PostponeResponse(BaseModel):
    """El original pospuesto y el hijo creado (200 de POST /postpone)."""

    original: ReminderResponse
    child: ReminderResponse
