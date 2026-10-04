"""Tests del Human-in-the-loop (15% de la rúbrica).

Dos cosas distintas: la REGLA (qué tarea se considera crítica, decidida en código y no por el
modelo) y el MECANISMO (el job se pausa, espera la aprobación de afuera y sigue donde estaba).
"""

from __future__ import annotations

import fakeredis.aioredis
import httpx
import pytest

from app.api import crear_app
from app.cola import ColaRedis
from app.esquemas import EstadoJob
from app.hitl import UMBRAL_COSTO_APROBACION, es_critica, vencer_aprobaciones
from app.worker import procesar_job

PREGUNTA = "Publicá el resumen de las políticas de teletrabajo en el portal interno"


@pytest.fixture
async def cola():
    c = ColaRedis(cliente=fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield c
    await c.limpiar_todo()


# --- la regla -------------------------------------------------------------------------


def test_una_accion_con_efecto_es_critica():
    critica, motivo = es_critica("Publicá el resumen en el portal interno")
    assert critica is True
    assert "public" in motivo.lower()


def test_borrar_tambien_es_critico():
    assert es_critica("Borrá los documentos vencidos del repositorio")[0] is True


def test_una_consulta_comun_no_es_critica():
    critica, motivo = es_critica("¿Cuántos días de vacaciones corresponden con 12 años?")
    assert critica is False
    assert motivo == ""


def test_el_costo_alto_es_critico_aunque_no_haya_accion():
    critica, motivo = es_critica("Analizá el histórico completo de los últimos 10 años",
                                 costo_estimado=UMBRAL_COSTO_APROBACION + 0.01)
    assert critica is True
    assert "costo" in motivo.lower()


def test_un_costo_bajo_no_alcanza_para_pausar():
    assert es_critica("Resumí dos párrafos", costo_estimado=0.001)[0] is False


# --- el mecanismo ---------------------------------------------------------------------


async def ejecutor_que_pausa(pregunta: str, reanudacion: dict | None = None) -> dict:
    if reanudacion:  # volvió aprobada: sigue desde el checkpoint y cierra
        return {"resultado": "Publicado después de la aprobación", "pasos": 3,
                "contribuciones": [{"agente": "investigador"}], "interrumpido": False,
                "instruccion_pendiente": None, "hilo_id": "hilo-1"}
    return {"resultado": None, "pasos": 1, "contribuciones": [{"agente": "investigador"}],
            "interrumpido": True, "instruccion_pendiente": "publicar en el portal",
            "hilo_id": "hilo-1"}


async def test_la_tarea_critica_queda_esperando_aprobacion(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    datos = await procesar_job(job_id, cola, ejecutor_que_pausa)
    assert datos["estado"] == EstadoJob.ESPERANDO_APROBACION.value
    assert datos["instruccion_pendiente"] == "publicar en el portal"
    assert datos["hilo_id"] == "hilo-1"


async def test_una_tarea_normal_termina_sin_pausar(cola):
    async def ejecutor_normal(pregunta: str, reanudacion: dict | None = None) -> dict:
        return {"resultado": "listo", "pasos": 1, "contribuciones": [], "interrumpido": False,
                "instruccion_pendiente": None, "hilo_id": "hilo-2"}

    job_id = await cola.crear(pregunta="Resumí las políticas de licencia")
    datos = await procesar_job(job_id, cola, ejecutor_normal)
    assert datos["estado"] == EstadoJob.DONE.value


async def test_la_aprobacion_reanuda_y_termina(cola):
    app = crear_app(cola=cola)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as cliente:
        job_id = (await cliente.post("/tareas", json={"pregunta": PREGUNTA})).json()["job_id"]
        await procesar_job(job_id, cola, ejecutor_que_pausa)

        r = await cliente.post(f"/tareas/{job_id}/aprobar", json={"aprobado": True, "comentario": "ok"})
        assert r.status_code == 200

        datos = await procesar_job(job_id, cola, ejecutor_que_pausa, reanudacion={"aprobado": True})
        assert datos["estado"] == EstadoJob.DONE.value
        assert "aprobación" in datos["resultado"]


async def test_el_rechazo_cierra_el_job(cola):
    app = crear_app(cola=cola)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as cliente:
        job_id = (await cliente.post("/tareas", json={"pregunta": PREGUNTA})).json()["job_id"]
        await procesar_job(job_id, cola, ejecutor_que_pausa)
        r = await cliente.post(f"/tareas/{job_id}/aprobar", json={"aprobado": False})
        assert r.status_code == 200
        assert (await cola.leer(job_id))["estado"] == EstadoJob.RECHAZADO.value


async def test_no_se_puede_aprobar_un_job_que_no_esta_esperando(cola):
    app = crear_app(cola=cola)
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as cliente:
        job_id = (await cliente.post("/tareas", json={"pregunta": PREGUNTA})).json()["job_id"]
        r = await cliente.post(f"/tareas/{job_id}/aprobar", json={"aprobado": True})
        assert r.status_code == 409


async def test_una_aprobacion_que_nadie_contesta_vense(cola):
    job_id = await cola.crear(pregunta=PREGUNTA)
    await procesar_job(job_id, cola, ejecutor_que_pausa)
    vencidos = await vencer_aprobaciones(cola, minutos=0)
    assert job_id in vencidos
    assert (await cola.leer(job_id))["estado"] == EstadoJob.RECHAZADO_POR_TIMEOUT.value
