"""Run reproducible data-quality checks over cleaned documents and chunks.

The checks deliberately distinguish machine-verifiable preservation from
semantic or external-source claims that still require manual review.  The
script does not modify source documents or processed datasets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Optional

try:
    from scripts.html_cleaning import clean_document, raw_path
except ModuleNotFoundError:  # Support direct execution as python scripts/quality_check.py.
    from html_cleaning import clean_document, raw_path


TOKEN_PATTERN = re.compile(
    r"(?:S\$|\$)?\d[\d,.]*(?:%|[A-Za-z]+)?|[^\W_]+(?:[’'\-][^\W_]+)*",
    flags=re.UNICODE,
)
NUMBER_PATTERN = re.compile(r"(?:S\$|\$)?\d[\d,.]*(?:%|[A-Za-z]+)?", re.I)
CONDITION_PATTERN = re.compile(
    r"\b(?:must|must not|shall|only if|only|eligible|eligibility|at least|up to|"
    r"within|provided that|subject to|may not|cannot|can\s+only)\b",
    re.I,
)
EXCEPTION_PATTERN = re.compile(
    r"\b(?:unless|except|exception|excluding|must not|does not|not eligible|"
    r"cannot|may not|subject to|however|provided that)\b",
    re.I,
)
SUBSECTION_PATTERN = re.compile(r"(?<!\w)\((?:\d+|[a-z]+|[ivxlcdm]+)\)", re.I)
LEGAL_REFERENCE_PATTERN = re.compile(
    r"\b(?:section|sections|regulation|regulations|paragraph|subsection|Part|"
    r"Division|Schedule)\s+(?:\d+[A-Za-z]?|[IVXLC]+|\([0-9A-Za-z]+\))"
    r"(?:\s*(?:\([0-9A-Za-z]+\)|to|and|or|,|-))*",
    re.I,
)
NAVIGATION_PATTERNS = {
    "cookie_banner": re.compile(r"\b(?:accept all cookies|cookie preferences)\b", re.I),
    "feedback_widget": re.compile(r"\b(?:was this (?:page|article) helpful|submit feedback)\b", re.I),
    "navigation_control": re.compile(r"\b(?:skip to main content|open navigation menu)\b", re.I),
    "embedded_payload": re.compile(r"(?:data:image/|<script\b|javascript:)", re.I),
}


@dataclass
class QualityResult:
    check_id: str
    category: str
    check_name: str
    status: str
    severity: str
    scope: str
    target_id: str
    source: str
    automatable: str
    details: str
    evidence: str
    recommended_action: str


def tokens(text: str) -> list[str]:
    """Return the same deterministic word-like tokens used by chunking."""
    text = re.sub(r"<br\s*/?>", " ", text or "", flags=re.I)
    return [match.group(0).casefold() for match in TOKEN_PATTERN.finditer(text)]


def normalized_text(text: str) -> str:
    return " ".join(tokens(text))


def ngrams(values: list[str], size: int = 5) -> set[tuple[str, ...]]:
    return {
        tuple(values[index : index + size])
        for index in range(max(0, len(values) - size + 1))
    }


def sequence_covered(source_text: str, chunk_texts: Iterable[str]) -> bool:
    """Check short exact sequences or all 5-grams across associated chunks."""
    source_tokens = tokens(source_text)
    candidates = [tokens(text) for text in chunk_texts]
    if not source_tokens:
        return True
    if len(source_tokens) < 5:
        needle = " ".join(source_tokens)
        return any(needle in " ".join(candidate) for candidate in candidates)
    available = set().union(*(ngrams(candidate) for candidate in candidates))
    return ngrams(source_tokens) <= available


def merge_overlapping_tokens(existing: list[str], piece: list[str]) -> list[str]:
    maximum = min(len(existing), len(piece), 100)
    for overlap in range(maximum, 0, -1):
        if existing[-overlap:] == piece[:overlap]:
            return existing + piece[overlap:]
    return existing + piece


def table_matrix(table: dict[str, Any]) -> list[list[str]]:
    rows = int(table.get("row_count", 0))
    columns = int(table.get("column_count", 0))
    occupied: dict[tuple[int, int], str] = {}
    for cell in table.get("cells", []):
        for row_offset in range(max(1, int(cell.get("rowspan", 1)))):
            for column_offset in range(max(1, int(cell.get("colspan", 1)))):
                occupied[(int(cell["row"]) + row_offset, int(cell["column"]) + column_offset)] = cell.get("text", "")
    return [[occupied.get((row, column), "") for column in range(columns)] for row in range(rows)]


def navigation_markers(text: str) -> list[str]:
    return [name for name, pattern in NAVIGATION_PATTERNS.items() if pattern.search(text or "")]


def content_hash(text: str) -> str:
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def excluded_exact_duplicate_ids(rows: Iterable[dict[str, str]]) -> list[str]:
    """Return raw document IDs explicitly excluded as canonical exact copies."""
    excluded: set[str] = set()
    for row in rows:
        duplicate_type = row.get("duplicate_type", "").casefold()
        action = row.get("recommended_action", "").casefold()
        document_id = row.get("document_id", "")
        if duplicate_type.startswith("exact") and "exclude" in action and document_id:
            excluded.add(document_id)
    return sorted(excluded)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_config_section(path: Path, section: str) -> dict[str, Any]:
    """Read a flat subsection from the simple project YAML without PyYAML."""
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
        result[key] = int(value) if value.isdigit() else value.strip("'\"")
    return result


def result(
    check_id: str,
    category: str,
    name: str,
    status: str,
    severity: str,
    details: str,
    evidence: str,
    *,
    scope: str = "dataset",
    target_id: str = "ALL",
    source: str = "ALL",
    automatable: str = "yes",
    action: str = "None",
) -> QualityResult:
    return QualityResult(
        check_id, category, name, status, severity, scope, target_id, source,
        automatable, details, evidence, action,
    )


def index_data(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]], dict[tuple[str, str], list[dict[str, Any]]]]:
    documents_by_id = {document["document_id"]: document for document in documents}
    blocks: dict[tuple[str, str], dict[str, Any]] = {}
    chunks_by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunks_by_block: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for document in documents:
        for block in document.get("blocks", []):
            blocks[(document["document_id"], block["block_id"])] = block
    for chunk in chunks:
        chunks_by_document[chunk["document_id"]].append(chunk)
        for block_id in chunk.get("source_block_ids", []):
            chunks_by_block[(chunk["document_id"], block_id)].append(chunk)
    return documents_by_id, blocks, chunks_by_document, chunks_by_block


def evaluate_quality(
    documents: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    inventory: list[dict[str, str]],
    *,
    raw_root: Optional[Path] = None,
    duplicate_rows: Optional[list[dict[str, str]]] = None,
    content_validation_rows: Optional[list[dict[str, str]]] = None,
    short_threshold: int = 10,
    long_threshold: int = 500,
    reparse_raw: bool = True,
) -> tuple[list[QualityResult], dict[str, Any]]:
    results: list[QualityResult] = []
    duplicate_rows = duplicate_rows or []
    content_validation_rows = content_validation_rows or []
    docs_by_id, blocks, chunks_by_doc, chunks_by_block = index_data(documents, chunks)
    inventory_by_id = {row["file_id"]: row for row in inventory}
    manual_review_docs: set[str] = set()

    # General document checks.
    empty = [d for d in documents if not d.get("content", "").strip() or not d.get("blocks")]
    results.append(result("G01", "general", "Empty documents", "PASS" if not empty else "FAIL", "high" if empty else "info", f"{len(empty)} empty documents", f"Checked {len(documents)} cleaned documents"))

    missing_titles = [d["document_id"] for d in documents if not d.get("title", "").strip()]
    results.append(result("G02", "general", "Missing titles", "PASS" if not missing_titles else "FAIL", "high" if missing_titles else "info", f"{len(missing_titles)} documents missing titles", "; ".join(missing_titles) or "All titles present"))

    missing_metadata = []
    for document in documents:
        missing = [key for key in ("source", "source_url", "retrieved_at", "raw_sha256") if not document.get(key)]
        if missing:
            missing_metadata.append((document["document_id"], missing))
    results.append(result("G03", "general", "Missing source information", "PASS" if not missing_metadata else "FAIL", "high" if missing_metadata else "info", f"{len(missing_metadata)} documents missing source metadata", "; ".join(f"{doc}: {','.join(keys)}" for doc, keys in missing_metadata) or "Required source fields present"))

    parsing_failures = [row["file_id"] for row in inventory if row.get("parsing_status") != "success" or row.get("content_extraction_status") != "success"]
    results.append(result("G04", "general", "Parsing failures", "PASS" if not parsing_failures else "FAIL", "high" if parsing_failures else "info", f"{len(parsing_failures)} raw files failed parsing or extraction", "; ".join(parsing_failures) or f"All {len(inventory)} inventory rows parsed"))

    noisy = []
    for document in documents:
        markers = navigation_markers(document.get("content", ""))
        if markers:
            noisy.append((document["document_id"], markers))
    results.append(result("G05", "general", "Excessive navigation noise", "PASS" if not noisy else "WARNING", "medium" if noisy else "info", f"{len(noisy)} documents contain navigation-noise markers", "; ".join(f"{doc}: {','.join(items)}" for doc, items in noisy) or "No configured navigation-noise markers found"))

    # Duplicate checks at document and chunk level.
    document_hashes: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        document_hashes[document.get("content_sha256") or content_hash(document.get("content", ""))].append(document["document_id"])
    duplicate_documents = [ids for ids in document_hashes.values() if len(ids) > 1]
    excluded_exact = excluded_exact_duplicate_ids(duplicate_rows)
    results.append(result("G06A", "general", "Duplicate documents", "PASS" if not duplicate_documents else "FAIL", "high" if duplicate_documents else "info", f"{len(duplicate_documents)} duplicate groups remain; {len(excluded_exact)} exact duplicates excluded upstream", "; ".join(",".join(group) for group in duplicate_documents) or ("Excluded: " + ", ".join(excluded_exact) if excluded_exact else "No duplicate documents")))

    chunk_hashes: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        chunk_hashes[content_hash(chunk.get("content", ""))].append(chunk["chunk_id"])
    duplicate_chunks = [ids for ids in chunk_hashes.values() if len(ids) > 1]
    results.append(result("G06B", "general", "Duplicate chunk content", "WARNING" if duplicate_chunks else "PASS", "low" if duplicate_chunks else "info", f"{len(duplicate_chunks)} exact-content chunk groups", "; ".join(",".join(group) for group in duplicate_chunks) or "No exact duplicate chunks", action="Retain when source text is intentionally repeated; retrieval team may deduplicate results." if duplicate_chunks else "None"))

    short_chunks = [chunk for chunk in chunks if int(chunk.get("token_count", 0)) <= short_threshold]
    for chunk in short_chunks:
        structural = "heading_without_body" in chunk.get("flags", [])
        status = "MANUAL_REVIEW" if structural else "WARNING"
        if structural:
            manual_review_docs.add(chunk["document_id"])
        results.append(result("G07", "general", "Extremely short chunk", status, "medium" if structural else "low", f"{chunk['token_count']} regex_words_v1 tokens; flags={','.join(chunk.get('flags', [])) or 'none'}", chunk.get("content", "")[:240], scope="chunk", target_id=chunk["chunk_id"], source=chunk.get("source", ""), automatable="partial", action="Review hierarchy/merging suitability." if structural else "Retain if the short legal or policy marker is meaningful."))
    if not short_chunks:
        results.append(result("G07", "general", "Extremely short chunks", "PASS", "info", "0 extremely short chunks", f"Threshold <= {short_threshold}"))

    long_chunks = [chunk for chunk in chunks if int(chunk.get("token_count", 0)) > long_threshold or chunk.get("oversized")]
    results.append(result("G08", "general", "Extremely long chunks", "WARNING" if long_chunks else "PASS", "medium" if long_chunks else "info", f"{len(long_chunks)} chunks exceed {long_threshold} regex_words_v1 tokens", "; ".join(chunk["chunk_id"] for chunk in long_chunks) or "No oversized regex-token chunks"))

    # Hierarchy checks: block association, orphan headings and policy documents with no paths.
    association_errors = []
    for key, block in blocks.items():
        for chunk in chunks_by_block.get(key, []):
            block_path = block.get("section_path", [])
            chunk_path = chunk.get("section_path", [])
            valid = block_path == chunk_path if block.get("type") != "heading" else block_path == chunk_path[: len(block_path)]
            if not valid:
                association_errors.append((key, chunk["chunk_id"]))
    if association_errors:
        results.append(result("G09A", "structure", "Broken block-to-section association", "FAIL", "high", f"{len(association_errors)} association errors", "; ".join(f"{key[0]}/{key[1]}->{chunk}" for key, chunk in association_errors[:20])))
    else:
        results.append(result("G09A", "structure", "Block-to-section association", "PASS", "info", "All traced blocks retain compatible section paths", f"Checked {len(blocks)} source blocks"))

    orphan_headings = [chunk for chunk in chunks if "heading_without_body" in chunk.get("flags", [])]
    for chunk in orphan_headings:
        manual_review_docs.add(chunk["document_id"])
        results.append(result("G09B", "structure", "Heading without associated body", "MANUAL_REVIEW", "medium", "Heading is preserved in a standalone chunk but not joined to child content", chunk.get("content", ""), scope="chunk", target_id=chunk["chunk_id"], source=chunk.get("source", ""), automatable="partial", action="Confirm whether it should remain standalone or be attached to child sections."))

    hierarchy_missing_docs = []
    for document in documents:
        document_chunks = [chunk for chunk in chunks_by_doc.get(document["document_id"], []) if "legal_front_matter" not in chunk.get("block_types", [])]
        if document.get("source") != "SSO" and document_chunks and all(not chunk.get("section_path") for chunk in document_chunks):
            hierarchy_missing_docs.append(document["document_id"])
            manual_review_docs.add(document["document_id"])
            results.append(result("G09C", "structure", "Document has no structured section paths", "MANUAL_REVIEW", "medium", "All substantive chunks have an empty section_path", "Content is present but hierarchy cannot be used for retrieval context", scope="document", target_id=document["document_id"], source=document.get("source", ""), automatable="partial", action="Review whether source headings were represented as plain paragraphs."))
    if not hierarchy_missing_docs:
        results.append(result("G09C", "structure", "Missing document hierarchy", "PASS", "info", "All policy documents have at least one structured section path", "No hierarchy-empty policy documents"))

    # Traceability and table integrity.
    untraceable = []
    for chunk in chunks:
        if chunk.get("document_id") not in docs_by_id or not chunk.get("source_block_ids") or not chunk.get("source_url"):
            untraceable.append(chunk["chunk_id"])
            continue
        if any((chunk["document_id"], block_id) not in blocks for block_id in chunk["source_block_ids"]):
            untraceable.append(chunk["chunk_id"])
    missing_blocks = [key for key in blocks if not chunks_by_block.get(key)]
    results.append(result("G13", "traceability", "Untraceable chunks or blocks", "FAIL" if untraceable or missing_blocks else "PASS", "high" if untraceable or missing_blocks else "info", f"{len(untraceable)} untraceable chunks; {len(missing_blocks)} untraced source blocks", "; ".join(untraceable[:20]) or f"All {len(chunks)} chunks and {len(blocks)} blocks are linked"))

    table_issues = []
    table_count = 0
    for document in documents:
        for block in document.get("blocks", []):
            if block.get("type") != "table":
                continue
            table_count += 1
            associated = chunks_by_block.get((document["document_id"], block["block_id"]), [])
            matrix = table_matrix(block["table"])
            header_rows = sorted({int(cell["row"]) for cell in block["table"].get("cells", []) if cell.get("is_header")}) or ([0] if matrix else [])
            body_rows = [index for index in range(len(matrix)) if index not in header_rows] or header_rows
            covered_rows: set[int] = set()
            for chunk in associated:
                for fragment in chunk.get("table_fragments", []):
                    if fragment.get("source_block_id") == block["block_id"]:
                        covered_rows.update(int(index) for index in fragment.get("original_row_indices", []))
            if set(body_rows) - covered_rows:
                table_issues.append(f"{document['document_id']}/{block['block_id']}: missing rows {sorted(set(body_rows)-covered_rows)}")
            texts = [chunk.get("content", "") for chunk in associated]
            for cell in block["table"].get("cells", []):
                if cell.get("text") and not sequence_covered(cell["text"], texts):
                    table_issues.append(f"{document['document_id']}/{block['block_id']}: cell {cell['row']},{cell['column']} text loss")
    results.append(result("G10", "structure", "Broken table relationships", "FAIL" if table_issues else "PASS", "high" if table_issues else "info", f"{len(table_issues)} table preservation issues", "; ".join(table_issues[:30]) or f"All {table_count} tables preserve rows, headers and cell sequences"))

    # Policy conditions and exceptions.
    condition_blocks = []
    exception_blocks = []
    for document in documents:
        if document.get("source") == "SSO":
            continue
        for block in document.get("blocks", []):
            if block.get("type") == "table":
                cell_text = "\n".join(cell.get("text", "") for cell in block["table"].get("cells", []))
                text = cell_text
            else:
                text = block.get("text", "")
            if CONDITION_PATTERN.search(text):
                condition_blocks.append((document["document_id"], block, text))
            if EXCEPTION_PATTERN.search(text):
                exception_blocks.append((document["document_id"], block, text))

    def coverage_failures(items: list[tuple[str, dict[str, Any], str]]) -> list[str]:
        failures = []
        for document_id, block, text in items:
            associated_text = [chunk.get("content", "") for chunk in chunks_by_block.get((document_id, block["block_id"]), [])]
            if block.get("type") == "table":
                # Individual cells are checked by G10; whole-table sequences cross cell boundaries.
                continue
            if not sequence_covered(text, associated_text):
                failures.append(f"{document_id}/{block['block_id']}")
        return failures

    condition_failures = coverage_failures(condition_blocks)
    exception_failures = coverage_failures(exception_blocks)
    results.append(result("G11", "semantics", "Missing policy conditions", "FAIL" if condition_failures else "PASS", "high" if condition_failures else "info", f"{len(condition_failures)} condition-bearing blocks failed sequence preservation", "; ".join(condition_failures) or f"Checked {len(condition_blocks)} condition-bearing blocks", automatable="partial", action="Manual semantic review remains necessary; this check proves textual preservation only."))
    results.append(result("G12", "semantics", "Missing policy exceptions", "FAIL" if exception_failures else "PASS", "high" if exception_failures else "info", f"{len(exception_failures)} exception-bearing blocks failed sequence preservation", "; ".join(exception_failures) or f"Checked {len(exception_blocks)} exception-bearing blocks", automatable="partial", action="Manual semantic review remains necessary; this check proves textual preservation only."))

    # Raw-to-cleaned reproducibility and cleaned-to-chunk preservation.
    raw_mismatches = []
    if reparse_raw and raw_root is not None:
        for row in inventory:
            path = raw_path(raw_root, row)
            if not path.exists():
                raw_mismatches.append(f"{row['file_id']}: inventory raw file missing")
                continue
            expected_hash = row.get("sha256_file_hash")
            if expected_hash and hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
                raw_mismatches.append(f"{row['file_id']}: raw file differs from audited inventory hash")
        for document in documents:
            row = inventory_by_id.get(document["document_id"])
            if not row:
                raw_mismatches.append(f"{document['document_id']}: inventory row missing")
                continue
            path = raw_path(raw_root, row)
            if not path.exists():
                raw_mismatches.append(f"{document['document_id']}: raw file missing")
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != document.get("raw_sha256"):
                raw_mismatches.append(f"{document['document_id']}: raw SHA-256 mismatch")
                continue
            try:
                regenerated, _ = clean_document(path, row)
            except Exception as error:  # one malformed file should not abort the report
                raw_mismatches.append(f"{document['document_id']}: reparse failed ({error})")
                continue
            if regenerated.get("content_sha256") != document.get("content_sha256") or regenerated.get("blocks") != document.get("blocks"):
                raw_mismatches.append(f"{document['document_id']}: cleaned output is not reproducible from raw")

    sequence_failures = []
    numeric_missing = []
    numeric_extra = []
    for document in documents:
        source_numbers = []
        for block in document.get("blocks", []):
            if block.get("type") == "table":
                source_numbers.extend(match.group(0).casefold() for cell in block["table"].get("cells", []) for match in NUMBER_PATTERN.finditer(cell.get("text", "")))
                continue
            text = block.get("text", "")
            source_numbers.extend(match.group(0).casefold() for match in NUMBER_PATTERN.finditer(text))
            if block.get("type") != "legal_provision" and not sequence_covered(text, [chunk.get("content", "") for chunk in chunks_by_block.get((document["document_id"], block["block_id"]), [])]):
                sequence_failures.append(f"{document['document_id']}/{block['block_id']}")
        output_numbers = [match.group(0).casefold() for chunk in chunks_by_doc.get(document["document_id"], []) for match in NUMBER_PATTERN.finditer(chunk.get("content", ""))]
        if set(source_numbers) - set(output_numbers):
            numeric_missing.append(document["document_id"])
        if set(output_numbers) - set(source_numbers):
            numeric_extra.append(document["document_id"])
    loss_failures = raw_mismatches + sequence_failures + numeric_missing + numeric_extra
    results.append(result("G14", "preservation", "Unexpected content loss or mutation", "FAIL" if loss_failures else "PASS", "high" if loss_failures else "info", f"{len(raw_mismatches)} raw/clean reproducibility issues; {len(sequence_failures)} cleaned/chunk sequence issues; {len(numeric_missing)} documents with missing numbers; {len(numeric_extra)} with introduced numbers", "; ".join(loss_failures[:30]) or "Raw hashes and regenerated cleaning match; chunk text and numeric values are preserved"))

    # SSO-specific checks.
    legal_documents = [document for document in documents if document.get("source") == "SSO"]
    legal_provisions = [(document, block) for document in legal_documents for block in document.get("blocks", []) if block.get("type") == "legal_provision"]
    missing_sections = []
    hierarchy_errors = []
    reference_errors = []
    merged_provisions = []
    for document, block in legal_provisions:
        associated = sorted(chunks_by_block.get((document["document_id"], block["block_id"]), []), key=lambda chunk: chunk.get("chunk_index", 0))
        if not block.get("section_number") or any(str(chunk.get("section_number")) != str(block.get("section_number")) for chunk in associated):
            missing_sections.append(f"{document['document_id']}/{block['block_id']}")
        reconstructed: list[str] = []
        for chunk in associated:
            reconstructed = merge_overlapping_tokens(reconstructed, tokens(chunk.get("content", "")))
            section_numbers = {
                str(blocks[(document["document_id"], block_id)].get("section_number"))
                for block_id in chunk.get("source_block_ids", [])
                if blocks.get((document["document_id"], block_id), {}).get("type") == "legal_provision"
            }
            if len(section_numbers) > 1:
                merged_provisions.append(chunk["chunk_id"])
        source_tokens = tokens(block.get("text", ""))
        if source_tokens != reconstructed:
            hierarchy_errors.append(f"{document['document_id']}/{block['section_number']}: token sequence")
        output_text = "\n".join(chunk.get("content", "") for chunk in associated)
        source_markers = {marker.casefold() for marker in SUBSECTION_PATTERN.findall(block.get("text", ""))}
        output_markers = {marker.casefold() for marker in SUBSECTION_PATTERN.findall(output_text)}
        if source_markers - output_markers:
            hierarchy_errors.append(f"{document['document_id']}/{block['section_number']}: subsection markers")
        for reference in LEGAL_REFERENCE_PATTERN.findall(block.get("text", "")):
            if normalized_text(reference) not in normalized_text(output_text):
                reference_errors.append(f"{document['document_id']}/{block['section_number']}: {reference}")

    results.append(result("S01", "SSO", "Missing legal section numbers", "FAIL" if missing_sections else "PASS", "high" if missing_sections else "info", f"{len(missing_sections)} section-number errors", "; ".join(missing_sections) or f"All {len(legal_provisions)} legal provisions retain section numbers"))
    results.append(result("S02", "SSO", "Broken subsection hierarchy", "FAIL" if hierarchy_errors else "PASS", "high" if hierarchy_errors else "info", f"{len(hierarchy_errors)} hierarchy or token reconstruction errors", "; ".join(hierarchy_errors[:30]) or "All legal provision token sequences and subsection markers reconstruct exactly"))

    part_blocks = [(document, block) for document in legal_documents for block in document.get("blocks", []) if block.get("type") == "legal_part"]
    missing_parts = [f"{document['document_id']}/{block['block_id']}" for document, block in part_blocks if not chunks_by_block.get((document["document_id"], block["block_id"]))]
    results.append(result("S03", "SSO", "Missing Part or Division headings", "FAIL" if missing_parts else "PASS", "high" if missing_parts else "info", f"{len(missing_parts)} captured legal hierarchy headings were lost", "; ".join(missing_parts) or f"All {len(part_blocks)} captured Part/Division headings are traceable", automatable="partial", action="Absence from the raw capture cannot be disproved automatically."))
    results.append(result("S04", "SSO", "Lost legal cross-references", "FAIL" if reference_errors else "PASS", "high" if reference_errors else "info", f"{len(reference_errors)} legal cross-references lost", "; ".join(reference_errors[:30]) or "All detected legal cross-reference strings are retained"))

    schedule_gaps = []
    for document in legal_documents:
        row = inventory_by_id.get(document["document_id"], {})
        expected = int(row.get("sso_toc_schedule_count") or 0)
        captured = int(row.get("sso_captured_schedule_count") or 0)
        if captured < expected:
            schedule_gaps.append(f"{document['document_id']}: captured {captured}/{expected}")
            manual_review_docs.add(document["document_id"])
    results.append(result("S05", "SSO", "Missing schedules", "MANUAL_REVIEW" if schedule_gaps else "PASS", "high" if schedule_gaps else "info", f"{len(schedule_gaps)} SSO documents have incomplete schedule captures", "; ".join(schedule_gaps) or "No schedule gap detected in inventory", automatable="partial", action="Obtain complete official source captures before relying on absent schedules." if schedule_gaps else "None"))
    results.append(result("S06", "SSO", "Incorrectly merged legal provisions", "FAIL" if merged_provisions else "PASS", "high" if merged_provisions else "info", f"{len(merged_provisions)} chunks merge multiple legal provisions", "; ".join(merged_provisions) or "No legal chunk combines different section numbers"))

    unverified_versions = []
    for document in legal_documents:
        metadata = document.get("legal_metadata") or {}
        if not metadata.get("status") or not metadata.get("revised_edition"):
            unverified_versions.append(f"{document['document_id']}: captured version metadata incomplete")
        else:
            unverified_versions.append(f"{document['document_id']}: captured metadata present; not checked against live SSO")
        manual_review_docs.add(document["document_id"])
    results.append(result("S07", "SSO", "Legal version verification", "NOT_VERIFIED", "high", "Captured legal version metadata is present but has not been independently checked against live SSO", "; ".join(unverified_versions), automatable="no", action="Verify operative versions against the official live SSO source before legal reliance."))

    incomplete_provisions = [document["document_id"] for document in legal_documents if document.get("source_capture_status") == "incomplete_provisions"]
    for document_id in incomplete_provisions:
        manual_review_docs.add(document_id)
    if incomplete_provisions:
        results.append(result("S08", "SSO", "Incomplete provision capture", "MANUAL_REVIEW", "high", f"{len(incomplete_provisions)} SSO documents are marked incomplete_provisions", "; ".join(incomplete_provisions), automatable="yes", action="Replace with complete source captures before treating the corpus as comprehensive."))

    # Reference-question alignment remains preservation-only, not RAG evaluation.
    source_gaps = [row for row in content_validation_rows if row.get("cleaning_preservation_result") != "PASS"]
    results.append(result("E01", "reference", "Reference-question preservation", "WARNING" if source_gaps else "PASS", "medium" if source_gaps else "info", f"{len(content_validation_rows)} reference rows checked upstream; {len(source_gaps)} source gaps", "; ".join(f"{row.get('validation_id')}: {row.get('answerability_note')}" for row in source_gaps) or "All mapped evidence rows passed cleaning preservation", automatable="partial", action="Treat the files as preservation references, not answer-accuracy evaluation."))

    results.append(result("M01", "model_compatibility", "Embedding tokenizer compatibility", "NOT_VERIFIED", "medium", "regex_words_v1 counts are not embedding-model token counts", "BAAI/bge-small-en-v1.5 tokenizer was not available locally during verification", automatable="no", action="Check chunks with the selected embedding tokenizer before embedding generation."))

    token_counts = [int(chunk.get("token_count", 0)) for chunk in chunks]
    metrics = {
        "total_raw_documents": len(inventory),
        "successfully_cleaned_documents": len(documents),
        "excluded_exact_duplicates": len(excluded_exact),
        "excluded_exact_duplicate_ids": excluded_exact,
        "documents_requiring_manual_review": sorted(manual_review_docs),
        "total_generated_chunks": len(chunks),
        "chunk_min": min(token_counts) if token_counts else 0,
        "chunk_median": median(token_counts) if token_counts else 0,
        "chunk_mean": mean(token_counts) if token_counts else 0,
        "chunk_max": max(token_counts) if token_counts else 0,
        "short_chunks": len(short_chunks),
        "long_chunks": len(long_chunks),
        "missing_metadata_documents": len(missing_metadata),
        "table_preservation_issues": len(table_issues),
        "legal_structure_issues": len(missing_sections) + len(hierarchy_errors) + len(reference_errors) + len(merged_provisions),
        "duplicate_chunk_groups": len(duplicate_chunks),
        "orphan_heading_chunks": len(orphan_headings),
        "hierarchy_missing_documents": hierarchy_missing_docs,
        "schedule_gap_documents": schedule_gaps,
        "raw_reproducibility_issues": len(raw_mismatches),
        "source_gap_reference_rows": len(source_gaps),
        "status_counts": dict(Counter(item.status for item in results)),
    }
    return results, metrics


def write_report(rows: list[QualityResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(QualityResult.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def write_summary(metrics: dict[str, Any], path: Path) -> None:
    failures = metrics["status_counts"].get("FAIL", 0)
    overall = "FAIL" if failures else "PASS WITH CONDITIONS"
    review_ids = metrics["documents_requiring_manual_review"]
    text = f"""# Data Quality Validation Summary

