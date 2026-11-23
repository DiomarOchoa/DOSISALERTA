"""Comandos de vinculacion (Fase 6, RF15 y RF20).

- ``/vincular CODIGO``: vincula la propia cuenta de Telegram del
  paciente con el codigo generado en la web (15 minutos, un solo
  uso). El servicio valida el codigo, la expiracion y el limite
  de intentos; cualquier fallo devuelve el mismo mensaje generico.
- ``/vincular_cuidador CODIGO``: el cuidador presenta el codigo
  de invitacion del paciente. El cuidador debe tener su propia
  cuenta vinculada primero (su chat resuelve a su usuario). El
  vinculo queda INVITADO: falta la aceptacion explicita del
  paciente con los permisos (web o bot).

Los dos comandos exigen un codigo como argumento; sin el, el bot
explica como conseguirlo. Ninguno revela si un codigo existe.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.bot.context import _chat_id_of, _telegram_user_of, linked_session
from app.bot.keyboards import build_main_menu

_GENERIC_CODE_ERROR = (
    "Código no válido o expirado. Pide un código nuevo en la web "
    "e inténtalo de nuevo."
)


async def handle_vincular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Vincula la cuenta con el codigo de la web (/vincular CODIGO)."""
    if update.message is None:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Para vincular tu cuenta, envíame el código así:\n\n"
            "/vincular CÓDIGO\n\n"
            "El código lo generas en la web de DosisAlerta, en tu Perfil, "
            "pulsando «Vincular Telegram». Caduca en 15 minutos."
        )
        return
    code = args[0]
    chat_id = _chat_id_of(update)
    telegram_user_id, username = _telegram_user_of(update)
    if chat_id is None or telegram_user_id is None:
        return
    # Import perezoso: no cargar servicios al importar el bot. La
    # vinculacion no exige un vinculo previo (es el paso que lo
    # crea), asi que abre su propia sesion.
    from app.database import AsyncSessionLocal
    from app.services import telegram_link_service

    async with AsyncSessionLocal() as session:
        try:
            await telegram_link_service.confirm_link(
                session, code, telegram_user_id, chat_id, username
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 404:
                await update.message.reply_text(_GENERIC_CODE_ERROR)
            else:
                await update.message.reply_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        text = (
            "✅ ¡Cuenta vinculada!\n\n"
            "Ya puedes usar DosisAlerta desde Telegram. "
            "Te avisaré aquí cuando sea la hora de tus medicamentos.\n\n"
            "👇 Elige una opción:"
        )
        await update.message.reply_text(text, reply_markup=build_main_menu())


async def handle_vincular_cuidador(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """El cuidador presenta el codigo de invitacion (/vincular_cuidador CODIGO)."""
    if update.message is None:
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Para vincularte como cuidador, envíame el código así:\n\n"
            "/vincular_cuidador CÓDIGO\n\n"
            "El código te lo da el paciente (lo genera en la web, en "
            "«Mi familiar o cuidador»). Caduca en 15 minutos. Primero "
            "vincula tu propia cuenta con /vincular si aún no lo has hecho."
        )
        return
    code = args[0]
    chat_id = _chat_id_of(update)
    telegram_user_id, _username = _telegram_user_of(update)
    if chat_id is None or telegram_user_id is None:
        return
    from app.schemas.caregivers import AcceptCodeRequest
    from app.services import caregiver_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            link = await caregiver_service.accept_code(
                session,
                user,
                AcceptCodeRequest(code=code),
                chat_id=chat_id,
                telegram_user_id=telegram_user_id,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 404:
                await update.message.reply_text(_GENERIC_CODE_ERROR)
            else:
                await update.message.reply_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        patient_name = link.patient_name or "el paciente"
        await update.message.reply_text(
            "✅ Código aceptado.\n\n"
            f"Quedaste vinculado como cuidador de {patient_name}. "
            "El paciente debe aceptar tu invitación y elegir qué puedes "
            "ver y hacer; hasta entonces no puedes consultar sus datos."
        )
