"""nodes.py: los nodos que envuelven a los especialistas y el de la síntesis final.

Dos decisiones que se explican en el README:

1. CONTEXTO ACOTADO (anti "Contaminación de Contexto"): a cada especialista le paso solo
   el ÚLTIMO mensaje, que es la instrucción puntual, no el historial completo. Si le
   mandara toda la conversación, el especialista tendría que adivinar qué parte le toca.
2. Cada nodo devuelve su aporte al estado compartido (`contribuciones`) y suma un paso:
   así el supervisor puede ver quién aportó qué y el corte por pasos tiene con qué contar.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage

from llm_factory import mensaje_de_error, texto
from state import contribucion


def _instruccion(state) -> str:
    """La instrucción puntual que el supervisor le dejó al especialista.

    Primero la instrucción explícita del supervisor. Si por algún motivo no hay, cae al
    último mensaje del estado (comportamiento mínimo).
    """

    explicita = (state.get("instruccion") or "").strip()
    if explicita:
        return explicita

    mensajes = state.get("messages") or []
    if not mensajes:
        return ""
    ultimo = mensajes[-1]
    return texto(ultimo.content if hasattr(ultimo, "content") else ultimo)


def _pregunta_original(state) -> str:
    """La pregunta del usuario: el especialista la necesita para saber QUÉ calcular."""

    mensajes = state.get("messages") or []
    if not mensajes:
        return ""
    primero = mensajes[0]
    return texto(primero.content if hasattr(primero, "content") else primero)


def _contexto_aportes(state) -> str:
    """Los aportes que ya hay, en formato compacto.

    Esto es el "contexto necesario" del que habla la consigna: el analista necesita los
    NÚMEROS que trajo el investigador, pero no necesita la conversación entera ni la
    metadata del sistema. Solo los aportes, uno por línea.
    """

    aportes = state.get("contribuciones") or []
    return "\n".join(f"- [{c.get('agente')}] {texto(c.get('aporte', ''))}" for c in aportes)


def _correr_especialista(agente, state, nombre: str) -> dict:
    """Le pasa al especialista la pregunta, su instrucción y los aportes; guarda su aporte.

    Nota de diseño (aprendida en la corrida real): el contexto acotado NO puede quedarse
    afuera la pregunta original. Sin ella, el analista no sabe cuántos años tiene el
    colaborador y contesta que le falta un número. Acotado quiere decir "sin el historial
    completo ni la metadata del sistema", no "sin el pedido del usuario".
    """

    bloques = []
    pregunta = _pregunta_original(state)
    if pregunta:
        bloques.append(f"Pregunta original: {pregunta}")
    bloques.append(f"Instrucción del supervisor: {_instruccion(state)}")

    contexto = _contexto_aportes(state)
    if contexto:
        bloques.append(f"Contexto disponible (aportes del equipo hasta ahora):\n{contexto}")

    contenido = "\n\n".join(bloques)

    # Un especialista que se cae no puede tumbar el grafo: si la llamada al modelo falla, el
    # aporte vuelve marcado como ERROR (con el mensaje traducido por `mensaje_de_error`, no
    # con un volcado de excepción) y el supervisor decide si lo manda de nuevo o cierra. Es
    # el mismo camino que ya usaba el validador para detectar un aporte inservible.
    try:
        resultado = agente.invoke({"messages": [HumanMessage(content=contenido)]})
    except Exception as exc:  # noqa: BLE001 - se traduce a un mensaje legible, ver arriba
        respuesta = f"ERROR: {mensaje_de_error(exc)}"
    else:
        respuesta = texto(resultado["messages"][-1])

    return {
        "messages": [AIMessage(content=respuesta, name=nombre)],
        "contribuciones": [contribucion(nombre, respuesta)],
        "pasos": (state.get("pasos", 0) or 0) + 1,
    }


def nodo_investigador(state, agente=None) -> dict:
    """Nodo del especialista en búsqueda."""

    if agente is None:
        from agents.research_agent import build_research_agent

        agente = build_research_agent()
    return _correr_especialista(agente, state, "investigador")


def nodo_analista(state, agente=None) -> dict:
    """Nodo del especialista en cálculo."""

    if agente is None:
        from agents.analyst_agent import build_analyst_agent

        agente = build_analyst_agent()
    return _correr_especialista(agente, state, "analista")


def nodo_sintesis(state, llm=None) -> dict:
    """Nodo final: combina los aportes en UNA respuesta para el usuario."""

    if llm is None:
        from llm_factory import get_llm

        llm = get_llm()

    mensajes = state.get("messages") or []
    pregunta_original = texto(mensajes[0].content if mensajes else "")

    aportes = "\n".join(
        f"- [{c.get('agente')}] {texto(c.get('aporte', ''))}" for c in (state.get("contribuciones") or [])
    )
    if not aportes:
        aportes = "(el equipo no produjo aportes)"

    informe = state.get("validacion") or {}
    faltantes = informe.get("faltantes") or []
    aviso = ""
    if faltantes:
        aviso = (
            f"\n\nAclaración: no se pudo completar el aporte de {', '.join(faltantes)}, "
            "así que la respuesta se arma solo con lo que sí hay."
        )

    prompt = (
        f"Pregunta original: {pregunta_original}\n\n"
        f"Aportes del equipo:\n{aportes}\n\n"
        "Redactá la respuesta final para el usuario, clara y breve, combinando esos aportes. "
        "Si algún dato no está, decilo; no inventes números."
        f"{aviso}"
    )
    respuesta = llm.invoke(prompt)

    return {
        "messages": [AIMessage(content=texto(respuesta), name="supervisor")],
        "task_completed": True,
    }
