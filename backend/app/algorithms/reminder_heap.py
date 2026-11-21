"""Cola de prioridad del motor de recordatorios (Fase 5, D15-D16).

El scheduler ordena los recordatorios por su instante programado
(``scheduled_at`` en UTC) y siempre atiende primero el mas proximo.
Esta cola es el corazon del motor, asi que la asignatura exige
demostrar la estructura de datos real: :class:`ReminderHeap` es un
heap binario propio (subir/bajar, insercion y extraccion) y
:class:`HeapqPriorityQueue` es la misma interfaz con ``heapq`` de la
biblioteca estandar como respaldo. Si la implementacion propia
fallara sus pruebas, el envio no se queda sin cola: se cambia la
implementacion, no el scheduler (D15).

Ambas clases comparten la misma interfaz (:class:`PriorityQueue`) y
el mismo borrado perezoso: cancelar un recordatorio marca su
entrada como muerta sin recorrer ni reconstruir la cola; la
entrada muerta se descarta cuando asoma a la cima. Los indices
``jobs_by_id`` / ``jobs_by_user`` que permiten cancelar o
reprogramar en O(1) viven en el scheduler (D16), no aqui: esta
cola solo ordena.

Orden: por ``(scheduled_at, reminder_id)``. El desempate por id
hace determinista el orden de extraccion cuando dos tomas caen en
el mismo instante (misma convencion que el resto del proyecto:
``scheduled_at`` y despues ``id``).

Solo se aceptan instantes con zona horaria (los ``scheduled_at``
son siempre UTC en este proyecto); un ``datetime`` ingenuo es un
error de programacion y se rechaza con ``ValueError``.
"""

from __future__ import annotations

import heapq
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

__all__ = [
    "HeapJob",
    "PriorityQueue",
    "ReminderHeap",
    "HeapqPriorityQueue",
]


@dataclass(frozen=True, order=True)
class HeapJob:
    """Un recordatorio en la cola.

    Se ordena por ``(scheduled_at, reminder_id)``: primero el
    instante programado y, en caso de empate, el id menor.
    """

    scheduled_at: datetime
    reminder_id: int


class PriorityQueue(ABC):
    """Interfaz de cola de prioridad para el scheduler.

    Las dos implementaciones (:class:`ReminderHeap` y
    :class:`HeapqPriorityQueue`) son intercambiables: el scheduler
    solo conoce esta interfaz.
    """

    @abstractmethod
    def push(self, job: HeapJob) -> None:
        """Encola un trabajo (si su id ya estaba vivo, lo reemplaza)."""

    @abstractmethod
    def pop(self) -> HeapJob | None:
        """Extrae y devuelve el trabajo mas proximo, o None si esta vacia."""

    @abstractmethod
    def peek(self) -> HeapJob | None:
        """Devuelve el trabajo mas proximo sin extraerlo, o None si esta vacia."""

    @abstractmethod
    def remove(self, reminder_id: int) -> bool:
        """Marca como muerto el trabajo vivo con ese id.

        Devuelve True si habia un trabajo vivo con ese id y False
        si no habia ninguno (o ya estaba muerto).
        """

    @abstractmethod
    def __len__(self) -> int:
        """Numero de trabajos vivos en la cola."""

    def __bool__(self) -> bool:
        return len(self) > 0


