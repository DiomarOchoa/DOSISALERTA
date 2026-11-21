"""Pruebas de propiedades de la cola de prioridad (Fase 5, Etapa 1, D15).

Puras y sin base de datos: comparan :class:`ReminderHeap` contra
``heapq`` (a traves de :class:`HeapqPriorityQueue`) y contra un
modelo de referencia (un dict de trabajos vivos). Los datos son
aleatorios con semilla fija, asi que las pruebas son
deterministicas.

Criterios que se verifican (aceptacion de la Etapa 1):
- El mismo orden de extraccion que ``heapq`` con las mismas
  inserciones (y que ``sorted``).
- Desempate determinista por ``reminder_id`` cuando coincide
  ``scheduled_at``.
- Borrado perezoso: quitar un trabajo no recorre la cola y el
  trabajo no vuelve a salir; re-encolar el mismo id reemplaza la
  entrada anterior.
- ``peek`` no extrae; ``pop``/``peek`` en vacio devuelven None.
- Solo se aceptan instantes con zona horaria.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from app.algorithms.reminder_heap import (
    HeapJob,
    HeapqPriorityQueue,
    PriorityQueue,
    ReminderHeap,
)

QUEUE_CLASSES = [ReminderHeap, HeapqPriorityQueue]

BASE = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def job(minutes: int, reminder_id: int) -> HeapJob:
    return HeapJob(BASE + timedelta(minutes=minutes), reminder_id)


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_empty_queue(cls: type[PriorityQueue]) -> None:
    q = cls()
    assert len(q) == 0
    assert not q
    assert q.pop() is None
    assert q.peek() is None
    assert q.remove(1) is False


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_push_pop_order_matches_sorted(cls: type[PriorityQueue]) -> None:
    rng = random.Random(7)
    jobs = [job(rng.randrange(0, 10_000), i) for i in range(200)]
    q = cls()
    for j in jobs:
        q.push(j)
    assert len(q) == 200
    assert bool(q)
    assert [q.pop() for _ in range(200)] == sorted(jobs)
    assert len(q) == 0
    assert q.pop() is None


def test_both_implementations_extract_in_the_same_order() -> None:
    rng = random.Random(11)
    jobs = [job(rng.randrange(0, 10_000), i) for i in range(500)]
    heaps = [ReminderHeap(), HeapqPriorityQueue()]
    for q in heaps:
        for j in jobs:
            q.push(j)
    assert [heaps[0].pop() for _ in range(500)] == [
        heaps[1].pop() for _ in range(500)
    ]


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_ties_are_broken_by_reminder_id(cls: type[PriorityQueue]) -> None:
    q = cls()
    for reminder_id in (9, 3, 7, 1):
        q.push(job(60, reminder_id))
    assert [q.pop() for _ in range(4)] == [job(60, i) for i in (1, 3, 7, 9)]


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_peek_does_not_remove(cls: type[PriorityQueue]) -> None:
    q = cls()
    q.push(job(30, 1))
    q.push(job(10, 2))
    assert q.peek() == job(10, 2)
    assert len(q) == 2
    assert q.peek() == job(10, 2)
    assert q.pop() == job(10, 2)
    assert len(q) == 1


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_remove_skips_the_entry(cls: type[PriorityQueue]) -> None:
    q = cls()
    for minutes, rid in ((10, 1), (20, 2), (30, 3)):
        q.push(job(minutes, rid))
    assert q.remove(2) is True
    assert q.remove(2) is False
    assert q.remove(99) is False
    assert len(q) == 2
    assert [q.pop(), q.pop()] == [job(10, 1), job(30, 3)]


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_repush_after_remove_replaces_the_old_entry(cls: type[PriorityQueue]) -> None:
    q = cls()
    q.push(job(10, 1))
    q.push(job(20, 2))
    assert q.remove(1) is True
    q.push(job(5, 1))
    assert len(q) == 2
    assert [q.pop(), q.pop()] == [job(5, 1), job(20, 2)]


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_push_same_id_replaces_the_live_entry(cls: type[PriorityQueue]) -> None:
    q = cls()
    q.push(job(50, 1))
    q.push(job(10, 1))
    assert len(q) == 1
    assert q.pop() == job(10, 1)
    assert len(q) == 0


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_large_random_matches_sorted(cls: type[PriorityQueue]) -> None:
    rng = random.Random(20261120)
    jobs = [job(rng.randrange(0, 100_000), i) for i in range(1000)]
    q = cls()
    for j in jobs:
        q.push(j)
    assert [q.pop() for _ in range(1000)] == sorted(jobs)


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
def test_naive_datetime_is_rejected(cls: type[PriorityQueue]) -> None:
    q = cls()
    with pytest.raises(ValueError):
        q.push(HeapJob(datetime(2026, 11, 21, 8, 0), 1))


@pytest.mark.parametrize("cls", QUEUE_CLASSES)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_interleaved_operations_match_a_reference_model(
    cls: type[PriorityQueue], seed: int
) -> None:
    """Operaciones mezcladas contra un modelo (dict de vivos).

    En cada paso se hace una operacion al azar (encolar, extraer,
    mirar o quitar) y se comprueba que la cola responde igual que
    el modelo: mismo minimo, misma longitud, mismo extraido.
    """
    rng = random.Random(seed)
    q = cls()
    live: dict[int, datetime] = {}
    next_id = 1
    for _ in range(300):
        op = rng.random()
        if op < 0.5 or not live:
            # Encolar: id nuevo o uno vivo con otra hora.
            if live and rng.random() < 0.3:
                rid = rng.choice(list(live))
            else:
                rid = next_id
                next_id += 1
            when = BASE + timedelta(minutes=rng.randrange(0, 5_000))
            q.push(HeapJob(when, rid))
            live[rid] = when
        elif op < 0.7:
            expected = (
                min(live.items(), key=lambda kv: (kv[1], kv[0]))
                if live
                else None
            )
            assert q.pop() == (
                HeapJob(expected[1], expected[0]) if expected else None
            )
            if expected:
                del live[expected[0]]
        elif op < 0.85:
            expected = (
                min(live.items(), key=lambda kv: (kv[1], kv[0]))
                if live
                else None
            )
            assert q.peek() == (
                HeapJob(expected[1], expected[0]) if expected else None
            )
        else:
            rid = rng.randrange(1, next_id + 1)
            assert q.remove(rid) == (rid in live)
            live.pop(rid, None)
        assert len(q) == len(live)
        assert bool(q) == bool(live)
    assert [q.pop() for _ in range(len(live))] == sorted(
        HeapJob(when, rid) for rid, when in live.items()
    )
