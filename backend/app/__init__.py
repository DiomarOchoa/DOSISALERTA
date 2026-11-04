"""DosisAlerta: backend en Python con FastAPI.

Paquete principal. La aplicacion se crea en ``app.main.create_app``.
Las capas estan separadas a proposito, aunque en la Fase 1 solo
existan la configuracion y el endpoint de salud:

- ``core``: configuracion central (variables de entorno).
- ``api``: rutas HTTP (routers). No contienen logica de negocio.
- ``services``: logica de negocio (a partir de la Fase 4).
- ``repositories``: acceso a la base de datos (a partir de la Fase 2).
- ``models`` / ``schemas``: tablas SQLAlchemy y esquemas Pydantic.
- ``bot`` / ``scheduler`` / ``algorithms``: Telegram y motor de
  recordatorios (Fases 5 y 6). En la Fase 1 solo existen como
  paquetes vacios, para que la estructura no cambie despues.
"""
