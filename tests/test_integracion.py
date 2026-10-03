"""test_integracion.py: el test que vale: el flujo completo, de punta a punta.

Corre el grafo REAL (el mismo que se usa con Gemini) pero con dobles en los tres lugares
donde habría red: el supervisor, los dos especialistas y el LLM de la síntesis.

Demuestra los tres criterios que pide la consigna:
1. la consulta obliga a delegar en el investigador, después en el analista y recién ahí cierra;
2. el estado compartido guarda QUIÉN aportó QUÉ (las dos contribuciones quedan);
3. hay un corte: con un supervisor que se empecina en delegar, el flujo termina igual.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from graph import build_app
from supervisor import MAX_PASOS, DecisionSupervisor, Supervisor


class LLMFalso:
    """Doble del LLM de síntesis."""

    def invoke(self, prompt):
        return AIMessage(content="RESPUESTA FINAL SINTETIZADA")


class AgenteInvestigadorFalso:
    def invoke(self, entrada):
        return {
            "messages": [
                AIMessage(
                    content="[Fuente: politica_vacaciones.txt] Menos de 3 años: 15 días; de 3 a 8 "
                    "años: 20 días; más de 8 años: 25 días."
                )
            ]
        }


class AgenteAnalistaFalso:
    def invoke(self, entrada):
        return {"messages": [AIMessage(content="Resultado: 250. Cuenta: 2*15 + 6*20 + 4*25.")]}


class LLMSupervisorFalso:
    """Supervisor planificado: investigador → analista → FINISH."""

    def __init__(self, plan):
        self.plan = list(plan)
        self.consultas = 0

    def with_structured_output(self, esquema):
        return self

    def invoke(self, mensajes):
        self.consultas += 1
        siguiente = self.plan.pop(0) if self.plan else "FINISH"
        return DecisionSupervisor(
            next=siguiente,
            instruccion=f"Hacé tu parte: {siguiente}",
            razon=f"decido {siguiente}",
        )


def correr(plan, pregunta="Un empleado cumplió 12 años: ¿cuántos días de vacaciones juntó?"):
    llm_supervisor = LLMSupervisorFalso(plan)
    app = build_app(
        llm=LLMFalso(),
        research_agent=AgenteInvestigadorFalso(),
        analyst_agent=AgenteAnalistaFalso(),
        supervisor=Supervisor(llm=llm_supervisor),
    )

    from langchain_core.messages import HumanMessage

    estado_inicial = {
        "messages": [HumanMessage(content=pregunta)],
        "next_agent": None,
        "contribuciones": [],
        "pasos": 0,
        "task_completed": False,
        "validacion": None,
    }
    return app.invoke(estado_inicial), llm_supervisor


def test_flujo_completo_investigador_analista_sintesis():
    resultado, _ = correr(["investigador", "analista"])

    agentes = [c["agente"] for c in resultado["contribuciones"]]
    assert agentes == ["investigador", "analista"]  # los dos dominios, en orden
    assert resultado["validacion"]["suficiente"] is True
    assert resultado["task_completed"] is True
    assert resultado["messages"][-1].content == "RESPUESTA FINAL SINTETIZADA"


def test_el_estado_deja_la_traza_de_quien_aporto_que():
    resultado, _ = correr(["investigador", "analista"])
    aportes = {c["agente"]: c["aporte"] for c in resultado["contribuciones"]}

    assert "15 días" in aportes["investigador"]
    assert aportes["investigador"].startswith("[Fuente: politica_vacaciones.txt]")
    assert aportes["analista"] == "Resultado: 250. Cuenta: 2*15 + 6*20 + 4*25."


def test_el_supervisor_infinito_tiene_corte():
    """Un supervisor que siempre delega al investigador no puede colgar el grafo."""

    resultado, _ = correr(["investigador"] * 20)

    assert resultado["task_completed"] is True
    assert resultado["messages"][-1].content == "RESPUESTA FINAL SINTETIZADA"
    assert len(resultado["contribuciones"]) <= MAX_PASOS


def test_el_grafo_corrige_al_supervisor_que_insiste_con_un_agente():
    """Aunque el supervisor se empecine, el dominio que falta se cubre igual."""

    resultado, _ = correr(["investigador"] * 20)

    dominios = {c["agente"] for c in resultado["contribuciones"]}
    assert dominios == {"investigador", "analista"}


def test_una_pregunta_de_un_solo_dominio_igual_termina():
    """Si el supervisor cierra de entrada, el validador manda a síntesis y no se cuelga."""

    resultado, _ = correr([], pregunta="¿Hola, quién sos?")
    assert resultado["messages"][-1].content == "RESPUESTA FINAL SINTETIZADA"
