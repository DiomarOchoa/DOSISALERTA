"""Reconciliación de recordatorios: PERDIDA y ENVIANDO caídos (Fase 5, Etapa 5).

El reconciliador es la pasada que cierra el motor: marca PERDIDA
los recordatorios vencidos fuera de la gracia de 30 minutos y
libera los ENVIANDO caídos (reclamados hace más de 5 minutos sin
registro de intento) devolviéndolos a PENDIENTE para que el
scheduler los reenvíe por el camino normal.

Reglas (plan corregido 2026-11-21):

- PERDIDA: estados PENDIENTE, ENVIADA y ENVIANDO con
  ``scheduled_at`` más de 30 minutos en el pasado. TOMADA,
  POSPUESTA, CANCELADA y FALLIDA nunca se tocan. No se crea
  ninguna toma.
- Caídos: ENVIANDO con ``claimed_at`` de hace más de 5 minutos
  y sin log para su ``current_attempt_id``, dentro de gracia.
  Al liberar se limpian ``current_attempt_id``, ``claimed_at`` y
  ``next_attempt_at`` (incluido un valor viejo de un ciclo
  anterior: la reclamación no lo limpia, así que no se exige
  ``next_attempt_at IS NULL``). ``attempt_count`` se conserva.
- Los reintentos NO los libera el reconciliador: un reintento
  vuelve a PENDIENTE con ``next_attempt_at`` (``set_next_attempt``)
  y el cargador lo recoge cuando vence su hora. La pasada de
  PERDIDA cancela los reintentos cuya gracia ya pasó.
- En modo simulado se salta la liberación de caídos (en simulado
  no hay logs por diseño, así que "sin log" no distingue una
  caída); la marca PERDIDA sí aplica.

Cada regla es su propia transacción y su propio try/except: si
una falla, la otra sigue y el bucle del scheduler no muere. Los
UPDATEs son atómicos con subconsulta LIMIT 500 y re-validación
de las condiciones en el UPDATE exterior (precisiones B y C).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories import reminder_repository

logger = logging.getLogger(__name__)

GRACE_MINUTES = 30
STALE_MINUTES = 5
BATCH_LIMIT = 500

__all__ = [
    "Reconciler",
    "ReconcileResult",
    "GRACE_MINUTES",
    "STALE_MINUTES",
    "BATCH_LIMIT",
]


@dataclass
class ReconcileResult:
    """Contadores de una pasada de reconciliación.

    ``skipped_simulated`` es 1 cuando la regla de caídos se saltó
    por el modo simulado en esta pasada (0 en caso contrario):
    cuenta pasadas saltadas, no filas (en simulado no se consulta
    cuántas filas habría liberado).
    """

    marked_perdida: int = 0
    released_stale: int = 0
    skipped_simulated: int = 0
    perdida_ids: list[int] = field(default_factory=list)


class Reconciler:
    """Pasada de PERDIDA + liberación de caídos (Etapa 5)."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        *,
        grace_minutes: int = GRACE_MINUTES,
        stale_minutes: int = STALE_MINUTES,
        simulated: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._grace_minutes = grace_minutes
        self._stale_minutes = stale_minutes
        self._simulated = simulated

    async def reconcile(self, now: datetime) -> ReconcileResult:
        """Una pasada: PERDIDA y luego liberación de caídos.

        El orden importa: PERDIDA primero, para cancelar todo lo
        vencido (incluidos los reintentos pendientes) antes de
        liberar nada. Nunca levanta una excepción por una regla:
        cada una se registra y la pasada sigue.
        """
        started = time.monotonic()
        result = ReconcileResult()
        # 1. PERDIDA (siempre, también en simulado).
        try:
            async with self._session_factory() as session:
                ids = await reminder_repository.mark_perdida(
                    session,
                    cutoff=now - timedelta(minutes=self._grace_minutes),
                    limit=BATCH_LIMIT,
                )
                await session.commit()
            result.marked_perdida = len(ids)
            result.perdida_ids = ids
        except Exception:
            logger.exception("Reconciliación: error al marcar PERDIDA")
        # 2. Caídos (saltada en simulado: sin logs no hay caída
        # que distinguir de un envío simulado normal).
        if self._simulated:
            result.skipped_simulated = 1
        else:
            try:
                async with self._session_factory() as session:
                    released = await reminder_repository.release_stale_sending(
                        session,
                        stale_cutoff=now
                        - timedelta(minutes=self._stale_minutes),
                        grace_cutoff=now
                        - timedelta(minutes=self._grace_minutes),
                        limit=BATCH_LIMIT,
                    )
                    await session.commit()
                result.released_stale = len(released)
            except Exception:
                logger.exception(
                    "Reconciliación: error al liberar ENVIANDO caídos"
                )
        logger.info(
            "Reconciliación: PERDIDA=%d caídos_liberados=%d simulado_saltado=%d (%.2fs)",
            result.marked_perdida,
            result.released_stale,
            result.skipped_simulated,
            time.monotonic() - started,
        )
        return result
