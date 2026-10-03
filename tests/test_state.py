"""test_state.py: el estado compartido.

Lo que se prueba: que las contribuciones de los especialistas se ACUMULEN en vez de
pisarse. Es justo el punto que pide la consigna ("evitar la pérdida de contexto en la
comunicación asíncrona"): si el reducer estuviera mal, el aporte del investigador
desaparecería cuando el analista escribe el suyo.
"""

from __future__ import annotations

import operator
from typing import get_args, get_type_hints

from langgraph.graph import MessagesState

from state import AgentState, contribucion


def test_hereda_de_messages_state():
    """No se puede usar issubclass (TypedDict no lo soporta): comparo el reducer heredado."""

    def reducer(tipo):
        return get_args(get_type_hints(tipo, include_extras=True)["messages"])[1]

    assert "messages" in AgentState.__annotations__
    assert reducer(AgentState) is reducer(MessagesState)


def test_campos_extra_que_pide_la_consigna():
    hints = get_type_hints(AgentState, include_extras=True)
    assert "next_agent" in hints
    assert "task_completed" in hints


def test_contribuciones_se_acumulan_y_no_se_pisan():
    hints = get_type_hints(AgentState, include_extras=True)
    anotacion = hints["contribuciones"]

    # El reducer tiene que ser operator.add (el "sumador" de listas de Python).
    assert operator.add in get_args(anotacion)

    aporte_investigador = [contribucion("investigador", "14 días con menos de 5 años")]
    aporte_analista = [contribucion("analista", "Resultado: 287")]
    acumulado = operator.add(aporte_investigador, aporte_analista)

    assert len(acumulado) == 2
    assert [c["agente"] for c in acumulado] == ["investigador", "analista"]


def test_contribucion_tiene_las_dos_claves():
    aporte = contribucion("investigador", "algo")
    assert set(aporte) == {"agente", "aporte"}
