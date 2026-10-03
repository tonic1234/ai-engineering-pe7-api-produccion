"""test_rag.py: el dataset y el recuperador.

Dos cosas se prueban acá y no en otro lado:

1. Que cada documento de data/ sea lo bastante largo como para partirse en varios chunks. En
   la devolución de la pre-entrega 3 me marcaron que los .txt eran demasiado cortos para el
   umbral de tokens de la consigna: con documentos de ~250 tokens el chunking de 600 no hacía
   nada (un documento = un chunk) y la recuperación no tenía de dónde elegir. Este test es el
   guardián de eso: si alguien vuelve a dejar un documento corto, falla.
2. Que el modo de recuperación se pueda INFORMAR (híbrido o léxico) leyéndolo del retriever
   real, en vez de suponerlo: degradar en silencio fue un punto que me marcaron en la
   pre-entrega 4.
"""

from __future__ import annotations

import tiktoken

from rag import RAGSystem, chunk_documents, load_dataset, nombre_modo

TAMANO_DE_CHUNK = 600


def test_cada_documento_supera_el_tamano_de_chunk():
    """Un documento más chico que el chunk nunca se parte: es un documento de mentira."""

    codificador = tiktoken.get_encoding("cl100k_base")
    for documento in load_dataset():
        tokens = len(codificador.encode(documento.page_content))
        assert tokens >= TAMANO_DE_CHUNK, (
            f"{documento.metadata['source']} tiene {tokens} tokens: por debajo del tamaño de "
            f"chunk ({TAMANO_DE_CHUNK}), así que no se fragmenta"
        )


def test_el_dataset_se_parte_en_varios_chunks_por_documento():
    chunks = chunk_documents(load_dataset())

    por_documento: dict[str, list] = {}
    for chunk in chunks:
        por_documento.setdefault(chunk.metadata["source"], []).append(chunk)

    assert len(por_documento) >= 4
    for fuente, suyos in por_documento.items():
        assert len(suyos) >= 2, f"{fuente} quedó en un solo chunk"
    assert len(chunks) >= 2 * len(por_documento)

    # Los metadatos que después se usan para citar la fuente en la respuesta.
    assert all(chunk.metadata.get("categoria") for chunk in chunks)
    assert all(chunk.metadata.get("chunk_id") is not None for chunk in chunks)


def test_el_modo_se_lee_del_retriever_real():
    """El modo sale del objeto que quedó armado, no de lo que pide el .env."""

    Hibrido = type("EnsembleRetriever", (), {})
    Lexico = type("BM25Retriever", (), {})
    Otro = type("OtroRetriever", (), {})

    assert "híbrido" in nombre_modo(Hibrido())
    assert "léxico" in nombre_modo(Lexico())
    assert "personalizado" in nombre_modo(Otro())


def test_sin_pinecone_el_sistema_queda_en_modo_lexico(monkeypatch):
    """Sin clave no se cae: sigue en modo léxico, y el modo queda declarado."""

    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    sistema = RAGSystem()

    assert "léxico" in sistema.modo
    fragmentos = sistema.obtener_top_k("vacaciones por antigüedad")
    assert fragmentos, "el modo léxico tiene que devolver fragmentos igual"
    assert all({"contenido", "fuente", "categoria"} <= set(f) for f in fragmentos)
