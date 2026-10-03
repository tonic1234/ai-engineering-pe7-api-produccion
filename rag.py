"""rag.py: el sistema de recuperación que usan los agentes como "fuente externa".

Es el mismo camino de la pre-entrega 4 y lo reutilizo acá a propósito: el hilo del curso
es que cada módulo se apoye en el anterior. Entonces:

- dataset propio en data/ (políticas internas de una empresa ficticia; el texto es
  inventado, no hay datos reales de ninguna empresa);
- chunking medido en TOKENS (tiktoken), no en caracteres;
- embeddings LOCALES con sentence-transformers/all-MiniLM-L6-v2 (384 dimensiones): así el
  repo se puede correr gratis y sin tarjeta;
- búsqueda híbrida: BM25 (palabras exactas) + vectorial (significado) con EnsembleRetriever.

La consigna de la pre-entrega 6 acepta "Tavily o una búsqueda simulada sobre tu Vector DB
de pre-entregas anteriores": esto es exactamente la segunda opción.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List

from dotenv import load_dotenv
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

logger = logging.getLogger(__name__)

TOP_K = 5
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CANTIDAD_CARACTERES_PREVIEW = 160


def load_dataset() -> List[Document]:
    """Lee los .txt de data/ y les pone la categoría según el nombre del archivo."""

    loader = DirectoryLoader(
        DATA_DIR,
        glob="*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    documentos = loader.load()
    for documento in documentos:
        documento.metadata["source"] = os.path.basename(documento.metadata["source"])
        # La categoría la saco del nombre del archivo (politica_vacaciones.txt -> "vacaciones").
        nombre = os.path.splitext(documento.metadata["source"])[0]
        documento.metadata["categoria"] = nombre.split("_")[-1]
    return documentos


def chunk_documents(documentos: List[Document]):
    """Parte los documentos en chunks de ~600 tokens con 100 de solapamiento."""

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=600, chunk_overlap=100
    )
    chunks = splitter.split_documents(documentos)
    for i, chunk in enumerate(chunks):
        chunk.metadata["chunk_id"] = i
    return chunks


def build_vector_retriever(k: int = TOP_K):
    """Conecta con el índice de Pinecone (si ya existe, no se reingesta nada)."""

    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_pinecone import PineconeVectorStore

    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    indice = os.getenv("INDEX_NAME", "dendra-rag-hibrido")
    namespace = os.getenv("PINECONE_NAMESPACE", "politicas-dendra")

    vectorstore = PineconeVectorStore(index_name=indice, embedding=embeddings, namespace=namespace)
    return vectorstore.as_retriever(search_kwargs={"k": k, "namespace": namespace})


def build_hybrid_retriever(k: int = TOP_K):
    """Arma el EnsembleRetriever si hay Pinecone; si no, devuelve solo BM25 (modo local)."""

    chunks = chunk_documents(load_dataset())

    retriever_bm25 = BM25Retriever.from_documents(chunks)
    retriever_bm25.k = k

    if not os.getenv("PINECONE_API_KEY"):
        # Antes esto era un logger.info y pasaba desapercibido: en la devolución de la
        # pre-entrega 4 me marcaron justamente que degradar en silencio "puede enmascarar
        # errores de configuración". Ahora es warning y la demo imprime el modo real.
        logger.warning(
            "SIN PINECONE_API_KEY: recuperador en modo LÉXICO (solo BM25, sin la pata "
            "vectorial). El flujo funciona, pero la búsqueda es peor: completá la clave en "
            ".env para correr en modo híbrido."
        )
        return retriever_bm25

    try:
        retriever_vectorial = build_vector_retriever(k)
    except Exception as exc:  # si la nube falla, seguimos con la parte léxica
        logger.warning("No pude armar la rama vectorial (%s); sigo con BM25", exc)
        return retriever_bm25

    from langchain_classic.retrievers import EnsembleRetriever

    logger.info("Recuperador HÍBRIDO (BM25 + vectorial)")
    return EnsembleRetriever(retrievers=[retriever_bm25, retriever_vectorial], weights=[0.5, 0.5])


def nombre_modo(retriever) -> str:
    """Nombre legible del modo de recuperación, leído del retriever real."""

    tipo = type(retriever).__name__
    if tipo == "EnsembleRetriever":
        return "híbrido (BM25 + vectorial sobre Pinecone)"
    if tipo == "BM25Retriever":
        return "léxico (solo BM25, sin Pinecone)"
    return f"personalizado ({tipo})"


class RAGSystem:
    """Envoltorio simple: `obtener_top_k(pregunta)` devuelve los fragmentos con su fuente."""

    def __init__(self, retriever=None, k: int = TOP_K) -> None:
        self.retriever = retriever or build_hybrid_retriever(k)
        self.k = k
        # El modo se lee del retriever que REALMENTE quedó armado (no de lo que pide el .env):
        # así la demo puede decir en qué modo corrió sin depender de una suposición.
        self.modo = nombre_modo(self.retriever)

    def obtener_top_k(self, query: str) -> List[Dict]:
        docs: List[Document] = self.retriever.invoke(query)[: self.k]
        return [
            {
                "contenido": d.page_content,
                "fuente": d.metadata.get("source", "desconocida"),
                "categoria": d.metadata.get("categoria", "desconocida"),
            }
            for d in docs
        ]


def serializar_fragmentos(fragmentos: List[Dict]) -> str:
    """Formato que le devuelvo al LLM: cada fragmento con su fuente a la vista."""

    if not fragmentos:
        return ""
    return "\n\n".join(f"[{f['fuente']}] {f['contenido']}" for f in fragmentos)


if __name__ == "__main__":  # pragma: no cover - prueba manual
    sistema = RAGSystem()
    for i, fragmento in enumerate(sistema.obtener_top_k("¿cuántos días de vacaciones por antigüedad?"), 1):
        print(f"{i}. [{fragmento['fuente']}] {fragmento['contenido'][:CANTIDAD_CARACTERES_PREVIEW]}...")
