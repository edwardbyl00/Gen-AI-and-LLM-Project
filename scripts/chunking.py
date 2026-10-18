"""Create structure-aware chunks from deduplicated cleaned documents.

Policy pages are grouped by section path, large tables are split by row while
repeating headers, and legislation is split at numeric subsection boundaries
where possible. No text is summarized or generated.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Optional


TOKEN_PATTERN = re.compile(
    r"(?:S\$|\$)?\d[\d,.]*(?:%|[A-Za-z]+)?|[^\W_]+(?:[’'\-][^\W_]+)*",
    flags=re.UNICODE,
)


@dataclass
class Unit:
    segment_id: str
    source_block_ids: list[str]
    block_types: list[str]
    section_path: list[str]
    content: str
    overlap_tokens: int = 0
    flags: list[str] = field(default_factory=list)
    legal_fields: dict[str, Any] = field(default_factory=dict)
    table_fragment: Optional[dict[str, Any]] = None


@dataclass
class ChunkingReportRow:
    document_id: str
    source: str
    source_block_count: int
    chunk_count: int
    total_chunk_tokens: int
    minimum_chunk_tokens: int
    maximum_chunk_tokens: int
    average_chunk_tokens: str
    oversized_chunk_count: int
    table_chunk_count: int
    legal_chunk_count: int
    source_capture_status: str
    warnings: str


def token_spans(text: str) -> list[tuple[int, int]]:
    return [match.span() for match in TOKEN_PATTERN.finditer(text)]


def count_tokens(text: str) -> int:
    """Count deterministic word-like tokens using regex_words_v1."""
    return len(token_spans(text))


def window_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    """Split long text by token spans without dropping leading/trailing content."""
    spans = token_spans(text)
    if len(spans) <= chunk_size:
        return [(text.strip(), 0)]
    step = max(1, chunk_size - overlap)
    windows: list[tuple[str, int]] = []
    start_token = 0
    while start_token < len(spans):
        end_token = min(len(spans), start_token + chunk_size)
        start_char = 0 if start_token == 0 else spans[start_token][0]
        end_char = len(text) if end_token == len(spans) else spans[end_token - 1][1]
        windows.append((text[start_char:end_char].strip(), 0 if start_token == 0 else overlap))
        if end_token == len(spans):
            break
        start_token += step
    return windows


def split_legal_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int, list[str]]]:
    if count_tokens(text) <= chunk_size:
        return [(text, 0, [])]
    boundaries = [
        match.start()
        for match in re.finditer(r"(?<!\w)\(\d+[A-Za-z]?\)\s*", text)
    ]
    parts: list[str] = []
    if len(boundaries) >= 2:
        # Keep the section number/title and subsection (1) together, then split
        # before each later numeric subsection. Lettered paragraphs stay with
        # their parent subsection.
        starts = [0] + boundaries[1:]
        parts = [text[start:end].strip() for start, end in zip(starts, starts[1:] + [len(text)])]
    else:
        parts = [text]

    results: list[tuple[str, int, list[str]]] = []
    for part in parts:
        if count_tokens(part) <= chunk_size:
            results.append((part, 0, ["split_at_legal_subsection"] if len(parts) > 1 else []))
            continue
        for piece, piece_overlap in window_text(part, chunk_size, overlap):
            results.append(
                (piece, piece_overlap, ["split_long_legal_subsection"])
            )
    return results


def table_matrix(table: dict[str, Any]) -> list[list[str]]:
    rows = int(table.get("row_count", 0))
    columns = int(table.get("column_count", 0))
    occupied: dict[tuple[int, int], str] = {}
    for cell in table.get("cells", []):
        row = int(cell["row"])
        column = int(cell["column"])
        rowspan = max(1, int(cell.get("rowspan", 1)))
        colspan = max(1, int(cell.get("colspan", 1)))
        for row_offset in range(rowspan):
            for column_offset in range(colspan):
                occupied[(row + row_offset, column + column_offset)] = cell.get("text", "")
    return [
        [occupied.get((row, column), "") for column in range(columns)]
        for row in range(rows)
    ]


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def render_table_rows(matrix: list[list[str]], row_indices: list[int]) -> str:
    if not row_indices or not matrix:
        return ""
    rows = [[markdown_cell(value) for value in matrix[index]] for index in row_indices]
    output = ["| " + " | ".join(rows[0]) + " |"]
    output.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
    output.extend("| " + " | ".join(row) + " |" for row in rows[1:])
    return "\n".join(output)


def split_oversized_table_row(
    block: dict[str, Any],
    matrix: list[list[str]],
    header_rows: list[int],
    row_index: int,
    chunk_size: int,
    overlap: int,
) -> list[Unit]:
    row = matrix[row_index]
    headers = matrix[header_rows[-1]] if header_rows else [f"Column {index + 1}" for index in range(len(row))]
    row_label = row[0] if row else f"Row {row_index}"
    content_columns = [index for index, value in enumerate(row) if value and (index > 0 or len(row) == 1)]
    if not content_columns:
        content_columns = [0]
    units: list[Unit] = []
    fragment_number = 0
    for column_index in content_columns:
        value = row[column_index]
        header = headers[column_index] if column_index < len(headers) else f"Column {column_index + 1}"
        prefix = f"Table row: {row_label}\nColumn: {header}\nValue:"
        budget = max(20, chunk_size - count_tokens(prefix))
        piece_overlap = min(overlap, max(0, budget // 4))
        for piece, intrinsic_overlap in window_text(value, budget, piece_overlap):
            fragment_number += 1
            content = f"{prefix}\n{piece}".strip()
            flags = ["table_row_converted_to_key_value", "split_oversized_table_row"]
            if header_rows:
                flags.append("table_header_repeated")
            if count_tokens(content) > chunk_size:
                flags.append("oversized_atomic_table_cell")
            units.append(
                Unit(
                    segment_id=f"{block['block_id']}:table-row:{row_index}:fragment:{fragment_number}",
                    source_block_ids=[block["block_id"]],
                    block_types=["table"],
                    section_path=list(block.get("section_path", [])),
                    content=content,
                    overlap_tokens=intrinsic_overlap,
                    flags=flags,
                    table_fragment={
                        "source_block_id": block["block_id"],
                        "fragment_index": fragment_number,
                        "fragment_count": 0,
                        "original_row_indices": [row_index],
                        "repeated_header_row_indices": header_rows,
                        "column_count": len(row),
                        "column_index": column_index,
                        "column_header": header,
                        "row_label": row_label,
                    },
                )
            )
    for unit in units:
        if unit.table_fragment:
            unit.table_fragment["fragment_count"] = len(units)
    return units


def table_units(block: dict[str, Any], chunk_size: int, overlap: int = 0) -> list[Unit]:
    table = block["table"]
    matrix = table_matrix(table)
    if not matrix:
        return []
    header_rows = sorted(
        {
            int(cell["row"])
            for cell in table.get("cells", [])
            if cell.get("is_header")
        }
    )
    if not header_rows:
        header_rows = [0]
    body_rows = [index for index in range(len(matrix)) if index not in header_rows]
    if not body_rows:
        body_rows = header_rows
        header_rows = []

    fragments: list[list[int]] = []
    current: list[int] = []
    for row in body_rows:
        candidate = header_rows + current + [row]
        if current and count_tokens(render_table_rows(matrix, candidate)) > chunk_size:
            fragments.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        fragments.append(current)

    units: list[Unit] = []
    for index, body_fragment in enumerate(fragments, start=1):
        included_rows = header_rows + body_fragment
        content = render_table_rows(matrix, included_rows)
        if len(body_fragment) == 1 and count_tokens(content) > chunk_size:
            units.extend(
                split_oversized_table_row(
                    block,
                    matrix,
                    header_rows,
                    body_fragment[0],
                    chunk_size,
                    overlap,
                )
            )
            continue
        flags = ["table_header_repeated"] if header_rows and index > 1 else []
        if count_tokens(content) > chunk_size:
            flags.append("oversized_atomic_table_row")
        units.append(
            Unit(
                segment_id=f"{block['block_id']}:table:{index}",
                source_block_ids=[block["block_id"]],
                block_types=["table"],
                section_path=list(block.get("section_path", [])),
                content=content,
                flags=flags,
                table_fragment={
                    "source_block_id": block["block_id"],
                    "fragment_index": index,
                    "fragment_count": len(fragments),
                    "original_row_indices": body_fragment,
                    "repeated_header_row_indices": header_rows if index > 1 else [],
                    "column_count": table.get("column_count", 0),
                },
            )
        )
    return units


def heading_context_unit(
    path: list[str], heading_blocks: list[dict[str, Any]], sequence: int
) -> Optional[Unit]:
    relevant = [
        block
        for block in heading_blocks
        if tuple(block.get("section_path", []))
        and tuple(path[: len(block.get("section_path", []))])
        == tuple(block.get("section_path", []))
    ]
    if not relevant:
        return None
    content = "\n".join(
        f"{'#' * int(block.get('level', 2))} {block['text']}" for block in relevant
    )
    return Unit(
        segment_id=f"heading-context:{sequence}",
        source_block_ids=[block["block_id"] for block in relevant],
        block_types=["heading"],
        section_path=list(path),
        content=content,
        flags=["heading_context"],
    )


def document_units(document: dict[str, Any], chunk_size: int, overlap: int) -> list[Unit]:
    units: list[Unit] = []
    heading_blocks = [block for block in document["blocks"] if block["type"] == "heading"]
    emitted_heading_paths: set[tuple[str, ...]] = set()
    covered_heading_ids: set[str] = set()
    segment_sequence = 0
    for block in document["blocks"]:
        if block["type"] == "heading":
            continue
        path = list(block.get("section_path", []))
        path_key = tuple(path)
        if path_key not in emitted_heading_paths:
            context = heading_context_unit(path, heading_blocks, segment_sequence)
            if context:
                units.append(context)
                covered_heading_ids.update(context.source_block_ids)
                segment_sequence += 1
            emitted_heading_paths.add(path_key)

        if block["type"] == "table":
            units.extend(table_units(block, chunk_size, overlap))
            continue

        legal_fields = {
            key: block.get(key)
            for key in ("section_number", "section_title", "section_status")
            if block.get(key) not in (None, "")
        }
        if block["type"] == "legal_provision":
            pieces = split_legal_text(block["text"], chunk_size, overlap)
        elif count_tokens(block["text"]) > chunk_size:
            pieces = [
                (piece, piece_overlap, ["split_long_policy_block"])
                for piece, piece_overlap in window_text(block["text"], chunk_size, overlap)
            ]
        else:
            pieces = [(block["text"], 0, [])]
        for part_index, (content, intrinsic_overlap, flags) in enumerate(pieces, start=1):
            units.append(
                Unit(
                    segment_id=f"{block['block_id']}:part:{part_index}",
                    source_block_ids=[block["block_id"]],
                    block_types=[block["type"]],
                    section_path=path,
                    content=content,
                    overlap_tokens=intrinsic_overlap,
                    flags=flags,
                    legal_fields=legal_fields,
                )
            )

    # Preserve headings with no following content.
    for block in heading_blocks:
        path_key = tuple(block.get("section_path", []))
        if block["block_id"] in covered_heading_ids:
            continue
        units.append(
            Unit(
                segment_id=f"{block['block_id']}:heading-only",
                source_block_ids=[block["block_id"]],
                block_types=["heading"],
                section_path=list(path_key),
                content=f"{'#' * int(block.get('level', 2))} {block['text']}",
                flags=["heading_without_body"],
            )
        )
    return units


def unique_in_order(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def assemble_chunk(
    document: dict[str, Any], units: list[Unit], chunk_number: int, chunk_size: int, overlap: int
) -> dict[str, Any]:
    content = "\n\n".join(unit.content for unit in units if unit.content).strip()
    flags = unique_in_order(flag for unit in units for flag in unit.flags)
    token_count = count_tokens(content)
    if token_count > chunk_size and not any(flag.startswith("oversized_") for flag in flags):
        flags.append("oversized_grouped_context")
    legal_values: dict[str, Any] = {}
    for key in ("section_number", "section_title", "section_status"):
        values = unique_in_order(
            str(unit.legal_fields[key])
            for unit in units
            if key in unit.legal_fields
        )
        legal_values[key] = values[0] if len(values) == 1 else values or None
    table_fragments = [unit.table_fragment for unit in units if unit.table_fragment]
    return {
        "schema_version": "1.0",
        "chunk_id": f"{document['document_id']}_c{chunk_number:04d}",
        "chunk_index": chunk_number,
        "chunk_count": 0,
        "document_id": document["document_id"],
        "source": document["source"],
        "title": document["title"],
        "document_type": document["document_type"],
        "section_path": list(units[0].section_path) if units else [],
        "section_number": legal_values["section_number"],
        "section_title": legal_values["section_title"],
        "section_status": legal_values["section_status"],
        "source_url": document["source_url"],
        "retrieved_at": document["retrieved_at"],
        "effective_date": document.get("effective_date"),
        "source_capture_status": document.get("source_capture_status", "not_applicable"),
        "source_block_ids": unique_in_order(
            block_id for unit in units for block_id in unit.source_block_ids
        ),
        "source_segments": [unit.segment_id for unit in units],
        "block_types": unique_in_order(
            block_type for unit in units for block_type in unit.block_types
        ),
        "contains_table": bool(table_fragments),
        "table_fragments": table_fragments,
        "token_counter": "regex_words_v1",
        "token_count": token_count,
        "target_chunk_size": chunk_size,
        "configured_overlap": overlap,
        "actual_overlap_tokens": max((unit.overlap_tokens for unit in units), default=0),
        "oversized": token_count > chunk_size,
        "flags": flags,
        "content": content,
    }


def chunk_document(document: dict[str, Any], chunk_size: int, overlap: int) -> list[dict[str, Any]]:
    units = document_units(document, chunk_size, overlap)
    chunks: list[dict[str, Any]] = []
    current: list[Unit] = []

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(assemble_chunk(document, current, len(chunks) + 1, chunk_size, overlap))
            current = []

    for unit in units:
        unit_tokens = count_tokens(unit.content)
        if unit_tokens > chunk_size:
            flush()
            current = [unit]
            flush()
            continue
        if not current:
            current = [unit]
            continue
        same_section = tuple(current[0].section_path) == tuple(unit.section_path)
        candidate_content = "\n\n".join(item.content for item in current + [unit])
        if same_section and count_tokens(candidate_content) <= chunk_size:
            current.append(unit)
            continue

        previous = current
        flush()
        carry: list[Unit] = []
        if same_section and unit.overlap_tokens == 0:
            carried_tokens = 0
            for previous_unit in reversed(previous):
                size = count_tokens(previous_unit.content)
                if carried_tokens + size > overlap:
                    break
                carry.insert(0, previous_unit)
                carried_tokens += size
            while carry and count_tokens(
                "\n\n".join(item.content for item in carry + [unit])
            ) > chunk_size:
                carry.pop(0)
            if carry:
                unit.overlap_tokens = sum(count_tokens(item.content) for item in carry)
        current = carry + [unit]
    flush()
    for chunk in chunks:
        chunk["chunk_count"] = len(chunks)
    return chunks


def load_simple_chunking_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    result: dict[str, Any] = {}
    in_chunking = False
    chunking_indent = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()
        if stripped == "chunking:":
            in_chunking = True
            chunking_indent = indent
            continue
        if in_chunking and indent <= chunking_indent:
            in_chunking = False
        if not in_chunking or ":" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split(":", 1)]
        if value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value.strip("'\"")
    return result


def write_jsonl(items: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def report_for_document(document: dict[str, Any], chunks: list[dict[str, Any]]) -> ChunkingReportRow:
    counts = [chunk["token_count"] for chunk in chunks]
    return ChunkingReportRow(
        document_id=document["document_id"],
        source=document["source"],
        source_block_count=len(document["blocks"]),
        chunk_count=len(chunks),
        total_chunk_tokens=sum(counts),
        minimum_chunk_tokens=min(counts) if counts else 0,
        maximum_chunk_tokens=max(counts) if counts else 0,
        average_chunk_tokens=f"{mean(counts):.2f}" if counts else "0.00",
        oversized_chunk_count=sum(chunk["oversized"] for chunk in chunks),
        table_chunk_count=sum(chunk["contains_table"] for chunk in chunks),
        legal_chunk_count=sum("legal_provision" in chunk["block_types"] for chunk in chunks),
        source_capture_status=document.get("source_capture_status", "not_applicable"),
        warnings="; ".join(document.get("cleaning_warnings", [])),
    )


def write_report(rows: list[ChunkingReportRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(ChunkingReportRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def write_summary(
    documents: list[dict[str, Any]], chunks: list[dict[str, Any]], chunk_size: int, overlap: int, path: Path
) -> None:
    counts = [chunk["token_count"] for chunk in chunks]
    oversized = [chunk for chunk in chunks if chunk["oversized"]]
    text = f"""# Structure Aware Chunking Summary

