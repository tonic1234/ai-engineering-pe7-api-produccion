"""Tests de la API: lo que la consigna pide del endpoint asíncrono.

El POST no puede correr el agente: tiene que encolar y devolver el id al instante. Estos
tests miden eso y no la forma en que está escrito por dentro.
"""

from __future__ import annotations

import time

import httpx
import pytest

from app.api import crear_app
from app.cola import ColaRedis
from app.esquemas import EstadoJob

PREGUNTA = "¿Cuántos días de vacaciones le corresponden a alguien con 12 años en la empresa?"


@pytest.fixture
async def cola():
    c = ColaRedis(cliente=__import__("fakeredis").aioredis.FakeRedis(decode_responses=True))
    yield c
    await c.limpiar_todo()


@pytest.fixture
async def cliente(cola):
    app = crear_app(cola=cola)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as c:
        yield c


async def test_post_devuelve_202_con_job_id(cliente):
    r = await cliente.post("/tareas", json={"pregunta": PREGUNTA})
    assert r.status_code == 202
    cuerpo = r.json()
    assert cuerpo["job_id"]
    assert cuerpo["estado"] == EstadoJob.PENDIENTE.value


async def test_el_post_no_espera_al_agente(cliente):
    """El endpoint responde en milisegundos aunque el grafo tarde 80 segundos."""

    inicio = time.perf_counter()
    r = await cliente.post("/tareas", json={"pregunta": PREGUNTA})
    transcurrido = time.perf_counter() - inicio
    assert r.status_code == 202
    assert transcurrido < 0.5, f"el POST tardó {transcurrido:.2f}s: está corriendo el agente adentro"


async def test_una_pregunta_vacia_no_entra(cliente):
    r = await cliente.post("/tareas", json={"pregunta": "corto"})
    assert r.status_code == 422

async def test_consultar_un_job_que_no_existe_da_404(cliente):
    r = await cliente.get("/tareas/no-existe")
    assert r.status_code == 404


async def test_consultar_un_job_recien_creado_lo_muestra_pendiente(cliente):
    job_id = (await cliente.post("/tareas", json={"pregunta": PREGUNTA})).json()["job_id"]
    r = await cliente.get(f"/tareas/{job_id}")
    assert r.status_code == 200
    assert r.json()["estado"] == EstadoJob.PENDIENTE.value


async def test_health_dice_si_redis_contesta_y_que_modelo_usa(cliente):
    r = await cliente.get("/health")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["redis"] == "ok"
    assert cuerpo["modelo"]
