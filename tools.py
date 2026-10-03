"""tools.py: las herramientas acotadas de cada especialista.

La consigna pide "al menos una herramienta funcional" por agente y que cada uno tenga
herramientas ACOTADAS (que el investigador no calcule y el analista no investigue).

Dos herramientas, entonces:

1. `buscar_en_politicas_internas`: la del investigador. Consulta el vector DB de las
   pre-entregas anteriores (Pinecone/BM25) y devuelve los fragmentos CON su fuente.
2. `calculadora`: la del analista. Y acá está el detalle que importa: el argumento viene
   de un LLM, o sea que es texto de un tercero. Pasarle eso a `eval()` sería regalar la
   máquina (un `__import__('os').system(...)` alcanza). Por eso parseo la expresión con
   `ast` y solo habilito operaciones aritméticas: nada de nombres, llamadas ni atributos.
"""

from __future__ import annotations

import ast
import logging
import operator as op

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# El RAG se inyecta desde afuera (patrón chico pero clave): en producción es el
# RAGSystem real, en los tests un doble. Así la suite corre sin claves y sin red.
# ---------------------------------------------------------------------------
_rag = None


def set_rag(sistema) -> None:
    """Inyecta el recuperador (o None para volver al de producción)."""

    global _rag
    _rag = sistema


def get_rag():
    """Devuelve el recuperador: el inyectado o, si no hay, el real (import perezoso)."""

    global _rag
    if _rag is None:
        from rag import RAGSystem

        _rag = RAGSystem()
        # Se informa el modo REAL del recuperador en la primera búsqueda: si alguien corre la
        # demo sin Pinecone tiene que enterarse por pantalla, no por un resultado peor.
        logger.info("herramienta de búsqueda lista: recuperador %s", getattr(_rag, "modo", "?"))
    return _rag


# ---------------------------------------------------------------------------
# Herramienta 1: investigación
# ---------------------------------------------------------------------------
@tool
def buscar_en_politicas_internas(pregunta: str) -> str:
    """Busca información en las políticas internas de la empresa (vacaciones, teletrabajo,
    seguridad informática, onboarding). Usar SIEMPRE que haga falta un dato concreto de la
    empresa: reglas, plazos o números. No sirve para calcular.
    """

    fragmentos = get_rag().obtener_top_k(pregunta)
    if not fragmentos:
        return "No se encontró información relevante en las políticas internas."

    return "\n\n".join(f"[Fuente: {f['fuente']}] {f['contenido']}" for f in fragmentos)


# ---------------------------------------------------------------------------
# Herramienta 2: cálculo seguro
# ---------------------------------------------------------------------------
_OPERADORES_BINARIOS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
}

_OPERADORES_UNARIOS = {ast.USub: op.neg, ast.UAdd: op.pos}


def _evaluar_nodo(nodo) -> float:
    """Recorre el AST permitiendo solo números y operaciones aritméticas."""

    if isinstance(nodo, ast.Expression):
        return _evaluar_nodo(nodo.body)

    if isinstance(nodo, ast.Constant):
        if isinstance(nodo.value, (int, float)) and not isinstance(nodo.value, bool):
            return nodo.value
        raise ValueError("Solo se permiten números")

    if isinstance(nodo, ast.BinOp):
        operacion = _OPERADORES_BINARIOS.get(type(nodo.op))
        if operacion is None:
            raise ValueError(f"Operación no permitida: {type(nodo.op).__name__}")
        return operacion(_evaluar_nodo(nodo.left), _evaluar_nodo(nodo.right))

    if isinstance(nodo, ast.UnaryOp):
        operacion = _OPERADORES_UNARIOS.get(type(nodo.op))
        if operacion is None:
            raise ValueError(f"Operación unaria no permitida: {type(nodo.op).__name__}")
        return operacion(_evaluar_nodo(nodo.operand))

    # Nombres, llamadas, atributos, subíndices... todo esto queda afuera a propósito.
    raise ValueError(f"Expresión no permitida: {type(nodo).__name__}")


@tool
def calculadora(expresion: str) -> str:
    """Evalúa una expresión matemática con números (soporta +, -, *, /, **, % y paréntesis).
    Ejemplo: '5*14 + 5*21 + 2*28'. Usar SOLO con números que ya se tengan del contexto;
    no busca información nueva. Devuelve un mensaje de ERROR si la expresión no es válida.
    """

    try:
        resultado = _evaluar_nodo(ast.parse(expresion, mode="eval"))
        return f"Resultado: {resultado}"
    except Exception as exc:  # devuelvo el error como texto: el agente lo lee y decide
        return f"Error al calcular '{expresion}': {exc}"
