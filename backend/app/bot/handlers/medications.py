"""Seccion "Mis medicamentos" (Fase 6, RF16/RF18).

Muestra la lista real de medicamentos del usuario y el detalle
de cada uno, con el mismo servicio y validaciones que la web
(RF18). Acciones:

- "Ver" (detalle con presentacion, concentracion, unidad y notas).
- "Desactivar" (con confirmacion; cancela sus futuros
  recordatorios PENDIENTE, conserva el historial).
- "➕ Nuevo medicamento" (creacion guiada por pasos: nombre,
  presentacion, concentracion, unidad, notas y confirmacion).

La creacion guiada guarda su estado en `context.user_data`
(`med_create`): `menu.handle_text` deriva el texto libre a
`handle_create_text` mientras el flujo esta activo. Enviar
"—" deja un campo opcional vacio; /cancelar abandona el flujo.
"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.context import linked_session
from app.bot.keyboards import with_home

_CREATE_STEPS = ("name", "presentation", "concentration", "unit", "notes")
_CREATE_PROMPTS = {
    "name": "¿Cómo se llama el medicamento?",
    "presentation": "¿Presentación? (por ejemplo: cápsulas, tabletas, jarabe)\n\nEnvía — si no quieres indicarla.",
    "concentration": "¿Concentración? (por ejemplo: 500 mg)\n\nEnvía — si no quieres indicarla.",
    "unit": "¿Unidad? (por ejemplo: cápsula, tableta)\n\nEnvía — si no quieres indicarla.",
    "notes": "¿Alguna nota? (por ejemplo: tomar con comida)\n\nEnvía — si no quieres añadir notas.",
}
_CREATE_LABELS = {
    "name": "Nombre",
    "presentation": "Presentación",
    "concentration": "Concentración",
    "unit": "Unidad",
    "notes": "Notas",
}
_SKIP = "—"


def _med_line(med) -> str:
    """Una linea de la lista: nombre + concentracion."""
    line = f"• {med.name}"
    if med.concentration:
        line += f" {med.concentration}"
    return line


def _detail_text(med) -> str:
    """Detalle de un medicamento."""
    lines = [f"💊 {med.name}", ""]
    if med.presentation:
        lines.append(f"Presentación: {med.presentation}")
    if med.concentration:
        lines.append(f"Concentración: {med.concentration}")
    if med.unit:
        lines.append(f"Unidad: {med.unit}")
    if med.notes:
        lines.append(f"Notas: {med.notes}")
    lines.append(f"Estado: {'Activo' if med.is_active else 'Inactivo'}")
    return "\n".join(lines)


async def show_medications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Lista real de medicamentos (boton del menu o /medicamentos)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    from app.services import medication_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        meds = await medication_service.list_medications(session, user, is_active=True)
        lines = ["💊 Mis medicamentos", ""]
        rows: list[list[InlineKeyboardButton]] = []
        for med in meds:
            lines.append(_med_line(med))
            rows.append(
                [
                    InlineKeyboardButton(
                        f"Ver {med.name}", callback_data=f"med:{med.id}"
                    )
                ]
            )
        if not meds:
            lines.append("No tienes medicamentos activos.")
        rows.append(
            [
                InlineKeyboardButton(
                    "➕ Nuevo medicamento", callback_data="med:create"
                )
            ]
        )
        text = "\n".join(lines)
        keyboard = with_home(rows)
        if query is not None:
            await query.edit_message_text(text, reply_markup=keyboard)
        elif update.message is not None:
            await update.message.reply_text(text, reply_markup=keyboard)


async def show_medication_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Detalle real de un medicamento (boton Ver)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("med:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese medicamento.")
        return
    medication_id = int(rest)
    from app.services import medication_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            med = await medication_service.get_medication(
                session, user, medication_id
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (404, 403):
                await query.edit_message_text("No encontré ese medicamento.")
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        rows: list[list[InlineKeyboardButton]] = []
        if med.is_active:
            rows.append(
                [
                    InlineKeyboardButton(
                        "🚫 Desactivar",
                        callback_data=f"med:deactivate:{med.id}",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Mis medicamentos", callback_data="menu:medications"
                )
            ]
        )
        await query.edit_message_text(
            _detail_text(med), reply_markup=with_home(rows)
        )


async def ask_deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pide confirmacion antes de desactivar (boton Desactivar)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("med:deactivate:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese medicamento.")
        return
    medication_id = int(rest)
    from app.services import medication_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            med = await medication_service.get_medication(
                session, user, medication_id
            )
        except Exception:
            await query.edit_message_text("No encontré ese medicamento.")
            return
        rows = [
            [
                InlineKeyboardButton(
                    "✅ Sí, desactivar",
                    callback_data=f"med:deactivate_confirm:{med.id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar", callback_data=f"med:{med.id}"
                )
            ],
        ]
        await query.edit_message_text(
            "¿Desactivar "
            f"«{med.name}»?\n\n"
            "Sus próximos recordatorios se cancelarán. "
            "El historial no se borra y podrás reactivarlo desde la web.",
            reply_markup=InlineKeyboardMarkup(rows),
        )


async def confirm_deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Desactiva el medicamento (confirmacion)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    rest = data.removeprefix("med:deactivate_confirm:")
    if not rest.isdigit():
        await query.edit_message_text("No encontré ese medicamento.")
        return
    medication_id = int(rest)
    from app.services import medication_service

    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            med = await medication_service.deactivate_medication(
                session, user, medication_id
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (404, 403):
                await query.edit_message_text("No encontré ese medicamento.")
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        await query.edit_message_text(
            f"✅ «{med.name}» desactivado.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis medicamentos",
                            callback_data="menu:medications",
                        )
                    ]
                ]
            ),
        )


# ------------------------------------------------------------------
# Creacion guiada
# ------------------------------------------------------------------


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancelar", callback_data="med:create_cancel")]]
    )


async def start_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Inicia la creacion guiada (boton Nuevo medicamento)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    context.user_data["med_create"] = {"step": "name", "data": {}}
    await query.edit_message_text(
        "➕ Nuevo medicamento\n\n" + _CREATE_PROMPTS["name"],
        reply_markup=_cancel_keyboard(),
    )


async def cancel_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Abandona la creacion guiada (boton Cancelar)."""
    query = update.callback_query
    if query is not None:
        await query.answer()
    context.user_data.pop("med_create", None)
    text = "Creación cancelada. No se guardó nada."
    keyboard = with_home(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Mis medicamentos", callback_data="menu:medications"
                )
            ]
        ]
    )
    if query is not None:
        await query.edit_message_text(text, reply_markup=keyboard)
    elif update.message is not None:
        await update.message.reply_text(text, reply_markup=keyboard)


