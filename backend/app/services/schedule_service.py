"""Generacion de recordatorios (Fase 4, diseno §4.7).

Logica de negocio, no repositorio ni router: la usan la
creacion de tratamientos y vinculos (al crear sus horarios) y
el resume de tratamientos (al regenerar).

**HORIZONTE: exactamente 72 horas, no 7 dias ni 4 dias
naturales.** El diseno §4.7 decia 7 dias y la decision vigente
del usuario (escenario A, 2026-11-20) era generar 3 dias
(hoy..hoy+3, 4 dias naturales); la decision del usuario de
2026-11-20 fija la ventana en `[ahora, ahora + 72 h)` en tiempo
absoluto. El parametro `horizon_hours` existe para que el cambio
quede en un solo lugar; el valor por defecto es el vigente (72).

**Ventana:** un candidato (fecha, hora de pared) se genera si y
solo si `ahora <= scheduled_at < ahora + 72 h`, con `ahora` en
UTC y la hora de pared convertida desde la zona horaria del
usuario. Las fechas de inicio y fin del horario y del
tratamiento siguen recortando la ventana por ambos lados. Las
horas de hoy ya pasadas quedan fuera (son `< ahora`): ya no se
crean recordatorios PENDIENTE en el pasado.

**Idempotencia:** la UNIQUE parcial `(schedule_id, scheduled_at)`
(`uq_reminders_schedule_time`, solo estados PENDIENTE, ENVIANDO y
ENVIADA) lo garantiza; la insercion usa `INSERT ... ON CONFLICT
DO NOTHING`, asi que regenerar nunca duplica un recordatorio
activo. Un hueco con una fila CANCELADA (u otra inactiva) si
admite un PENDIENTE nuevo: por eso el resume crea recordatorios
sin borrar el historial (decision B).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import Treatment
from app.models.schedules import MedicationSchedule
from app.models.users import User
from app.repositories import reminder_repository

# Horizonte vigente de generacion (decision del usuario, 2026-11-20).
GENERATION_HORIZON_HOURS = 72


def _wall_to_utc(day: date, wall: time, tz: ZoneInfo) -> datetime:
    """Convierte una hora de pared a UTC, con reglas DST (RNF04).

    Hora inexistente por cambio de horario: se desplaza a la
    primera hora valida. Hora ambigua: primera ocurrencia
    (`fold=0`, el comportamiento por defecto de `zoneinfo`).
    """
    naive = datetime.combine(day, wall)
    aware = naive.replace(tzinfo=tz)
    back = aware.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
    if back != naive:
        # La hora no existe (salto DST): `back` es la primera
        # hora valida tras el salto; desplazar hasta ella.
        aware = (naive + (back - naive)).replace(tzinfo=tz)
    return aware.astimezone(timezone.utc)


def _matches_frequency(day: date, schedule: MedicationSchedule) -> bool:
    """True si la fecha cae en la recurrencia del horario."""
    if schedule.frequency == "DIARIO":
        return True
    if schedule.frequency == "DIAS_SEMANA":
        return (
            schedule.days_of_week is not None
            and day.weekday() in schedule.days_of_week
        )
    if schedule.frequency == "INTERVALO_DIAS":
        return (
            schedule.interval_days is not None
            and (day - schedule.start_date).days % schedule.interval_days == 0
        )
    return False


async def generate_reminders_for_schedule(
    session: AsyncSession,
    schedule: MedicationSchedule,
    treatment: Treatment,
    user: User,
    *,
    horizon_hours: int = GENERATION_HORIZON_HOURS,
    now: datetime | None = None,
    parent_by_scheduled_at: dict[datetime, int] | None = None,
) -> int:
    """Genera los recordatorios de un horario (idempotente).

    Un recordatorio por fecha de la ventana que coincida con la
    frecuencia y por cada hora de `times` (ordenadas), solo si su
    instante cae en `[ahora, ahora + 72 h)`. Estado PENDIENTE,
    `scheduled_at` en UTC. `parent_by_scheduled_at` relaciona cada
    fila nueva con la CANCELADA que reemplaza (lo usa el resume);
    sin el, `parent_reminder_id` queda en NULL. Devuelve el numero
    de recordatorios insertados (0 si la ventana esta vacia o si
    ya existian todos).
    """
    tz = ZoneInfo(user.timezone)
    current = now or datetime.now(timezone.utc)
    limit = current + timedelta(hours=horizon_hours)
    today = current.astimezone(tz).date()
    last_day = limit.astimezone(tz).date()
    window_start = max(schedule.start_date, treatment.start_date, today)
    ends = [
        end
        for end in (schedule.end_date, treatment.end_date, last_day)
        if end is not None
    ]
    window_end = min(ends)
    if window_end < window_start:
        return 0
    rows: list[dict] = []
    day = window_start
    while day <= window_end:
        if _matches_frequency(day, schedule):
            for wall in sorted(set(schedule.times)):
                scheduled_at = _wall_to_utc(day, wall, tz)
                if current <= scheduled_at < limit:
                    row: dict = {
                        "schedule_id": schedule.id,
                        "treatment_medication_id": schedule.treatment_medication_id,
                        "user_id": schedule.user_id,
                        "scheduled_at": scheduled_at,
                        "status": "PENDIENTE",
                    }
                    if parent_by_scheduled_at is not None:
                        parent_id = parent_by_scheduled_at.get(scheduled_at)
                        if parent_id is not None:
                            row["parent_reminder_id"] = parent_id
                    rows.append(row)
        day += timedelta(days=1)
    return await reminder_repository.create_many(session, rows)


async def regenerate_reminders_for_schedule(
    session: AsyncSession,
    schedule: MedicationSchedule,
    treatment: Treatment,
    user: User,
    *,
    horizon_hours: int = GENERATION_HORIZON_HOURS,
    now: datetime | None = None,
) -> int:
    """Regeneracion (§4.7): borrar los PENDIENTE futuros del
    horario y generar de nuevo.

    Nunca toca TOMADA, POSPUESTA, PERDIDA, ENVIADA, ENVIANDO ni
    CANCELADA. Es la regeneracion de la edicion de horarios (su
    endpoint llega con ese modulo).
    """
    current = now or datetime.now(timezone.utc)
    await reminder_repository.delete_pending_for_schedule(
        session, schedule.id, current
    )
    return await generate_reminders_for_schedule(
        session, schedule, treatment, user,
        horizon_hours=horizon_hours, now=current,
    )


async def regenerate_reminders_for_resume(
    session: AsyncSession,
    schedule: MedicationSchedule,
    treatment: Treatment,
    user: User,
    *,
    horizon_hours: int = GENERATION_HORIZON_HOURS,
    now: datetime | None = None,
) -> int:
    """Regeneracion tras reanudar un tratamiento (decision B).

    NO borra ninguna fila CANCELADA: las CANCELADA futuras quedan
    intactas como historial. Como el indice UNIQUE parcial solo
    cubre los estados activos, la insercion crea PENDIENTE nuevos
    en esos huecos (`ON CONFLICT DO NOTHING` salta los que ya
    tienen un activo); cada fila nueva apunta a la CANCELADA mas
    reciente del hueco con `parent_reminder_id`. Los PENDIENTE
    futuros si se borran antes (no tienen historial, segun §4.7)
    y se regeneran.
    """
    current = now or datetime.now(timezone.utc)
    await reminder_repository.delete_pending_for_schedule(
        session, schedule.id, current
    )
    cancelled = await reminder_repository.list_cancelled_for_schedule(
        session, schedule.id, current
    )
    parents: dict[datetime, int] = {}
    for row in cancelled:
        # Ordenadas por (scheduled_at, id): la mas reciente por
        # hueco (mayor id) gana si hay varias.
        parents[row.scheduled_at] = row.id
    return await generate_reminders_for_schedule(
        session, schedule, treatment, user,
        horizon_hours=horizon_hours, now=current,
        parent_by_scheduled_at=parents,
    )
