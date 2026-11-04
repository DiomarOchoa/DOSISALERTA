"""Endpoint de salud de la aplicacion.

``GET /health`` es el endpoint canonico para comprobar que el
backend esta levantado (lo usan personas, scripts y, mas adelante,
contenedores). ``GET /api/v1/health`` devuelve exactamente lo mismo
para que el frontend, que trabaja contra ``/api/v1``, no tenga que
salirse de su URL base.

La respuesta es intencionadamente sencilla y no revela nada sensible:
solo que la aplicacion responde, su nombre y su version.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def health_payload() -> dict[str, str]:
    """Construye la respuesta de salud, sin tocar base de datos ni secretos."""
    try:
        app_version = version("dosisalerta")
    except PackageNotFoundError:
        # Ocurre si se ejecuta sin haber instalado el paquete con pip.
        # En ese caso, la version de desarrollo es suficiente para /health.
        app_version = "0.1.0-dev"
    return {"status": "ok", "app": "DosisAlerta", "version": app_version}


@router.get("/health")
def get_health() -> dict[str, str]:
    """Comprueba que la aplicacion responde. Siempre 200 si el proceso vive."""
    return health_payload()
