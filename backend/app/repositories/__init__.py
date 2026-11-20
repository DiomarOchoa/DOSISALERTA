"""Consultas a la base de datos, sin logica de negocio.

Desde la Fase 2 viven aqui los repositorios de los modelos
(`user_repository.py` y `refresh_token_repository.py` llegan en
la Fase 3). Desde la Fase 4, `medication_repository.py`
(catalogo propio del usuario), `treatment_repository.py`,
`treatment_medication_repository.py`, `schedule_repository.py`
y `reminder_repository.py` (tratamientos, vinculos, horarios y
recordatorios). Ninguna ruta debe hacer SQL directamente.
"""
