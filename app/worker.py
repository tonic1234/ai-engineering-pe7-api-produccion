"""El worker: el proceso que saca trabajos de la cola y corre el grafo.

Corre FUERA del request (es el punto de la consigna): la API contesta en milisegundos y acá
adentro puede tardar los 80 segundos que tarda el equipo de agentes.

El ejecutor se recibe por parámetro para poder probar este módulo sin modelo ni red.
"""

from __future__ import annotations

import asyncio
import logging
import os

from app.esquemas import EstadoJob
from app.hitl import vencer_aprobaciones

log = logging.getLogger(__name__)

INTERVALO_S = 0.5


async def procesar_job(job_id: str, cola, ejecutor, reanudacion: dict | None = None) -> dict:
    """Corre un trabajo y deja el resultado (o el motivo del fallo) en Redis."""
    datos = await cola.leer(job_id)
    if datos is None:
        raise KeyError(f"el trabajo {job_id} no está en Redis")

    await cola.actualizar(job_id, EstadoJob.EN_PROCESO)

    try:
        salida = await ejecutor(datos["pregunta"], reanudacion)
    except Exception as error:  # noqa: BLE001: sin esto el cliente queda en polling infinito
        log.warning("el trabajo %s falló: %s", job_id, error)
        return await cola.actualizar(
            job_id, EstadoJob.FALLO, error=f"{type(error).__name__}: {error}"[:500]
        )

    comunes = {
        "pasos": salida.get("pasos", 0),
        "contribuciones": salida.get("contribuciones", []),
        "hilo_id": salida.get("hilo_id"),
    }

    if salida.get("interrumpido"):
        return await cola.actualizar(
            job_id,
            EstadoJob.ESPERANDO_APROBACION,
            instruccion_pendiente=salida.get("instruccion_pendiente"),
            **comunes,
        )

    return await cola.actualizar(
        job_id, EstadoJob.DONE, resultado=salida.get("resultado"), **comunes
    )


async def correr_worker(
    cola,
    ejecutor,
    max_jobs: int | None = None,
    concurrencia: int | None = None,
    revisar_vencidas: bool = True,
) -> int:
    """Bucle del worker: saca trabajos de la cola y los corre de a varios.

    La API no se bloquea por esto (corre en otro proceso), pero si el worker fuera de a uno la
    quinta petición de una tanda esperaría a las cuatro anteriores. `WORKER_CONCURRENCIA` fija
    cuántos a la vez (el curso cuenta que el worker puede escalar a varias instancias).
    """
    concurrencia = concurrencia or int(os.getenv("WORKER_CONCURRENCIA", "3"))
    semaforo = asyncio.Semaphore(concurrencia)
    en_curso: set[asyncio.Task] = set()
    procesados = 0

    async def _correr(job_id: str, reanudacion: dict | None) -> None:
        async with semaforo:
            await procesar_job(job_id, cola, ejecutor, reanudacion=reanudacion)

    while max_jobs is None or procesados < max_jobs:
        job_id = await cola.tomar()

        if job_id is None:
            if en_curso:
                hechas, en_curso = await asyncio.wait(en_curso, timeout=INTERVALO_S, return_when=asyncio.FIRST_COMPLETED)
                procesados += len(hechas)
                continue
            if revisar_vencidas:
                await vencer_aprobaciones(cola)
            await asyncio.sleep(INTERVALO_S)
            continue

        datos = await cola.leer(job_id)
        if datos is None:  # el trabajo venció en Redis: no hay nada que hacer
            continue

        reanudacion = None
        if datos.get("aprobado_en"):
            reanudacion = {
                "aprobado": True,
                "hilo_id": datos.get("hilo_id"),
                "comentario": datos.get("comentario"),
            }
        en_curso.add(asyncio.create_task(_correr(job_id, reanudacion)))

    if en_curso:
        await asyncio.gather(*en_curso)
        procesados += len(en_curso)

    return procesados
