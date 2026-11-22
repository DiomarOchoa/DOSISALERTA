"""Configuracion del proceso bot de DosisAlerta.

Lee solo lo que el bot necesita para arrancar en polling:

- ``TELEGRAM_BOT_TOKEN``: token del bot (@DosisAlertaBot). Vive
  solo en ``.env``. En este esqueleto de demostracion el token
  puede estar vacio: sin token el bot no puede hacer polling y
  ``main()`` se niega a arrancar con un mensaje claro, pero el
  resto del paquete (teclados, handlers, datos ficticios) se
  puede importar y probar sin el.
- ``TELEGRAM_BOT_USERNAME``: nombre de usuario del bot, solo
  para los mensajes de arranque. Por defecto ``DosisAlertaBot``.

Reglas de seguridad (especificacion §5.8):

- El token nunca se escribe en codigo, documentacion ni logs.
  Por eso el campo ``token`` tiene ``repr=False``: un
  ``repr(config)`` accidental no lo muestra.
- El token nunca se imprime en mensajes de error: los errores
  hablan del problema, nunca del valor.

Este modulo es independiente de ``app.core.config`` a proposito:
el proceso bot debe poder arrancar y probarse sin la
configuracion de la API (sin PostgreSQL, sin JWT y sin los
servicios que todavia no existen).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


def _load_env_file() -> None:
    """Carga ``.env`` buscando hacia arriba desde este archivo.

    El ``.env`` del proyecto vive en la raiz del repositorio
    (``DOSISALERTA/.env``). La busqueda parte de este archivo y
    sube por sus directorios padres, para no depender del
    directorio de trabajo desde el que se lanza el bot: asi un
    ``.env`` ajeno que exista en el arbol del directorio de
    trabajo nunca tapa al del proyecto (leccion de la Fase 2:
    en el PC existe un ``.env`` ajeno en ``C:\\Users\\ASUS``).
    Si no hay ``.env``, no pasa nada: las variables de entorno
    del sistema mandan igual.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate)
            return


@dataclass(frozen=True)
class BotConfig:
    """Configuracion del bot, leida una sola vez al arrancar."""

    token: str = field(default="", repr=False)
    username: str = "DosisAlertaBot"

    @classmethod
    def from_env(cls) -> BotConfig:
        """Construye la configuracion desde variables de entorno."""
        _load_env_file()
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        username = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip()
        return cls(token=token, username=username or "DosisAlertaBot")

    @property
    def can_poll(self) -> bool:
        """True cuando hay token y el bot puede hacer polling."""
        return bool(self.token)

    def require_token(self) -> str:
        """Devuelve el token o falla con un mensaje claro.

        El mensaje nunca incluye el valor del token.
        """
        if not self.token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN no está configurado. "
                "Añade el token del bot a .env (nunca en el código) "
                "para poder iniciar el polling."
            )
        return self.token
