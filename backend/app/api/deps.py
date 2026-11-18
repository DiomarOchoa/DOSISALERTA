"""Dependencias de autenticacion para proteger endpoints (Fase 3).

Usa `HTTPBearer` (no `OAuth2PasswordBearer`): el login es JSON y
Swagger solo necesita un campo donde pegar el access token, sin
formulario de usuario/contrasena. `auto_error=False` para devolver
401 (no 403) cuando falta la cabecera.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.database import get_session
from app.models.users import User
from app.services import auth_service

# auto_error=False: si falta la cabecera, devuelve None en lugar de
# lanzar un 403. Asi devolvemos nosotros el 401 (el codigo correcto
# para "no autenticado"). Con auto_error=True, FastAPI devolveria 403.
bearer_scheme = HTTPBearer(auto_error=False, bearerFormat="JWT")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Resuelve el usuario autenticado desde `Authorization: Bearer <token>`.

    401 si falta la cabecera, si el token es invalido o expiro, si
    `sub` no es un entero, si el usuario no existe o esta inactivo.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="No se pudo validar la sesión")
    try:
        payload = security.decode_access_token(credentials.credentials)
    except security.InvalidTokenError:
        raise HTTPException(
            status_code=401, detail="No se pudo validar la sesión"
        ) from None
    return await auth_service.resolve_current_user(session, payload)


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Alias de `get_current_user` (todos los usuarios activos lo son).

    Los routers de las Fases 4+ usaran esta dependencia; `get_current_user`
    ya exige que el usuario exista y este activo.
    """
    return current_user
