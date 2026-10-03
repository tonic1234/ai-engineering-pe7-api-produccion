"""Punto de entrada para el servidor: `uvicorn app.main:app`.

La app se arma acá y no en `api.py` para que importar el módulo en los tests no tenga efectos
(conectar Redis o instrumentar trazas son cosas que hace el servidor, no una importación).
"""

from __future__ import annotations

from app.api import crear_app
from app.ejecutor import EjecutorDelGrafo

app = crear_app(ejecutor=EjecutorDelGrafo())
