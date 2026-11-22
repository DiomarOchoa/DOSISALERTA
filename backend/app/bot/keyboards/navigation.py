"""Botones de navegacion comunes a todas las pantallas.

Regla de la especificacion (§1.5): toda pantalla que no sea el
menu principal lleva un boton "🏠 Menú principal". Nunca hay
callejones sin salida: el usuario siempre puede volver al menu
sin escribir ningun comando.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

HOME_BUTTON_TEXT = "🏠 Menú principal"
HOME_CALLBACK_DATA = "menu:main"


def home_button() -> InlineKeyboardButton:
    """Boton para volver al menu principal."""
    return InlineKeyboardButton(HOME_BUTTON_TEXT, callback_data=HOME_CALLBACK_DATA)


def with_home(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Añade el boton de inicio al final de un teclado."""
    return InlineKeyboardMarkup([*rows, [home_button()]])
