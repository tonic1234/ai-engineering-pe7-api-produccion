"""test_ingest.py: el script que puebla el índice.

No toca la red: prueba las dos cosas que pueden romper el índice sin que nadie se entere.

- Los ids de los chunks tienen que ser DETERMINISTAS (mismo dataset → mismos ids). Si no lo
  fueran, cada corrida del ingestor duplicaría vectores en Pinecone.
- Sin la clave tiene que CORTAR con un mensaje claro. Esto es a propósito: en la devolución
  de la pre-entrega 4 me marcaron que degradar en silencio "puede enmascarar errores de
  configuración", y un ingestor que sigue sin clave deja el índice a medio actualizar.
"""

from __future__ import annotations

import pytest

from ingest import _exigir_clave, ids_de_chunks
from rag import chunk_documents, load_dataset


def test_los_ids_son_deterministas_y_unicos():
    ids_una_vez = ids_de_chunks(chunk_documents(load_dataset()))
    ids_otra_vez = ids_de_chunks(chunk_documents(load_dataset()))

    assert ids_una_vez == ids_otra_vez, "los ids cambiaron entre dos corridas: duplicaría vectores"
    assert len(ids_una_vez) == len(set(ids_una_vez)), "hay ids repetidos"
    assert ids_una_vez[0].endswith("::0"), "el id tiene que nombrar el archivo y el chunk"


def test_sin_clave_corta_con_un_mensaje_que_explica_que_hacer(monkeypatch):
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    with pytest.raises(SystemExit) as error:
        _exigir_clave()

    mensaje = str(error.value)
    assert "PINECONE_API_KEY" in mensaje
    assert ".env" in mensaje


def test_con_clave_devuelve_indice_y_namespace(monkeypatch):
    monkeypatch.setenv("PINECONE_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("INDEX_NAME", "indice-de-prueba")
    monkeypatch.setenv("PINECONE_NAMESPACE", "namespace-de-prueba")

    assert _exigir_clave() == ("indice-de-prueba", "namespace-de-prueba")
