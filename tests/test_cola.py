"""Tests de la cola: el estado del job en Redis (25% de la rúbrica).

El punto fino que marca la unidad del curso: el estado 'pendiente' se guarda ANTES de encolar.
Si el worker gana la carrera, el cliente consulta y recibe un 404 que parece un bug nuestro.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from app.cola import TTL_SEGUNDOS, ColaRedis
from app.esquemas import EstadoJob

PREGUNTA = "¿Cuántos días de vacaciones le corresponden a alguien con 12 años en la empresa?"


@pytest.fixture
async def cola():
    c = ColaRedis(cliente=fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield c
    await c.limpiar_todo()


async def test_el_estado_queda_antes_de_encolar(cola, monkeypatch):
    """Espía el orden real de los comandos que salen hacia Redis."""

    orden: list[str] = []
    original = cola.cliente.execute_command

    async def espia(*args, **kwargs):
        if args and isinstance(args[0], str):
            orden.append(args[0].upper())
        return await original(*args, **kwargs)

    monkeypatch.setattr(cola.cliente, "execute_command", espia)
    await cola.crear(pregunta=PREGUNTA)

    indice_estado = next(i for i, c in enumerate(orden) if c in {"HSET", "HMSET"})
    indice_cola = next(i for i, c in enumerate(orden) if c in {"LPUSH", "RPUSH"})
    assert indice_estado < indice_cola, f"se encoló antes de guardar el estado: {orden}"


async def test_el_job_arranca_pendiente(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    datos = await cola.leer(job_id)
    assert datos["estado"] == EstadoJob.PENDIENTE.value
    assert datos["pregunta"] == PREGUNTA


async def test_se_puede_actualizar_el_estado(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    await cola.actualizar(job_id, EstadoJob.EN_PROCESO)
    assert (await cola.leer(job_id))["estado"] == EstadoJob.EN_PROCESO.value


async def test_el_fallo_guarda_el_motivo(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    await cola.actualizar(job_id, EstadoJob.FALLO, error="ResourceExhausted: cuota agotada")
    datos = await cola.leer(job_id)
    assert datos["estado"] == EstadoJob.FALLO.value
    assert "cuota agotada" in datos["error"]


async def test_tomar_saca_el_job_de_la_cola(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    assert await cola.tomar(timeout_s=1) == job_id
    assert await cola.tomar(timeout_s=1) is None


async def test_dos_workers_no_agarran_el_mismo_job(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    primero = await cola.tomar(timeout_s=1)
    segundo = await cola.tomar(timeout_s=1)
    assert [primero, segundo].count(job_id) == 1


async def test_el_estado_no_vive_en_el_objeto_de_python(cola):
    """Otro objeto de cola (en la vida real, otro proceso) ve el mismo estado."""

    job_id = await cola.crear(pregunta=PREGUNTA)
    otro = ColaRedis(cliente=cola.cliente)
    assert (await otro.leer(job_id))["estado"] == EstadoJob.PENDIENTE.value


async def test_el_estado_tiene_vencimiento(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    ttl = await cola.cliente.ttl(cola.clave(job_id))
    assert 0 < ttl <= TTL_SEGUNDOS


async def test_el_health_reporta_redis_ok(cola):
    assert await cola.esta_viva() is True
