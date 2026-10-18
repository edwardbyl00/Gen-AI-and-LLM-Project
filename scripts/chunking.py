"""Create embedding-safe, structure-aware chunks from cleaned documents.

The chunk text is never summarized.  Headings are repeated as context, tables
are represented row by row, and long logical units are linked explicitly.
Token limits are measured with the selected embedding model tokenizer and
include its special tokens.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Optional


TOKENIZER_NAME = "BAAI/bge-base-en-v1.5"
TARGET_TOKENS = 400
MAX_TOKENS = 512
HEADING_TYPES = {"heading", "legal_part"}


@dataclass
class Fragment:
    logical_unit_id: str
    source_block_ids: list[str]
    source_segments: list[str]
    source_slices: list[dict[str, Any]]
    block_types: list[str]
    section_path: list[str]
    source_content: str
    context_text: str
    content: str
    hierarchy: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    legal_fields: dict[str, Any] = field(default_factory=dict)
    table_fragments: list[dict[str, Any]] = field(default_factory=list)
    link_group: Optional[str] = None


@dataclass
class ChunkingReportRow:
    document_id: str
    source: str
    source_block_count: int
    chunk_count: int
    minimum_chunk_tokens: int
    maximum_chunk_tokens: int
    average_chunk_tokens: str
    oversized_chunk_count: int
    linked_chunk_count: int
    table_chunk_count: int
    legal_chunk_count: int
    manual_review_count: int
    validation_status: str


def load_embedding_tokenizer(name: str = TOKENIZER_NAME) -> Any:
    """Load the official fast Hugging Face tokenizer without truncation."""
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "transformers is required; install the pinned project requirements"
        ) from exc
    tokenizer = AutoTokenizer.from_pretrained(name, use_fast=True)
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError(f"{name} did not provide a fast tokenizer")
    return tokenizer


def token_count(text: str, tokenizer: Any) -> int:
    """Count model tokens, including special tokens, with no truncation."""
    encoded = tokenizer(text, add_special_tokens=True, truncation=False)
    return len(encoded["input_ids"])


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def comparable_text(text: str) -> str:
    """Normalize cleaned Markdown and raw HTML text for exact label matching."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("*", "")
    return normalized(text)


def enrich_document_structure(document: dict[str, Any], raw_root: Optional[Path]) -> dict[str, Any]:
    """Recover CPF section paths from explicit CSS heading semantics in raw HTML.

    This is an in-memory enrichment only: cleaned and raw files are never
    modified.  Ambiguous text is left untouched.
    """
    if document.get("source") != "CPF" or raw_root is None or not document.get("source_filename"):
        return document
    raw_path = raw_root / "cpf" / document["source_filename"]
    if not raw_path.exists():
        return document
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover - declared project dependency
        return document
    soup = BeautifulSoup(raw_path.read_text(encoding="utf-8", errors="replace"), "lxml")
    heading_levels: dict[str, int] = {}
    for element in soup.find_all(True):
        classes = set(element.get("class", []))
        if "cmp-teaser__title" in classes or "section-head" in classes:
            continue
        level: Optional[int] = None
        if "mast-head-title" in classes or "mast-head-subtitle" in classes or "headline-6" in classes:
            level = 1
        elif "headline-2" in classes or element.name == "h1":
            level = 2
        elif "headline-3" in classes or element.name == "h2":
            level = 2
        elif "headline-4" in classes or element.name == "h3":
            level = 3
        elif "headline-5" in classes or element.name in {"h4", "h5", "h6"}:
            level = 4
        if level is None:
            continue
        label = comparable_text(element.get_text(" ", strip=True))
        if label:
            heading_levels[label] = min(level, heading_levels.get(label, level))
    if not heading_levels:
        return document

    enriched = deepcopy(document)
    stack: list[str] = []
    for block in enriched["blocks"]:
        if block.get("section_path"):
            stack = list(block["section_path"])
            continue
        label = comparable_text(block.get("text", ""))
        level = heading_levels.get(label)
        if level is not None:
            stack = stack[: max(0, level - 1)]
            stack.append(block.get("text", "").strip())
            block["raw_heading_level"] = level
            block["structure_source"] = "raw_html_heading_css"
        if stack:
            block["section_path"] = list(stack)
    return enriched


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value not in (None, "")))


def safe_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")[:48]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{clean}-{digest}" if clean else digest


def join_context(context: str, body: str) -> str:
    return f"{context}\n\n{body}".strip() if context else body.strip()


