#!/usr/bin/env python3
"""Generate and validate normalized BGE embeddings without building a vector store."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Optional

import numpy as np
import torch
import torch.nn.functional as F
from transformers import AutoModel, AutoTokenizer


DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIMENSION = 768
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
LINK_FIELDS = (
    "parent_id",
    "part_index",
    "total_parts",
    "previous_chunk_id",
    "next_chunk_id",
    "requires_context",
)
SMOKE_QUESTIONS = (
    "What are the eligibility conditions for buying an HDB flat?",
    "What income ceiling applies to an HDB housing loan?",
    "How much CPF savings can I retain in my Ordinary Account when taking a housing loan?",
    "What restrictions apply to second-timer applicants?",
    "When is Additional Buyer's Stamp Duty payable for a residential property?",
)


def load_config_section(path: Path, section: str) -> dict[str, Any]:
    """Read a flat subsection from the project's intentionally simple YAML file."""
    if not path.exists():
        return {}
    result: dict[str, Any] = {}
    active = False
    section_indent = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped == f"{section}:":
            active = True
            section_indent = indent
            continue
        if active and indent <= section_indent:
            active = False
        if not active or ":" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split(":", 1)]
        if value.casefold() in {"true", "false"}:
            result[key] = value.casefold() == "true"
        elif value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value.strip("'\"")
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_chunks(path: Path) -> list[dict[str, Any]]:
    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    required = {"chunk_id", "document_id", "content", "source"}
    for index, chunk in enumerate(chunks):
        missing = sorted(required - set(chunk))
        if missing:
            raise ValueError(f"input row {index + 1} is missing required fields: {', '.join(missing)}")
    return chunks


