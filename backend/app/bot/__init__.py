"""Bot de Telegram con python-telegram-bot (polling).

Esqueleto de demostracion con datos ficticios (sin PostgreSQL,
sin JWT, sin servicios reales). La integracion completa es de
la Fase 6; la estructura de este paquete ya es la definitiva:

- ``main.py``: punto de entrada (``python -m app.bot.main``).
- ``config.py``: configuracion desde variables de entorno.
- ``handlers/``: un modulo por seccion del menu.
- ``keyboards/``: menu principal y navegacion.
- ``services/``: en demostracion, solo datos ficticios.

El bot nunca tocara PostgreSQL directamente: solo llamara a
servicios, igual que la web.
"""
