"""state.py: el estado compartido del orquestador.

La consigna pide un esquema que permita "rastrear qué agente contribuyó con qué
información, evitando la pérdida de contexto en la comunicación asíncrona".

Dos decisiones que se explican solas:

1. Heredo de MessagesState (LangGraph) porque ya trae `messages` con su reducer
   `add_messages`: no quiero reimplementar el manejo del historial.
2. `contribuciones` es una LISTA con reducer `operator.add`. Ese es el punto: si un nodo
   escribiera `{"contribuciones": [...]}` sin el reducer, su aporte PISARÍA el del
   especialista anterior y el supervisor perdería de vista quién dijo qué. Con el reducer,
   cada devolución se SUMA a la lista que ya estaba.

Nota: no uso `from __future__ import annotations` a propósito, para que las anotaciones
sean objetos reales (así los tests pueden leer el reducer del tipo).
"""

import operator
from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph import MessagesState


def contribucion(agente: str, aporte: str) -> Dict[str, str]:
    """Formato único de un aporte: quién lo dijo y qué dijo."""

    return {"agente": agente, "aporte": aporte}


class AgentState(MessagesState):
    """Estado que viaja por todo el grafo."""

    # A quién decidió llamar el supervisor en este turno ("investigador", "analista" o "FINISH").
    next_agent: Optional[str]

    # La instrucción puntual que el supervisor le dejó al especialista elegido.
    instruccion: Optional[str]

    # Registro acumulativo de aportes (el reducer operator.add es lo que evita que se pisen).
    contribuciones: Annotated[List[Dict[str, str]], operator.add]

    # Cuántos especialistas corrieron: es el contador del corte contra el "Supervisor Infinito".
    pasos: int

    # Se prende cuando el validador da el visto bueno (o cuando el flujo llegó a la síntesis).
    task_completed: bool

    # Informe del nodo de validación (suficiente, faltantes, motivo...).
    validacion: Optional[Dict[str, Any]]

    # Cuántas veces el validador mandó a refinar: la segunda red del corte.
    reintentos: int
