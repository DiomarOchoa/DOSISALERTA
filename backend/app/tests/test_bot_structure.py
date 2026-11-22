"""Pruebas de la estructura del bot de Telegram (demostracion).

Estas pruebas no necesitan conexion a Telegram ni a PostgreSQL:

- Los handlers se prueban con objetos simulados (``AsyncMock``),
  nunca con la API real de Telegram.
- La aplicacion se construye con un token falso (``build`` no
  conecta a la red; el polling nunca se inicia en pruebas).
- Los datos son los ficticios de ``mock_data``.
- La separacion de responsabilidades se comprueba en un
  subproceso: importar el bot no debe cargar SQLAlchemy,
  asyncpg ni los modelos/servicios del backend.

Se ejecutan desde la carpeta ``backend/`` con::

    pytest app/tests/test_bot_structure.py
    pytest   # suite completa (Fase 1 + Fase 2 + bot)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler

from app.bot import main as bot_main
from app.bot.config import BotConfig
from app.bot.handlers import (
    caregivers,
    help as help_handler,
    history,
    medications,
    menu,
    reminders,
    settings,
    start,
    treatments,
)
from app.bot.keyboards import build_main_menu, with_home
from app.bot.services import mock_data

BACKEND_DIR = Path(__file__).resolve().parents[2]
FAKE_TOKEN = "123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"


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
    decoy.write_text("TELEGRAM_BOT_TOKEN=token-falso-del-decoy\n", encoding="utf-8")
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


def test_todas_las_pantallas_tienen_boton_de_inicio() -> None:
    """Cada pantalla que no es el menu lleva "🏠 Menú principal"."""
    keyboards = [
        with_home([]),
        medications.render_medications()[1],
        treatments.render_treatments()[1],
        reminders.render_upcoming()[1],
        history.render_history()[1],
        caregivers.render_caregivers()[1],
        settings.render_settings()[1],
        help_handler.render_help()[1],
    ]
    for keyboard in keyboards:
        home_buttons = [
            button
            for row in keyboard.inline_keyboard
            for button in row
            if button.callback_data == "menu:main"
        ]
        assert len(home_buttons) == 1
        assert home_buttons[0].text == "🏠 Menú principal"


# ---------------------------------------------------------------------------
# Datos ficticios
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
# Handlers con objetos simulados (sin Telegram real)
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


async def test_start_muestra_bienvenida_y_menu() -> None:
    """El comando /start responde con la bienvenida y el menu."""
    update, message = _message_update()
    await start.start(update, MagicMock())
    message.reply_text.assert_awaited_once()
    text = message.reply_text.await_args.args[0]
    keyboard = message.reply_text.await_args.kwargs["reply_markup"]
    assert "DosisAlerta" in text
    assert "demostración" in text
    assert len(keyboard.inline_keyboard) == 7


async def test_menu_principal_desde_callback() -> None:
    """El boton de inicio vuelve al menu principal."""
    update, query = _callback_update("menu:main")
    await menu.show_main_menu(update, MagicMock())
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "Menú principal" in text


async def test_texto_libre_muestra_el_menu() -> None:
    """Escribir texto (sin comando) tambien abre el menu."""
    update, message = _message_update()
    await menu.handle_text(update, MagicMock())
    message.reply_text.assert_awaited_once()
    text = message.reply_text.await_args.args[0]
    assert "Menú principal" in text


async def test_callback_desconocido_no_rompe_el_bot() -> None:
    """Un boton viejo responde con el menu, sin errores tecnicos."""
    update, query = _callback_update("menu:algo-que-no-existe")
    await menu.unknown_callback(update, MagicMock())
    query.answer.assert_awaited_once()
    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args.args[0]
    assert "Menú principal" in text


async def test_medicamentos_muestra_lista_y_detalle() -> None:
    """La lista de medicamentos y su detalle llevan aviso de demo."""
    update, query = _callback_update("menu:medications")
    await medications.show_medications(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    assert "Mis medicamentos" in text
    assert "Amoxicilina" in text
    assert "demostración" in text

    update, query = _callback_update("med:demo-med-1")
    await medications.show_medication_detail(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    assert "Amoxicilina 500 mg" in text


async def test_medicamento_inexistente_responde_sin_error() -> None:
    """Un id inventado responde un mensaje amable, no una excepcion."""
    update, query = _callback_update("med:no-existe")
    await medications.show_medication_detail(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    assert "No encontré ese medicamento" in text


async def test_tratamientos_muestra_lista_y_detalle() -> None:
    """La lista de tratamientos y su detalle llevan aviso de demo."""
    update, query = _callback_update("menu:treatments")
    await treatments.show_treatments(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    assert "Mis tratamientos" in text
    assert "ACTIVO" in text

    update, query = _callback_update("treat:demo-treat-1")
    await treatments.show_treatment_detail(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    assert "Infección respiratoria" in text


async def test_proximas_tomas_sin_botones_de_registro() -> None:
    """Las proximas tomas NO llevan botones que registren nada.

    YA LO TOMÉ y RECORDARME DESPUÉS pertenecen a la experiencia
    futura de recordatorios: en la demostracion solo se explican,
    nunca se simula un registro real.
    """
    update, query = _callback_update("menu:reminders")
    await reminders.show_upcoming(update, MagicMock())
    text = query.edit_message_text.await_args.args[0]
    keyboard = query.edit_message_text.await_args.kwargs["reply_markup"]
    assert "Próximas tomas" in text
    assert "08:00" in text
    assert "YA LO TOMÉ" in text  # solo como explicacion, no como boton
    callback_datas = [
        button.callback_data
        for row in keyboard.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert callback_datas == ["menu:main"]
    assert not any("confirm" in data or "postpone" in data for data in callback_datas)


async def test_historial_cuidador_configuracion_y_ayuda() -> None:
    """Cada seccion responde con su contenido y el aviso de demo."""
    cases = [
        ("menu:history", history.show_history, "Mi historial"),
        ("menu:caregivers", caregivers.show_caregivers, "Mi familiar o cuidador"),
        ("menu:settings", settings.show_settings, "Configuración"),
        ("menu:help", help_handler.show_help, "Necesito ayuda"),
    ]
    for data, handler, expected in cases:
        update, query = _callback_update(data)
        await handler(update, MagicMock())
        text = query.edit_message_text.await_args.args[0]
        assert expected in text
        assert "demostración" in text


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
    assert len(command_handlers) == 2  # /start y /help
    assert len(callback_handlers) >= 10  # 7 secciones + detalle x2 + generico
    assert len(message_handlers) == 1  # texto libre -> menu
    patterns = [str(getattr(h, "pattern", "")) for h in callback_handlers]
    for expected in ("menu:main", "menu:medications", "menu:reminders", "menu:history"):
        assert any(expected in pattern for pattern in patterns)


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
