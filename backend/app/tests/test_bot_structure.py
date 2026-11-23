"""Pruebas de la estructura del bot de Telegram (Fase 6).

Estas pruebas no necesitan conexion a Telegram ni a PostgreSQL:

- Los handlers se prueban con objetos simulados (``AsyncMock``),
  nunca con la API real de Telegram.
- La aplicacion se construye con un token falso (``build`` no
  conecta a la red; el polling nunca se inicia en pruebas).
- Los handlers reales resuelven el usuario desde el chat_id
  (RF19): en estas pruebas la sesion vinculada se simula como
  ausente (chat sin vincular) y se comprueba que el handler no
  muestra ningun dato. Los flujos con datos reales viven en
  ``test_bot_telegram_flows.py`` (con la base de datos de pruebas).
- ``mock_data`` se conserva como modulo de datos ficticios de la
  demostracion, ya sin uso en los handlers; sus pruebas quedan
  como regresion del modulo.
- La separacion de responsabilidades se comprueba en un
  subproceso: importar el bot no debe cargar SQLAlchemy,
  asyncpg ni los modelos/servicios del backend.

Se ejecutan desde la carpeta ``backend/`` con::

    pytest app/tests/test_bot_structure.py
    pytest   # suite completa
"""

from __future__ import annotations

import subprocess
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

from app.bot import main as bot_main
from app.bot.config import BotConfig
from app.bot.handlers import (
    caregivers,
    help as help_handler,
    history,
    intake,
    link,
    medications,
    menu,
    reminders,
    settings,
    start,
    treatments,
)
from app.bot.keyboards import build_main_menu, with_home
from app.bot.services import mock_data
from app.scheduler.telegram_sender import reminder_keyboard

BACKEND_DIR = Path(__file__).resolve().parents[2]
FAKE_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


@asynccontextmanager
async def _unlinked_session(update):  # noqa: ARG001
    """Sesion vinculada simulada como ausente (chat sin vincular)."""
    yield None, None


def _patch_unlinked(monkeypatch: pytest.MonkeyPatch, module) -> None:
    """Sustituye linked_session en el modulo indicado (sin vincular)."""
    monkeypatch.setattr(module, "linked_session", _unlinked_session)


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------


def test_config_sin_token_no_puede_hacer_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin token, el bot esta en modo demostracion y no arranca."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    config = BotConfig.from_env()
    assert config.token == ""
    assert config.can_poll is False
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        config.require_token()


def test_config_con_token_no_lo_muestra_en_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """El token nunca aparece en repr() ni en logs accidentales."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_TOKEN)
    config = BotConfig.from_env()
    assert config.token == FAKE_TOKEN
    assert config.can_poll is True
    assert FAKE_TOKEN not in repr(config)
    assert config.require_token() == FAKE_TOKEN


def test_config_username_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin username en el entorno, usa DosisAlertaBot."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    assert BotConfig.from_env().username == "DosisAlertaBot"


def test_config_ignora_un_env_ajeno_en_el_directorio_de_trabajo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Un .env ajeno en el cwd no debe tapar la configuración.

    Regresión de la lección de la Fase 2: un .env ajeno por encima
    del proyecto en el árbol del directorio de trabajo. La búsqueda
    del .env parte del archivo del paquete, no del directorio de
    trabajo (corrección de la auditoría del bot, 2026-11-11).
    """
    decoy = tmp_path / ".env"
    decoy.write_text("TELEGRAM_BOT_TOKEN=<redacted>\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert BotConfig.from_env().token == ""


def test_main_sin_token_no_arranca(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() sin token falla con un mensaje claro (sin el valor)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN"):
        bot_main.main()


# ---------------------------------------------------------------------------
# Teclados
# ---------------------------------------------------------------------------


def test_menu_principal_tiene_las_7_opciones() -> None:
    """El menu principal muestra las 7 secciones aprobadas."""
    keyboard = build_main_menu()
    rows = keyboard.inline_keyboard
    assert len(rows) == 7
    labels = [row[0].text for row in rows]
    assert labels == [
        "💊 Mis medicamentos",
        "⏰ Próximas tomas",
        "🗂️ Mis tratamientos",
        "📋 Mi historial",
        "👨‍👩‍👧 Mi familiar o cuidador",
        "⚙️ Configuración",
        "🆘 Necesito ayuda",
    ]


def test_todos_los_callback_data_caben_en_64_bytes() -> None:
    """Ningun callback_data supera el limite de Telegram (64 bytes)."""
    keyboard = build_main_menu()
    for row in keyboard.inline_keyboard:
        for button in row:
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) <= 64
            assert button.text.strip() != ""


def test_with_home_anade_boton_de_inicio() -> None:
    """with_home anade exactamente un boton "🏠 Menú principal"."""
    keyboard = with_home([])
    rows = keyboard.inline_keyboard
    assert len(rows) == 1
    assert rows[0][0].callback_data == "menu:main"
    assert rows[0][0].text == "🏠 Menú principal"


def test_intake_keyboard_lleva_confirmar_y_posponer() -> None:
    """El teclado de una toma lleva YA LO TOMÉ y RECORDARME DESPUÉS."""
    keyboard = intake.intake_keyboard(42)
    rows = keyboard.inline_keyboard
    assert len(rows) == 2  # un boton por fila
    assert rows[0][0].text == "✅ YA LO TOMÉ"
    assert rows[0][0].callback_data == "intake:confirm:42"
    assert rows[1][0].text == "⏰ RECORDARME DESPUÉS"
    assert rows[1][0].callback_data == "intake:postpone:42"
    for row in rows:
        for button in row:
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_delay_keyboard_ofrece_15_30_60() -> None:
    """El selector de posposicion ofrece 15, 30 y 60 minutos."""
    keyboard = intake._delay_keyboard(7)
    datas = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
    ]
    assert "intake:delay:7:15" in datas
    assert "intake:delay:7:30" in datas
    assert "intake:delay:7:60" in datas
    assert "menu:reminders" in datas
    for data in datas:
        assert len(data.encode("utf-8")) <= 64


