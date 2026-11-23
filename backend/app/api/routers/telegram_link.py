"""Endpoints de vinculacion de Telegram (Etapa 6, RF15).

Las rutas solo validan la entrada, llaman al servicio y devuelven
la respuesta; no contienen logica de negocio ni SQL. El servicio
decide cada 404 generico y registra los intentos.

Flujo (ESPECIFICACION_BOT_TELEGRAM.md §5.2):
1. El paciente genera el codigo desde la web (POST /link): recibe
   el codigo UNA SOLA VEZ para escribirlo en el bot. El codigo
   caduca en 15 minutos.
2. El paciente abre el bot y envia `/vincular CODIGO`: el bot
   llama a `telegram_link_service.confirm_link` (no es un endpoint
   HTTP) y el vinculo pasa a VINCULADA.
3. El paciente puede desvincularse desde la web (POST /unlink):
   el vinculo pasa a REVOCADA y el scheduler deja de enviar
   avisos a ese chat.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.database import get_session
from app.models.users import User
from app.schemas.telegram_link import (
    TelegramLinkCodeResponse,
    TelegramLinkStatusResponse,
)
from app.services import telegram_link_service

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post("/link", response_model=TelegramLinkCodeResponse, status_code=201)
async def create_link_code(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TelegramLinkCodeResponse:
    """Genera un codigo de vinculacion y lo devuelve (una sola vez)."""
    return await telegram_link_service.create_link_code(session, current_user)


@router.post("/unlink", response_model=TelegramLinkStatusResponse)
async def unlink_telegram(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TelegramLinkStatusResponse:
    """Desvincula Telegram del usuario (el vinculo pasa a REVOCADA)."""
    account = await telegram_link_service.unlink(session, current_user)
    if account is None:
        return TelegramLinkStatusResponse(
            status="SIN_VINCULAR",
            telegram_username=None,
            linked_at=None,
            has_pending_code=False,
        )
    return TelegramLinkStatusResponse(
        status=account.status,
        telegram_username=account.username,
        linked_at=account.linked_at,
        has_pending_code=False,
    )


@router.get("/status", response_model=TelegramLinkStatusResponse)
async def telegram_status(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(deps.get_current_active_user),
) -> TelegramLinkStatusResponse:
    """Estado de vinculacion de Telegram del usuario."""
    return await telegram_link_service.get_status(session, current_user)
