"""agents/analyst_agent.py: el especialista en análisis/cómputo.

Es el segundo dominio del equipo, y el que hace que la consulta de la demo necesite a los
dos: el investigador trae los números de la política, y el analista los convierte en el
resultado (por ejemplo, cuántos días de vacaciones se acumulan).

Igual que el investigador, tiene UNA herramienta acotada: la calculadora segura. Si se
equivoca (o el resultado no alcanza), el supervisor lo puede mandar de nuevo a refinar:
eso es lo que pide la consigna como "flujo de supervisión".
"""

from __future__ import annotations

from tools import calculadora

ANALISTA_PROMPT = (
    "Sos el especialista en análisis y cálculo de un equipo. Tu única función es hacer "
    "cuentas con la herramienta calculadora, a partir de los números que ya están en el "
    "contexto.\n\n"
    "Cómo trabajás:\n"
    "- Armá la expresión matemática completa y pasásela a la calculadora.\n"
    "- No busques información nueva: si falta un número, respondé que falta y pedí el dato.\n"
    "- Si la instrucción que recibís te pide algo que NO es calcular (por ejemplo buscar o "
    "transcribir un documento), no lo hagas: calculá igual la cuenta que responde la "
    "pregunta original con los números que tengas en el contexto.\n"
    "- Devolvé SIEMPRE la salida de la calculadora tal cual, empezando con 'Resultado: ' "
    "(así el validador puede comprobar que el número salió de la herramienta y no de tu "
    "cabeza), y agregá en una línea qué cuenta hiciste.\n"
    "- Si la calculadora devuelve un error, no adivines: respondé empezando con 'ERROR:'."
)


def build_analyst_agent(llm=None):
    """Arma el agente de análisis con su herramienta acotada."""

    from langchain.agents import create_agent

    if llm is None:
        from llm_factory import get_llm

        llm = get_llm()

    return create_agent(
        model=llm,
        tools=[calculadora],
        system_prompt=ANALISTA_PROMPT,
    )