## Overall result

**{overall}**

Automated preservation checks found {failures} failed checks. Conditions remain because structural/manual review items and external model/legal verification cannot be resolved by automated local checks alone.

## Dataset totals

- Total raw documents: {metrics['total_raw_documents']}
- Successfully cleaned and retained documents: {metrics['successfully_cleaned_documents']}
- Excluded exact duplicates: {metrics['excluded_exact_duplicates']} ({', '.join(metrics['excluded_exact_duplicate_ids']) or 'none'})
- Documents requiring manual review: {len(review_ids)} ({', '.join(review_ids) or 'none'})
- Total generated chunks: {metrics['total_generated_chunks']}

## Chunk size distribution

- Counter: `regex_words_v1` (not an embedding-model tokenizer)
- Minimum: {metrics['chunk_min']}
- Median: {metrics['chunk_median']}
- Mean: {metrics['chunk_mean']:.2f}
- Maximum: {metrics['chunk_max']}
- Extremely short chunks: {metrics['short_chunks']}
- Extremely long chunks: {metrics['long_chunks']}

## Preservation results

- Documents with missing metadata: {metrics['missing_metadata_documents']}
- Raw-to-cleaned reproducibility issues: {metrics['raw_reproducibility_issues']}
- Table preservation issues: {metrics['table_preservation_issues']}
- Legal structure preservation issues: {metrics['legal_structure_issues']}
- Exact-content chunk groups: {metrics['duplicate_chunk_groups']}
- Standalone heading chunks: {metrics['orphan_heading_chunks']}
- Policy documents with no structured section paths: {len(metrics['hierarchy_missing_documents'])} ({', '.join(metrics['hierarchy_missing_documents']) or 'none'})
- Reference-question source gaps: {metrics['source_gap_reference_rows']}

