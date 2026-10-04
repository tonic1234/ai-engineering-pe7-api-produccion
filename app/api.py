"""La API: recibe la tarea, la encola y devuelve el id.

Acá no se corre ningún agente. El endpoint contesta en milisegundos (el POST devuelve 202 con
el job_id) y el trabajo de verdad lo hace el worker, que es un proceso aparte. El cliente
consulta el estado con polling: es el patrón que pide el módulo.
"""

from __future__ import annotations

import json
import logging
import os

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from app.cola import ColaRedis, ahora
from app.esquemas import AprobacionIn, EstadoJob, InformeJob, TareaCreada, TareaIn
from app.observabilidad import activar_trazas, trazas_activas

log = logging.getLogger(__name__)


class RespuestaLegible(JSONResponse):
    """JSON en UTF-8, sin escapar los acentos.

    Por defecto, el JSON sale con las tildes escapadas (\\u00ed) y cualquier persona que lea la
    respuesta ve ruido en vez del texto. El contenido es el mismo, sólo se escribe legible.
    """

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

CAMPOS_INFORME = (
    "job_id", "estado", "pregunta", "resultado", "error", "pasos",
    "contribuciones", "instruccion_pendiente", "hilo_id", "creada_en", "actualizada_en",
)


def crear_app(cola: ColaRedis | None = None, ejecutor=None, instrumentar: bool = False) -> FastAPI:
    """Arma la API.

    `instrumentar` queda en False a propósito: la API no corre el grafo, y la instrumentación de
    LangChain engancha también FastAPI, con lo cual cada consulta de estado del cliente dejaría su
    span y llenaría el dashboard. Las trazas se activan en el worker, que es donde se ejecuta el
    agente (ver `app/worker_main.py`).
    """
    cola = cola or ColaRedis()
    if instrumentar:
        activar_trazas()

    app = FastAPI(
        title="API del orquestador multi-agente",
        version="1.0",
        description="Encola la consulta, la corre en un worker y expone el estado del trabajo.",
        default_response_class=RespuestaLegible,
    )
    app.state.cola = cola
    app.state.ejecutor = ejecutor

    @app.post("/tareas", response_model=TareaCreada, status_code=status.HTTP_202_ACCEPTED)
    async def crear_tarea(tarea: TareaIn) -> TareaCreada:
        job_id = await cola.crear(tarea.pregunta)
        log.info("trabajo %s encolado", job_id)
        return TareaCreada(job_id=job_id, estado=EstadoJob.PENDIENTE)

    @app.get("/tareas/{job_id}", response_model=InformeJob)
    async def consultar_tarea(job_id: str) -> InformeJob:
        datos = await cola.leer(job_id)
        if datos is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no conozco el trabajo {job_id}")
        return InformeJob(**{campo: datos.get(campo) for campo in CAMPOS_INFORME})

    @app.post("/tareas/{job_id}/aprobar")
    async def aprobar_tarea(job_id: str, decision: AprobacionIn) -> dict:
        datos = await cola.leer(job_id)
        if datos is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no conozco el trabajo {job_id}")
        if datos.get("estado") != EstadoJob.ESPERANDO_APROBACION.value:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"el trabajo está en '{datos.get('estado')}': no hay nada que aprobar",
            )

        if decision.aprobado:
            # Queda aprobado y vuelve a la cola: el worker lo retoma desde el checkpoint.
            await cola.actualizar(
                job_id, EstadoJob.APROBADO, aprobado_en=ahora(), comentario=decision.comentario
            )
            await cola.encolar(job_id)
            log.info("trabajo %s aprobado", job_id)
            return {"job_id": job_id, "estado": EstadoJob.APROBADO.value}

        await cola.actualizar(
            job_id,
            EstadoJob.RECHAZADO,
            error=f"rechazado por quien revisa: {decision.comentario or 'sin comentario'}",
        )
        log.info("trabajo %s rechazado", job_id)
        return {"job_id": job_id, "estado": EstadoJob.RECHAZADO.value}

    @app.get("/health")
    async def health() -> dict:
        viva = await cola.esta_viva()
        return {
            "redis": "ok" if viva else "sin_conexion",
            "modelo": os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            "pendientes": await cola.pendientes() if viva else None,
            "trazas": trazas_activas(),
        }

    return app
