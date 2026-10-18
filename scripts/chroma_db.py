#!/usr/bin/env python3
"""Shared validation, ingestion and lookup helpers for the Stage 8 Chroma store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import chromadb
import numpy as np
from chromadb.config import Settings


MODEL_NAME = "BAAI/bge-base-en-v1.5"
COLLECTION_NAME = "hdb_housing_advisory_bge_base_v1_5"
DISTANCE_METRIC = "cosine"
EXPECTED_COUNT = 1282
EXPECTED_DIMENSION = 768
METADATA_TRANSFORM_VERSION = "1.0"

PRIMITIVE_METADATA_FIELDS = (
    "chunk_id", "document_id", "source", "source_url", "title",
    "document_type", "effective_date", "retrieved_at", "source_capture_status",
    "schema_version", "section_number", "section_title", "section_status",
    "logical_unit_id", "chunk_index", "chunk_count", "token_count",
    "token_count_including_special_tokens", "token_counter", "tokenizer",
    "target_chunk_size", "maximum_chunk_size", "configured_overlap",
    "oversized", "contains_table", "requires_context", "parent_id",
    "part_index", "total_parts", "previous_chunk_id", "next_chunk_id",
)
JSON_METADATA_FIELDS = (
    "section_path", "hierarchy", "block_types", "flags", "source_block_ids",
)
LINK_FIELDS = (
    "parent_id", "part_index", "total_parts", "previous_chunk_id",
    "next_chunk_id", "requires_context",
)


@dataclass(frozen=True)
class ArtifactBundle:
    chunks_path: Path
    chunks: list[dict[str, Any]]
    embeddings: np.ndarray
    metadata: list[dict[str, Any]]
    manifest: dict[str, Any]

    @property
    def chunk_by_id(self) -> dict[str, dict[str, Any]]:
        return {item["chunk_id"]: item for item in self.chunks}

    @property
    def metadata_by_id(self) -> dict[str, dict[str, Any]]:
        return {item["chunk_id"]: item for item in self.metadata}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid JSONL artifact: {path}: {exc}") from exc


def validate_link_references(chunks: list[dict[str, Any]]) -> None:
    by_id = {item["chunk_id"]: item for item in chunks}
    for chunk in chunks:
        previous_id = chunk.get("previous_chunk_id")
        next_id = chunk.get("next_chunk_id")
        if previous_id:
            previous = by_id.get(previous_id)
            if previous is None or previous.get("next_chunk_id") != chunk["chunk_id"]:
                raise ValueError(f"broken previous link on {chunk['chunk_id']}: {previous_id}")
        if next_id:
            next_chunk = by_id.get(next_id)
            if next_chunk is None or next_chunk.get("previous_chunk_id") != chunk["chunk_id"]:
                raise ValueError(f"broken next link on {chunk['chunk_id']}: {next_id}")


def load_and_validate_artifacts(
    chunks_path: Path,
    embedding_dir: Path,
    *,
    expected_count: Optional[int] = EXPECTED_COUNT,
    expected_dimension: Optional[int] = EXPECTED_DIMENSION,
) -> ArtifactBundle:
    required = {
        "chunks": chunks_path,
        "vectors": embedding_dir / "embeddings.npy",
        "metadata": embedding_dir / "metadata.jsonl",
        "manifest": embedding_dir / "manifest.json",
    }
    missing = [f"{name}={path}" for name, path in required.items() if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing required Stage 6 artifact(s): " + ", ".join(missing))

    chunks = read_jsonl(chunks_path)
    metadata = read_jsonl(required["metadata"])
    try:
        manifest = json.loads(required["manifest"].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid embedding manifest: {required['manifest']}: {exc}") from exc
    embeddings = np.load(required["vectors"], allow_pickle=False)

    counts = (len(chunks), len(metadata), int(embeddings.shape[0]) if embeddings.ndim >= 1 else -1)
    if len(set(counts)) != 1:
        raise ValueError(f"artifact count mismatch: chunks={counts[0]}, metadata={counts[1]}, vectors={counts[2]}")
    if expected_count is not None and counts[0] != expected_count:
        raise ValueError(f"expected {expected_count} records, found {counts[0]}")
    if embeddings.ndim != 2:
        raise ValueError(f"embeddings must be two-dimensional, found shape {embeddings.shape}")
    if expected_dimension is not None and embeddings.shape[1] != expected_dimension:
        raise ValueError(f"expected embedding dimension {expected_dimension}, found {embeddings.shape[1]}")

    chunk_ids = [item.get("chunk_id") for item in chunks]
    metadata_ids = [item.get("chunk_id") for item in metadata]
    if any(not isinstance(item, str) or not item for item in chunk_ids + metadata_ids):
        raise ValueError("chunk IDs must be non-empty strings")
    if len(set(chunk_ids)) != len(chunk_ids) or len(set(metadata_ids)) != len(metadata_ids):
        raise ValueError("duplicate chunk ID detected")
    for index, (chunk, record) in enumerate(zip(chunks, metadata)):
        if chunk["chunk_id"] != record["chunk_id"] or record.get("embedding_index") != index:
            raise ValueError(f"embedding order mismatch at index {index}")
        if not isinstance(chunk.get("content"), str) or not chunk["content"].strip():
            raise ValueError(f"empty chunk content: {chunk['chunk_id']}")
        text_hash = hashlib.sha256(chunk["content"].encode("utf-8")).hexdigest()
        if record.get("embedding_text_field") != "content" or record.get("embedding_text_sha256") != text_hash:
            raise ValueError(f"embedding text mapping mismatch: {chunk['chunk_id']}")
        for key, value in chunk.items():
            if key != "content" and record.get(key) != value:
                raise ValueError(f"metadata mismatch for {chunk['chunk_id']} field {key}")

    if not np.isfinite(embeddings).all():
        raise ValueError("embeddings contain NaN or Inf")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms == 0):
        raise ValueError("embeddings contain zero vectors")
    if not np.allclose(norms, 1.0, atol=1e-5):
        raise ValueError("embeddings are not L2 normalized")

    fingerprint = sha256_file(chunks_path)
    expected_manifest = {
        "model_name": MODEL_NAME,
        "embedding_count": counts[0],
        "embedding_dimension": embeddings.shape[1],
        "normalization": "L2",
        "embedded_field": "content",
        "input_sha256": fingerprint,
        "input_chunk_count": counts[0],
        "max_input_tokens": 512,
        "truncation": False,
    }
    mismatches = {
        key: {"expected": value, "actual": manifest.get(key)}
        for key, value in expected_manifest.items()
        if manifest.get(key) != value
    }
    if mismatches:
        raise ValueError(f"embedding manifest mismatch: {mismatches}")
    validate_link_references(chunks)
    return ArtifactBundle(chunks_path, chunks, embeddings.astype(np.float32, copy=False), metadata, manifest)


def chroma_metadata(record: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Create a primitive-only representation; nested fields are explicit JSON strings."""
    result: dict[str, str | int | float | bool] = {
        "metadata_transform_version": METADATA_TRANSFORM_VERSION,
        "source_metadata_sha256": sha256_json(record),
        "content_sha256": record["embedding_text_sha256"],
    }
    for field in PRIMITIVE_METADATA_FIELDS:
        value = record.get(field)
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)) and not isinstance(value, complex):
            result[field] = value
        else:
            raise ValueError(f"unsupported primitive metadata value for {record['chunk_id']}.{field}")
    for field in JSON_METADATA_FIELDS:
        value = record.get(field)
        if value is not None:
            result[f"{field}_json"] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return result


