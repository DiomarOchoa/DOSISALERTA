"""Logica de negocio, un modulo por dominio.

Desde la Fase 3 vive aqui ``auth_service.py`` (registro, login,
renovacion y cierre de sesion). Desde la Fase 4, ``medication_
service.py`` (catalogo propio del usuario) y ``caregiver_
access.py`` (resolucion de actor dueno/cuidador, compartido por
los servicios de Fase 4). La web y el bot llamaran a estos mismos
servicios; por eso no viven en las rutas.
"""
