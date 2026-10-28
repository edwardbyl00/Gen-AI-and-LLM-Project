import json
from pathlib import Path


def normalize_chunk(chunk):
    """
    Convert P4's chunk schema into the common format
    expected by the P5 retrieval pipeline.
    """

    return {
        "document_id": chunk.get("document_id"),
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get("title"),
        "source": chunk.get("source"),
        "category": (
            chunk.get("category")
            or chunk.get("document_type")
        ),
        "url": (
            chunk.get("url")
            or chunk.get("source_url")
        ),
        "effective_date": chunk.get("effective_date"),
        "text": (
            chunk.get("text")
            or chunk.get("content")
        ),
        "section_title": chunk.get("section_title"),
        "section_path": chunk.get("section_path"),
        "section_number": chunk.get("section_number"),
    }


def load_chunks_jsonl(file_path):
    """
    Load P4's chunks.jsonl and normalize every chunk.
    """

    file_path = Path(file_path)

    chunks = []

    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                raw_chunk = json.loads(line)
                chunks.append(normalize_chunk(raw_chunk))

    return chunks


if __name__ == "__main__":
    # Mock sample using P4's real schema
    sample = {
        "document_id": "H01",
        "chunk_id": "H01_c0001",
        "title": "Couples and Families",
        "source": "HDB",
        "document_type": "policy",
        "source_url": "https://www.hdb.gov.sg/example",
        "effective_date": None,
        "content": "Example HDB policy content.",
        "section_title": None,
        "section_path": ["Couples and Families"],
        "section_number": None,
    }

    normalized = normalize_chunk(sample)

    print(normalized)