"""Teclado principal del bot (menu por botones).

Las 7 opciones del menu conceptual aprobado
(``docs/ESPECIFICACION_BOT_TELEGRAM.md`` §2):

1. Mis medicamentos.
2. Próximas tomas.
3. Mis tratamientos.
4. Mi historial.
5. Mi familiar o cuidador.
6. Configuración.
7. Necesito ayuda.

Cada opcion es un boton en linea (``InlineKeyboardButton``) con
un ``callback_data`` corto (siempre por debajo del limite de
64 bytes de Telegram): solo lleva la seccion, nunca datos
sensibles ni identificadores de usuario.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MAIN_MENU_OPTIONS: tuple[tuple[str, str], ...] = (
    ("💊 Mis medicamentos", "menu:medications"),
    ("⏰ Próximas tomas", "menu:reminders"),
    ("🗂️ Mis tratamientos", "menu:treatments"),
    ("📋 Mi historial", "menu:history"),
    ("👨‍👩‍👧 Mi familiar o cuidador", "menu:caregivers"),
    ("⚙️ Configuración", "menu:settings"),
    ("🆘 Necesito ayuda", "menu:help"),
)


def build_main_menu() -> InlineKeyboardMarkup:
    """Construye el teclado del menu principal (7 opciones)."""
    rows = [[InlineKeyboardButton(text, callback_data=data)] for text, data in MAIN_MENU_OPTIONS]
    return InlineKeyboardMarkup(rows)