def collection_metadata(bundle: ArtifactBundle, manifest_reference: str) -> dict[str, str | int | float | bool]:
    return {
        "embedding_model": bundle.manifest["model_name"],
        "model_revision": bundle.manifest.get("model_revision", "unrecorded"),
        "embedding_dimension": int(bundle.embeddings.shape[1]),
        "embedding_normalization": bundle.manifest["normalization"],
        "dataset_fingerprint": bundle.manifest["input_sha256"],
        "chunk_count": len(bundle.chunks),
        "distance_metric": DISTANCE_METRIC,
        "manifest_schema_version": str(bundle.manifest.get("schema_version", "unrecorded")),
        "manifest_reference": manifest_reference,
        "metadata_transform_version": METADATA_TRANSFORM_VERSION,
    }


def persistent_client(path: Path) -> Any:
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(path),
        settings=Settings(anonymized_telemetry=False),
    )


def _collection_names(client: Any) -> set[str]:
    return {getattr(item, "name", str(item)) for item in client.list_collections()}


def get_collection(client: Any, name: str = COLLECTION_NAME) -> Any:
    if name not in _collection_names(client):
        raise ValueError(f"Chroma collection does not exist: {name}")
    return client.get_collection(name=name, embedding_function=None)


def validate_collection_identity(collection: Any, expected: dict[str, Any]) -> None:
    actual = collection.metadata or {}
    mismatches = {
        key: {"expected": value, "actual": actual.get(key)}
        for key, value in expected.items()
        if actual.get(key) != value
    }
    configuration = getattr(collection, "configuration_json", {}) or {}
    actual_space = (configuration.get("hnsw") or {}).get("space")
    if actual_space != DISTANCE_METRIC:
        mismatches["hnsw.space"] = {"expected": DISTANCE_METRIC, "actual": actual_space}
    if mismatches:
        raise ValueError(f"existing collection configuration mismatch; refusing to overwrite: {mismatches}")


