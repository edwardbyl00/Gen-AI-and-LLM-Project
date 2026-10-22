"""Source-aware HTML cleaning for HDB, CPF, IRAS, and SSO documents.

The cleaner is deterministic and extractive: it never rewrites policy text,
invents values, or mutates raw inputs. Exact duplicates previously resolved in
the file inventory are excluded from downstream output but remain on disk.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag


SOURCE_DIRECTORIES = {
    "HDB": "hdb",
    "CPF": "cpf",
    "SSO": "sso",
    "IRAS": "iras",
}

COMMON_NOISE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "form",
    "input",
    "select",
    "textarea",
    "nav",
    "aside",
    '[role="navigation"]',
    '[aria-hidden="true"]',
    '[class*="breadcrumb" i]',
    '[class*="cookie" i]',
    '[id*="cookie" i]',
    '[class*="social" i]',
    '[class*="sidebar" i]',
    '[class*="backtotop" i]',
    '[class*="chat" i]',
]

SOURCE_NOISE_SELECTORS = {
    "HDB": [
        "main > header",
        "main > footer",
        '[class*="PFooter"]',
        '[class*="PNav"]',
        '[class*="PSidebar"]',
        "#sgds-masthead",
    ],
    "CPF": [
        '[class*="global-header"]',
        '[class*="global-footer"]',
        '[class*="header_overlay"]',
        "#sgds-masthead",
    ],
    "IRAS": [
        '[class*="inner-nav"]',
        '[class*="page-anchors"]',
        '[class*="footer" i]',
        "#sgds-masthead",
    ],
}

BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "ul",
    "ol",
    "li",
    "table",
    "blockquote",
    "pre",
    "dl",
    "dt",
    "dd",
}


@dataclass
class CleaningReportRow:
    document_id: str
    source: str
    source_filename: str
    status: str
    source_capture_status: str
    block_count: int
    table_count: int
    raw_selected_text_length: int
    cleaned_text_length: int
    retention_ratio: str
    warning_count: int
    warnings: str


def normalize_text(value: str) -> str:
    value = value.replace("\xa0", " ")
    value = re.sub(r"[ \t\f\v]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def safe_link(href: str, base_url: str) -> str:
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
        return ""
    resolved = urljoin(base_url, href) if base_url else href
    parts = urlsplit(resolved)
    return resolved if parts.scheme in {"http", "https"} and parts.netloc else ""


def inline_markdown(node: Tag, base_url: str) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, NavigableString):
            parts.append(str(item))
            return
        if not isinstance(item, Tag):
            return
        if item.name in {"script", "style", "svg", "template", "ul", "ol", "table"}:
            return
        if item.name == "br":
            parts.append("\n")
            return
        if item.name == "a":
            label = normalize_text(item.get_text(" ", strip=True))
            href = safe_link(item.get("href", ""), base_url)
            parts.append(f"[{label}]({href})" if label and href else label)
            return
        if item.name in {"strong", "b"}:
            label = normalize_text(item.get_text(" ", strip=True))
            parts.append(f"**{label}**" if label else "")
            return
        if item.name in {"em", "i"}:
            label = normalize_text(item.get_text(" ", strip=True))
            parts.append(f"*{label}*" if label else "")
            return
        if item.name == "sup":
            label = normalize_text(item.get_text(" ", strip=True))
            parts.append(f"[{label}]" if label else "")
            return
        for child in item.children:
            visit(child)

    for child in node.children:
        visit(child)
    return normalize_text("".join(parts))


def select_main_container(soup: BeautifulSoup, source: str) -> Optional[Tag]:
    if source == "SSO":
        return soup.find(id="legisContent")
    if source == "IRAS":
        return soup.find("main", id="mainContent") or soup.find("main")
    return soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")


def clone_and_remove_noise(container: Tag, source: str) -> Tag:
    cloned_soup = BeautifulSoup(str(container), "lxml")
    cloned = cloned_soup.find(container.name) or cloned_soup.body or cloned_soup
    selectors = COMMON_NOISE_SELECTORS + SOURCE_NOISE_SELECTORS.get(source, [])
    for selector in selectors:
        try:
            for node in cloned.select(selector):
                node.decompose()
        except Exception:
            continue
    for text_node in list(cloned.find_all(string=True)):
        if normalize_text(str(text_node)).casefold() in {
            "was this article helpful?",
            "share this page",
        }:
            parent = text_node.find_parent(["p", "div"])
            if parent:
                parent.decompose()
    return cloned


def cell_text(cell: Tag, base_url: str) -> str:
    clone_soup = BeautifulSoup(str(cell), "lxml")
    clone = clone_soup.find(cell.name)
    if not clone:
        return ""
    for unwanted in clone.find_all(["script", "style", "svg", "template"]):
        unwanted.decompose()
    for link in clone.find_all("a"):
        label = normalize_text(link.get_text(" ", strip=True))
        href = safe_link(link.get("href", ""), base_url)
        link.replace_with(f"[{label}]({href})" if label and href else label)
    for br in clone.find_all("br"):
        br.replace_with("\n")
    return normalize_text(clone.get_text("\n", strip=True))


def table_structure(table: Tag, base_url: str) -> dict[str, Any]:
    rows = [
        row
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]
    occupied: dict[tuple[int, int], str] = {}
    cells: list[dict[str, Any]] = []
    max_column = 0
    for row_index, row in enumerate(rows):
        column = 0
        direct_cells = [
            cell
            for cell in row.find_all(["th", "td"], recursive=False)
        ]
        for cell in direct_cells:
            while (row_index, column) in occupied:
                column += 1
            try:
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except ValueError:
                rowspan = 1
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
            except ValueError:
                colspan = 1
            text = cell_text(cell, base_url)
            entry = {
                "row": row_index,
                "column": column,
                "rowspan": rowspan,
                "colspan": colspan,
                "is_header": cell.name == "th",
                "text": text,
            }
            cells.append(entry)
            for row_offset in range(rowspan):
                for column_offset in range(colspan):
                    occupied[(row_index + row_offset, column + column_offset)] = text
            column += colspan
            max_column = max(max_column, column)

    matrix = [
        [occupied.get((row, column), "") for column in range(max_column)]
        for row in range(len(rows))
    ]
    def markdown_cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", "<br>")

    markdown_matrix = [[markdown_cell(value) for value in row] for row in matrix]
    markdown_lines: list[str] = []
    if matrix and max_column:
        markdown_lines.append("| " + " | ".join(markdown_matrix[0]) + " |")
        markdown_lines.append("| " + " | ".join(["---"] * max_column) + " |")
        markdown_lines.extend(
            "| " + " | ".join(row) + " |" for row in markdown_matrix[1:]
        )
    return {
        "row_count": len(rows),
        "column_count": max_column,
        "cells": cells,
        "markdown": "\n".join(markdown_lines),
    }


def has_block_ancestor(tag: Tag, container: Tag) -> bool:
    parent = tag.parent
    while isinstance(parent, Tag) and parent is not container:
        if parent.name in BLOCK_TAGS:
            if tag.name == "li" and parent.name in {"ul", "ol", "li"}:
                parent = parent.parent
                continue
            # Tables sometimes appear inside explanatory list items. The list
            # item's inline representation deliberately omits nested tables,
            # so allow the table to become its own structured block instead of
            # silently losing its cells.
            if tag.name == "table" and parent.name in {"ul", "ol", "li"}:
                parent = parent.parent
                continue
            return True
        parent = parent.parent
    return False


def list_item_text(item: Tag, base_url: str) -> str:
    clone_soup = BeautifulSoup(str(item), "lxml")
    clone = clone_soup.find("li")
    if not clone:
        return ""
    for nested in clone.find_all(["ul", "ol"]):
        nested.decompose()
    return inline_markdown(clone, base_url) or normalize_text(clone.get_text(" ", strip=True))


def extract_policy_blocks(container: Tag, base_url: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []
    last_signature = ""
    candidates = container.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table", "blockquote", "pre", "dt", "dd", "div"]
    )
    for tag in candidates:
        if has_block_ancestor(tag, container):
            continue
        block: dict[str, Any]
        if re.fullmatch(r"h[1-6]", tag.name or "") or tag.get("role") == "heading":
            text = inline_markdown(tag, base_url) or normalize_text(tag.get_text(" ", strip=True))
            if not text:
                continue
            level = (
                int(tag.name[1])
                if re.fullmatch(r"h[1-6]", tag.name or "")
                else max(1, min(6, int(tag.get("aria-level", 2))))
            )
            heading_stack = [(old_level, value) for old_level, value in heading_stack if old_level < level]
            heading_stack.append((level, text))
            block = {
                "type": "heading",
                "level": level,
                "section_path": [value for _, value in heading_stack],
                "text": text,
            }
        elif tag.name == "table":
            table = table_structure(tag, base_url)
            if not table["markdown"]:
                continue
            block = {
                "type": "table",
                "section_path": [value for _, value in heading_stack],
                "text": table["markdown"],
                "table": table,
            }
        elif tag.name == "li":
            text = list_item_text(tag, base_url)
            if not text:
                continue
            parent_list = tag.find_parent(["ul", "ol"])
            block = {
                "type": "list_item",
                "list_type": "ordered" if parent_list and parent_list.name == "ol" else "unordered",
                "section_path": [value for _, value in heading_stack],
                "text": text,
            }
        elif tag.name in {"dt", "dd"}:
            text = inline_markdown(tag, base_url) or normalize_text(tag.get_text(" ", strip=True))
            if not text:
                continue
            block = {
                "type": "definition_term" if tag.name == "dt" else "definition_description",
                "section_path": [value for _, value in heading_stack],
                "text": text,
            }
        else:
            if tag.name == "div" and tag.find(BLOCK_TAGS):
                continue
            text = inline_markdown(tag, base_url) or normalize_text(tag.get_text(" ", strip=True))
            if not text:
                continue
            block = {
                "type": "quote" if tag.name == "blockquote" else "paragraph",
                "section_path": [value for _, value in heading_stack],
                "text": text,
            }

        signature = f"{block['type']}\x00{block['text']}"
        if signature == last_signature:
            continue
        block["block_id"] = f"b{len(blocks) + 1:04d}"
        blocks.append(block)
        last_signature = signature
    return blocks


def first_text(node: Optional[Tag]) -> str:
    return normalize_text(node.get_text(" ", strip=True)) if node else ""


def provision_number(provision: Tag) -> str:
    identified = (
        provision
        if re.match(r"^pr", provision.get("id", ""), flags=re.I)
        else provision.find(id=re.compile(r"^pr", re.I))
    )
    if not identified:
        return ""
    match = re.match(r"^pr(\d+[A-Za-z]?)", identified.get("id", ""), flags=re.I)
    return match.group(1) if match else ""


def extract_legal_blocks(container: Tag) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    current_part = ""
    pending_part_number = ""
    handled: set[int] = set()
    for tag in container.find_all(True):
        classes = set(tag.get("class", []))
        if "partNo" in classes:
            pending_part_number = first_text(tag)
            continue
        if "partHdr" in classes:
            part_title = first_text(tag)
            current_part = normalize_text(f"{pending_part_number} {part_title}")
            if current_part:
                blocks.append(
                    {
                        "block_id": f"b{len(blocks) + 1:04d}",
                        "type": "legal_part",
                        "section_path": [current_part],
                        "text": current_part,
                    }
                )
            continue
        if classes.intersection({"prov1", "prov1Rep"}) and id(tag) not in handled:
            handled.add(id(tag))
            text = first_text(tag)
            if not text:
                continue
            number = provision_number(tag)
            heading = first_text(tag.find(class_="prov1Hdr"))
            label = normalize_text(f"Section {number} {heading}") if number else heading
            path = [value for value in (current_part, label) if value]
            block = {
                "block_id": f"b{len(blocks) + 1:04d}",
                "type": "legal_provision",
                "section_number": number,
                "section_title": heading,
                "section_path": path,
                "text": text,
            }
            if "prov1Rep" in classes:
                block["section_status"] = "repealed_or_deleted"
            blocks.append(block)

    front = container.find(class_="front")
    if front:
        front_text = first_text(front)
        first_provision_text = next(
            (block["text"] for block in blocks if block["type"] == "legal_provision"),
            "",
        )
        if first_provision_text and first_provision_text in front_text:
            front_text = normalize_text(front_text.split(first_provision_text, 1)[0])
        if front_text:
            blocks.insert(
                0,
                {
                    "block_id": "b0001",
                    "type": "legal_front_matter",
                    "section_path": [],
                    "text": front_text,
                },
            )
            for index, block in enumerate(blocks, start=1):
                block["block_id"] = f"b{index:04d}"
    return blocks


def extract_legal_metadata(soup: BeautifulSoup) -> dict[str, Optional[str]]:
    status_row = soup.find(class_="status-row")
    return {
        "status": first_text(status_row) or None,
        "revised_edition": first_text(soup.find(class_="revdHdr")) or None,
        "revision_note": first_text(soup.find(class_="revdTxt")) or None,
        "commencement_text": first_text(soup.find(class_="cDate")) or None,
        "long_title": first_text(soup.find(class_="longTitle")) or None,
    }


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    rendered: list[str] = []
    for block in blocks:
        block_type = block["type"]
        text = block["text"]
        if block_type == "heading":
            rendered.append(f"{'#' * block['level']} {text}")
        elif block_type == "legal_part":
            rendered.append(f"## {text}")
        elif block_type == "legal_provision":
            rendered.append(f"### {block.get('section_title') or block.get('section_number')}\n\n{text}")
        elif block_type == "list_item":
            marker = "1." if block.get("list_type") == "ordered" else "-"
            rendered.append(f"{marker} {text}")
        elif block_type == "quote":
            rendered.append("\n".join(f"> {line}" for line in text.splitlines()))
        else:
            rendered.append(text)
    return "\n\n".join(part for part in rendered if part).strip()


def clean_document(path: Path, inventory: dict[str, str]) -> tuple[dict[str, Any], CleaningReportRow]:
    source = inventory["source_organization"]
    warnings: list[str] = []
    soup = BeautifulSoup(path.read_bytes(), "lxml")
    container = select_main_container(soup, source)
    if not container:
        raise ValueError("main content container not found")
    raw_selected_length = len(normalize_text(container.get_text(" ", strip=True)))
    cleaned_container = clone_and_remove_noise(container, source)
    if source == "SSO":
        blocks = extract_legal_blocks(cleaned_container)
    else:
        blocks = extract_policy_blocks(cleaned_container, inventory["original_source_url"])
    content = blocks_to_markdown(blocks)
    table_count = sum(block["type"] == "table" for block in blocks)
    if not blocks:
        warnings.append("no content blocks extracted")
    if len(content) < 500:
        warnings.append("cleaned content is suspiciously short")
    capture_status = inventory.get("legal_content_coverage_status", "not_applicable")
    if source == "SSO" and capture_status != "complete":
        warnings.append(f"raw SSO capture is {capture_status}; cleaning cannot recover missing text")
    ratio = len(content) / raw_selected_length if raw_selected_length else 0.0
    if source != "SSO" and ratio < 0.20:
        warnings.append("low text-retention ratio; manual comparison recommended")
    status = "success_with_warnings" if warnings else "success"
    document = {
        "schema_version": "1.0",
        "document_id": inventory["file_id"],
        "source": source,
        "source_filename": inventory["filename"],
        "recommended_filename": inventory.get("recommended_filename") or inventory["filename"],
        "title": inventory["actual_html_title"],
        "source_url": inventory["original_source_url"],
        "retrieved_at": inventory["saved_date"],
        "effective_date": None,
        "document_type": "legislation" if source == "SSO" else "policy",
        "legal_metadata": extract_legal_metadata(soup) if source == "SSO" else None,
        "raw_sha256": inventory["sha256_file_hash"],
        "source_capture_status": capture_status,
        "cleaning_status": status,
        "blocks": blocks,
        "content": content,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "cleaning_warnings": warnings,
    }
    report = CleaningReportRow(
        document_id=inventory["file_id"],
        source=source,
        source_filename=inventory["filename"],
        status=status,
        source_capture_status=capture_status,
        block_count=len(blocks),
        table_count=table_count,
        raw_selected_text_length=raw_selected_length,
        cleaned_text_length=len(content),
        retention_ratio=f"{ratio:.4f}",
        warning_count=len(warnings),
        warnings="; ".join(warnings),
    )
    return document, report


def load_inventory(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def raw_path(raw_root: Path, row: dict[str, str]) -> Path:
    return raw_root / SOURCE_DIRECTORIES[row["source_organization"]] / row["filename"]


def write_jsonl(documents: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for document in documents:
            handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")


def write_report(rows: Iterable[CleaningReportRow], path: Path) -> None:
    fields = [field.name for field in CleaningReportRow.__dataclass_fields__.values()]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=Path("reports/file_inventory.csv"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/cleaned/cleaned_documents.jsonl")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("reports/cleaning_report.csv")
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    inventory = load_inventory(args.inventory)
    documents: list[dict[str, Any]] = []
    report_rows: list[CleaningReportRow] = []
    failures: list[str] = []
    for row in inventory:
        if row.get("downstream_action") == "exclude_exact_duplicate":
            report_rows.append(
                CleaningReportRow(
                    document_id=row["file_id"],
                    source=row["source_organization"],
                    source_filename=row["filename"],
                    status="excluded_exact_duplicate",
                    source_capture_status=row.get("legal_content_coverage_status", "not_applicable"),
                    block_count=0,
                    table_count=0,
                    raw_selected_text_length=0,
                    cleaned_text_length=0,
                    retention_ratio="0.0000",
                    warning_count=0,
                    warnings=f"duplicate of {row.get('duplicate_of', '')}",
                )
            )
            continue
        path = raw_path(args.raw_root, row)
        try:
            document, report = clean_document(path, row)
            documents.append(document)
            report_rows.append(report)
        except Exception as exc:
            failures.append(row["file_id"])
            report_rows.append(
                CleaningReportRow(
                    document_id=row["file_id"],
                    source=row["source_organization"],
                    source_filename=row["filename"],
                    status="failed",
                    source_capture_status=row.get("legal_content_coverage_status", "not_applicable"),
                    block_count=0,
                    table_count=0,
                    raw_selected_text_length=0,
                    cleaned_text_length=0,
                    retention_ratio="0.0000",
                    warning_count=1,
                    warnings=f"{type(exc).__name__}: {exc}",
                )
            )
    write_jsonl(documents, args.output)
    write_report(report_rows, args.report)
    summary = {
        "inventory_documents": len(inventory),
        "cleaned_documents": len(documents),
        "excluded_exact_duplicates": sum(
            row.status == "excluded_exact_duplicate" for row in report_rows
        ),
        "failed_documents": failures,
        "documents_with_warnings": sum(
            row.status == "success_with_warnings" for row in report_rows
        ),
        "total_blocks": sum(row.block_count for row in report_rows),
        "total_tables": sum(row.table_count for row in report_rows),
        "output_path": str(args.output),
        "report_path": str(args.report),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
