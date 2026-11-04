"""Configuracion centralizada de DosisAlerta.

Toda la configuracion sale de variables de entorno. En desarrollo,
esas variables se leen de un archivo ``.env`` en la raiz del proyecto
(copiado desde ``.env.example``); en produccion, del entorno real.

Reglas que este archivo cumple:

- Nunca hay credenciales reales escritas en el codigo: solo nombres
  de variables y valores de ejemplo para desarrollo local.
- No se usa ``pydantic-settings``: la configuracion se construye con
  Pydantic (validacion de tipos) + ``python-dotenv`` (carga de
  ``.env``), que ya son dependencias del proyecto. Asi no se anade
  ninguna libreria innecesaria en la Fase 1.
- Lo que todavia no se usa en la Fase 1 (JWT, token de Telegram) NO
  se lee aqui todavia: se anadira en su fase, para no aparentar
  funcionalidades que no existen.

Uso::

    from app.core.config import get_settings

    settings = get_settings()
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import BaseModel

# Carga .env si existe. Si no existe, no falla: se usan los valores
# por defecto de desarrollo local que hay abajo. En la Fase 1 eso es
# suficiente porque todavia no hay base de datos ni secretos que leer.
load_dotenv()


def _getenv(name: str, default: str) -> str:
    """Lee una variable de entorno sin exponer su valor en logs."""
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _getint(name: str, default: int) -> int:
    """Lee una variable entera; si no es un numero, usa el defecto."""
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings(BaseModel):
    """Ajustes de la aplicacion. Un solo objeto, leido una sola vez."""

    app_name: str = "DosisAlerta"
    debug: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

    # Servidor HTTP (uvicorn). Por defecto, el puerto de la Fase 0/1.
    host: str = "127.0.0.1"
    port: int = 8000

    # CORS: origenes permitidos, separados por comas en CORS_ORIGINS.
    # En desarrollo, solo el frontend local de Vite.
    cors_origins_raw: str = "http://localhost:5173"

    # PostgreSQL (docker-compose.yml). En la Fase 1 solo se guarda la
    # configuracion; la conexion con SQLAlchemy llega en la Fase 2.
    # Por eso no hay ningun motor ni sesion de base de datos todavia.
    postgres_db: str = "dosisalerta"
    postgres_user: str = "dosisalerta"
    postgres_password: str = "dosisalerta"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    def __init__(self, **data):
        """Sobrescribe los defectos con variables de entorno, si existen."""
        data.setdefault("host", _getenv("HOST", "127.0.0.1"))
        data.setdefault("port", _getint("PORT", 8000))
        data.setdefault("cors_origins_raw", _getenv("CORS_ORIGINS", "http://localhost:5173"))
        data.setdefault("postgres_db", _getenv("POSTGRES_DB", "dosisalerta"))
        data.setdefault("postgres_user", _getenv("POSTGRES_USER", "dosisalerta"))
        data.setdefault("postgres_password", _getenv("POSTGRES_PASSWORD", "dosisalerta"))
        data.setdefault("postgres_host", _getenv("POSTGRES_HOST", "localhost"))
        data.setdefault("postgres_port", _getint("POSTGRES_PORT", 5432))
        super().__init__(**data)

    @property
    def cors_origins(self) -> list[str]:
        """Origenes CORS como lista, sin espacios ni entradas vacias."""
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def database_url(self) -> str:
        """URL async para SQLAlchemy (Fase 2). En Fase 1 no se usa.

        La contrasena va en la URL solo cuando SQLAlchemy la necesite.
        Nunca se imprime esta URL en logs: contiene la contrasena.
        """
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Devuelve la configuracion (una sola instancia en todo el proceso)."""
    return Settings()
