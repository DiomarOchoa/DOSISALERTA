"""Esquemas Pydantic de historial y estadísticas (Fase 7, RF13/RF14).

Entrada y salida de `GET /api/v1/reminders/history` y
`GET /api/v1/stats/compliance`.

Los esquemas no conocen al actor ni a la zona horaria: el
servicio resuelve el usuario efectivo y el periodo.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class HistoryItemResponse(BaseModel):
    """Una fila del historial (RF13).

    Más rica que `ReminderResponse`: trae medicamento, dosis y
    tratamiento para poder mostrarla, y la toma si existe.
    `cancel_reason` solo tiene valor cuando el estado es
    `CANCELADA` (D-11); `null` si la fila es anterior a la
    migración o el estado no es `CANCELADA`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    scheduled_at: datetime
    status: str
    cancel_reason: str | None = None
    parent_reminder_id: int | None = None
    postponed_count: int
    medication_id: int
    medication_name: str
    dose_amount: Decimal
    dose_unit: str
    treatment_id: int
    treatment_title: str
    taken_at: datetime | None = None
    source: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("dose_amount")
    def _serialize_dose_amount(self, value: Decimal) -> str:
        """`dose_amount` como cadena decimal (plan §3.3 y §5.1).

        El contrato del historial la pide como texto
        (`"500.000"`), a diferencia de
        `TreatmentMedicationResponse` (que la serializa como
        número). `str(Decimal)` conserva los 3 decimales de
        `Numeric(10,3)`.
        """
        return str(value)


class HistoryPageResponse(BaseModel):
    """Una página del historial (RF13, D-6).

    `total` es la cantidad de registros que cumplen exactamente
    los mismos filtros del listado (fotografía del momento de la
    consulta); `limit` y `offset` son los valores efectivos.
    """

    items: list[HistoryItemResponse]
    total: int
    limit: int
    offset: int


class ComplianceSummary(BaseModel):
    """Resumen de cumplimiento de un periodo (RF14).

    `scheduled` es el total de tomas programadas en el periodo
    con desenlace (`taken_on_time + taken_late + lost +
    cancelled`). El denominador es `scheduled - cancelled +
    unknown` (D-1 opción 2; D-11 Alt 3, aprobada): los cinco
    motivos conocidos quedan fuera y `unknown` (NULL) entra.
    `compliance_percentage` es `null` cuando el denominador es 0.
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: date = Field(alias="from")
    to: date
    scheduled: int
    taken_on_time: int
    taken_late: int
    lost: int
    cancelled: int
    cancelled_by_reason: dict[str, int]
    compliance_percentage: float | None


class ComplianceBucket(ComplianceSummary):
    """Un grupo del desglose (RF14, D-7; se puebla en el commit 4).

    Los grupos temporales se identifican por `period_start` +
    `period_label`; los de medicamento, por `medication_id` +
    `medication_name`. `from`/`to` conservan los límites del
    periodo completo de la consulta, no los del bucket. Los
    campos que no corresponden al tipo de grupo quedan en `null`
    y el endpoint los omite al serializar (commit 4).
    """

    period_start: date | None = None
    period_label: str | None = None
    medication_id: int | None = None
    medication_name: str | None = None


class ComplianceResponse(BaseModel):
    """Respuesta de `GET /api/v1/stats/compliance` (RF14).

    Sin `group_by`, `groups` es `null` y solo se devuelve
    `summary`. Con `group_by` (commit 4), se devuelven ambos.
    """

    summary: ComplianceSummary
    groups: list[ComplianceBucket] | None = None
