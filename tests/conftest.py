"""conftest.py: deja el entorno listo para que los tests corran SIN claves y SIN red.

Los tests no llaman a Gemini ni a Pinecone: inyectan dobles (fakes) en los nodos. Igual
fijamos valores dummy para que cualquier import que lea el entorno no explote.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

os.environ.setdefault("GOOGLE_API_KEY", "test-key")
os.environ.setdefault("LLM_PROVIDER", "gemini")

# La suite promete correr SIN claves: saco la de Pinecone aunque esté en el entorno, así
# ninguna prueba puede terminar pegándole a la nube por accidente (el repo no la necesita
# para testear: el recuperador tiene dobles).
os.environ.pop("PINECONE_API_KEY", None)


@pytest.fixture
def estado_base():
    """Estado inicial mínimo, como el que se le pasa al grafo."""

    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content="¿Cuántos días de vacaciones juntó un empleado con 12 años?")],
        "next_agent": None,
        "instruccion": None,
        "contribuciones": [],
        "pasos": 0,
        "task_completed": False,
        "validacion": None,
        "reintentos": 0,
    }
