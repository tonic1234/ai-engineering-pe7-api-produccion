"""El ejecutor: el único que sabe de LangGraph.

Lo que cubren estos tests no necesita modelo ni Redis de verdad: el grafo y el saver se
reemplazan. Es el test de regresión del fallo que apareció en la corrida de carga: dos tareas
concurrentes del worker pedían crear los índices de checkpoints al mismo tiempo y la segunda
se caía con "index already exists", dejando el trabajo en FALLO.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ejecutor import EjecutorDelGrafo


class SaverQueCuenta:
    """Se hace pasar por el RedisSaver: cuenta los asetup y tarda (eso es lo que abre la carrera)."""

    def __init__(self):
        self.creados = 0

    async def asetup(self):
        self.creados += 1
        await asyncio.sleep(0.05)


class GrafoFalso:
    async def ainvoke(self, *args, **kwargs):
        return {}


@pytest.fixture
def ejecutor(monkeypatch):
    instancia = EjecutorDelGrafo(redis_url="redis://no-se-usa/0")
    saver = SaverQueCuenta()

    async def crear_saver_falso(self):
        await saver.asetup()
        return saver

    monkeypatch.setattr(EjecutorDelGrafo, "_crear_saver", crear_saver_falso)
    monkeypatch.setattr("app.ejecutor.construir_grafo", lambda **kwargs: GrafoFalso())
    instancia.saver_falso = saver
    return instancia


async def test_preparar_en_paralelo_crea_el_saver_una_sola_vez(ejecutor):
    await asyncio.gather(ejecutor.preparar(), ejecutor.preparar(), ejecutor.preparar())
    assert ejecutor.saver_falso.creados == 1


async def test_preparar_dos_veces_seguidas_no_rearma_el_grafo(ejecutor):
    await ejecutor.preparar()
    await ejecutor.preparar()
    assert ejecutor.saver_falso.creados == 1


async def test_el_grafo_queda_armado(ejecutor):
    await ejecutor.preparar()
    assert ejecutor._grafo is not None


async def test_si_el_indice_ya_existe_no_se_propaga_el_error(monkeypatch):
    """El otro worker pudo haber creado el índice primero: eso no es un fallo del trabajo."""

    import langgraph.checkpoint.redis.aio as aio

    class SaverConIndiceExistente:
        def __init__(self, *args, **kwargs):
            pass

        async def asetup(self):
            raise RuntimeError("SEARCH_INDEX_EXISTS Index already exists: checkpoint_write")

    monkeypatch.setattr(aio, "AsyncRedisSaver", SaverConIndiceExistente)
    monkeypatch.setattr("app.ejecutor.construir_grafo", lambda **kwargs: GrafoFalso())

    ejecutor = EjecutorDelGrafo(redis_url="redis://no-se-usa/0")
    await ejecutor.preparar()  # no tiene que levantar el error
    assert ejecutor._grafo is not None
