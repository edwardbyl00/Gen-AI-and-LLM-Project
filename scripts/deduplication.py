"""Detect exact duplicates, near duplicates, and cross-source topic overlap.

Only confirmed exact duplicates are excluded from the downstream dataset. Near
duplicates and cross-source overlaps are reported for review and retained.
Raw source files are never changed or deleted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


TOPIC_RULES = {
    "cpf_housing_usage": (
        "cpf savings",
        "ordinary account",
        "remaining lease",
        "valuation price",
        "age 95",
    ),
    "housing_financing": (
        "housing loan",
        "downpayment",
        "monthly instalment",
        "loan amount",
        "financial institution",
    ),
    "property_sale_and_cpf_refund": (
        "cpf refund",
        "accrued interest",
        "selling price",
        "outstanding housing loan",
        "sales proceeds",
    ),
    "stamp_duty": (
        "buyer’s stamp duty",
        "buyer's stamp duty",
        "additional buyer’s stamp duty",
        "additional buyer's stamp duty",
        "stamp duty",
        "absd",
        "bsd",
    ),
}


@dataclass
class DuplicateReportRow:
    document_id: str
    duplicate_candidate: str
    source: str
    candidate_source: str
    similarity_score: str
    jaccard_similarity: str
    containment_similarity: str
    cosine_similarity: str
    duplicate_type: str
    overlap_topics: str
    recommended_action: str
    review_status: str
    review_notes: str


def normalized_tokens(content: str) -> list[str]:
    content = re.sub(r"\]\([^)]*\)", "]", content.casefold())
    return re.findall(r"[a-z0-9$%]+", content)


def normalized_content_hash(content: str) -> str:
    normalized = " ".join(normalized_tokens(content))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def token_shingles(tokens: list[str], size: int) -> set[tuple[str, ...]]:
    if not tokens:
        return set()
    if len(tokens) < size:
        return {tuple(tokens)}
    return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


def similarity(
    first: set[tuple[str, ...]], second: set[tuple[str, ...]]
) -> tuple[float, float]:
    if not first or not second:
        return 0.0, 0.0
    intersection = len(first & second)
    jaccard = intersection / len(first | second)
    containment = intersection / min(len(first), len(second))
    return jaccard, containment


def cosine_similarity(first: Counter[str], second: Counter[str]) -> float:
    dot = sum(first[token] * second[token] for token in first.keys() & second.keys())
    magnitude = math.sqrt(sum(value * value for value in first.values())) * math.sqrt(
        sum(value * value for value in second.values())
    )
    return dot / magnitude if magnitude else 0.0


def content_topics(content: str) -> set[str]:
    folded = content.casefold()
    topics: set[str] = set()
    for topic, phrases in TOPIC_RULES.items():
        if sum(phrase in folded for phrase in phrases) >= 2:
            topics.add(topic)
    return topics


def pair_note(first: dict[str, Any], second: dict[str, Any], duplicate_type: str) -> str:
    if duplicate_type == "near_duplicate":
        return (
            f"High lexical overlap, but titles/scopes differ: '{first['title']}' versus "
            f"'{second['title']}'. Retained because buyer category, grant type, conditions, "
            "or exceptions may differ."
        )
    return (
        "The documents discuss a shared policy topic but come from different official sources. "
        "Explanatory guidance and legislation/agency rules serve different retrieval purposes."
    )


def canonical_pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


def detect_duplicates(
    documents: list[dict[str, Any]],
    inventory: list[dict[str, str]],
    *,
    shingle_size: int = 5,
    near_jaccard: float = 0.40,
    near_containment: float = 0.75,
) -> tuple[list[DuplicateReportRow], set[str]]:
    rows: list[DuplicateReportRow] = []
    excluded: set[str] = set()
    document_by_id = {document["document_id"]: document for document in documents}

    # Carry forward exact-duplicate decisions made against raw/normalized main content
    # during the audit, including duplicates already excluded from cleaned_documents.
    for item in inventory:
        if item.get("downstream_action") != "exclude_exact_duplicate":
            continue
        duplicate = item["file_id"]
        canonical = item.get("duplicate_of", "")
        excluded.add(duplicate)
        rows.append(
            DuplicateReportRow(
                document_id=duplicate,
                duplicate_candidate=canonical,
                source=item["source_organization"],
                candidate_source=(
                    document_by_id.get(canonical, {}).get("source")
                    or item["source_organization"]
                ),
                similarity_score="1.0000",
                jaccard_similarity="1.0000",
                containment_similarity="1.0000",
                cosine_similarity="1.0000",
                duplicate_type="exact_normalized_content",
                overlap_topics="",
                recommended_action=f"exclude {duplicate}; retain canonical {canonical}",
                review_status="confirmed",
                review_notes="Raw file is retained; only downstream processing excludes this copy.",
            )
        )

    # Detect any exact normalized duplicates that remain in the cleaned input.
    hash_groups: dict[str, list[str]] = {}
    for document in documents:
        content_hash = normalized_content_hash(document["content"])
        hash_groups.setdefault(content_hash, []).append(document["document_id"])
    for identifiers in hash_groups.values():
        if len(identifiers) < 2:
            continue
        canonical = identifiers[0]
        for duplicate in identifiers[1:]:
            excluded.add(duplicate)
            first = document_by_id[duplicate]
            second = document_by_id[canonical]
            rows.append(
                DuplicateReportRow(
                    document_id=duplicate,
                    duplicate_candidate=canonical,
                    source=first["source"],
                    candidate_source=second["source"],
                    similarity_score="1.0000",
                    jaccard_similarity="1.0000",
                    containment_similarity="1.0000",
                    cosine_similarity="1.0000",
                    duplicate_type="exact_normalized_content",
                    overlap_topics="",
                    recommended_action=f"exclude {duplicate}; retain canonical {canonical}",
                    review_status="confirmed",
                    review_notes="Exact normalized content match in cleaned input.",
                )
            )

    features: dict[str, dict[str, Any]] = {}
    for document in documents:
        tokens = normalized_tokens(document["content"])
        features[document["document_id"]] = {
            "shingles": token_shingles(tokens, shingle_size),
            "counter": Counter(tokens),
            "topics": content_topics(document["content"]),
        }

    reported_pairs: set[tuple[str, str]] = {
        canonical_pair(row.document_id, row.duplicate_candidate) for row in rows
    }
    for index, first in enumerate(documents):
        for second in documents[index + 1 :]:
            pair = canonical_pair(first["document_id"], second["document_id"])
            if pair in reported_pairs:
                continue
            first_features = features[first["document_id"]]
            second_features = features[second["document_id"]]
            jaccard, containment = similarity(
                first_features["shingles"], second_features["shingles"]
            )
            cosine = cosine_similarity(first_features["counter"], second_features["counter"])
            shared_topics = first_features["topics"] & second_features["topics"]

            duplicate_type = ""
            if first["source"] == second["source"] and (
                jaccard >= near_jaccard or containment >= near_containment
            ):
                duplicate_type = "near_duplicate"
            elif first["source"] != second["source"] and shared_topics and cosine >= 0.75:
                duplicate_type = "cross_source_topic_overlap"
            if not duplicate_type:
                continue

            rows.append(
                DuplicateReportRow(
                    document_id=first["document_id"],
                    duplicate_candidate=second["document_id"],
                    source=first["source"],
                    candidate_source=second["source"],
                    similarity_score=(
                        f"{cosine:.4f}"
                        if duplicate_type == "cross_source_topic_overlap"
                        else f"{max(jaccard, containment):.4f}"
                    ),
                    jaccard_similarity=f"{jaccard:.4f}",
                    containment_similarity=f"{containment:.4f}",
                    cosine_similarity=f"{cosine:.4f}",
                    duplicate_type=duplicate_type,
                    overlap_topics=";".join(sorted(shared_topics)),
                    recommended_action="retain both",
                    review_status="reviewed_keep_distinct",
                    review_notes=pair_note(first, second, duplicate_type),
                )
            )
            reported_pairs.add(pair)
    rows.sort(key=lambda row: (row.duplicate_type, row.document_id, row.duplicate_candidate))
    return rows, excluded


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_inventory(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_jsonl(documents: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")


def write_report(rows: Iterable[DuplicateReportRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(DuplicateReportRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def write_summary(
    rows: list[DuplicateReportRow], input_count: int, output_count: int, path: Path
) -> None:
    counts = Counter(row.duplicate_type for row in rows)
    text = f"""# Deduplication Summary

