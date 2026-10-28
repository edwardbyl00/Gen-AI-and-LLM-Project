#!/usr/bin/env python3
"""Build the persistent Stage 8 ChromaDB from validated existing embeddings."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.chroma_db import COLLECTION_NAME, ingest_bundle, load_and_validate_artifacts, persistent_client


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=Path("data/processed/chunks.jsonl"))
    parser.add_argument("--embedding-dir", type=Path, default=Path("data/embeddings/bge-base-en-v1.5"))
    parser.add_argument("--persist-directory", type=Path, default=Path("data/vector_db/chroma"))
    parser.add_argument("--collection-name", default=COLLECTION_NAME)
    parser.add_argument("--batch-size", type=int, default=100)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    bundle = load_and_validate_artifacts(args.chunks, args.embedding_dir)
    print(
        f"Validated {len(bundle.chunks)} chunks and embeddings "
        f"({bundle.embeddings.shape[1]} dimensions, fingerprint={bundle.manifest['input_sha256']})",
        flush=True,
    )
    client = persistent_client(args.persist_directory)
    collection, result = ingest_bundle(
        client,
        bundle,
        collection_name=args.collection_name,
        batch_size=args.batch_size,
        manifest_reference=str(args.embedding_dir / "manifest.json"),
    )
    result.update({
        "status": "PASS",
        "collection_name": collection.name,
        "storage_path": str(args.persist_directory),
        "embedding_model": bundle.manifest["model_name"],
        "embedding_dimension": bundle.embeddings.shape[1],
        "dataset_fingerprint": bundle.manifest["input_sha256"],
        "distance_metric": "cosine",
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
