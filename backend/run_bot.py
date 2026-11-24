"""Lanzador del bot de DosisAlerta para Render Free (servicio web).

Render exige que un servicio web escuche en ``$PORT``. El bot hace
polling (saliente) y no abre ningun puerto, asi que este lanzador
levanta un servidor HTTP minimo (stdlib) en un hilo — responde 200
en ``/`` y ``/health`` — y corre el polling en el hilo principal.

Si el polling falla (sin token, token invalido, sin red), el
proceso termina y Render lo reinicia; el servidor de salud muere
con el proceso, asi no hay un servicio "vivo" con el bot caido.

Se ejecuta con::

    python run_bot.py

desde la carpeta ``backend/`` (con el entorno virtual activado).
No lee ni muestra ningun secreto: el token lo lee
``app.bot.main`` desde el entorno, como siempre.
"""

from __future__ import annotations

import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    """Responde 200 en / y /health; 404 en lo demas."""

    def do_GET(self) -> None:
        if self.path in ("/", "/health"):
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:
        # Sin logs de acceso: el servicio no necesita ruido.
        return


def _start_health_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = Thread(target=server.serve_forever, name="health-server", daemon=True)
    thread.start()
    logger.info("Servidor de salud en el puerto %d.", port)
    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    port = int(os.environ.get("PORT", "8000"))
    _start_health_server(port)
    # El polling bloquea aqui; si falla, el proceso termina y
    # Render lo reinicia (el servidor de salud muere con el).
    from app.bot.main import main as run_bot

    run_bot()


if __name__ == "__main__":
    main()
