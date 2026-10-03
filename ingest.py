"""ingest.py: puebla el índice de Pinecone con los documentos de data/.

Por qué este script existe (y no sólo el retriever): si el índice y los .txt de data/ se
separan, el sistema recupera fragmentos que ya no están en el dataset. Es un problema real:
el índice quedó desactualizado una vez y el resultado fue que la búsqueda devolvía texto que
ya no existía en los archivos. Acá la única fuente de verdad es `data/`.

- Nada de degradar en silencio: si falta la clave, el script corta con un mensaje claro (no
  sigue "en modo local" y deja el índice a medio actualizar sin avisar).
- Idempotente: los ids son deterministas (`<archivo>::<n>`) y el namespace se limpia antes de
  subir, así correrlo dos veces deja exactamente el mismo estado.

Uso:
    python ingest.py              # limpia el namespace y sube los chunks actuales
    python ingest.py --verificar  # sólo informa qué hay hoy en el índice (no escribe nada)
"""

from __future__ import annotations

import os
import sys
from typing import List

from dotenv import load_dotenv
from langchain_core.documents import Document

from rag import chunk_documents, load_dataset

load_dotenv()


def ids_de_chunks(chunks: List[Document]) -> List[str]:
    """Id determinista por chunk: mismo dataset, mismos ids (nada duplicado)."""

    ids = []
    for chunk in chunks:
        ids.append(f"{chunk.metadata['source']}::{chunk.metadata['chunk_id']}")
    return ids


def embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def _exigir_clave() -> tuple[str, str]:
    """Devuelve (índice, namespace) y corta si falta la clave: sin degradar en silencio."""

    if not os.getenv("PINECONE_API_KEY"):
        raise SystemExit(
            "Falta PINECONE_API_KEY. Copiá .env.example a .env y completá la clave para "
            "poblar el índice (sin la clave el script no hace nada, a propósito: actualizar "
            "el índice a medias es peor que no actualizarlo)."
        )
    return (
        os.getenv("INDEX_NAME", "dendra-rag-hibrido"),
        os.getenv("PINECONE_NAMESPACE", "politicas-dendra"),
    )


def verificar() -> None:
    """Muestra qué hay HOY en el índice, para poder compararlo con data/."""

    from pinecone import Pinecone

    indice, namespace = _exigir_clave()
    stats = Pinecone(api_key=os.getenv("PINECONE_API_KEY")).Index(indice).describe_index_stats()
    total = getattr(stats, "total_vector_count", None)
    if total is None:
        total = stats.get("total_vector_count")
    print(f"índice: {indice} | vectores totales: {total}")
    por_namespace = getattr(stats, "namespaces", None) or {}
    for nombre, datos in por_namespace.items():
        cantidad = datos.get("vector_count") if isinstance(datos, dict) else getattr(datos, "vector_count", "?")
        print(f"  namespace '{nombre}': {cantidad} vectores")
    print(f"namespace que usa este proyecto: '{namespace}'")


def main() -> None:
    if "--verificar" in sys.argv:
        verificar()
        return

    indice, namespace = _exigir_clave()

    chunks = chunk_documents(load_dataset())
    ids = ids_de_chunks(chunks)
    print(f"dataset: {len(chunks)} chunks de {len(set(c.metadata['source'] for c in chunks))} documentos")
    for chunk in chunks:
        print(f"  [{chunk.metadata['source']}] chunk {chunk.metadata['chunk_id']} ({len(chunk.page_content)} caracteres)")

    from langchain_pinecone import PineconeVectorStore

    store = PineconeVectorStore(index_name=indice, embedding=embeddings(), namespace=namespace)

    print(f"\nlimpiando el namespace '{namespace}' de {indice}...")
    store.delete(delete_all=True)

    print("subiendo los chunks actuales...")
    subidos = store.add_documents(documents=chunks, ids=ids)
    print(f"listo: {len(subidos)} vectores subidos a '{namespace}'")

    verificar()


if __name__ == "__main__":
    main()