def test_sender_keyboard_usa_el_mismo_callback_que_intake() -> None:
    """El teclado del aviso usa el mismo callback que los handlers."""
    sender_keyboard = reminder_keyboard(99)
    intake_keyboard = intake.intake_keyboard(99)
    sender_datas = [
        button.callback_data
        for row in sender_keyboard.inline_keyboard
        for button in row
    ]
    intake_datas = [
        button.callback_data
        for row in intake_keyboard.inline_keyboard
        for button in row
    ]
    assert sender_datas == intake_datas


# ---------------------------------------------------------------------------
# Datos ficticios (modulo legacy, sin uso en los handlers)
# ---------------------------------------------------------------------------


def test_mock_data_no_esta_vacio_y_esta_marcado_como_demo() -> None:
    """Las listas ficticias tienen contenido y son claramente demo."""
    assert len(mock_data.list_medications()) >= 1
    assert len(mock_data.list_treatments()) >= 1
    assert len(mock_data.list_upcoming_intakes()) >= 1
    assert len(mock_data.list_history()) >= 1
    assert "demostración" in mock_data.DEMO_NOTICE
    for medication in mock_data.list_medications():
        assert medication.id.startswith("demo-")
    for treatment in mock_data.list_treatments():
        assert treatment.id.startswith("demo-")
    for intake in mock_data.list_upcoming_intakes():
        assert intake.id.startswith("demo-")


def test_mock_data_busqueda_por_id() -> None:
    """Buscar por id devuelve el registro o None, nunca una excepcion."""
    assert mock_data.get_medication("demo-med-1") is not None
    assert mock_data.get_medication("demo-med-1").name == "Amoxicilina"
    assert mock_data.get_medication("no-existe") is None
    assert mock_data.get_treatment("demo-treat-1") is not None
    assert mock_data.get_treatment("no-existe") is None


def test_proximas_tomas_ordenadas_por_hora() -> None:
    """Las proximas tomas salen ordenadas por hora."""
    times = [intake.time for intake in mock_data.list_upcoming_intakes()]
    assert times == sorted(times)


# ---------------------------------------------------------------------------
# Funciones puras de los handlers (sin base de datos)
# ---------------------------------------------------------------------------


def test_render_welcome_sin_aviso_de_demo() -> None:
    """La bienvenida ya no lleva el aviso de demostracion."""
    text, keyboard = start.render_welcome("Diomar")
    assert "DosisAlerta" in text
    assert "Diomar" in text
    assert "demostración" not in text
    assert len(keyboard.inline_keyboard) == 7


