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
  ninguna libreria innecesaria.
- Lo que todavia no se usa (JWT, token de Telegram) NO se lee aqui
  todavia: se anadira en su fase (Fase 3 y Fase 6), para no aparentar
  funcionalidades que no existen. Ver ``.env.example``: esas
  variables estan marcadas como RESERVADAS.

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
# por defecto de desarrollo local que hay abajo. Desde la Fase 2 hay
# base de datos y secretos que leer (POSTGRES_PASSWORD), asi que en
# un PC sin .env el backend arranca solo con los defectos locales.
load_dotenv()


def _getenv(name: str, default: str) -> str:
    """Lee una variable de entorno sin exponer su valor en logs."""
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _getint(name: str, default: int) -> int:
    """Lee una variable entera de puerto, con validacion explicita.

    - Si la variable no existe o esta vacia, usa el defecto.
    - Si no es un numero entero, falla con un error que nombra la
      variable, en lugar de arrancar en silencio con el defecto.
    - Si no esta entre 1 y 65535, falla con un error que nombra la
      variable y el valor.

    Esta funcion solo se usa para puertos (`PORT` y
    `POSTGRES_PORT`). Si en el futuro se necesitara para otro numero
    que no sea un puerto, habria que separar la validacion de rango.
    Fallar al arrancar es intencionado: una configuracion mal escrita
    debe verse en la configuracion, no mas tarde en Uvicorn o en la
    base de datos con un error confuso.
    """
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(
            f"La variable {name} debe ser un numero entero, "
            f"pero vale {raw!r}. Revisa tu .env."
        ) from None
    if not 1 <= value <= 65535:
        raise ValueError(
            f"La variable {name} debe ser un puerto entre 1 y 65535, "
            f"pero vale {value}."
        )
    return value


class Settings(BaseModel):
    """Ajustes de la aplicacion. Un solo objeto, leido una sola vez."""

    app_name: str = "DosisAlerta"
    debug: bool = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

    # Servidor HTTP (uvicorn). Los valores de abajo son los defectos;
    # las variables HOST y PORT los sobrescriben si existen.
    host: str = "127.0.0.1"
    port: int = 8000

    # CORS: origenes permitidos, separados por comas en CORS_ORIGINS.
    # En desarrollo, solo el frontend local de Vite.
    cors_origins_raw: str = "http://localhost:5173"

    # PostgreSQL (docker-compose.yml). Este archivo solo guarda la
    # configuracion; el motor y la sesion de SQLAlchemy viven en
    # `database/` y `models/` desde la Fase 2, y Alembic toma la URL
    # de aqui (`database_url`).
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
        """URL async para SQLAlchemy. La usan los modelos (Fase 2)
        y Alembic para las migraciones.

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
