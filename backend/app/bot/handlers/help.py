"""Seccion "Necesito ayuda" y comando /help (Fase 6).

Ayuda de uso del bot, en lenguaje sencillo. No es soporte
medico: nunca da consejos de salud, solo explica como usar
el bot. Solo para chats vinculados (RF19): un chat sin vincular
recibe las instrucciones de vinculacion.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

HELP_TEXT = (
    "🆘 Necesito ayuda\n\n"
    "Soy DosisAlerta, tu ayudante de medicamentos.\n\n"
    "• Usa los botones para moverte, no hace falta escribir.\n"
    "• En «Próximas tomas» verás tus medicamentos de hoy y mañana, "
    "y podrás confirmar cada toma o posponerla.\n"
    "• En «Mi historial» verás las tomas que ya registraste.\n"
    "• En «Mi familiar o cuidador» puedes invitar a un cuidador y "
    "elegir qué puede ver.\n"
    "• Para crear un medicamento nuevo, usa «Mis medicamentos» y "
    "luego «➕ Nuevo medicamento». Los tratamientos se crean desde "
    "la web de DosisAlerta.\n"
    "• Si cambias de zona horaria, usa «Configuración».\n\n"
    "Para vincular otra cuenta de Telegram, genera un código nuevo "
    "en la web (Perfil → Vincular Telegram) y envíame: "
    "/vincular CÓDIGO\n\n"
    "No doy consejos de salud. Si te sientes mal, contacta con "
    "tu médico o con tu cuidador."
)


def render_help() -> tuple[str, object]:
    """Texto de ayuda y teclado con el boton de inicio."""
    return HELP_TEXT, with_home([])


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la ayuda (boton del menu)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_help()
        await query.edit_message_text(text, reply_markup=keyboard)


async def show_help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la ayuda con el comando /help."""
    if update.message is None:
        return
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        text, keyboard = render_help()
        await update.message.reply_text(text, reply_markup=keyboard)