def _records_by_id(collection: Any, *, include_embeddings: bool = False) -> dict[str, dict[str, Any]]:
    include = ["documents", "metadatas"]
    if include_embeddings:
        include.append("embeddings")
    result = collection.get(include=include)
    embeddings = result.get("embeddings")
    records: dict[str, dict[str, Any]] = {}
    for index, chunk_id in enumerate(result["ids"]):
        if chunk_id in records:
            raise ValueError(f"duplicate ID returned by Chroma: {chunk_id}")
        records[chunk_id] = {
            "document": result["documents"][index],
            "metadata": result["metadatas"][index],
            "embedding": None if embeddings is None else np.asarray(embeddings[index], dtype=np.float32),
        }
    return records


def validate_existing_records(collection: Any, bundle: ArtifactBundle, *, include_embeddings: bool) -> None:
    existing = _records_by_id(collection, include_embeddings=include_embeddings)
    expected_ids = {item["chunk_id"] for item in bundle.chunks}
    unknown = sorted(set(existing) - expected_ids)
    if unknown:
        raise ValueError(f"collection contains IDs outside the validated dataset: {unknown[:10]}")
    index_by_id = {record["chunk_id"]: index for index, record in enumerate(bundle.metadata)}
    for chunk_id, stored in existing.items():
        index = index_by_id[chunk_id]
        expected_document = bundle.chunks[index]["content"]
        expected_metadata = chroma_metadata(bundle.metadata[index])
        if stored["document"] != expected_document:
            raise ValueError(f"stored document mismatch: {chunk_id}")
        if stored["metadata"] != expected_metadata:
            raise ValueError(f"stored metadata mismatch: {chunk_id}")
        if include_embeddings:
            vector = stored["embedding"]
            if vector is None or vector.shape != (bundle.embeddings.shape[1],):
                raise ValueError(f"stored embedding dimension mismatch: {chunk_id}")
            if not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                raise ValueError(f"invalid stored embedding: {chunk_id}")
            if not np.allclose(vector, bundle.embeddings[index], atol=1e-6):
                raise ValueError(f"stored embedding value mismatch: {chunk_id}")


def ingest_bundle(
    client: Any,
    bundle: ArtifactBundle,
    *,
    collection_name: str = COLLECTION_NAME,
    batch_size: int = 100,
    manifest_reference: str = "data/embeddings/bge-base-en-v1.5/manifest.json",
    progress: bool = True,
) -> tuple[Any, dict[str, Any]]:
    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    expected_metadata = collection_metadata(bundle, manifest_reference)
    created = collection_name not in _collection_names(client)
    if created:
        collection = client.create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": DISTANCE_METRIC}},
            metadata=expected_metadata,
            embedding_function=None,
        )
    else:
        collection = client.get_collection(name=collection_name, embedding_function=None)
        validate_collection_identity(collection, expected_metadata)
        validate_existing_records(collection, bundle, include_embeddings=True)

    existing_ids = set(_records_by_id(collection))
    missing_indices = [index for index, item in enumerate(bundle.chunks) if item["chunk_id"] not in existing_ids]
    inserted = 0
    for start in range(0, len(missing_indices), batch_size):
        indices = missing_indices[start : start + batch_size]
        collection.add(
            ids=[bundle.chunks[index]["chunk_id"] for index in indices],
            embeddings=bundle.embeddings[indices],
            documents=[bundle.chunks[index]["content"] for index in indices],
            metadatas=[chroma_metadata(bundle.metadata[index]) for index in indices],
        )
        inserted += len(indices)
        if progress:
            print(f"Inserted {inserted}/{len(missing_indices)} missing records", flush=True)

    if collection.count() != len(bundle.chunks):
        raise ValueError(f"final collection count mismatch: {collection.count()} != {len(bundle.chunks)}")
    validate_collection_identity(collection, expected_metadata)
    validate_existing_records(collection, bundle, include_embeddings=True)
    return collection, {
        "created": created,
        "inserted": inserted,
        "already_present": len(bundle.chunks) - inserted,
        "record_count": collection.count(),
        "idempotent": inserted == 0,
    }


def _single_result(result: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return {
        "chunk_id": result["ids"][index],
        "document": result["documents"][index],
        "metadata": result["metadatas"][index],
    }


def get_chunk_by_id(collection: Any, chunk_id: str) -> Optional[dict[str, Any]]:
    result = collection.get(ids=[chunk_id], include=["documents", "metadatas"])
    return None if not result["ids"] else _single_result(result)


def get_linked_chunks(collection: Any, chunk_id: str) -> dict[str, Any]:
    chunk = get_chunk_by_id(collection, chunk_id)
    if chunk is None:
        raise KeyError(f"chunk not found: {chunk_id}")
    links: dict[str, Any] = {}
    for relation in ("previous_chunk_id", "next_chunk_id"):
        linked_id = chunk["metadata"].get(relation)
        if linked_id:
            linked = get_chunk_by_id(collection, str(linked_id))
            if linked is None:
                raise ValueError(f"stored linked chunk is missing: {chunk_id}.{relation}={linked_id}")
            links[relation] = linked
    return {"chunk": chunk, "linked_chunks": links}