async def handle_create_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Avanza un paso de la creacion guiada con el texto libre.

    Devuelve True si el texto pertenecia al flujo (y se consumo).
    """
    flow = context.user_data.get("med_create")
    if not flow or update.message is None or update.message.text is None:
        return False
    text = update.message.text.strip()
    if text.lower() in ("/cancelar", "cancelar"):
        await cancel_create(update, context)
        return True
    step = flow["step"]
    data = flow["data"]
    value = None if text == _SKIP else text
    if step == "name" and not value:
        await update.message.reply_text(
            "El nombre no puede estar vacío. ¿Cómo se llama el medicamento?"
        )
        return True
    data[step] = value
    idx = _CREATE_STEPS.index(step)
    if idx + 1 < len(_CREATE_STEPS):
        next_step = _CREATE_STEPS[idx + 1]
        flow["step"] = next_step
        await update.message.reply_text(
            _CREATE_PROMPTS[next_step], reply_markup=_cancel_keyboard()
        )
        return True
    # Ultimo paso: resumen y confirmacion.
    lines = ["➕ Nuevo medicamento", "", "Revisa los datos:", ""]
    for key in _CREATE_STEPS:
        lines.append(f"{_CREATE_LABELS[key]}: {data.get(key) or '—'}")
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar", callback_data="med:create_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar", callback_data="med:create_cancel"
                )
            ],
        ]
    )
    flow["step"] = "confirm"
    await update.message.reply_text("\n".join(lines), reply_markup=keyboard)
    return True


async def confirm_create(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Crea el medicamento (confirmacion del resumen)."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    flow = context.user_data.get("med_create")
    if not flow or flow.get("step") != "confirm":
        await query.edit_message_text("No hay ninguna creación en curso.")
        return
    data = flow["data"]
    from pydantic import ValidationError

    from app.schemas.medications import MedicationCreate
    from app.services import medication_service

    try:
        payload = MedicationCreate(
            name=data.get("name") or "",
            presentation=data.get("presentation"),
            concentration=data.get("concentration"),
            unit=data.get("unit"),
            notes=data.get("notes"),
        )
    except ValidationError as exc:
        await query.edit_message_text(
            "No pude crear el medicamento: "
            f"{exc.errors()[0]['msg'] if exc.errors() else 'datos no válidos'}"
        )
        return
    async with linked_session(update) as (session, user):
        if session is None or user is None:
            return
        try:
            med = await medication_service.create_medication(
                session, user, payload
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status == 403:
                await query.edit_message_text(
                    "No tienes permiso para crear medicamentos."
                )
            else:
                await query.edit_message_text(
                    "Algo falló. Inténtalo de nuevo en un momento."
                )
            return
        context.user_data.pop("med_create", None)
        await query.edit_message_text(
            f"✅ «{med.name}» creado.",
            reply_markup=with_home(
                [
                    [
                        InlineKeyboardButton(
                            "⬅️ Mis medicamentos",
                            callback_data="menu:medications",
                        )
                    ]
                ]
            ),
        )
