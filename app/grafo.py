"""El grafo de producción: el mismo orquestador de la pre-entrega 6 + la aprobación humana.

La topología de PE6 no se toca: acá se le mete un nodo de más entre el supervisor y el
especialista. El supervisor decide a quién delegar (eso ya estaba); antes de que la tarea se
ejecute, el nodo de aprobación mira si la instrucción pide una acción con efecto y, si la pide,
PAUSA el grafo y espera una respuesta de afuera.

    START ─▶ supervisor ─┬─▶ aprobacion ─┬─▶ investigador ─┐
                         │               ├─▶ analista ─────┤
                         │               └─▶ sintesis      │  (si la rechazan, cierra)
                         └─▶ validacion ─┬─▶ sintesis ─▶ END
                                         └─▶ supervisor
"""

from __future__ import annotations

from functools import partial
from typing import Literal, Optional

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from nodes import nodo_analista, nodo_investigador, nodo_sintesis
from state import AgentState
from supervisor import Supervisor, nodo_supervisor
from validation import nodo_validador

from app.hitl import es_critica

MAX_REINTENTOS = 2


class EstadoProduccion(AgentState, total=False):
    """El estado de PE6 más lo que necesita saber el control humano."""

    aprobacion_rechazada: bool
    aprobado_en_el_hilo: bool


def _pregunta_del_usuario(state) -> str:
    for mensaje in state.get("messages") or []:
        if isinstance(mensaje, HumanMessage):
            contenido = mensaje.content
            return contenido if isinstance(contenido, str) else str(contenido)
    return ""


def nodo_aprobacion(state, costo_estimado: float | None = None) -> dict:
    """Pausa el grafo si lo que se va a hacer es crítico. Si no, deja pasar sin tocar nada.

    La aprobación se pide UNA vez por trabajo: si ya se aprobó, las rondas siguientes del
    supervisor pasan de largo. (Sin esto, el grafo volvía a pedir permiso en cada ronda: el
    pedido original sigue diciendo "publicá" y nunca se terminaba.)
    """

    decision = state.get("next_agent")
    if decision not in ("investigador", "analista"):
        return {}  # el supervisor quiere cerrar: no hay acción que aprobar

    if state.get("aprobado_en_el_hilo"):
        return {}

    # Se mira la instrucción que redactó el supervisor Y lo que pidió la persona: si el pedido
    # original es "publicá el resumen...", la acción es sensible aunque la instrucción la
    # reformule el supervisor.
    a_evaluar = f"{state.get('instruccion') or ''} {_pregunta_del_usuario(state)}"
    critica, motivo = es_critica(a_evaluar, costo_estimado)
    if not critica:
        return {}

    respuesta = interrupt(
        {
            "esperando": "aprobacion_humana",
            "agente": decision,
            "instruccion": state.get("instruccion"),
            "motivo": motivo,
        }
    )
    aprobado = respuesta.get("aprobado") if isinstance(respuesta, dict) else bool(respuesta)

    if aprobado:
        return {"aprobado_en_el_hilo": True}

    return {
        "aprobacion_rechazada": True,
        "task_completed": True,
        "validacion": {
            "suficiente": True,
            "motivo": "la persona que revisa rechazó la acción propuesta",
        },
    }


def enrutar(state) -> Literal["aprobacion", "validacion"]:
    """Del supervisor al nodo de aprobación (que después sigue al especialista)."""

    return "aprobacion"


def tras_aprobacion(state) -> Literal["investigador", "analista", "sintesis", "validacion"]:
    """Qué se hace después de la aprobación: seguir con el especialista o cerrar."""

    if state.get("aprobacion_rechazada"):
        return "sintesis"
    decision = state.get("next_agent")
    if decision in ("investigador", "analista"):
        return decision
    return "validacion"


def ruta_tras_validacion(state) -> Literal["sintesis", "supervisor"]:
    """Igual que en PE6: cierra si la rúbrica se cumple o si se agotaron las redes de corte."""

    informe = state.get("validacion") or {}
    if informe.get("suficiente"):
        return "sintesis"
    if (state.get("pasos", 0) or 0) >= 6:
        return "sintesis"
    if (state.get("reintentos", 0) or 0) >= MAX_REINTENTOS:
        return "sintesis"
    if not (state.get("contribuciones") or []):
        return "sintesis"
    return "supervisor"


def construir_grafo(
    llm=None,
    research_agent=None,
    analyst_agent=None,
    supervisor: Optional[Supervisor] = None,
    checkpointer=None,
    costo_estimado: float | None = None,
):
    """Arma y compila el grafo con el nodo de aprobación y los checkpoints en Redis."""

    grafo = StateGraph(EstadoProduccion)

    supervisor = supervisor or Supervisor()
    grafo.add_node("supervisor", partial(nodo_supervisor, supervisor=supervisor))
    grafo.add_node("aprobacion", partial(nodo_aprobacion, costo_estimado=costo_estimado))
    grafo.add_node("investigador", partial(nodo_investigador, agente=research_agent))
    grafo.add_node("analista", partial(nodo_analista, agente=analyst_agent))
    grafo.add_node("validacion", nodo_validador)
    grafo.add_node("sintesis", partial(nodo_sintesis, llm=llm))

    grafo.add_edge(START, "supervisor")
    grafo.add_edge("supervisor", "aprobacion")
    grafo.add_conditional_edges(
        "aprobacion",
        tras_aprobacion,
        {
            "investigador": "investigador",
            "analista": "analista",
            "sintesis": "sintesis",
            "validacion": "validacion",
        },
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
    return app.get_graph().draw_mermaid()
