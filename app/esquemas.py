"""Esquemas de la API y los estados por los que pasa un trabajo.

Un job no es un booleano: pasa por estados, y el cliente tiene que poder leerlos todos desde
afuera (incluso el de un fallo) sin quedarse esperando.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EstadoJob(str, Enum):
    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    ESPERANDO_APROBACION = "esperando_aprobacion"
    APROBADO = "aprobado"
    DONE = "done"
    FALLO = "fallo"
    RECHAZADO = "rechazado"
    RECHAZADO_POR_TIMEOUT = "rechazado_por_timeout"


ESTADOS_FINALES = {EstadoJob.DONE, EstadoJob.FALLO, EstadoJob.RECHAZADO, EstadoJob.RECHAZADO_POR_TIMEOUT}


class TareaIn(BaseModel):
    """Lo que manda el cliente. La pregunta corta no entra: no hay nada que orquestar."""

    pregunta: str = Field(min_length=10, max_length=2000)


class TareaCreada(BaseModel):
    job_id: str
    estado: EstadoJob


class AprobacionIn(BaseModel):
    aprobado: bool
    comentario: str | None = Field(default=None, max_length=500)


class InformeJob(BaseModel):
    """Lo que devuelve GET /tareas/{job_id}: el estado y lo que haya para mostrar."""

    job_id: str
    estado: EstadoJob
    pregunta: str
    resultado: str | None = None
    error: str | None = None
    pasos: int = 0
    contribuciones: list[dict] = Field(default_factory=list)
    instruccion_pendiente: str | None = None
    hilo_id: str | None = None
    creada_en: str | None = None
    actualizada_en: str | None = None