## Configuration

- Input documents: {len(documents)}
- Target chunk size: {chunk_size} regex word tokens
- Configured overlap: {overlap} regex word tokens
- Token counter: regex_words_v1

## Result

- Generated chunks: {len(chunks)}
- Minimum chunk tokens: {min(counts) if counts else 0}
- Median chunk tokens: {median(counts) if counts else 0}
- Maximum chunk tokens: {max(counts) if counts else 0}
- Oversized chunks retained intentionally: {len(oversized)}
- Chunks containing table fragments: {sum(chunk['contains_table'] for chunk in chunks)}
- Legal provision chunks: {sum('legal_provision' in chunk['block_types'] for chunk in chunks)}

Tables are split by row with their header rows repeated. Legal provisions are split at numeric subsection boundaries where possible. A table row or legal subsection that cannot be safely divided may exceed the target and is explicitly flagged rather than truncated.
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
    parser.add_argument("--chunk-size", type=int)
    parser.add_argument("--chunk-overlap", type=int)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_simple_chunking_config(args.config)
    input_path = args.input or Path(config.get("input", "data/cleaned/deduplicated_documents.jsonl"))
    output_path = args.output or Path(config.get("output", "data/processed/chunks.jsonl"))
    report_path = args.report or Path(config.get("report", "reports/chunking_report.csv"))
    summary_path = args.summary or Path(config.get("summary", "reports/chunking_summary.md"))
    chunk_size = args.chunk_size or int(config.get("chunk_size", 500))
    overlap = args.chunk_overlap if args.chunk_overlap is not None else int(config.get("chunk_overlap", 75))
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and chunk_overlap must be between 0 and chunk_size")

    documents = [
        json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line
    ]
    all_chunks: list[dict[str, Any]] = []
    report_rows: list[ChunkingReportRow] = []
    for document in documents:
        document_chunks = chunk_document(document, chunk_size, overlap)
        all_chunks.extend(document_chunks)
        report_rows.append(report_for_document(document, document_chunks))
    write_jsonl(all_chunks, output_path)
    write_report(report_rows, report_path)
    write_summary(documents, all_chunks, chunk_size, overlap, summary_path)
    print(
        json.dumps(
            {
                "documents": len(documents),
                "chunks": len(all_chunks),
                "oversized_chunks": sum(chunk["oversized"] for chunk in all_chunks),
                "table_chunks": sum(chunk["contains_table"] for chunk in all_chunks),
                "legal_chunks": sum("legal_provision" in chunk["block_types"] for chunk in all_chunks),
                "output": str(output_path),
                "report": str(report_path),
                "summary": str(summary_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
