"""Pruebas puras de la politica de reintentos (Fase 5, Etapa 3).

Sin base de datos: la politica decide a partir de la cuenta de
intentos y del resultado del envio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.scheduler.retry_policy import (
    AMBIGUOUS_DELAY,
    CLEAR_FAILURE_DELAYS,
    decide,
)
from app.scheduler.sender import SendResult

NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def _ok(message_id: int = 101) -> SendResult:
    return SendResult(ok=True, kind="ok", telegram_message_id=message_id)


def _clear() -> SendResult:
    return SendResult(ok=False, kind="clear", error="BadRequest: chat not found")


def _ambiguous() -> SendResult:
    return SendResult(ok=False, kind="ambiguous", error="TimedOut: Timed out")


def _rate_limited(seconds: int) -> SendResult:
    return SendResult(
        ok=False,
        kind="rate_limited",
        retry_after_seconds=seconds,
        error=f"RetryAfter: {seconds}s",
    )


def test_success_marks_sent() -> None:
    decision = decide(_ok(), attempt_count=1, now=NOW)
    assert decision.action == "sent"
    assert decision.next_attempt_at is None


def test_clear_failure_backoff_first_attempt() -> None:
    decision = decide(_clear(), attempt_count=1, now=NOW)
    assert decision.action == "retry"
    assert decision.next_attempt_at == NOW + CLEAR_FAILURE_DELAYS[0]
    assert decision.next_attempt_at == NOW + timedelta(minutes=1)


def test_clear_failure_backoff_second_attempt() -> None:
    decision = decide(_clear(), attempt_count=2, now=NOW)
    assert decision.action == "retry"
    assert decision.next_attempt_at == NOW + timedelta(minutes=5)


def test_clear_failure_third_attempt_is_terminal() -> None:
    decision = decide(_clear(), attempt_count=3, now=NOW)
    assert decision.action == "failed"
    assert decision.next_attempt_at is None


def test_ambiguous_retries_after_ten_minutes() -> None:
    decision = decide(_ambiguous(), attempt_count=1, now=NOW)
    assert decision.action == "retry"
    assert decision.next_attempt_at == NOW + AMBIGUOUS_DELAY
    assert decision.next_attempt_at == NOW + timedelta(minutes=10)


def test_ambiguous_third_attempt_is_terminal() -> None:
    decision = decide(_ambiguous(), attempt_count=3, now=NOW)
    assert decision.action == "failed"
    assert decision.next_attempt_at is None


def test_rate_limited_respects_retry_after_exactly() -> None:
    decision = decide(_rate_limited(120), attempt_count=1, now=NOW)
    assert decision.action == "retry"
    assert decision.next_attempt_at == NOW + timedelta(seconds=120)


def test_rate_limited_has_no_cap() -> None:
    # Ajuste aprobado: se respeta el retry_after aunque sea grande.
    decision = decide(_rate_limited(3600), attempt_count=1, now=NOW)
    assert decision.action == "retry"
    assert decision.next_attempt_at == NOW + timedelta(seconds=3600)


def test_rate_limited_third_attempt_is_terminal() -> None:
    decision = decide(_rate_limited(120), attempt_count=3, now=NOW)
    assert decision.action == "failed"


def test_custom_delays_are_used() -> None:
    decision = decide(
        _clear(),
        attempt_count=1,
        now=NOW,
        clear_delays=(timedelta(seconds=2), timedelta(seconds=3)),
        ambiguous_delay=timedelta(seconds=4),
    )
    assert decision.next_attempt_at == NOW + timedelta(seconds=2)
    decision = decide(
        _ambiguous(),
        attempt_count=1,
        now=NOW,
        clear_delays=(timedelta(seconds=2), timedelta(seconds=3)),
        ambiguous_delay=timedelta(seconds=4),
    )
    assert decision.next_attempt_at == NOW + timedelta(seconds=4)