def select_device(requested: str) -> torch.device:
    if requested == "cpu":
        return torch.device("cpu")
    mps_available = bool(hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
    if requested == "mps" and not mps_available:
        raise RuntimeError("MPS was requested but is not available")
    return torch.device("mps" if mps_available else "cpu")


def token_lengths(tokenizer: Any, texts: Iterable[str]) -> list[int]:
    return [
        len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
        for text in texts
    ]


def validate_input(chunks: list[dict[str, Any]], tokenizer: Any, max_length: int) -> list[int]:
    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        duplicates = sorted({chunk_id for chunk_id in ids if ids.count(chunk_id) > 1})
        raise ValueError(f"duplicate chunk_ids: {duplicates[:10]}")
    empty = [chunk["chunk_id"] for chunk in chunks if not chunk["content"].strip()]
    if empty:
        raise ValueError(f"empty chunk text: {empty[:10]}")
    lengths = token_lengths(tokenizer, (chunk["content"] for chunk in chunks))
    oversized = [(chunk["chunk_id"], length) for chunk, length in zip(chunks, lengths) if length > max_length]
    if oversized:
        raise ValueError(f"chunks exceed {max_length} tokens without truncation: {oversized[:10]}")
    return lengths


def encode_texts(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    device: torch.device,
    batch_size: int,
    max_length: int,
    *,
    progress_label: str,
) -> np.ndarray:
    vectors: list[np.ndarray] = []
    total_batches = math.ceil(len(texts) / batch_size)
    with torch.inference_mode():
        for batch_number, start in enumerate(range(0, len(texts), batch_size), start=1):
            batch = texts[start : start + batch_size]
            encoded = tokenizer(
                batch,
                padding=True,
                truncation=False,
                return_tensors="pt",
            )
            if encoded["input_ids"].shape[1] > max_length:
                raise ValueError("tokenizer produced an over-limit batch; no truncation was performed")
            encoded = {key: value.to(device) for key, value in encoded.items()}
            output = model(**encoded)
            pooled = output.last_hidden_state[:, 0]
            pooled = F.normalize(pooled, p=2, dim=1)
            vectors.append(pooled.detach().to("cpu", dtype=torch.float32).numpy())
            print(
                f"[{progress_label}] batch {batch_number}/{total_batches}; "
                f"items {start + 1}-{start + len(batch)}/{len(texts)}",
                flush=True,
            )
    return np.concatenate(vectors, axis=0) if vectors else np.empty((0, EMBEDDING_DIMENSION), dtype=np.float32)


def metadata_record(chunk: dict[str, Any], embedding_index: int) -> dict[str, Any]:
    """Keep all source metadata while storing the embedded content only in chunks.jsonl."""
    record = {key: value for key, value in chunk.items() if key != "content"}
    record.update({
        "embedding_index": embedding_index,
        "embedding_text_field": "content",
        "embedding_text_sha256": text_sha256(chunk["content"]),
    })
    return record


def validate_artifact(
    chunks: list[dict[str, Any]],
    vectors: np.ndarray,
    records: list[dict[str, Any]],
    token_counts: list[int],
    max_length: int,
) -> dict[str, Any]:
    checks = {
        "one_embedding_per_chunk": vectors.shape[0] == len(chunks) == len(records),
        "unique_chunk_ids": len({chunk["chunk_id"] for chunk in chunks}) == len(chunks),
        "embedding_dimension_768": vectors.ndim == 2 and vectors.shape[1] == EMBEDDING_DIMENSION,
        "no_nan": not bool(np.isnan(vectors).any()),
        "no_inf": not bool(np.isinf(vectors).any()),
        "no_zero_vectors": bool(np.all(np.linalg.norm(vectors, axis=1) > 0)),
        "no_empty_chunk_text": all(bool(chunk["content"].strip()) for chunk in chunks),
        "inputs_within_512_tokens": max(token_counts, default=0) <= max_length,
        "chunk_id_mapping_preserved": all(
            record.get("embedding_index") == index
            and record.get("chunk_id") == chunk.get("chunk_id")
            and record.get("embedding_text_sha256") == text_sha256(chunk["content"])
            for index, (chunk, record) in enumerate(zip(chunks, records))
        ),
        "linked_metadata_intact": all(
            all(record.get(field) == chunk.get(field) for field in LINK_FIELDS)
            for chunk, record in zip(chunks, records)
        ),
    }
    return checks


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def run_smoke_test(
    model: Any,
    tokenizer: Any,
    vectors: np.ndarray,
    chunks: list[dict[str, Any]],
    device: torch.device,
    batch_size: int,
    max_length: int,
) -> list[dict[str, Any]]:
    instructed = [QUERY_INSTRUCTION + question for question in SMOKE_QUESTIONS]
    query_lengths = token_lengths(tokenizer, instructed)
    if max(query_lengths, default=0) > max_length:
        raise ValueError("a smoke-test query exceeds the model token limit")
    queries = encode_texts(
        model, tokenizer, instructed, device, batch_size, max_length, progress_label="smoke test"
    )
    rows: list[dict[str, Any]] = []
    for question, query in zip(SMOKE_QUESTIONS, queries):
        scores = vectors @ query
        top_indices = np.argsort(-scores, kind="stable")[:5]
        for rank, index in enumerate(top_indices, start=1):
            chunk = chunks[int(index)]
            rows.append({
                "question": question,
                "rank": rank,
                "cosine_similarity": f"{float(scores[index]):.6f}",
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "source": chunk["source"],
                "title": chunk.get("title", ""),
                "section": " > ".join(chunk.get("section_path") or []),
                "content_preview": " ".join(chunk["content"].split())[:300],
            })
    return rows


def write_smoke_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary(
    path: Path,
    *,
    chunks: list[dict[str, Any]],
    model_name: str,
    device: torch.device,
    duration_seconds: float,
    vectors: np.ndarray,
    token_counts: list[int],
    checks: dict[str, Any],
    smoke_rows: list[dict[str, Any]],
    output_dir: Path,
    fingerprint: str,
) -> None:
    norms = np.linalg.norm(vectors, axis=1)
    failed = [name for name, passed in checks.items() if not passed]
    lines = [
        "# Stage 6 Embedding Generation and Validation Summary",
        "",
        "## Generation",
        "",
        f"- Status: **{'PASS' if not failed else 'FAIL'}**",
        f"- Total chunks processed: {len(chunks)}",
        f"- Embeddings generated: {vectors.shape[0]}",
        f"- Model: `{model_name}`",
        f"- Embedded field: `content` (the JSON object itself was not embedded)",
        f"- Embedding dimension: {vectors.shape[1] if vectors.ndim == 2 else 'invalid'}",
        f"- Device: `{device.type.upper()}`",
        f"- Processing time: {duration_seconds:.2f} seconds",
        f"- Normalized for cosine similarity: yes",
        f"- Input maximum tokens (special tokens included; no truncation): {max(token_counts, default=0)}",
        f"- Input dataset SHA-256: `{fingerprint}`",
        f"- Artifact directory: `{output_dir}`",
        "- Failures or skipped chunks: none" if not failed else f"- Failed checks: {', '.join(failed)}",
        "",
        "## Artifact Structure",
        "",
        "- `embeddings.npy`: float32 vectors in deterministic input order",
        "- `metadata.jsonl`: every original non-text field plus `embedding_index` and a SHA-256 of the embedded text",
        "- `manifest.json`: model, generation, validation, normalization, and input-fingerprint provenance",
        "- Join key: `chunk_id`; the unchanged `chunks.jsonl` remains the source of `content`, avoiding duplicate text storage",
        "",
        "## Vector Norm Statistics",
        "",
        f"- Minimum: {float(norms.min()):.8f}",
        f"- Mean: {float(norms.mean()):.8f}",
        f"- Maximum: {float(norms.max()):.8f}",
        "",
        "## Validation",
        "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'} — `{name}`" for name, passed in checks.items())
    lines.extend([
        "",
        "## Semantic Similarity Smoke Test",
        "",
        "Queries use the BGE retrieval instruction. The results below are a diagnostic sanity check only and do not prove retrieval accuracy.",
        "",
    ])
    for question in SMOKE_QUESTIONS:
        lines.extend([f"### {question}", "", "| Rank | Score | Chunk | Source | Title / section |", "|---:|---:|---|---|---|"])
        for row in [item for item in smoke_rows if item["question"] == question]:
            label = " / ".join(part for part in (row["title"], row["section"]) if part).replace("|", "\\|")
            lines.append(
                f"| {row['rank']} | {row['cosine_similarity']} | `{row['chunk_id']}` | "
                f"{row['source']} | {label} |"
            )
        lines.append("")
    lines.extend([
        "Full previews are available in `reports/embedding_smoke_test.csv`.",
        "",
        "## Conclusion",
        "",
        "The artifact is ready for future ChromaDB ingestion." if not failed else "The artifact is not ready for ChromaDB ingestion.",
        "No ChromaDB collection, retrieval pipeline, reranker, or answer-generation component was created.",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--smoke-test", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--max-length", type=int)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config_section(args.config, "embedding")
    input_path = args.input or Path(config.get("input", "data/processed/chunks.jsonl"))
    output_dir = args.output_dir or Path(config.get("output_dir", "data/embeddings/bge-base-en-v1.5"))
    summary_path = args.summary or Path(config.get("summary", "reports/embedding_summary.md"))
    smoke_path = args.smoke_test or Path(config.get("smoke_test", "reports/embedding_smoke_test.csv"))
    model_name = args.model or config.get("model", DEFAULT_MODEL)
    batch_size = args.batch_size or int(config.get("batch_size", 16))
    max_length = args.max_length or int(config.get("max_length", 512))
    normalize = config.get("normalize", True)
    if model_name != DEFAULT_MODEL or max_length != 512 or normalize is not True:
        raise ValueError("Stage 6 requires BAAI/bge-base-en-v1.5, max_length=512, and normalization")
    if batch_size < 1:
        raise ValueError("batch size must be positive")

    started = time.perf_counter()
    generated_at = datetime.now(timezone.utc).isoformat()
    fingerprint = file_sha256(input_path)
    chunks = load_chunks(input_path)
    device = select_device(args.device)
    random.seed(0)
    np.random.seed(0)
    torch.manual_seed(0)

    print(f"Loading tokenizer and model: {model_name}", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()
    model.to(device)
    print(f"Device: {device.type}; input chunks: {len(chunks)}; batch size: {batch_size}", flush=True)

    token_counts = validate_input(chunks, tokenizer, max_length)
    vectors = encode_texts(
        model,
        tokenizer,
        [chunk["content"] for chunk in chunks],
        device,
        batch_size,
        max_length,
        progress_label="embeddings",
    )
    records = [metadata_record(chunk, index) for index, chunk in enumerate(chunks)]
    checks = validate_artifact(chunks, vectors, records, token_counts, max_length)
    smoke_rows = run_smoke_test(model, tokenizer, vectors, chunks, device, batch_size, max_length)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = output_dir.with_name(output_dir.name + ".tmp")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)
    np.save(temporary_dir / "embeddings.npy", vectors, allow_pickle=False)
    write_jsonl(records, temporary_dir / "metadata.jsonl")

    revision = getattr(model.config, "_commit_hash", None)
    norms = np.linalg.norm(vectors, axis=1)
    manifest = {
        "schema_version": "1.0",
        "generated_at_utc": generated_at,
        "model_name": model_name,
        "model_revision": revision,
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_count": int(vectors.shape[0]),
        "normalization": "L2",
        "pooling": "CLS token (last_hidden_state[:, 0])",
        "embedded_field": "content",
        "query_instruction": QUERY_INSTRUCTION,
        "max_input_tokens": max_length,
        "special_tokens_included": True,
        "truncation": False,
        "device": device.type,
        "batch_size": batch_size,
        "input_path": str(input_path),
        "input_sha256": fingerprint,
        "input_chunk_count": len(chunks),
        "input_max_tokens_observed": max(token_counts, default=0),
        "vector_dtype": str(vectors.dtype),
        "vector_norm_min": float(norms.min()),
        "vector_norm_mean": float(norms.mean()),
        "vector_norm_max": float(norms.max()),
        "validation": checks,
        "files": {"vectors": "embeddings.npy", "metadata": "metadata.jsonl"},
    }
    (temporary_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    os.replace(temporary_dir, output_dir)

    write_smoke_csv(smoke_rows, smoke_path)
    duration = time.perf_counter() - started
    write_summary(
        summary_path,
        chunks=chunks,
        model_name=model_name,
        device=device,
        duration_seconds=duration,
        vectors=vectors,
        token_counts=token_counts,
        checks=checks,
        smoke_rows=smoke_rows,
        output_dir=output_dir,
        fingerprint=fingerprint,
    )
    failed = [name for name, passed in checks.items() if not passed]
    print(json.dumps({
        "status": "FAIL" if failed else "PASS",
        "chunks": len(chunks),
        "embeddings": int(vectors.shape[0]),
        "dimension": int(vectors.shape[1]),
        "device": device.type,
        "duration_seconds": round(duration, 2),
        "failed_checks": failed,
        "artifact": str(output_dir),
        "summary": str(summary_path),
    }, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
