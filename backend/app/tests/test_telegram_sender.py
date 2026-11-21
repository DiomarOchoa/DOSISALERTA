"""Pruebas unitarias del sender real de Telegram (Fase 5, Etapa 3).

Con un Bot falso (un doble que registra las llamadas y devuelve
un mensaje falso o lanza el error configurado): sin trafico real
a Telegram. El token real sigue siendo un marcador; aqui solo se
usa un valor ficticio para probar ``from_config``.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from telegram import Bot
from telegram.error import (
    BadRequest,
    Forbidden,
    NetworkError,
    RetryAfter,
    TimedOut,
)

from app.scheduler.sender import SendPayload
from app.scheduler.telegram_sender import (
    TelegramSender,
    build_reminder_text,
    day_label,
)

CHAT_ID = 123456789
NOW = datetime(2026, 11, 21, 8, 0, tzinfo=timezone.utc)


def _payload(**overrides) -> SendPayload:
    data = {
        "reminder_id": 1,
        "user_id": 2,
        "chat_id": CHAT_ID,
        "text": "🔔 Es hora de su medicamento",
        "scheduled_at": NOW,
    }
    data.update(overrides)
    return SendPayload(**data)


class FakeMessage:
    def __init__(self, message_id: int | None):
        self.message_id = message_id


class FakeBot:
    """Doble de telegram.Bot: registra llamadas y actua segun el guion."""

    def __init__(self, behavior: str = "ok", message_id: int = 101, retry_after: int = 120):
        self.calls: list[dict] = []
        self.behavior = behavior
        self.message_id = message_id
        self.retry_after = retry_after

    async def send_message(self, *, chat_id, text, **kwargs):
        self.calls.append({"chat_id": chat_id, "text": text})
        if self.behavior == "ok":
            return FakeMessage(self.message_id)
        if self.behavior == "bad_request":
            raise BadRequest("Bad Request: chat not found")
        if self.behavior == "forbidden":
            raise Forbidden("Forbidden: bot was blocked by the user")
        if self.behavior == "timeout":
            raise TimedOut("Timed out")
        if self.behavior == "network":
            raise NetworkError("Network error")
        if self.behavior == "retry_after":
            raise RetryAfter(self.retry_after)
        if self.behavior == "no_id":
            return FakeMessage(None)
        raise AssertionError(f"comportamiento desconocido: {self.behavior}")


async def test_success_returns_message_id() -> None:
    bot = FakeBot()
    sender = TelegramSender(bot)
    result = await sender.send(_payload())
    assert result.ok is True
    assert result.telegram_message_id == 101
    assert result.kind == "ok"
    assert bot.calls == [
        {"chat_id": CHAT_ID, "text": "🔔 Es hora de su medicamento"}
    ]


async def test_bad_request_is_a_clear_failure() -> None:
    sender = TelegramSender(FakeBot("bad_request"))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "clear"
    assert result.telegram_message_id is None
    assert "BadRequest" in (result.error or "")


async def test_forbidden_is_a_clear_failure() -> None:
    sender = TelegramSender(FakeBot("forbidden"))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "clear"
    assert "Forbidden" in (result.error or "")


async def test_timeout_is_ambiguous() -> None:
    sender = TelegramSender(FakeBot("timeout"))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "ambiguous"
    assert result.telegram_message_id is None


async def test_network_error_is_ambiguous() -> None:
    sender = TelegramSender(FakeBot("network"))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "ambiguous"


async def test_retry_after_is_rate_limited_with_exact_seconds() -> None:
    sender = TelegramSender(FakeBot("retry_after", retry_after=120))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "rate_limited"
    assert result.retry_after_seconds == 120


async def test_retry_after_has_no_cap() -> None:
    sender = TelegramSender(FakeBot("retry_after", retry_after=3600))
    result = await sender.send(_payload())
    assert result.kind == "rate_limited"
    assert result.retry_after_seconds == 3600


async def test_missing_message_id_is_ambiguous() -> None:
    # Sin message_id no hay confirmacion que registrar.
    sender = TelegramSender(FakeBot("no_id"))
    result = await sender.send(_payload())
    assert result.ok is False
    assert result.kind == "ambiguous"
    assert result.telegram_message_id is None


def test_build_reminder_text_contains_the_required_parts() -> None:
    # Fechas relativas a hoy (Bogota): la dosis es hoy a las 08:00.
    today = datetime.now(ZoneInfo("America/Bogota")).date()
    scheduled = datetime.combine(
        today, time(13, 0), tzinfo=timezone.utc
    )  # 13:00 UTC = 08:00 Bogota
    text = build_reminder_text(
        medication_name="Amoxicilina",
        dose_amount=Decimal("1"),
        dose_unit="cápsula",
        concentration="500 mg",
        treatment_title="Infección respiratoria",
        scheduled_at=scheduled,
        user_timezone="America/Bogota",
    )
    assert "Amoxicilina 500 mg — 1 cápsula" in text
    assert "Infección respiratoria" in text
    assert "Hoy, 08:00" in text
    assert "YA LO TOMÉ" not in text
    assert "RECORDARME" not in text


def test_build_reminder_text_without_concentration() -> None:
    # La dosis es mañana a las 08:00 (Bogota).
    today = datetime.now(ZoneInfo("America/Bogota")).date()
    tomorrow = today.fromordinal(today.toordinal() + 1)
    scheduled = datetime.combine(
        tomorrow, time(13, 0), tzinfo=timezone.utc
    )  # 13:00 UTC = 08:00 Bogota
    text = build_reminder_text(
        medication_name="Paracetamol",
        dose_amount=Decimal("500"),
        dose_unit="mg",
        concentration=None,
        treatment_title="Dolor",
        scheduled_at=scheduled,
        user_timezone="America/Bogota",
    )
    assert "Paracetamol 500 mg" in text
    assert "Mañana, 08:00" in text


def test_day_label() -> None:
    from datetime import date

    assert day_label(date(2026, 11, 21), date(2026, 11, 21)) == "Hoy"
    assert day_label(date(2026, 11, 22), date(2026, 11, 21)) == "Mañana"
    assert day_label(date(2026, 11, 25), date(2026, 11, 21)) == "25/11/2026"


def test_from_config_builds_a_real_bot_without_network(monkeypatch) -> None:
    # Token ficticio solo para la prueba; construir el Bot no toca la red.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-test-token-123")
    sender = TelegramSender.from_config()
    assert isinstance(sender._bot, Bot)


def test_from_config_without_token_raises(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(RuntimeError):
        TelegramSender.from_config()