class _LazyPriorityQueue(PriorityQueue):
    """Base con borrado perezoso comun a las dos implementaciones.

    Cada entrada del monticulo es ``[job, seq, viva]``: ``seq`` es
    un contador monotono que hace unica cada entrada (asi dos
    entradas con el mismo trabajo nunca se confunden) y ``viva``
    marca el borrado perezoso. ``_by_id`` apunta a la entrada viva
    de cada id, o no lo contiene si no hay ninguna.
    """

    def __init__(self) -> None:
        self._entries: list[list] = []
        self._by_id: dict[int, list] = {}
        self._seq = 0
        self._live = 0

    def push(self, job: HeapJob) -> None:
        if job.scheduled_at.tzinfo is None:
            raise ValueError(
                "HeapJob.scheduled_at debe tener zona horaria (UTC)"
            )
        old = self._by_id.get(job.reminder_id)
        if old is not None:
            # Reprogramacion del mismo id: la entrada anterior
            # queda muerta y se descarta cuando asome a la cima.
            old[2] = False
            self._live -= 1
        self._seq += 1
        entry = [job, self._seq, True]
        self._by_id[job.reminder_id] = entry
        self._heap_push(entry)
        self._live += 1

    def remove(self, reminder_id: int) -> bool:
        entry = self._by_id.pop(reminder_id, None)
        if entry is None:
            return False
        entry[2] = False
        self._live -= 1
        return True

    def pop(self) -> HeapJob | None:
        while True:
            entry = self._heap_pop()
            if entry is None:
                return None
            if entry[2]:
                self._by_id.pop(entry[0].reminder_id, None)
                self._live -= 1
                return entry[0]
            # Entrada muerta: ya fuera del monticulo, se sigue.

    def peek(self) -> HeapJob | None:
        while True:
            entry = self._heap_peek()
            if entry is None:
                return None
            if entry[2]:
                return entry[0]
            # La cima esta muerta: se limpia y se mira la siguiente.
            self._heap_pop()

    def __len__(self) -> int:
        return self._live

    # Primitivas del monticulo: cada implementacion las resuelve
    # con su propia estructura.

    @abstractmethod
    def _heap_push(self, entry: list) -> None:
        """Inserta una entrada en el monticulo."""

    @abstractmethod
    def _heap_pop(self) -> list | None:
        """Extrae y devuelve la entrada de la cima, o None si esta vacio."""

    @abstractmethod
    def _heap_peek(self) -> list | None:
        """Devuelve la entrada de la cima sin extraerla, o None si esta vacio."""


class ReminderHeap(_LazyPriorityQueue):
    """Heap binario propio (D15).

    El monticulo vive en ``self._entries`` (una lista): el padre
    de ``i`` esta en ``(i - 1) // 2`` y sus hijos en ``2*i + 1`` y
    ``2*i + 2``. ``_sift_up`` restaura el orden tras insertar y
    ``_sift_down`` tras extraer la cima. La comparacion es por
    ``HeapJob``: ``(scheduled_at, reminder_id)``.
    """

    def _heap_push(self, entry: list) -> None:
        self._entries.append(entry)
        self._sift_up(len(self._entries) - 1)

    def _heap_pop(self) -> list | None:
        entries = self._entries
        if not entries:
            return None
        top = entries[0]
        last = entries.pop()
        if entries:
            entries[0] = last
            self._sift_down(0)
        return top

    def _heap_peek(self) -> list | None:
        return self._entries[0] if self._entries else None

    def _sift_up(self, idx: int) -> None:
        """Sube la entrada en ``idx`` hasta su sitio (padre mayor)."""
        entries = self._entries
        while idx > 0:
            parent = (idx - 1) // 2
            if entries[idx][0] < entries[parent][0]:
                entries[idx], entries[parent] = entries[parent], entries[idx]
                idx = parent
            else:
                break

    def _sift_down(self, idx: int) -> None:
        """Baja la entrada en ``idx`` hasta su sitio (hijos menores)."""
        entries = self._entries
        n = len(entries)
        while True:
            left = 2 * idx + 1
            right = left + 1
            smallest = idx
            if left < n and entries[left][0] < entries[smallest][0]:
                smallest = left
            if right < n and entries[right][0] < entries[smallest][0]:
                smallest = right
            if smallest == idx:
                break
            entries[idx], entries[smallest] = entries[smallest], entries[idx]
            idx = smallest


class HeapqPriorityQueue(_LazyPriorityQueue):
    """Respaldo con ``heapq`` detras de la misma interfaz (D15).

    Misma semantica que :class:`ReminderHeap` (mismo borrado
    perezoso, mismo orden, mismo desempate): las pruebas de
    propiedades exigen que ambas extraigan en el mismo orden con
    las mismas inserciones. Las entradas son listas
    ``[job, seq, viva]``; ``heapq`` las compara por ``job`` y, en
    caso de empate exacto, por ``seq`` (unico), asi que nunca
    llega a comparar el booleano.
    """

    def _heap_push(self, entry: list) -> None:
        heapq.heappush(self._entries, entry)

    def _heap_pop(self) -> list | None:
        if not self._entries:
            return None
        return heapq.heappop(self._entries)

    def _heap_peek(self) -> list | None:
        return self._entries[0] if self._entries else None
