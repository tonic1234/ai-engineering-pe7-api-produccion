"""Instrumentación de trazas con Arize Phoenix (OpenInference sobre OpenTelemetry).

Se elige Phoenix porque corre local: no hace falta cuenta ni clave, y los datos no salen del
servidor. Si no hay endpoint configurado NO se activa nada, pero se avisa por log: una corrida
sin trazas que parece andar bien es peor que un error (es el "éxito silencioso" del módulo).

La configuración arma el exportador a mano en vez de usar el atajo `phoenix.otel.register()`.
Con el atajo, el dashboard terminó con cientos de spans de `GET /tareas/<id>` (el polling del
cliente) y las trazas de los agentes enterradas entre ellos: acá se instrumenta sólo LangChain,
que es lo que interesa ver (modelo, herramientas y recuperación).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_ACTIVAS = False


def endpoint_configurado() -> bool:
    return bool(
        os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    )


def nombre_proyecto() -> str:
    return os.getenv("PHOENIX_PROJECT_NAME", "pre-entrega-7")


def trazas_activas() -> bool:
    return _ACTIVAS


def _instrumentar(endpoint: str) -> None:
    """Deja el proveedor de trazas apuntando a Phoenix e instrumenta LangChain."""
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Phoenix agrupa las trazas por proyecto leyendo este atributo del resource.
    recurso = Resource.create(
        {
            "openinference.project.name": nombre_proyecto(),
            "service.name": nombre_proyecto(),
        }
    )
    proveedor = TracerProvider(resource=recurso)
    proveedor.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(proveedor)

    LangChainInstrumentor().instrument(tracer_provider=proveedor)


def activar_trazas(endpoint: str | None = None) -> bool:
    """Activa la instrumentación. Devuelve si quedó activa de verdad."""
    global _ACTIVAS

    endpoint = endpoint or os.getenv("PHOENIX_COLLECTOR_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    if not endpoint:
        log.warning(
            "sin PHOENIX_COLLECTOR_ENDPOINT: esta corrida queda sin trazas (no se instrumenta nada)"
        )
        _ACTIVAS = False
        return False

    try:
        _instrumentar(endpoint)
        _ACTIVAS = True
        log.info("trazas activas: proyecto '%s' -> %s", nombre_proyecto(), endpoint)
    except Exception as error:  # noqa: BLE001: si Phoenix no está, el sistema tiene que seguir
        log.warning("no se pudo activar la instrumentación (%s): la corrida sigue sin trazas", error)
        _ACTIVAS = False

    return _ACTIVAS