def test_render_help_explica_la_vinculacion() -> None:
    """La ayuda explica como vincular y no lleva aviso de demo."""
    text, keyboard = help_handler.render_help()
    assert "Necesito ayuda" in text
    assert "/vincular" in text
    assert "demostración" not in text
    assert keyboard.inline_keyboard[-1][0].callback_data == "menu:main"


def test_toggle_bits_gestionar_exige_ver() -> None:
    """Activar gestionar activa su lectura; quitar la lectura quita gestionar."""
    # Gestionar medicamentos (6) exige ver medicamentos (0).
    bits = caregivers._toggle_bits("00000000", 6)
    assert bits == "10000010"
    # Quitar ver medicamentos (0) quita gestionar medicamentos (6).
    bits = caregivers._toggle_bits("10000010", 0)
    assert bits == "00000000"
    # Gestionar horarios (7) exige ver horarios (2).
    bits = caregivers._toggle_bits("00000000", 7)
    assert bits == "00100001"


def test_caregiver_bits_a_permisos_y_vuelta() -> None:
    """La mascara de 8 bits se convierte a permisos y viceversa."""
    permissions = caregivers._bits_to_permissions("10100000")
    assert permissions.perm_view_medications is True
    assert permissions.perm_view_treatments is False
    assert permissions.perm_view_schedules is True
    link = SimpleNamespace(
        perm_view_medications=True,
        perm_view_treatments=False,
        perm_view_schedules=True,
        perm_view_upcoming=False,
        perm_view_history=False,
        perm_receive_notifications=False,
        perm_manage_medications=False,
        perm_manage_schedules=False,
    )
    assert caregivers._permissions_to_bits(link) == "10100000"


def test_when_text_hoy_y_manana() -> None:
    """La hora de una toma se muestra como Hoy/Mañana en la zona del usuario."""
    now = datetime.now(timezone.utc)
    assert reminders._when_text(now, "America/Bogota").startswith("Hoy, ")
    tomorrow = now + timedelta(days=1)
    assert reminders._when_text(tomorrow, "America/Bogota").startswith("Mañana, ")


def test_create_flow_tiene_5_pasos_y_textos() -> None:
    """La creacion guiada de medicamentos tiene sus 5 pasos con texto."""
    assert medications._CREATE_STEPS == (
        "name",
        "presentation",
        "concentration",
        "unit",
        "notes",
    )
    for step in medications._CREATE_STEPS:
        assert medications._CREATE_PROMPTS[step]
        assert medications._CREATE_LABELS[step]


# ---------------------------------------------------------------------------
# Handlers con objetos simulados: chat sin vincular (RF19)
# ---------------------------------------------------------------------------


def _message_update() -> tuple[MagicMock, AsyncMock]:
    update = MagicMock()
    update.message = AsyncMock()
    return update, update.message


def _callback_update(data: str) -> tuple[MagicMock, AsyncMock]:
    update = MagicMock()
    query = AsyncMock()
    query.data = data
    update.callback_query = query
    return update, query


async def test_start_sin_vincular_no_muestra_datos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un chat sin vincular no recibe la bienvenida ni el menu (RF19)."""
    _patch_unlinked(monkeypatch, start)
    update, message = _message_update()
    await start.start(update, MagicMock())
    message.reply_text.assert_not_awaited()


async def test_menu_sin_vincular_no_muestra_datos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El menu principal y el texto libre no muestran datos sin vincular."""
    _patch_unlinked(monkeypatch, menu)
    update, query = _callback_update("menu:main")
    await menu.show_main_menu(update, MagicMock())
    query.edit_message_text.assert_not_awaited()

    update, message = _message_update()
    context = MagicMock()
    context.user_data = {}
    await menu.handle_text(update, context)
    message.reply_text.assert_not_awaited()


async def test_callback_desconocido_sin_vincular_no_muestra_datos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un boton viejo en un chat sin vincular no muestra el menu."""
    _patch_unlinked(monkeypatch, menu)
    update, query = _callback_update("menu:algo-que-no-existe")
    await menu.unknown_callback(update, MagicMock())
    query.edit_message_text.assert_not_awaited()


async def test_secciones_sin_vincular_no_muestran_datos(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cada seccion, sin vincular, no edita el mensaje con datos (RF19)."""
    cases = [
        (medications, "menu:medications", medications.show_medications),
        (reminders, "menu:reminders", reminders.show_upcoming),
        (history, "menu:history", history.show_history),
        (caregivers, "menu:caregivers", caregivers.show_caregivers),
        (settings, "menu:settings", settings.show_settings),
        (help_handler, "menu:help", help_handler.show_help),
    ]
    for module, data, handler in cases:
        _patch_unlinked(monkeypatch, module)
        update, query = _callback_update(data)
        await handler(update, MagicMock())
        query.edit_message_text.assert_not_awaited()


