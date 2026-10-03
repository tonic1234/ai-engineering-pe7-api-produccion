"""llm_factory.py: el modelo, elegido por variable de entorno.

Misma idea que en las pre-entregas anteriores: el código de negocio no importa SDKs. Acá
se construye el chat model según LLM_PROVIDER (gemini por defecto, que tiene free tier y
es el camino con el que el repo corre sin tarjeta).

Ojo con el import perezoso: construir ChatGoogleGenerativeAI sin clave en el entorno
falla en el __init__. Si eso pasara al importar el módulo, la suite de tests (que corre
sin claves) no podría ni colectar.
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# Los scripts tienen que poder correrse solos: sin esto, `python main.py` no ve el .env.
load_dotenv()

# Qué variable de entorno necesita cada proveedor. Se valida ACÁ, antes de construir el
# cliente: sin esto, la falta de clave aparecía recién como un error opaco del SDK (o, peor,
# el script seguía como si nada y degradaba en silencio).
VARIABLES_DE_CLAVE = {
    "gemini": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
}

# Errores conocidos de los SDK, agrupados por nombre de clase. Prefiero mirar el NOMBRE de la
# excepción y no importar los tipos de cada proveedor: así el mismo traductor sirve para los
# tres SDK sin acoplar el código a sus versiones.
ERRORES_POR_CUOTA = ("RateLimit", "ResourceExhausted", "TooManyRequests", "QuotaExceeded")
ERRORES_POR_CLAVE = ("Authentication", "PermissionDenied", "Unauthenticated", "InvalidAPIKey", "APIKeyInvalid")
ERRORES_DE_RED = ("Connection", "Timeout", "ServiceUnavailable", "DeadlineExceeded", "InternalServerError")


def mensaje_de_error(exc: Exception) -> str:
    """Traduce una excepción del SDK a una frase accionable (sin volcar el stacktrace)."""

    nombre = type(exc).__name__
    detalle = str(exc).replace("\n", " ")[:180]

    if any(fragmento in nombre for fragmento in ERRORES_POR_CUOTA):
        return (
            f"el proveedor rechazó la llamada por cuota o límite de uso ({nombre}). "
            f"Volvé a intentar en unos minutos. Detalle: {detalle}"
        )
    if any(fragmento in nombre for fragmento in ERRORES_POR_CLAVE):
        return (
            f"la clave del proveedor fue rechazada ({nombre}). Revisá la variable de entorno "
            f"en el .env. Detalle: {detalle}"
        )
    if any(fragmento in nombre for fragmento in ERRORES_DE_RED):
        return f"no se pudo llegar al modelo por un problema de red ({nombre}). Detalle: {detalle}"
    return f"falló la llamada al modelo ({nombre}): {detalle}"


@lru_cache(maxsize=None)
def get_llm(provider: str | None = None):
    """Devuelve el chat model del proveedor pedido (o del que diga el entorno)."""

    proveedor = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()

    variables = VARIABLES_DE_CLAVE.get(proveedor)
    if variables is None:
        raise ValueError(
            f"Proveedor no soportado: {proveedor}. Opciones: {', '.join(sorted(VARIABLES_DE_CLAVE))}."
        )
    if not any(os.getenv(variable) for variable in variables):
        raise ValueError(
            f"Falta {' o '.join(variables)} para usar {proveedor}. Copiá .env.example a .env y "
            "completá la clave (la de Gemini se saca gratis en aistudio.google.com/apikey)."
        )

    if proveedor == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=os.getenv("GEMINI_MODEL", "gemini-flash-latest"),
            temperature=0,
        )

    if proveedor == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)

    if proveedor == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest"), temperature=0)

    # No hay rama de "proveedor no soportado" acá: la validación de arriba (VARIABLES_DE_CLAVE)
    # ya cortó con un mensaje claro antes de llegar a este punto.
    raise AssertionError("rama inalcanzable: revisar VARIABLES_DE_CLAVE")


def texto(mensaje) -> str:
    """Normaliza el contenido de un mensaje a texto plano.

    Gemini no siempre devuelve un string: puede venir una LISTA de bloques
    ([{'type': 'text', 'text': '...', 'extras': {...}}]). Sin normalizar, la respuesta se
    imprime como una lista de diccionarios con metadata interna del proveedor.
    """

    contenido = getattr(mensaje, "content", mensaje)
    if isinstance(contenido, str):
        return contenido
    if isinstance(contenido, list):
        partes = []
        for bloque in contenido:
            if isinstance(bloque, dict):
                partes.append(bloque.get("text", ""))
            else:
                partes.append(str(bloque))
        return "".join(partes).strip()
    return str(contenido)
