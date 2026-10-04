"""Tests del worker: el que corre el grafo fuera del request.

Cubre el error que la consigna marca como grave: si el agente falla en segundo plano y el job
no pasa a FALLO, el cliente queda consultando para siempre.

El ejecutor (el grafo) recibe la pregunta y, si es una reanudación, el dato de la aprobación.
Así el worker no sabe nada de LangGraph y se puede probar con un doble.
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.cola import ColaRedis
from app.esquemas import EstadoJob
from app.worker import procesar_job

PREGUNTA = "¿Cuántos días de vacaciones le corresponden a alguien con 12 años en la empresa?"


@pytest.fixture
async def cola():
    c = ColaRedis(cliente=fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield c
    await c.limpiar_todo()


async def ejecutor_ok(pregunta: str, reanudacion: dict | None = None) -> dict:
    await asyncio.sleep(0)
    return {
        "resultado": f"Respuesta simulada para: {pregunta}",
        "pasos": 2,
        "contribuciones": [{"agente": "investigador"}, {"agente": "analista"}],
        "interrumpido": False,
        "instruccion_pendiente": None,
        "hilo_id": "hilo-de-prueba",
    }


async def ejecutor_que_falla(pregunta: str, reanudacion: dict | None = None) -> dict:
    raise RuntimeError("ResourceExhausted: 429 del proveedor")


async def test_el_worker_deja_el_job_en_done(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    await cola.tomar(timeout_s=1)
    datos = await procesar_job(job_id, cola, ejecutor_ok)
    assert datos["estado"] == EstadoJob.DONE.value
    assert "Respuesta simulada" in datos["resultado"]
    assert datos["pasos"] == 2


async def test_el_worker_guarda_las_contribuciones(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    datos = await procesar_job(job_id, cola, ejecutor_ok)
    assert datos["contribuciones"]


async def test_el_worker_guarda_el_hilo(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    datos = await procesar_job(job_id, cola, ejecutor_ok)
    assert datos["hilo_id"] == "hilo-de-prueba"


async def test_un_fallo_del_agente_deja_el_job_en_fallo(cola):
    """Si esto no pasa, el cliente queda en polling infinito."""

    job_id = await cola.crear(pregunta=PREGUNTA)
    datos = await procesar_job(job_id, cola, ejecutor_que_falla)
    assert datos["estado"] == EstadoJob.FALLO.value
    assert "429" in datos["error"]


async def test_el_fallo_no_deja_el_job_en_proceso(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    await procesar_job(job_id, cola, ejecutor_que_falla)
    datos = await cola.leer(job_id)
    assert datos["estado"] not in {EstadoJob.EN_PROCESO.value, EstadoJob.PENDIENTE.value}


async def test_el_worker_marca_en_proceso_antes_de_correr(cola):
    visto = {}

    async def ejecutor_espia(pregunta: str, reanudacion: dict | None = None) -> dict:
        visto["estado"] = (await cola.leer(job_id))["estado"]
        return {"resultado": "ok", "pasos": 1, "contribuciones": [], "interrumpido": False,
                "instruccion_pendiente": None, "hilo_id": "x"}

    job_id = await cola.crear(pregunta=PREGUNTA)
    await procesar_job(job_id, cola, ejecutor_espia)
    assert visto["estado"] == EstadoJob.EN_PROCESO.value
