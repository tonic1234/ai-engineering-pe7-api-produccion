"""agents/research_agent.py: el especialista en investigación.

Es el agente que va a buscar los datos a la fuente externa. Sus características:

- tiene UNA herramienta acotada (buscar en las políticas internas): herramientas acotadas
  es lo que pide la consigna, y además es lo que evita que el agente se ponga a calcular;
- el system prompt le marca el límite: su trabajo es traer el dato con su fuente, no
  cerrar la respuesta. El que decide si alcanza es el supervisor.

Uso `create_agent` de LangChain (los agentes de esta versión de LangChain construidos
sobre LangGraph). Queda todo el ciclo ReAct adentro del nodo: el agente puede llamar a la
herramienta las veces que necesite.
"""

from __future__ import annotations

from tools import buscar_en_politicas_internas

INVESTIGADOR_PROMPT = (
    "Sos el especialista en investigación de un equipo. Tu única función es buscar datos "
    "concretos de la empresa (políticas internas de vacaciones, teletrabajo, seguridad "
    "informática y onboarding) usando tu herramienta de búsqueda.\n\n"
    "Cómo trabajás:\n"
    "- Hacé la búsqueda con los términos del pedido y devolvé los datos LITERALES que "
    "encuentres, con la fuente entre corchetes tal como te llegan.\n"
    "- No hagas cálculos: si el pedido pide una cuenta, devolvé los números y nada más.\n"
    "- Si la búsqueda no devuelve nada, respondé empezando con 'ERROR:' y explicá qué "
    "término buscaste. No inventes datos ni completes con suposiciones.\n"
    "- Contestá en pocas líneas: el dato y la fuente."
)


def build_research_agent(llm=None):
    """Arma el agente de investigación con su herramienta acotada."""

    from langchain.agents import create_agent

    if llm is None:
        from llm_factory import get_llm

        llm = get_llm()

    return create_agent(
        model=llm,
        tools=[buscar_en_politicas_internas],
        system_prompt=INVESTIGADOR_PROMPT,
    )
