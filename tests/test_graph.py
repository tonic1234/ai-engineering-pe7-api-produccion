"""test_graph.py: el armado del grafo.

Se prueban los dos mapeos que son fuente clásica de errores en LangGraph:
- la decisión del supervisor (que habla en nombres de agentes, o dice FINISH) tiene que
  transformarse en el nombre REAL del nodo;
- después de validar, hay que decidir si se cierra o si el supervisor pide un refinamiento.
"""

from __future__ import annotations

from graph import build_app, enrutar, ruta_tras_validacion


def test_finish_va_al_nodo_de_validacion():
    assert enrutar({"next_agent": "FINISH"}) == "validacion"
    assert enrutar({"next_agent": None}) == "validacion"


def test_los_agentes_van_a_su_nodo():
    assert enrutar({"next_agent": "investigador"}) == "investigador"
    assert enrutar({"next_agent": "analista"}) == "analista"


def test_validacion_suficiente_cierra_en_sintesis():
    estado = {"validacion": {"suficiente": True}, "pasos": 2}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_validacion_incompleta_vuelve_al_supervisor():
    estado = {
        "validacion": {"suficiente": False},
        "pasos": 1,
        "reintentos": 0,
        "contribuciones": [{"agente": "investigador", "aporte": "solo el dato, sin calcular"}],
    }
    assert ruta_tras_validacion(estado) == "supervisor"


def test_sin_ningun_aporte_no_tiene_sentido_mandarlo_de_nuevo():
    """Si el supervisor quiso cerrar sin que nadie aportara, se sintetiza y listo."""

    estado = {"validacion": {"suficiente": False}, "pasos": 0, "reintentos": 0, "contribuciones": []}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_demasiados_reintentos_cierran_igual():
    from graph import MAX_REINTENTOS

    estado = {
        "validacion": {"suficiente": False},
        "pasos": 2,
        "reintentos": MAX_REINTENTOS,
        "contribuciones": [{"agente": "investigador", "aporte": "algo"}],
    }
    assert ruta_tras_validacion(estado) == "sintesis"


def test_el_corte_por_max_pasos_cierra_igual():
    """Aunque el validador diga que falta, si se agotaron los pasos no se sigue iterando."""

    from supervisor import MAX_PASOS

    estado = {"validacion": {"suficiente": False}, "pasos": MAX_PASOS}
    assert ruta_tras_validacion(estado) == "sintesis"


def test_el_grafo_compila_con_los_nodos_y_el_ciclo():
    app = build_app(
        llm=None,
        research_agent=None,
        analyst_agent=None,
        supervisor=None,
        solo_topologia=True,
    )
    nodos = set(app.get_graph().nodes)
    assert {"supervisor", "investigador", "analista", "validacion", "sintesis"} <= nodos

    aristas = {(a.source, a.target) for a in app.get_graph().edges}
    # el ciclo: cada especialista vuelve al supervisor
    assert ("investigador", "supervisor") in aristas
    assert ("analista", "supervisor") in aristas
    assert ("validacion", "sintesis") in aristas
