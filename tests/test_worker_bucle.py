"""El bucle del worker: sacar de la cola y correr de a varios.

El bug que este test tapa: el bucle usaba una variable de entorno para la concurrencia y no
había ningún test que lo llamara, así que un `import` faltante sólo se veía al arrancar el
proceso en serio (y el worker moría en silencio dejando los trabajos en 'pendiente').
"""

from __future__ import annotations

import asyncio

import fakeredis.aioredis
import pytest

from app.cola import ColaRedis
from app.esquemas import EstadoJob
from app.worker import correr_worker

PREGUNTA = "¿Cuántos días de vacaciones le corresponden a alguien con 12 años en la empresa?"


@pytest.fixture
async def cola():
    c = ColaRedis(cliente=fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield c
    await c.limpiar_todo()


async def ejecutor_ok(pregunta: str, reanudacion: dict | None = None) -> dict:
    await asyncio.sleep(0)
    return {"resultado": "listo", "pasos": 1, "contribuciones": [{"agente": "investigador"}],
            "interrumpido": False, "instruccion_pendiente": None, "hilo_id": "hilo-bucle"}


async def test_el_bucle_procesa_lo_que_hay_en_la_cola(cola):
    primero = await cola.crear(pregunta=PREGUNTA)
    segundo = await cola.crear(pregunta=PREGUNTA + " (otra)")

    procesados = await correr_worker(cola, ejecutor_ok, max_jobs=2, concurrencia=2, revisar_vencidas=False)

    assert procesados == 2
    for job_id in (primero, segundo):
        assert (await cola.leer(job_id))["estado"] == EstadoJob.DONE.value


async def test_el_bucle_corre_varios_a_la_vez(cola):
    """Con concurrencia 2, dos trabajos de 0,3 s tardan menos que uno detrás del otro."""

    async def ejecutor_lento(pregunta: str, reanudacion: dict | None = None) -> dict:
        await asyncio.sleep(0.3)
        return {"resultado": "listo", "pasos": 1, "contribuciones": [], "interrumpido": False,
                "instruccion_pendiente": None, "hilo_id": "hilo-lento"}

    for _ in range(2):
        await cola.crear(pregunta=PREGUNTA)

    inicio = asyncio.get_event_loop().time()
    await correr_worker(cola, ejecutor_lento, max_jobs=2, concurrencia=2, revisar_vencidas=False)
    transcurrido = asyncio.get_event_loop().time() - inicio

    assert transcurrido < 0.55, f"tardó {transcurrido:.2f}s: los corrió de a uno"