async def test_create_text_avanza_sin_base_de_datos() -> None:
    """El flujo de creacion avanza por texto sin tocar la base de datos."""
    update, message = _message_update()
    update.message.text = "Amoxicilina"
    context = MagicMock()
    context.user_data = {"med_create": {"step": "name", "data": {}}}
    assert await medications.handle_create_text(update, context) is True
    assert context.user_data["med_create"]["step"] == "presentation"
    message.reply_text.assert_awaited_once()
    text = message.reply_text.await_args.args[0]
    assert "Presentación" in text


async def test_create_text_sin_flujo_no_consume_el_mensaje() -> None:
    """Sin flujo activo, el texto libre no pertenece a la creacion."""
    update, message = _message_update()
    update.message.text = "hola"
    context = MagicMock()
    context.user_data = {}
    assert await medications.handle_create_text(update, context) is False
    message.reply_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Registro de handlers y construccion de la aplicacion (sin red)
# ---------------------------------------------------------------------------


def test_build_application_registra_todos_los_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    """La aplicacion se construye sin token real ni conexion.

    Se limpian las variables de proxy del entorno de pruebas:
    python-telegram-bot las lee al construir su cliente HTTP y
    un proxy mal formado (o innecesario aqui) no debe romper
    una prueba que nunca toca la red. Ojo: tambien hay que
    limpiar NO_PROXY/no_proxy, porque su lista incluye literales
    IPv6 entre corchetes que httpx no sabe interpretar como
    patrones de URL.
    """
    for var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ):
        monkeypatch.delenv(var, raising=False)
    config = BotConfig(token=FAKE_TOKEN)
    application = bot_main.build_application(config)
    handlers = application.handlers[0]
    command_handlers = [h for h in handlers if isinstance(h, CommandHandler)]
    callback_handlers = [h for h in handlers if isinstance(h, CallbackQueryHandler)]
    message_handlers = [h for h in handlers if isinstance(h, MessageHandler)]
    assert len(command_handlers) == 7  # /start /help /vincular /vincular_cuidador /medicamentos /proximas /historial
    assert len(callback_handlers) == 29  # menu + secciones + acciones + generico
    assert len(message_handlers) == 1  # texto libre -> flujo o menu
    patterns = [str(getattr(h, "pattern", "")) for h in callback_handlers]
    for expected in (
        "menu:main",
        "menu:medications",
        "menu:reminders",
        "menu:history",
        "menu:caregivers",
        "menu:settings",
        "intake:confirm:",
        "intake:postpone:",
        "intake:delay:",
        "med:create",
        "med:deactivate:",
        "treat:(pause|cancel|complete):",
        "treat:(pause|resume|cancel|complete)_confirm:",
        "cg:toggle:",
        "cg:accept_confirm:",
        "cg:revoke:",
        "tz:set:",
    ):
        assert any(expected in pattern for pattern in patterns), expected
    commands = sorted(next(iter(h.commands)) for h in command_handlers)
    assert commands == [
        "help",
        "historial",
        "medicamentos",
        "proximas",
        "start",
        "vincular",
        "vincular_cuidador",
    ]


# ---------------------------------------------------------------------------
# Separacion de responsabilidades (sin PostgreSQL)
# ---------------------------------------------------------------------------


def test_importar_el_bot_no_carga_base_de_datos_ni_servicios() -> None:
    """Importar el bot no debe cargar SQLAlchemy ni capas de datos.

    Se comprueba en un subproceso limpio para que el resultado no
    dependa del orden en que pytest ejecute los demas archivos.
    """
    code = (
        "import app.bot.main, app.bot.config, app.bot.handlers, "
        "app.bot.keyboards, app.bot.services.mock_data\n"
        "import sys\n"
        "forbidden = [m for m in sys.modules if m.split('.')[0] in "
        "{'sqlalchemy', 'asyncpg', 'psycopg'} or m.startswith(("
        "'app.models', 'app.database', 'app.services', "
        "'app.repositories', 'app.scheduler'))]\n"
        "assert not forbidden, forbidden\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
