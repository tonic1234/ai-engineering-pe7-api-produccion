"""test_tools.py: las herramientas de los especialistas.

Dos cosas que se prueban acá:

1. La calculadora NO puede ejecutar código. El resultado de un LLM es texto: si le
   pasamos eso a eval() estamos regalando la máquina. La herramienta parsea con ast y
   solo permite aritmética.
2. La búsqueda en las políticas usa el RAG que le inyectemos (en los tests, un doble),
   así que la suite corre sin Pinecone ni embeddings.
"""

from __future__ import annotations

import tools


class RAGFalso:
    """Doble del RAGSystem: devuelve dos fragmentos fijos."""

    def __init__(self):
        self.consultas = []

    def obtener_top_k(self, pregunta):
        self.consultas.append(pregunta)
        return [
            {"contenido": "Vacaciones: 14 días con menos de 5 años.", "fuente": "politica_vacaciones.txt"},
            {"contenido": "Con 5 a 10 años: 21 días.", "fuente": "politica_vacaciones.txt"},
        ]


def test_calculadora_resuelve_la_expresion_del_caso():
    """3 años a 15 días + 5 años a 20 + 4 años a 25 = 245 (la cuenta de la demo)."""

    assert "245" in tools.calculadora.invoke({"expresion": "3*15 + 5*20 + 4*25"})


def test_calculadora_no_permite_codigo(tmp_path):
    """Los intentos clásicos tienen que devolver error y NO ejecutarse.

    La prueba de que no se ejecutó es un archivo que la expresión intentaría crear: si
    aparece, el código corrió.
    """

    bandera = tmp_path / "se_ejecuto"
    peligrosas = [
        f"__import__('os').system('touch {bandera}')",
        f"__import__('os').system('echo hackeado > {bandera}')",
        "open('/etc/passwd').read()",
        "(1).__class__.__bases__[0].__subclasses__()",
    ]
    for expresion in peligrosas:
        salida = tools.calculadora.invoke({"expresion": expresion})
        assert salida.startswith("Error al calcular"), expresion

    assert not bandera.exists()


def test_calculadora_devuelve_error_controlado_con_expresion_invalida():
    salida = tools.calculadora.invoke({"expresion": "5 + * 3"})
    assert salida.startswith("Error al calcular")


def test_busqueda_usa_el_rag_inyectado_y_cita_la_fuente():
    rag = RAGFalso()
    tools.set_rag(rag)
    try:
        salida = tools.buscar_en_politicas_internas.invoke({"pregunta": "¿cuántos días de vacaciones?"})
    finally:
        tools.set_rag(None)

    assert rag.consultas == ["¿cuántos días de vacaciones?"]
    assert "politica_vacaciones.txt" in salida
    assert "14 días" in salida


def test_busqueda_sin_resultados_lo_dice_en_vez_de_inventar():
    class RAGVacio(RAGFalso):
        def obtener_top_k(self, pregunta):
            return []

    tools.set_rag(RAGVacio())
    try:
        salida = tools.buscar_en_politicas_internas.invoke({"pregunta": "¿política de bonos?"})
    finally:
        tools.set_rag(None)

    assert "No se encontró" in salida
