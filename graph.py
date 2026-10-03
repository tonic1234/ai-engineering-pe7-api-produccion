"""graph.py: el armado del grafo (la topología jerárquica).

    START ──▶ supervisor ──┬──▶ investigador ──┐
              ▲            ├──▶ analista ──────┤   (los especialistas SIEMPRE vuelven
              │            └──▶ validacion     │    al supervisor: ahí está el ciclo)
              │                  │            │
              └──────────────────┘            │
                            (si falta algo)
                                 │
                                 ▼
                              sintesis ──▶ END

Por qué esta topología: el supervisor es el único que habla con el usuario y el único que
decide; los especialistas no se conocen entre sí (no hay arista investigador→analista), así
que no hay dos agentes negociando quién sigue. Eso es lo que la consigna llama topología
jerárquica, y es lo que evita los conflictos entre agentes: el orden lo fija un solo nodo,
que además es el que ve las contribuciones acumuladas.

Tres redes contra el "Supervisor Infinito":
1. el supervisor corta solo si `pasos >= MAX_PASOS` (supervisor.py);
2. el validador determinista decide si la rúbrica se cumple (validation.py);
3. `ruta_tras_validacion` cierra igual si se agotaron los pasos, si ya se reintentó
   demasiadas veces o si el supervisor quiere cerrar sin que nadie haya aportado nada.
"""

from __future__ import annotations

from functools import partial
from typing import Literal, Optional

from langgraph.graph import END, START, StateGraph

from nodes import nodo_analista, nodo_investigador, nodo_sintesis
from state import AgentState
from supervisor import MAX_PASOS, Supervisor, nodo_supervisor
from validation import nodo_validador

# Cuántas veces el validador puede mandar a refinar antes de cerrar igual.
MAX_REINTENTOS = 2


def enrutar(state) -> Literal["investigador", "analista", "validacion"]:
    """Traduce la decisión del supervisor al NOMBRE REAL del nodo siguiente.

    El supervisor contesta en su vocabulario ("investigador", "analista", "FINISH"): acá
    FINISH se convierte en el nodo de validación, que es el que decide de verdad si se
    cierra. Si esto no se mapeara, LangGraph fallaría con "unknown target".
    """

    decision = state.get("next_agent")
    if decision in ("investigador", "analista"):
        return decision
    return "validacion"


def ruta_tras_validacion(state) -> Literal["sintesis", "supervisor"]:
    """Decide si se cierra o si el supervisor pide un refinamiento."""

    informe = state.get("validacion") or {}
    if informe.get("suficiente"):
        return "sintesis"

    # Redes de corte: agotó pasos, ya reintentó, o el supervisor quiso cerrar sin aportes.
    if (state.get("pasos", 0) or 0) >= MAX_PASOS:
        return "sintesis"
    if (state.get("reintentos", 0) or 0) >= MAX_REINTENTOS:
        return "sintesis"
    if not (state.get("contribuciones") or []):
        return "sintesis"

    return "supervisor"


def _sin_implementar(nombre: str):
    """Nodo de relleno: se usa solo cuando se pide el grafo sin agentes (tests de topología)."""

    def _nodo(state):  # pragma: no cover - nunca se ejecuta en ese modo
        raise RuntimeError(f"El nodo '{nombre}' no se puede ejecutar: el grafo se armó solo como topología")

    return _nodo


def build_app(
    llm=None,
    research_agent=None,
    analyst_agent=None,
    supervisor: Optional[Supervisor] = None,
    checkpointer=None,
    solo_topologia: bool = False,
):
    """Arma y compila el grafo.

    `solo_topologia=True` deja los nodos vacíos: sirve para inspeccionar la topología
    (los tests de aristas) sin construir agentes ni tocar la red.
    """

    grafo = StateGraph(AgentState)

    if solo_topologia:
        grafo.add_node("supervisor", _sin_implementar("supervisor"))
        grafo.add_node("investigador", _sin_implementar("investigador"))
        grafo.add_node("analista", _sin_implementar("analista"))
    else:
        supervisor = supervisor or Supervisor()
        grafo.add_node("supervisor", partial(nodo_supervisor, supervisor=supervisor))
        grafo.add_node("investigador", partial(nodo_investigador, agente=research_agent))
        grafo.add_node("analista", partial(nodo_analista, agente=analyst_agent))

    grafo.add_node("validacion", nodo_validador)
    grafo.add_node("sintesis", partial(nodo_sintesis, llm=llm))

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges(
        "supervisor",
        enrutar,
        {"investigador": "investigador", "analista": "analista", "validacion": "validacion"},
    )
    grafo.add_edge("investigador", "supervisor")
    grafo.add_edge("analista", "supervisor")
    grafo.add_conditional_edges(
        "validacion",
        ruta_tras_validacion,
        {"supervisor": "supervisor", "sintesis": "sintesis"},
    )
    grafo.add_edge("sintesis", END)

    return grafo.compile(checkpointer=checkpointer)


def diagrama_mermaid(app) -> str:
    """Devuelve el diagrama del grafo en Mermaid (va en el README)."""

    return app.get_graph().draw_mermaid()
