from pathlib import Path

from scripts.chroma_db import (
    COLLECTION_NAME,
    get_chunk_by_id,
    get_collection,
    persistent_client,
)
from scripts.query_chroma_db import search


DEFAULT_DB_PATH = Path("data/vector_db/chroma")


def dense_retrieve(
    query: str,
    top_k: int = 5,
    device: str = "cpu",
    persist_directory: Path = DEFAULT_DB_PATH,
):
    """
    Adapter from P4's Chroma retriever into the P5 retrieval format.

    Returns full chunk text rather than only the CLI excerpt.
    """
    client = persistent_client(persist_directory)
    collection = get_collection(client, COLLECTION_NAME)

    ranked = search(
        collection=collection,
        query=query,
        top_k=top_k,
        document_id=None,
        device_name=device,
    )

    results = []

    for row in ranked:
        stored = get_chunk_by_id(
            collection,
            row["chunk_id"],
        )

        if stored is None:
            continue

        metadata = stored["metadata"]

        results.append(
            {
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "title": row["title"],
                "source": row["source"],
                "category": metadata.get("document_type"),
                "url": row["source_url"],
                "source_url": row["source_url"],
                "effective_date": metadata.get("effective_date"),
                "text": stored["document"],
                "content": stored["document"],
                "section_title": metadata.get("section_title"),
                "section_path": row["section_path"],
                "dense_score": row["cosine_similarity"],
                "score": row["cosine_similarity"],
            }
        )

    return results