## Result

- Cleaned documents inspected: {input_count}
- Deduplicated downstream documents: {output_count}
- Confirmed exact duplicates: {counts['exact_normalized_content']}
- Near-duplicate pairs reviewed and retained: {counts['near_duplicate']}
- Cross-source topic overlaps reviewed and retained: {counts['cross_source_topic_overlap']}

Only confirmed exact duplicates are excluded from downstream processing. Near duplicates remain because small differences can encode different buyer categories, grant rules, effective dates, conditions, or exceptions. Cross-source documents remain because agency guidance and legislation serve different purposes.

Raw source files were not changed or deleted.
"""
    path.write_text(text, encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/cleaned/cleaned_documents.jsonl"))
    parser.add_argument("--inventory", type=Path, default=Path("reports/file_inventory.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/cleaned/deduplicated_documents.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("reports/duplicate_report.csv"))
    parser.add_argument("--summary", type=Path, default=Path("reports/deduplication_summary.md"))
    parser.add_argument("--shingle-size", type=int, default=5)
    parser.add_argument("--near-jaccard", type=float, default=0.40)
    parser.add_argument("--near-containment", type=float, default=0.75)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    documents = load_jsonl(args.input)
    inventory = load_inventory(args.inventory)
    rows, excluded = detect_duplicates(
        documents,
        inventory,
        shingle_size=args.shingle_size,
        near_jaccard=args.near_jaccard,
        near_containment=args.near_containment,
    )
    output_documents = [
        document for document in documents if document["document_id"] not in excluded
    ]
    write_jsonl(output_documents, args.output)
    write_report(rows, args.report)
    write_summary(rows, len(documents), len(output_documents), args.summary)
    print(
        json.dumps(
            {
                "input_documents": len(documents),
                "output_documents": len(output_documents),
                "excluded_document_ids": sorted(excluded),
                "report_rows": len(rows),
                "report_types": dict(sorted(Counter(row.duplicate_type for row in rows).items())),
                "output": str(args.output),
                "report": str(args.report),
                "summary": str(args.summary),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