## Known limitations

- The BAAI/bge-small-en-v1.5 tokenizer was not available locally. Embedding-model token limits are **NOT VERIFIED**; regex token counts are not WordPiece counts.
- Standalone headings and documents without structured section paths require manual hierarchy review.
- SSO schedule/provision capture gaps originate in the supplied raw snapshots and cannot be recovered during cleaning or chunking.
- Captured legal version metadata has not been independently checked against the live official SSO service.
- Condition and exception checks verify textual preservation, not legal interpretation or answer correctness.
- The supplied question files are preservation references only; no RAG or answer-accuracy evaluation was performed.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--documents", type=Path)
    parser.add_argument("--chunks", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--duplicate-report", type=Path)
    parser.add_argument("--content-validation", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--short-chunk-threshold", type=int)
    parser.add_argument("--long-chunk-threshold", type=int)
    parser.add_argument("--skip-raw-reparse", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config_section(args.config, "quality")
    documents_path = args.documents or Path(config.get("documents", "data/cleaned/deduplicated_documents.jsonl"))
    chunks_path = args.chunks or Path(config.get("chunks", "data/processed/chunks.jsonl"))
    inventory_path = args.inventory or Path(config.get("inventory", "reports/file_inventory.csv"))
    duplicate_path = args.duplicate_report or Path(config.get("duplicate_report", "reports/duplicate_report.csv"))
    validation_path = args.content_validation or Path(config.get("content_validation", "reports/cleaning_content_validation.csv"))
    raw_root = args.raw_root or Path(config.get("raw_root", "data/raw"))
    report_path = args.report or Path(config.get("report", "reports/quality_report.csv"))
    summary_path = args.summary or Path(config.get("summary", "reports/data_quality_summary.md"))
    short_threshold = args.short_chunk_threshold if args.short_chunk_threshold is not None else int(config.get("short_chunk_threshold", 10))
    long_threshold = args.long_chunk_threshold if args.long_chunk_threshold is not None else int(config.get("long_chunk_threshold", 500))
    if short_threshold < 0 or long_threshold <= short_threshold:
        raise ValueError("quality chunk thresholds are invalid")

    rows, metrics = evaluate_quality(
        load_jsonl(documents_path),
        load_jsonl(chunks_path),
        load_csv(inventory_path),
        raw_root=raw_root,
        duplicate_rows=load_csv(duplicate_path),
        content_validation_rows=load_csv(validation_path),
        short_threshold=short_threshold,
        long_threshold=long_threshold,
        reparse_raw=not args.skip_raw_reparse,
    )
    write_report(rows, report_path)
    write_summary(metrics, summary_path)
    print(json.dumps({"report": str(report_path), "summary": str(summary_path), **metrics}, indent=2, ensure_ascii=False))
    return 1 if metrics["status_counts"].get("FAIL", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
