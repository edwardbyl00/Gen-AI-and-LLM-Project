#!/usr/bin/env python3
"""Search or inspect the local Stage 8 Chroma collection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

import torch
from transformers import AutoModel, AutoTokenizer

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.chroma_db import COLLECTION_NAME, MODEL_NAME, get_chunk_by_id, get_collection, get_linked_chunks, persistent_client
from scripts.evaluate_dense_retrieval import QUERY_INSTRUCTION, choose_device, encode_queries


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--query")
    mode.add_argument("--chunk-id")
    mode.add_argument("--linked-chunk-id")
    parser.add_argument("--document-id")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--persist-directory", type=Path, default=Path("data/vector_db/chroma"))
    parser.add_argument("--collection-name", default=COLLECTION_NAME)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    return parser.parse_args(argv)


def search(collection: Any, query: str, top_k: int, document_id: Optional[str], device_name: str) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top-k must be positive")
    device = choose_device(device_name)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, local_files_only=True)
    model = AutoModel.from_pretrained(MODEL_NAME, local_files_only=True).eval().to(device)
    query_vector = encode_queries([query], model, tokenizer, device, 1)[0]
    where = None if document_id is None else {"document_id": document_id}
    result = collection.query(
        query_embeddings=[query_vector.tolist()],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    rows = []
    for index, chunk_id in enumerate(result["ids"][0]):
        metadata = result["metadatas"][0][index]
        distance = float(result["distances"][0][index])
        document = result["documents"][0][index]
        rows.append({
            "rank": index + 1,
            "chunk_id": chunk_id,
            "document_id": metadata.get("document_id"),
            "source": metadata.get("source"),
            "cosine_distance": distance,
            "cosine_similarity": 1.0 - distance,
            "title": metadata.get("title"),
            "section_path": json.loads(metadata["section_path_json"]) if metadata.get("section_path_json") else None,
            "excerpt": " ".join(document.split())[:500],
            "source_url": metadata.get("source_url"),
        })
    return rows


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    client = persistent_client(args.persist_directory)
    collection = get_collection(client, args.collection_name)
    if args.query is not None:
        payload: Any = {
            "query": args.query,
            "query_instruction": QUERY_INSTRUCTION,
            "score_definition": "cosine_similarity = 1 - Chroma cosine_distance",
            "document_filter": args.document_id,
            "results": search(collection, args.query, args.top_k, args.document_id, args.device),
        }
    elif args.chunk_id is not None:
        payload = get_chunk_by_id(collection, args.chunk_id)
        if payload is None:
            raise KeyError(f"chunk not found: {args.chunk_id}")
    else:
        payload = get_linked_chunks(collection, args.linked_chunk_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
