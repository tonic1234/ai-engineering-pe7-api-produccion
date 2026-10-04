"""El README y la suite tienen que decir lo mismo.

El profe lo pidió en la devolución de la pre-entrega 6: el número de pruebas que anuncia el
README tiene que ser el que realmente se ejecuta. En vez de confiar en la memoria, este test
cuenta la colección real de pytest y la compara con la del README.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _declarado_en_el_readme() -> int:
    texto = (RAIZ / "README.md").read_text(encoding="utf-8")
    coincidencia = re.search(r"## Las pruebas \((\d+)", texto)
    assert coincidencia, "el README tiene que tener la sección '## Las pruebas (N, ...)'"
    return int(coincidencia.group(1))


def _coleccion_real() -> int:
    salida = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
        cwd=RAIZ, capture_output=True, text=True, timeout=300,
    )
    coincidencia = re.search(r"(\d+)\s+tests?\s+collected", salida.stdout)
    assert coincidencia, f"no se pudo leer el total de la colección:\n{salida.stdout[-800:]}"
    return int(coincidencia.group(1))


def test_el_numero_del_readme_es_el_real():
    assert _declarado_en_el_readme() == _coleccion_real()
