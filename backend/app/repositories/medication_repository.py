"""Consultas de medicamentos (Fase 4). Solo SQL, sin logica de negocio.

El repositorio solo consulta: el servicio decide (404/403/409,
reglas del cuidador). `create` y `update`/`deactivate` solo
anaden o modifican objetos en la sesion; el commit lo hace el
servicio, en una sola transaccion (patron de Fase 3).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medications import Medication, Treatment, TreatmentMedication


def create(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    presentation: str | None = None,
    concentration: str | None = None,
    unit: str | None = None,
    notes: str | None = None,
) -> Medication:
    """Crea el objeto Medication y lo anade a la sesion (sin commit).

    Sin unicidad de nombre: el catalogo admite dos "Amoxicilina"
    con distinta presentacion (diseno §4.6.2).
    """
    medication = Medication(
        user_id=user_id,
        name=name,
        presentation=presentation,
        concentration=concentration,
        unit=unit,
        notes=notes,
        is_active=True,
    )
    session.add(medication)
    return medication


async def get_by_id(
    session: AsyncSession, medication_id: int, user_id: int | None = None
) -> Medication | None:
    """Busca un medicamento por id.

    Con `user_id`, filtra por el dueno (el caso normal: el
    servicio ya resolvio el usuario efectivo). Sin `user_id`,
    busca en cualquier cuenta: el servicio lo usa para distinguir
    404 (no existe) de 403 (existe, pero es de otro usuario).
    """
    stmt = select(Medication).where(Medication.id == medication_id)
    if user_id is not None:
        stmt = stmt.where(Medication.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_by_user(
    session: AsyncSession, user_id: int, *, is_active: bool = True, limit: int = 100
) -> list[Medication]:
    """Medicamentos de un usuario, ordenados por nombre.

    Por defecto solo los activos; con `is_active=False`, solo los
    desactivados. El listado nunca mezcla cuentas: el filtro por
    `user_id` es obligatorio (diseno §4.10, R4).
    """
    stmt = (
        select(Medication)
        .where(
            Medication.user_id == user_id,
            Medication.is_active == is_active,
        )
        .order_by(Medication.name)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def update(session: AsyncSession, medication: Medication, **fields) -> Medication:
    """Aplica los campos dados al objeto (sin commit).

    Solo se pasan los campos presentes en el payload
    (`model_dump(exclude_unset=True)` en el servicio): un campo
    ausente no se toca y un campo en `None` se borra.
    """
    for name, value in fields.items():
        setattr(medication, name, value)
    return medication


def deactivate(session: AsyncSession, medication: Medication) -> Medication:
    """Desactivacion logica (`is_active=False`, sin commit).

    No borra nada: los tratamientos que lo referencian conservan
    su historial (diseno §4.6.2).
    """
    medication.is_active = False
    return medication


def reactivate(session: AsyncSession, medication: Medication) -> Medication:
    """Reactivacion logica (`is_active=True`, sin commit).

    No revive nada: los recordatorios CANCELADA conservan su motivo
    (decision B, D-11); los futuros nuevos nacen por el top-up o la
    regeneracion normal, no por esta funcion.
    """
    medication.is_active = True
    return medication


async def is_in_active_treatment(
    session: AsyncSession, medication_id: int, user_id: int
) -> bool:
    """True si el medicamento esta en un vinculo activo de un
    tratamiento ACTIVO del usuario.

    Lo usa el servicio para la regla del cuidador (C3): un
    cuidador solo desactiva medicamentos que no esten en
    tratamiento activo; si lo esta, 403 (desactivarlo silenciaria
    sus recordatorios, que es suspender el tratamiento por la
    puerta de atras).
    """
    stmt = (
        select(TreatmentMedication.id)
        .join(
            Treatment,
            Treatment.id == TreatmentMedication.treatment_id,
        )
        .where(
            TreatmentMedication.medication_id == medication_id,
            TreatmentMedication.user_id == user_id,
            TreatmentMedication.is_active.is_(True),
            Treatment.user_id == user_id,
            Treatment.status == "ACTIVO",
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None