def hierarchy_for(block: dict[str, Any], state: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Infer hierarchy only from explicit labels printed in the source text."""
    text = normalized(block.get("text", ""))
    flags: list[str] = []
    block_type = block.get("type", "")

    part_match = re.match(r"^(PART\s+[A-Z0-9IVX]+)\b(?:\s*[—:-]\s*(.*))?", text, re.I)
    if part_match:
        state["part_or_chapter"] = part_match.group(1)
    section = block.get("section_number")
    numbered_match = re.match(r"^(\d+[A-Za-z]?)[.)]\s+", text)
    printed_identifier = str(section) if section else (numbered_match.group(1) if numbered_match else None)
    if printed_identifier:
        state["subsection_identifier"] = printed_identifier

    list_labels = re.findall(r"(?m)^\s*(\([a-zivx]+\)|[a-zivx]+[.)])\s+", block.get("text", ""), re.I)
    definition = None
    definition_match = re.match(
        r"^[“\"]([^”\"]+)[”\"]\s+(?:means|includes|has the meaning)", text,
        re.I,
    )
    if definition_match:
        definition = definition_match.group(1)

    hierarchy = {
        "part_or_chapter": state.get("part_or_chapter"),
        "subsection_identifier": printed_identifier,
        "parent_clause": block.get("parent_clause") or (
            state.get("subsection_identifier") if list_labels and not printed_identifier else None
        ),
        "list_labels": unique(list_labels),
        "definition_term": definition,
    }
    if (
        block_type not in HEADING_TYPES | {"legal_front_matter"}
        and not block.get("section_path")
        and not section
        and not state.get("part_or_chapter")
    ):
        flags.extend(["hierarchy_ambiguous", "manual_review"])
    return hierarchy, flags


def context_for(document: dict[str, Any], block: dict[str, Any], hierarchy: dict[str, Any]) -> str:
    lines = [f"Document: {document['title']}"]
    path = block.get("section_path", [])
    if path:
        lines.append("Section: " + " > ".join(path))
    if hierarchy.get("part_or_chapter"):
        lines.append("Part/Chapter: " + hierarchy["part_or_chapter"])
    if block.get("section_number"):
        label = f"Provision: {block['section_number']}"
        if block.get("section_title"):
            label += f" — {block['section_title']}"
        lines.append(label)
    if hierarchy.get("definition_term"):
        lines.append("Definition: " + hierarchy["definition_term"])
    return "\n".join(lines)


def tokenizer_offsets(text: str, tokenizer: Any) -> list[tuple[int, int]]:
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        truncation=False,
        return_offsets_mapping=True,
    )
    return [tuple(pair) for pair in encoded["offset_mapping"] if pair[1] > pair[0]]


def boundary_positions(text: str) -> list[int]:
    """Return increasingly weaker semantic boundaries in source order."""
    patterns = [
        r"\n\s*\n+",                       # paragraphs
        r"(?<=[.!?])\s+(?=[A-Z0-9“\"(])", # sentences
        r"\n(?=\s*(?:[-•*]|\([a-z0-9]+\)))", # bullets/clauses
        r"(?<=;)\s+",                       # clause
        r"(?<=:)\s+",                       # last semantic fallback
    ]
    positions: set[int] = set()
    for pattern in patterns:
        positions.update(match.end() for match in re.finditer(pattern, text))
    return sorted(position for position in positions if 0 < position < len(text))


def split_to_fit(
    text: str,
    context: str,
    tokenizer: Any,
    max_tokens: int,
) -> tuple[list[str], bool]:
    """Split losslessly at semantic boundaries; use token offsets only last."""
    if token_count(join_context(context, text), tokenizer) <= max_tokens:
        return [text.strip()], False
    offsets = tokenizer_offsets(text, tokenizer)
    if not offsets:
        return [], False
    context_cost = token_count(join_context(context, ""), tokenizer)
    # context_cost already includes the tokenizer's special tokens.
    budget = max(1, max_tokens - context_cost)
    boundaries = boundary_positions(text)
    pieces: list[str] = []
    forced = False
    start_char = 0
    while start_char < len(text):
        remaining = text[start_char:]
        if token_count(join_context(context, remaining), tokenizer) <= max_tokens:
            if remaining.strip():
                pieces.append(remaining.strip())
            break
        local_offsets = tokenizer_offsets(remaining, tokenizer)
        hard_end = local_offsets[min(budget, len(local_offsets)) - 1][1]
        candidates = [p - start_char for p in boundaries if start_char < p <= start_char + hard_end]
        end = max(candidates) if candidates else hard_end
        if not candidates:
            forced = True
        piece = remaining[:end].strip()
        # Account for tokenization interactions at the boundary.
        while piece and token_count(join_context(context, piece), tokenizer) > max_tokens:
            piece_offsets = tokenizer_offsets(piece, tokenizer)
            piece = piece[: piece_offsets[-2][1]].strip()
            forced = True
        if not piece:
            raise ValueError("context consumes the entire model token budget")
        pieces.append(piece)
        consumed = text.find(piece, start_char) + len(piece)
        start_char = consumed
        while start_char < len(text) and text[start_char].isspace():
            start_char += 1
    return pieces, forced


def legal_boundaries(text: str) -> list[int]:
    numeric_positions = [
        match.start()
        for match in re.finditer(r"(?m)(?<!\w)(?=\(\d+[A-Za-z]?\)\s*)", text)
        if match.start() > 0
    ]
    # Keep the provision heading/preamble with its first numbered subsection.
    positions = numeric_positions[1:] if numeric_positions else []
    positions += [
        match.start()
        for match in re.finditer(
            r"(?m)(?=^[“\"][^”\"\n]+[”\"]\s+(?:means|includes|has the meaning))",
            text,
            re.I,
        )
        if match.start() > 0
    ]
    return sorted(set(positions))


def split_at_positions(text: str, positions: list[int]) -> list[str]:
    points = [0] + positions + [len(text)]
    return [text[a:b].strip() for a, b in zip(points, points[1:]) if text[a:b].strip()]


def fragment_for_piece(
    document: dict[str, Any],
    block: dict[str, Any],
    hierarchy: dict[str, Any],
    context: str,
    piece: str,
    part: int,
    flags: list[str],
    link_group: Optional[str],
) -> Fragment:
    return Fragment(
        logical_unit_id=f"{block['block_id']}:logical",
        source_block_ids=[block["block_id"]],
        source_segments=[f"{block['block_id']}:part:{part}"],
        source_slices=[{"block_id": block["block_id"], "part_index": part, "text": piece}],
        block_types=[block["type"]],
        section_path=list(block.get("section_path", [])),
        source_content=piece,
        context_text=context,
        content=join_context(context, piece),
        hierarchy=hierarchy,
        flags=unique(flags),
        legal_fields={
            key: block.get(key)
            for key in ("section_number", "section_title", "section_status")
            if block.get(key) not in (None, "")
        },
        link_group=link_group,
    )


def text_fragments(
    document: dict[str, Any],
    block: dict[str, Any],
    hierarchy: dict[str, Any],
    base_flags: list[str],
    tokenizer: Any,
    target_tokens: int,
    max_tokens: int,
) -> list[Fragment]:
    context = context_for(document, block, hierarchy)
    text = block.get("text", "").strip()
    initial = [text]
    flags = list(base_flags)
    if block["type"] == "legal_provision" and token_count(join_context(context, text), tokenizer) > max_tokens:
        initial = split_at_positions(text, legal_boundaries(text))
        if len(initial) > 1:
            flags.append("split_at_legal_boundary")
            packed: list[str] = []
            current = ""
            for unit in initial:
                candidate = f"{current} {unit}".strip()
                if current and token_count(join_context(context, candidate), tokenizer) > target_tokens:
                    packed.append(current)
                    current = unit
                else:
                    current = candidate
            if current:
                packed.append(current)
            initial = packed
    pieces: list[str] = []
    forced = False
    for unit in initial:
        fitted, unit_forced = split_to_fit(unit, context, tokenizer, max_tokens)
        pieces.extend(fitted)
        forced = forced or unit_forced
    if len(pieces) > 1:
        flags.append("linked_logical_unit")
    if forced:
        flags.extend(["forced_token_split", "manual_review"])
    link_group = f"{document['document_id']}:{block['block_id']}" if len(pieces) > 1 else None
    return [
        fragment_for_piece(document, block, hierarchy, context, piece, index, flags, link_group)
        for index, piece in enumerate(pieces, start=1)
    ]


def table_layout(table: dict[str, Any]) -> tuple[list[list[str]], list[list[tuple[int, int] | None]]]:
    rows = int(table.get("row_count", 0))
    columns = int(table.get("column_count", 0))
    occupied: dict[tuple[int, int], str] = {}
    origins: dict[tuple[int, int], tuple[int, int]] = {}
    for cell in table.get("cells", []):
        origin = (int(cell["row"]), int(cell["column"]))
        for row in range(int(cell["row"]), int(cell["row"]) + max(1, int(cell.get("rowspan", 1)))):
            for col in range(int(cell["column"]), int(cell["column"]) + max(1, int(cell.get("colspan", 1)))):
                occupied[(row, col)] = cell.get("text", "")
                origins[(row, col)] = origin
    matrix = [[occupied.get((row, col), "") for col in range(columns)] for row in range(rows)]
    origin_matrix = [[origins.get((row, col)) for col in range(columns)] for row in range(rows)]
    return matrix, origin_matrix


def table_matrix(table: dict[str, Any]) -> list[list[str]]:
    return table_layout(table)[0]


def table_header_rows(table: dict[str, Any]) -> list[int]:
    return sorted({int(cell["row"]) for cell in table.get("cells", []) if cell.get("is_header")})


def semantic_header_rows(matrix: list[list[str]]) -> list[int]:
    """Recognise only first rows whose own text explicitly names columns."""
    if len(matrix) < 2 or len(matrix[0]) < 2:
        return []
    first = [normalized(value).casefold() for value in matrix[0]]
    if any(len(value.split()) > 16 for value in first if value):
        return []
    joined = " | ".join(first)
    explicit_cues = (
        "type of flat", "type of purchase", "type of loan", "maximum amount",
        "property ownership", "amount to set aside", "date of property purchase",
        "using cash", "using cpf", "bank loan", "hdb housing loan",
        "hdb flat", "new flat", "resale flat", "age of youngest owner",
    )
    if first[0] == "" and "age of youngest owner" in joined and len(matrix) > 2:
        return [0, 1]
    if any(cue in joined for cue in explicit_cues):
        return [0]

    # A comparison table may express subject headers as source-written prose
    # rather than nouns.  Accept that layout only when the following row uses
    # the same explicit measure label in every column and the candidate
    # subjects remain distinct after numbers are removed.
    def canonical_without_numbers(value: str) -> str:
        return normalized(re.sub(r"(?:S\$|\$)?\d[\d,.%]*\*?", "", value)).casefold()

    candidate_subjects = [canonical_without_numbers(value) for value in matrix[0]]
    following_lines = [
        {canonical_without_numbers(line) for line in value.splitlines() if canonical_without_numbers(line)}
        for value in matrix[1]
    ]
    shared_measure = set.intersection(*following_lines) if following_lines and all(following_lines) else set()
    if all(candidate_subjects) and len(set(candidate_subjects)) == len(candidate_subjects) and shared_measure:
        return [0]
    return []


def combined_headers(matrix: list[list[str]], header_rows: list[int]) -> list[str]:
    if not matrix:
        return []
    return [
        " / ".join(unique(matrix[row][col] for row in header_rows if matrix[row][col])) or f"Column {col + 1}"
        for col in range(len(matrix[0]))
    ]


def table_context(document: dict[str, Any], block: dict[str, Any], hierarchy: dict[str, Any]) -> str:
    return context_for(document, block, hierarchy) + "\nContent type: table"


def table_row_items(
    headers: list[str], row: list[str], origins: list[tuple[int, int] | None]
) -> list[tuple[int, str, str]]:
    grouped: dict[tuple[int, int] | tuple[str, int], dict[str, Any]] = {}
    for column, value in enumerate(row):
        if not value:
            continue
        key: tuple[int, int] | tuple[str, int] = origins[column] or ("column", column)
        item = grouped.setdefault(key, {"column": column, "headers": [], "value": value})
        item["headers"].append(headers[column])
    return [
        (item["column"], " / ".join(unique(item["headers"])), item["value"])
        for item in grouped.values()
    ]


def table_row_body(
    headers: list[str], row: list[str], origins: list[tuple[int, int] | None], row_label: str
) -> str:
    lines = [f"Table row: {row_label}"]
    lines.extend(f"{header}: {value}" for _, header, value in table_row_items(headers, row, origins))
    return "\n".join(lines)


def table_fragments(
    document: dict[str, Any],
    block: dict[str, Any],
    hierarchy: dict[str, Any],
    base_flags: list[str],
    tokenizer: Any,
    max_tokens: int,
    inherited_headers: Optional[list[str]] = None,
) -> list[Fragment]:
    matrix, origins = table_layout(block["table"])
    if not matrix:
        return []
    headers_at = table_header_rows(block["table"])
    if not headers_at:
        headers_at = semantic_header_rows(matrix)
        if headers_at:
            base_flags = base_flags + ["semantic_header_recovered"]
        elif inherited_headers and len(inherited_headers) == len(matrix[0]):
            base_flags = base_flags + ["inherited_comparison_headers"]
        else:
            base_flags = base_flags + ["missing_explicit_table_header", "manual_review"]
    headers = (
        combined_headers(matrix, headers_at)
        if headers_at else list(inherited_headers)
        if inherited_headers and len(inherited_headers) == len(matrix[0])
        else [f"Column {index + 1}" for index in range(len(matrix[0]))]
    )
    body_rows = [row for row in range(len(matrix)) if row not in headers_at]
    if not body_rows and headers_at:
        body_rows = headers_at
        headers_at = []
    context = table_context(document, block, hierarchy)
    result: list[Fragment] = []
    for row_index in body_rows:
        row = matrix[row_index]
        row_label = row[0] or f"Row {row_index + 1}"
        items = table_row_items(headers, row, origins[row_index])
        whole_body = table_row_body(headers, row, origins[row_index], row_label)
        pieces: list[tuple[int | None, str]] = []
        forced = False
        if token_count(join_context(context, whole_body), tokenizer) <= max_tokens:
            pieces = [(None, whole_body)]
        else:
            for col_index, header, value in items:
                prefix = f"Table row: {row_label}\nColumn: {header}\nValue:"
                subpieces, subforced = split_to_fit(value, join_context(context, prefix), tokenizer, max_tokens)
                pieces.extend((col_index, join_context(prefix, piece)) for piece in subpieces)
                forced = forced or subforced
        link_group = (
            f"{document['document_id']}:{block['block_id']}:row:{row_index}"
            if len(pieces) > 1 else None
        )
        for part, (col_index, body) in enumerate(pieces, start=1):
            flags = list(base_flags) + ["table_headers_and_row_label_repeated"]
            if len(pieces) > 1:
                flags.extend(["split_oversized_table_row", "linked_logical_unit"])
            if forced:
                flags.extend(["forced_token_split", "manual_review"])
            table_meta = {
                "source_block_id": block["block_id"],
                "original_row_indices": [row_index],
                "header_row_indices": headers_at,
                "row_label": row_label,
                "column_index": col_index,
                "column_header": next((header for column, header, _ in items if column == col_index), None) if col_index is not None else None,
            }
            result.append(Fragment(
                logical_unit_id=f"{block['block_id']}:row:{row_index}",
                source_block_ids=[block["block_id"]],
                source_segments=[f"{block['block_id']}:row:{row_index}:part:{part}"],
                source_slices=[{
                    "block_id": block["block_id"], "row_index": row_index,
                    "column_index": col_index, "part_index": part,
                    "text": body.split("\nValue:\n", 1)[-1] if col_index is not None else whole_body,
                }],
                block_types=["table"], section_path=list(block.get("section_path", [])),
                source_content=body, context_text=context,
                content=join_context(context, body), hierarchy=hierarchy,
                flags=unique(flags), table_fragments=[table_meta], link_group=link_group,
            ))
    return result


def document_fragments(document: dict[str, Any], tokenizer: Any, target_tokens: int, max_tokens: int) -> list[Fragment]:
    fragments: list[Fragment] = []
    state: dict[str, Any] = {}
    previous_table_headers: Optional[list[str]] = None
    previous_table_section: Optional[list[str]] = None
    intervening_text: list[str] = []
    for block in document["blocks"]:
        hierarchy, flags = hierarchy_for(block, state)
        if block["type"] in HEADING_TYPES:
            continue
        if block["type"] == "table":
            matrix = table_matrix(block["table"])
            own_header_rows = table_header_rows(block["table"]) or semantic_header_rows(matrix)
            inherited_headers = None
            bridge = " ".join(intervening_text).casefold()
            if (
                not own_header_rows
                and previous_table_headers
                and previous_table_section == list(block.get("section_path", []))
                and len(intervening_text) <= 3
                and any(term in bridge for term in ("respective", "respectively", "based on their"))
                and len(previous_table_headers) == (len(matrix[0]) if matrix else 0)
            ):
                inherited_headers = previous_table_headers
            fragments.extend(
                table_fragments(
                    document, block, hierarchy, flags, tokenizer, max_tokens,
                    inherited_headers=inherited_headers,
                )
            )
            if own_header_rows:
                previous_table_headers = combined_headers(matrix, own_header_rows)
                previous_table_section = list(block.get("section_path", []))
            elif inherited_headers:
                previous_table_headers = inherited_headers
                previous_table_section = list(block.get("section_path", []))
            else:
                previous_table_headers = None
                previous_table_section = None
            intervening_text = []
        elif block.get("text", "").strip():
            fragments.extend(text_fragments(document, block, hierarchy, flags, tokenizer, target_tokens, max_tokens))
            if block.get("raw_heading_level"):
                previous_table_headers = None
                previous_table_section = None
                intervening_text = []
            else:
                intervening_text.append(block["text"])
    return fragments


def can_group(left: Fragment, right: Fragment) -> bool:
    return (
        not left.link_group and not right.link_group
        and not left.table_fragments and not right.table_fragments
        and left.section_path == right.section_path
        and left.context_text == right.context_text
        and not left.legal_fields and not right.legal_fields
    )


def merge_fragments(parts: list[Fragment]) -> Fragment:
    first = parts[0]
    source_content = "\n\n".join(part.source_content for part in parts)
    hierarchy = dict(first.hierarchy)
    hierarchy["list_labels"] = unique(
        label for part in parts for label in part.hierarchy.get("list_labels", [])
    )
    for key in ("part_or_chapter", "subsection_identifier", "parent_clause", "definition_term"):
        values = unique(str(part.hierarchy[key]) for part in parts if part.hierarchy.get(key))
        hierarchy[key] = values[0] if len(values) == 1 else values or None
    flags = unique(flag for part in parts for flag in part.flags)
    if any(hierarchy.get(key) for key in ("part_or_chapter", "subsection_identifier", "parent_clause", "list_labels")):
        flags = [flag for flag in flags if flag != "hierarchy_ambiguous"]
        if "missing_explicit_table_header" not in flags and "forced_token_split" not in flags:
            flags = [flag for flag in flags if flag != "manual_review"]
    return Fragment(
        logical_unit_id="+".join(part.logical_unit_id for part in parts),
        source_block_ids=unique(block for part in parts for block in part.source_block_ids),
        source_segments=[segment for part in parts for segment in part.source_segments],
        source_slices=[item for part in parts for item in part.source_slices],
        block_types=unique(kind for part in parts for kind in part.block_types),
        section_path=first.section_path, source_content=source_content,
        context_text=first.context_text, content=join_context(first.context_text, source_content),
        hierarchy=hierarchy,
        flags=flags,
        legal_fields=first.legal_fields if len(parts) == 1 else {},
        table_fragments=[item for part in parts for item in part.table_fragments],
        link_group=first.link_group if len(parts) == 1 else None,
    )


def group_fragments(fragments: list[Fragment], tokenizer: Any, target: int, maximum: int) -> list[Fragment]:
    groups: list[Fragment] = []
    current: list[Fragment] = []
    for fragment in fragments:
        if not current:
            current = [fragment]
            continue
        candidate = merge_fragments(current + [fragment])
        if can_group(current[-1], fragment) and token_count(candidate.content, tokenizer) <= target:
            current.append(fragment)
        else:
            groups.append(merge_fragments(current))
            current = [fragment]
    if current:
        groups.append(merge_fragments(current))
    if any(token_count(item.content, tokenizer) > maximum for item in groups):
        raise ValueError("grouping produced an oversized chunk")
    return groups


def chunk_from_fragment(document: dict[str, Any], fragment: Fragment, index: int, tokenizer: Any, target: int, maximum: int) -> dict[str, Any]:
    count = token_count(fragment.content, tokenizer)
    return {
        "schema_version": "2.0", "chunk_id": f"{document['document_id']}_c{index:04d}",
        "chunk_index": index, "chunk_count": 0, "document_id": document["document_id"],
        "source": document["source"], "title": document["title"],
        "document_type": document["document_type"], "section_path": fragment.section_path,
        "hierarchy": fragment.hierarchy,
        "section_number": fragment.legal_fields.get("section_number"),
        "section_title": fragment.legal_fields.get("section_title"),
        "section_status": fragment.legal_fields.get("section_status"),
        "source_url": document["source_url"], "retrieved_at": document["retrieved_at"],
        "effective_date": document.get("effective_date"),
        "source_capture_status": document.get("source_capture_status", "not_applicable"),
        "logical_unit_id": fragment.logical_unit_id,
        "source_block_ids": fragment.source_block_ids, "source_segments": fragment.source_segments,
        "source_slices": fragment.source_slices, "block_types": fragment.block_types,
        "contains_table": bool(fragment.table_fragments), "table_fragments": fragment.table_fragments,
        "context_text": fragment.context_text, "source_content": fragment.source_content,
        "tokenizer": TOKENIZER_NAME,
        "token_counter": f"{TOKENIZER_NAME}_including_special_tokens",
        "token_count": count,
        "token_count_including_special_tokens": count,
        "target_chunk_size": target, "maximum_chunk_size": maximum,
        "configured_overlap": 0, "oversized": count > maximum,
        "parent_id": safe_id(fragment.link_group) if fragment.link_group else None,
        "part_index": None, "total_parts": None,
        "previous_chunk_id": None, "next_chunk_id": None,
        "requires_context": bool(fragment.link_group), "flags": fragment.flags,
        "content": fragment.content,
    }


def apply_links(chunks: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        if chunk["parent_id"]:
            groups.setdefault(chunk["parent_id"], []).append(chunk)
    for members in groups.values():
        for index, chunk in enumerate(members):
            chunk["part_index"] = index + 1
            chunk["total_parts"] = len(members)
            chunk["previous_chunk_id"] = members[index - 1]["chunk_id"] if index else None
            chunk["next_chunk_id"] = members[index + 1]["chunk_id"] if index + 1 < len(members) else None


def chunk_document(document: dict[str, Any], tokenizer: Any, target: int = TARGET_TOKENS, maximum: int = MAX_TOKENS) -> list[dict[str, Any]]:
    fragments = document_fragments(document, tokenizer, target, maximum)
    grouped = group_fragments(fragments, tokenizer, target, maximum)
    chunks = [chunk_from_fragment(document, fragment, i, tokenizer, target, maximum) for i, fragment in enumerate(grouped, 1)]
    apply_links(chunks)
    for chunk in chunks:
        chunk["chunk_count"] = len(chunks)
    return chunks


def validate_chunks(documents: list[dict[str, Any]], chunks: list[dict[str, Any]], tokenizer: Any, maximum: int) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    if len(by_id) != len(chunks):
        issues.append({"severity": "FAIL", "document_id": "*", "chunk_id": "", "check": "unique_chunk_id", "detail": "duplicate chunk IDs"})
    documents_by_id = {doc["document_id"]: doc for doc in documents}
    covered: dict[tuple[str, str], list[str]] = {}
    chunks_by_parent: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        actual = token_count(chunk["content"], tokenizer)
        if actual != chunk["token_count_including_special_tokens"]:
            issues.append({"severity": "FAIL", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "token_count", "detail": f"stored={chunk['token_count_including_special_tokens']}; actual={actual}"})
        if actual > maximum:
            issues.append({"severity": "FAIL", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "model_limit", "detail": str(actual)})
        if set(chunk["block_types"]).issubset(HEADING_TYPES):
            issues.append({"severity": "FAIL", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "heading_only", "detail": "heading-only chunk"})
        for item in chunk["source_slices"]:
            covered.setdefault((chunk["document_id"], item["block_id"]), []).append(item.get("text", ""))
        if chunk["parent_id"]:
            chunks_by_parent.setdefault(chunk["parent_id"], []).append(chunk)
            expected_prev = chunk["previous_chunk_id"]
            expected_next = chunk["next_chunk_id"]
            if expected_prev and (expected_prev not in by_id or by_id[expected_prev]["next_chunk_id"] != chunk["chunk_id"]):
                issues.append({"severity": "FAIL", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "previous_link", "detail": str(expected_prev)})
            if expected_next and (expected_next not in by_id or by_id[expected_next]["previous_chunk_id"] != chunk["chunk_id"]):
                issues.append({"severity": "FAIL", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "next_link", "detail": str(expected_next)})
        if "manual_review" in chunk["flags"]:
            issues.append({"severity": "WARNING", "document_id": chunk["document_id"], "chunk_id": chunk["chunk_id"], "check": "manual_review", "detail": ";".join(chunk["flags"])})
    for parent_id, members in chunks_by_parent.items():
        ordered = sorted(members, key=lambda item: item["part_index"])
        expected = list(range(1, len(ordered) + 1))
        actual = [item["part_index"] for item in ordered]
        totals = {item["total_parts"] for item in ordered}
        if actual != expected or totals != {len(ordered)}:
            first = ordered[0]
            issues.append({"severity": "FAIL", "document_id": first["document_id"], "chunk_id": first["chunk_id"], "check": "link_group_order", "detail": parent_id})
    for document_id, document in documents_by_id.items():
        for block in document["blocks"]:
            if block["type"] in HEADING_TYPES or not block.get("text", "").strip() or block["type"] == "table":
                continue
            reconstructed = re.sub(r"\s+", "", "".join(covered.get((document_id, block["block_id"]), [])))
            if reconstructed != re.sub(r"\s+", "", block["text"]):
                issues.append({"severity": "FAIL", "document_id": document_id, "chunk_id": "", "check": "content_reconstruction", "detail": block["block_id"]})
        for block in (item for item in document["blocks"] if item["type"] == "table"):
            rendered = " ".join(
                chunk["source_content"] for chunk in chunks
                if chunk["document_id"] == document_id and block["block_id"] in chunk["source_block_ids"]
            )
            compact_rendered = re.sub(r"\s+", "", rendered)
            slices = [
                item for chunk in chunks
                if chunk["document_id"] == document_id and block["block_id"] in chunk["source_block_ids"]
                for item in chunk["source_slices"] if item["block_id"] == block["block_id"]
            ]
            missing_cells = []
            for cell in block["table"].get("cells", []):
                if not cell.get("text", "").strip():
                    continue
                cell_parts = [
                    item.get("text", "") for item in slices
                    if item.get("row_index") == int(cell["row"])
                    and item.get("column_index") == int(cell["column"])
                ]
                expected = re.sub(r"\s+", "", cell["text"])
                reconstructed = re.sub(r"\s+", "", "".join(cell_parts))
                if expected not in compact_rendered and reconstructed != expected:
                    missing_cells.append(f"r{cell['row']}c{cell['column']}")
            if missing_cells:
                issues.append({"severity": "FAIL", "document_id": document_id, "chunk_id": "", "check": "table_cell_coverage", "detail": f"{block['block_id']}: {','.join(missing_cells)}"})
        if not any(chunk["document_id"] == document_id for chunk in chunks):
            issues.append({"severity": "FAIL", "document_id": document_id, "chunk_id": "", "check": "document_coverage", "detail": "no chunks"})
    return issues


def load_simple_chunking_config(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    active = False
    base_indent = 0
    for raw in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if line.strip() == "chunking:":
            active, base_indent = True, indent
            continue
        if active and indent <= base_indent:
            active = False
        if active and ":" in line:
            key, value = [part.strip() for part in line.strip().split(":", 1)]
            result[key] = int(value) if value.isdigit() else value.strip("'\"")
    return result


def write_jsonl(items: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def write_csv(items: list[Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not items:
        path.write_text("", encoding="utf-8")
        return
    rows = [asdict(item) if hasattr(item, "__dataclass_fields__") else item for item in items]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def report_row(document: dict[str, Any], chunks: list[dict[str, Any]], issues: list[dict[str, str]]) -> ChunkingReportRow:
    counts = [chunk["token_count_including_special_tokens"] for chunk in chunks]
    failures = [issue for issue in issues if issue["severity"] == "FAIL" and issue["document_id"] in (document["document_id"], "*")]
    return ChunkingReportRow(
        document_id=document["document_id"], source=document["source"],
        source_block_count=len(document["blocks"]), chunk_count=len(chunks),
        minimum_chunk_tokens=min(counts) if counts else 0,
        maximum_chunk_tokens=max(counts) if counts else 0,
        average_chunk_tokens=f"{mean(counts):.2f}" if counts else "0.00",
        oversized_chunk_count=sum(chunk["oversized"] for chunk in chunks),
        linked_chunk_count=sum(chunk["requires_context"] for chunk in chunks),
        table_chunk_count=sum(chunk["contains_table"] for chunk in chunks),
        legal_chunk_count=sum("legal_provision" in chunk["block_types"] for chunk in chunks),
        manual_review_count=sum("manual_review" in chunk["flags"] for chunk in chunks),
        validation_status="FAIL" if failures else "PASS",
    )


def write_summary(documents: list[dict[str, Any]], chunks: list[dict[str, Any]], issues: list[dict[str, str]], path: Path, target: int, maximum: int) -> None:
    counts = sorted(chunk["token_count_including_special_tokens"] for chunk in chunks)
    failures = [issue for issue in issues if issue["severity"] == "FAIL"]
    warnings = [issue for issue in issues if issue["severity"] == "WARNING"]
    q1 = counts[(len(counts) - 1) // 4] if counts else 0
    q3 = counts[(3 * (len(counts) - 1)) // 4] if counts else 0
    text = f"""# Embedding-Safe Structure-Aware Chunking Summary

## Configuration

- Documents: {len(documents)}
- Tokenizer: `{TOKENIZER_NAME}` (special tokens included; no truncation)
- Target size: {target} tokens
- Hard maximum: {maximum} tokens
- Overlap: 0 tokens; linked chunks use explicit navigation metadata

## Results

- Chunks: {len(chunks)}
- Token distribution (min / Q1 / median / mean / Q3 / max): {min(counts) if counts else 0} / {q1} / {median(counts) if counts else 0} / {mean(counts):.2f} / {q3} / {max(counts) if counts else 0}
- Chunks over {maximum}: {sum(value > maximum for value in counts)}
- Linked chunks: {sum(chunk['requires_context'] for chunk in chunks)}
- Table chunks: {sum(chunk['contains_table'] for chunk in chunks)}
- Legal-provision chunks: {sum('legal_provision' in chunk['block_types'] for chunk in chunks)}
- Manual-review chunks: {sum('manual_review' in chunk['flags'] for chunk in chunks)}
- Validation failures: {len(failures)}
- Validation warnings: {len(warnings)}
- Overall validation: {'FAIL' if failures else 'PASS'}

Headings are stored as repeated context rather than standalone chunks. Tables preserve row labels and column headers. Long legal provisions and oversized table rows are split at semantic boundaries and connected through `parent_id`, ordered part fields, and previous/next chunk IDs.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--validation-report", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--tokenizer")
    parser.add_argument("--target-chunk-size", type=int)
    parser.add_argument("--max-chunk-size", type=int)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_simple_chunking_config(args.config)
    input_path = args.input or Path(config.get("input", "data/cleaned/deduplicated_documents.jsonl"))
    output_path = args.output or Path(config.get("output", "data/processed/chunks.jsonl"))
    report_path = args.report or Path(config.get("report", "reports/chunking_report.csv"))
    summary_path = args.summary or Path(config.get("summary", "reports/chunking_summary.md"))
    validation_path = args.validation_report or Path(config.get("validation_report", "reports/chunking_validation.csv"))
    raw_root = args.raw_root or Path(config.get("raw_root", "data/raw"))
    tokenizer_name = args.tokenizer or config.get("tokenizer", TOKENIZER_NAME)
    target = args.target_chunk_size or int(config.get("target_chunk_size", TARGET_TOKENS))
    maximum = args.max_chunk_size or int(config.get("max_chunk_size", MAX_TOKENS))
    if tokenizer_name != TOKENIZER_NAME:
        raise ValueError(f"this project requires {TOKENIZER_NAME}")
    if not 350 <= target <= 400 or maximum != 512:
        raise ValueError("target must be 350-400 and maximum must be 512")
    tokenizer = load_embedding_tokenizer(tokenizer_name)
    documents = [
        enrich_document_structure(json.loads(line), raw_root)
        for line in input_path.read_text(encoding="utf-8").splitlines() if line
    ]
    chunks: list[dict[str, Any]] = []
    for document in documents:
        chunks.extend(chunk_document(document, tokenizer, target, maximum))
    issues = validate_chunks(documents, chunks, tokenizer, maximum)
    write_jsonl(chunks, output_path)
    write_csv([report_row(doc, [c for c in chunks if c["document_id"] == doc["document_id"]], issues) for doc in documents], report_path)
    write_csv(issues, validation_path)
    write_summary(documents, chunks, issues, summary_path, target, maximum)
    failures = sum(issue["severity"] == "FAIL" for issue in issues)
    print(json.dumps({
        "documents": len(documents), "chunks": len(chunks),
        "minimum_tokens": min(c["token_count_including_special_tokens"] for c in chunks),
        "maximum_tokens": max(c["token_count_including_special_tokens"] for c in chunks),
        "oversized_chunks": sum(c["oversized"] for c in chunks),
        "linked_chunks": sum(c["requires_context"] for c in chunks),
        "validation_failures": failures, "validation_warnings": len(issues) - failures,
        "output": str(output_path), "validation_report": str(validation_path),
    }, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
