"""test_llm_factory.py: la fábrica del modelo y el traductor de errores.

Dos cosas que salieron de las devoluciones anteriores:

- "validá las variables de entorno de forma más estricta" (pre-entrega 4): acá se comprueba
  que falte la clave corta con un mensaje que dice QUÉ variable falta, en vez de fallar más
  tarde con un error opaco del SDK.
- "capturá excepciones específicas de cada SDK con mensajes informativos, no un try/except
  genérico" (pre-entrega 1): `mensaje_de_error` traduce cuota, clave y red mirando el nombre
  de la excepción, y los tests fijan esa traducción.
"""

from __future__ import annotations

import pytest

from llm_factory import mensaje_de_error, VARIABLES_DE_CLAVE


def test_sin_clave_lo_dice_con_el_nombre_exacto_de_la_variable(monkeypatch):
    for variable in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(variable, raising=False)

    from llm_factory import get_llm

    get_llm.cache_clear()
    with pytest.raises(ValueError) as error:
        get_llm("gemini")

    assert "GOOGLE_API_KEY" in str(error.value)
    assert "GEMINI_API_KEY" in str(error.value)


def test_proveedor_desconocido_lo_dice_con_las_opciones(monkeypatch):
    from llm_factory import get_llm

    get_llm.cache_clear()
    with pytest.raises(ValueError) as error:
        get_llm("modelo-magico")

    assert "modelo-magico" in str(error.value)
    assert "gemini" in str(error.value)


@pytest.mark.parametrize(
    "excepcion, esperado",
    [
        (type("ResourceExhausted", (Exception,), {})(), "cuota"),
        (type("RateLimitError", (Exception,), {})(), "cuota"),
        (type("Unauthenticated", (Exception,), {})(), "clave"),
        (type("APIConnectionError", (Exception,), {})(), "red"),
        (type("TimeoutError", (Exception,), {})(), "red"),
        (type("SomethingWeird", (Exception,), {})(), "falló la llamada al modelo"),
    ],
)
def test_el_traductor_de_errores_explica_el_tipo_de_problema(excepcion, esperado):
    mensaje = mensaje_de_error(excepcion)

    assert esperado in mensaje
    assert type(excepcion).__name__ in mensaje, "conviene saber qué excepción fue"


def test_las_variables_documentadas_son_las_que_usa_el_codigo():
    assert set(VARIABLES_DE_CLAVE) == {"gemini", "openai", "anthropic"}
    assert VARIABLES_DE_CLAVE["gemini"] == ("GOOGLE_API_KEY", "GEMINI_API_KEY")
