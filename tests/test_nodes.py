"""test_nodes.py: los nodos que envuelven a los especialistas.

Lo importante acá es la "Contaminación de Contexto" que nombra el enunciado: al
especialista hay que pasarle la INSTRUCCIÓN puntual, no todo el historial. El test espía
lo que recibe el agente falso y verifica que llegue un solo mensaje.

Y en la síntesis: la respuesta final tiene que estar armada con los aportes de los dos
especialistas, no inventada de cero.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

import nodes


class AgenteFalso:
    """Doble de un agente creado con create_agent: guarda lo que recibe."""

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = []

    def invoke(self, entrada):
        self.llamadas.append(entrada)
        return {"messages": [AIMessage(content=self.respuesta)]}


class LLMFalso:
    def __init__(self, respuesta="RESPUESTA FINAL"):
        self.respuesta = respuesta
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.respuesta)


def estado_con_historial():
    from langchain_core.messages import HumanMessage

    return {
        "messages": [
            HumanMessage(content="PREGUNTA ORIGINAL"),
            AIMessage(content="aporte viejo del investigador", name="investigador"),
            HumanMessage(content="INSTRUCCIÓN PUNTUAL PARA EL ANALISTA"),
        ],
        "instruccion": "INSTRUCCIÓN PUNTUAL PARA EL ANALISTA",
        "contribuciones": [
            {"agente": "investigador", "aporte": "14 + 21 + 28 días por período"},
            {"agente": "analista", "aporte": "Resultado: 245"},
        ],
        "pasos": 2,
        "next_agent": "analista",
        "task_completed": False,
        "validacion": None,
        "reintentos": 0,
    }


def test_el_especialista_recibe_la_pregunta_la_instruccion_y_el_contexto_necesario():
    """Un mensaje: pregunta original + instrucción + aportes. NO todo el historial."""

    agente = AgenteFalso("Respuesta del analista")

    actualizacion = nodes.nodo_analista(estado_con_historial(), agente=agente)

    assert len(agente.llamadas) == 1
    mensajes_recibidos = agente.llamadas[0]["messages"]
    assert len(mensajes_recibidos) == 1

    contenido = mensajes_recibidos[0].content
    assert "Pregunta original: PREGUNTA ORIGINAL" in contenido
    assert "Instrucción del supervisor: INSTRUCCIÓN PUNTUAL PARA EL ANALISTA" in contenido
    assert "14 + 21 + 28 días por período" in contenido  # el dato que necesita el analista
    assert "aporte viejo del investigador" not in contenido  # el historial no se vuelca
    assert actualizacion["messages"][0].name == "analista"


def test_sin_instruccion_explicita_cae_al_ultimo_mensaje():
    agente = AgenteFalso("Respuesta")
    estado = estado_con_historial()
    estado["instruccion"] = None
    estado["contribuciones"] = []

    nodes.nodo_analista(estado, agente=agente)

    assert "INSTRUCCIÓN PUNTUAL PARA EL ANALISTA" in agente.llamadas[0]["messages"][0].content


def test_el_nodo_suma_su_contribucion_y_cuenta_el_paso():
    agente = AgenteFalso("Respuesta del investigador")
    estado = estado_con_historial()

    actualizacion = nodes.nodo_investigador(estado, agente=agente)

    assert actualizacion["contribuciones"][0]["agente"] == "investigador"
    assert actualizacion["contribuciones"][0]["aporte"] == "Respuesta del investigador"
    assert actualizacion["pasos"] == estado["pasos"] + 1


def test_la_sintesis_arma_la_respuesta_con_los_aportes():
    llm = LLMFalso()
    estado = estado_con_historial()

    actualizacion = nodes.nodo_sintesis(estado, llm=llm)

    prompt = str(llm.prompts[0])
    assert "PREGUNTA ORIGINAL" in prompt
    assert "14 + 21 + 28" in prompt  # aporte del investigador
    assert "245" in prompt  # aporte del analista
    assert actualizacion["messages"][0].content == "RESPUESTA FINAL"
    assert actualizacion["task_completed"] is True


class AgenteQueSeCae:
    """Especialista cuya llamada al modelo falla (cuota agotada, red caída...)."""

    def __init__(self, excepcion):
        self.excepcion = excepcion

    def invoke(self, entrada):
        raise self.excepcion


def test_un_especialista_que_falla_no_tumba_el_grafo():
    """Si el proveedor rechaza la llamada, el aporte vuelve como ERROR legible.

    El grafo no se cae: el supervisor ve un aporte en error y puede volver a delegar (o
    cerrar). El mensaje tiene que ser informativo, no un volcado de excepción.
    """

    agente = AgenteQueSeCae(type("ResourceExhausted", (Exception,), {})("cuota agotada"))

    actualizacion = nodes.nodo_analista(estado_con_historial(), agente=agente)

    aporte = actualizacion["contribuciones"][0]["aporte"]
    assert aporte.startswith("ERROR:")
    assert "cuota" in aporte
    assert "ResourceExhausted" in aporte
    assert actualizacion["pasos"] == estado_con_historial()["pasos"] + 1


def test_el_error_de_un_especialista_no_cuenta_como_aporte_valido():
    """Lo que el validador hace con ese aporte en error: lo deja como dominio sin cubrir."""

    from validation import validar_estado

    agente = AgenteQueSeCae(type("APIConnectionError", (Exception,), {})("sin red"))
    actualizacion = nodes.nodo_analista(estado_con_historial(), agente=agente)

    estado = estado_con_historial()
    estado["contribuciones"] = actualizacion["contribuciones"]
    # La pregunta pide una cuenta (el contexto de este test es el aporte del ANALISTA): sin
    # eso la rúbrica no exige ese dominio y no habría nada que validar.
    from langchain_core.messages import HumanMessage

    estado["messages"] = [HumanMessage(content="¿Cuántos días de vacaciones en total?")]

    informe = validar_estado(estado)
    assert informe["suficiente"] is False
    assert "analista" in informe["faltantes"]
