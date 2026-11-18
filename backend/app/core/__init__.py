"""Configuracion y utilidades transversales del backend.

En la Fase 1 solo vive aqui ``config.py`` (ajustes desde ``.env``).
Desde la Fase 3 vive tambien ``security.py`` (hash bcrypt, JWT y
hash SHA-256 de refresh tokens). No hay manejo centralizado de
errores: FastAPI gestiona `HTTPException` y `RequestValidationError`
con sus manejadores propios.
"""
