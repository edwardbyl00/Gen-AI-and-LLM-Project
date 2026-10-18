"""Audit local SingleFile HTML sources without modifying them.

Stage 1 intentionally stops at inventory and diagnostics.  It does not clean,
rewrite, deduplicate, or remove any source document.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup


SOURCE_DIRECTORIES = {
    "HDB": "hdb",
    "CPF": "cpf",
    "SSO": "sso",
    "IRAS": "iras",
}

EXPECTED_GROUPS = {
    "HDB": {f"H{i:02d}" for i in range(1, 10)},
    "CPF": {f"C{i:02d}" for i in range(1, 11)},
    "SSO": {f"S{i:02d}" for i in range(1, 7)},
    "IRAS": {"IR01", "IR02"},
}

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
}

INVENTORY_FIELDS = [
    "file_id",
    "filename",
    "source_organization",
    "actual_html_title",
    "original_source_url",
    "saved_date",
    "file_size_bytes",
    "extracted_main_text_length",
    "sha256_file_hash",
    "normalized_content_sha256",
    "parsing_status",
    "content_extraction_status",
    "suspected_duplicate_status",
    "embedded_resource_count",
    "legal_title_present",
    "substantive_legal_provisions_present",
    "section_numbers_detectable",
    "schedules_present",
    "empty_viewer_shell",
    "sso_toc_provision_count",
    "sso_captured_provision_count",
    "sso_toc_schedule_count",
    "sso_captured_schedule_count",
    "legal_content_coverage_status",
    "recommended_filename",
    "downstream_action",
    "duplicate_of",
    "review_status",
    "requires_manual_review",
    "notes",
]


@dataclass
class AuditRecord:
    file_id: str
    filename: str
    source_organization: str
    actual_html_title: str
    original_source_url: str
    saved_date: str
    file_size_bytes: int
    extracted_main_text_length: int
    sha256_file_hash: str
    normalized_content_sha256: str
    parsing_status: str
    content_extraction_status: str
    suspected_duplicate_status: str
    embedded_resource_count: int
    legal_title_present: str
    substantive_legal_provisions_present: str
    section_numbers_detectable: str
    schedules_present: str
    empty_viewer_shell: str
    sso_toc_provision_count: str
    sso_captured_provision_count: str
    sso_toc_schedule_count: str
    sso_captured_schedule_count: str
    legal_content_coverage_status: str
    recommended_filename: str
    downstream_action: str
    duplicate_of: str
    review_status: str
    requires_manual_review: str
    notes: str


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_for_hash(value: str) -> str:
    return normalize_whitespace(value).casefold()


def clean_source_url(url: str) -> str:
    """Remove common tracking keys while preserving page-identifying queries."""
    url = url.strip().strip('"\'<>')
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            return ""
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in TRACKING_PARAMETERS
        ]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except ValueError:
        return ""


def extract_original_url(soup: BeautifulSoup, raw_prefix: str) -> str:
    meta_candidates = (
        ("name", "savepage-url"),
        ("name", "singlefile-original-url"),
        ("name", "original-url"),
        ("property", "og:url"),
        ("rel", "canonical"),
    )
    for attribute, value in meta_candidates:
        if attribute == "rel":
            tag = soup.find("link", attrs={attribute: value})
            candidate = tag.get("href", "") if tag else ""
        else:
            tag = soup.find("meta", attrs={attribute: re.compile(f"^{re.escape(value)}$", re.I)})
            candidate = tag.get("content", "") if tag else ""
        cleaned = clean_source_url(candidate)
        if cleaned:
            return cleaned

    patterns = (
        r"saved\s+from\s+url=\([^)]*\)(https?://[^\s>\"']+)",
        r"(?:^|[;\n])\s*(?:url|original[_ -]?url)\s*:\s*(https?://[^\s<>\"']+)",
    )
    for pattern in patterns:
        match = re.search(pattern, raw_prefix, flags=re.I | re.M)
        if match:
            cleaned = clean_source_url(match.group(1))
            if cleaned:
                return cleaned
    return ""


def extract_saved_date(soup: BeautifulSoup, raw_prefix: str) -> str:
    for name in ("savepage-date", "singlefile-saved-date", "saved-date", "date"):
        tag = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if tag and tag.get("content"):
            return normalize_whitespace(tag["content"])
    match = re.search(
        r"(?:saved[_ -]?date|date[_ -]?saved)\s*:\s*([^\n\r<]{4,100})",
        raw_prefix,
        flags=re.I,
    )
    return normalize_whitespace(match.group(1)) if match else ""


def extract_title(soup: BeautifulSoup) -> str:
    if soup.title:
        title = normalize_whitespace(soup.title.get_text(" ", strip=True))
        if title:
            return title
    tag = soup.find("meta", attrs={"property": re.compile(r"^og:title$", re.I)})
    if tag and tag.get("content"):
        return normalize_whitespace(tag["content"])
    heading = soup.find("h1")
    return normalize_whitespace(heading.get_text(" ", strip=True)) if heading else ""


def extract_main_text(soup: BeautifulSoup) -> str:
    for tag in soup.find_all(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    container = (
        soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find("article")
        or soup.body
        or soup
    )
    return normalize_whitespace(container.get_text(" ", strip=True))


def filename_group(filename: str) -> str:
    match = re.match(r"^(IR|H|C|S)(\d{2})", filename, flags=re.I)
    return f"{match.group(1).upper()}{match.group(2)}" if match else ""


def preferred_file_id(filename: str) -> str:
    stem = filename
    while stem.casefold().endswith(".html"):
        stem = stem[:-5]
    match = re.match(
        r"^(IR\d{2}|[HCS]\d{2})(?:[_\s—-]+([A-Z])(?=[_\s—-]|$))?",
        stem,
        flags=re.I,
    )
    if not match:
        return re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").upper()
    base = match.group(1).upper()
    suffix = match.group(2)
    return f"{base}_{suffix.upper()}" if suffix else base


def title_filename_mismatch(filename: str, title: str) -> bool:
    stem = filename
    while stem.casefold().endswith(".html"):
        stem = stem[:-5]
    stem = re.sub(
        r"^(IR\d{2}|[HCS]\d{2})(?:[_\s—-]+[A-Z](?=[_\s—-]|$))?",
        "",
        stem,
        flags=re.I,
    )
    generic_tokens = {
        "buying",
        "cpf",
        "eligibility",
        "families",
        "flat",
        "hdb",
        "home",
        "housing",
        "scheme",
        "singles",
    }

    def key_tokens(value: str) -> set[str]:
        value = re.sub(r"\bt\s*&\s*c\b", "terms conditions", value, flags=re.I)
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]{4,}", value.casefold())
            if token not in generic_tokens
        }
        stems: set[str] = set()
        for token in tokens:
            if len(token) > 6 and token.endswith("ing"):
                token = token[:-3]
            elif len(token) > 6 and token.endswith("ions"):
                token = token[:-4]
            elif len(token) > 6 and token.endswith("ion"):
                token = token[:-3]
            elif len(token) > 5 and token.endswith("s"):
                token = token[:-1]
            stems.add(token[:7] if len(token) >= 7 else token)
        return stems

    filename_tokens = key_tokens(stem)
    title_tokens = key_tokens(title)
    if not filename_tokens or not title_tokens:
        return False
    return len(filename_tokens & title_tokens) / len(filename_tokens) < 0.25


def legal_diagnostics(title: str, text: str, expected_name: str) -> dict[str, str]:
    combined = f"{title} {text}"
    expected_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", expected_name.casefold())
        if len(token) >= 4 and token not in {"html"}
    }
    combined_folded = combined.casefold()
    title_present = bool(expected_tokens) and all(
        token in combined_folded for token in expected_tokens
    )
    section_detected = bool(
        re.search(r"\b(?:section|regulation|rule)\s+\d+[A-Za-z]?\b", text, re.I)
        or re.search(r"(?:^|\s)\d+[A-Za-z]?\.?\s*[-.—:]?\s*[A-Z][A-Za-z]", text)
    )
    substantive = len(text) >= 1500 and section_detected
    schedules = bool(re.search(r"\b(?:First|Second|Third|Fourth)?\s*Schedule\b", text, re.I))
    viewer_shell = len(text) < 1500 or not section_detected
    return {
        "legal_title_present": str(title_present).lower(),
        "substantive_legal_provisions_present": str(substantive).lower(),
        "section_numbers_detectable": str(section_detected).lower(),
        "schedules_present": str(schedules).lower(),
        "empty_viewer_shell": str(viewer_shell).lower(),
    }


def legal_capture_coverage(soup: BeautifulSoup) -> dict[str, str]:
    toc = soup.find(id="toc")
    content = soup.find(id="legisContent")
    if not toc or not content:
        return {
            "sso_toc_provision_count": "0",
            "sso_captured_provision_count": "0",
            "sso_toc_schedule_count": "0",
            "sso_captured_schedule_count": "0",
            "legal_content_coverage_status": "unverifiable",
            "schedules_present": "false",
        }

    content_ids = {tag.get("id") for tag in content.find_all(id=True)}
    provision_targets = {
        anchor.get("href", "")[1:]
        for anchor in toc.find_all("a", href=True)
        if re.match(r"^#pr", anchor.get("href", ""), flags=re.I)
    }
    schedule_targets = {
        anchor.get("href", "")[1:]
        for anchor in toc.find_all("a", href=True)
        if re.match(r"^#sc", anchor.get("href", ""), flags=re.I)
    }
    captured_provisions = sum(target in content_ids for target in provision_targets)
    captured_schedules = sum(target in content_ids for target in schedule_targets)
    provision_ratio = (
        captured_provisions / len(provision_targets) if provision_targets else 0.0
    )
    if not provision_targets:
        coverage = "unverifiable"
    elif provision_ratio < 0.95:
        coverage = "incomplete_provisions"
    elif captured_schedules < len(schedule_targets):
        coverage = "incomplete_schedules"
    else:
        coverage = "complete"
    return {
        "sso_toc_provision_count": str(len(provision_targets)),
        "sso_captured_provision_count": str(captured_provisions),
        "sso_toc_schedule_count": str(len(schedule_targets)),
        "sso_captured_schedule_count": str(captured_schedules),
        "legal_content_coverage_status": coverage,
        "schedules_present": str(captured_schedules > 0).lower(),
    }


def audit_file(path: Path, source: str) -> AuditRecord:
    notes: list[str] = []
    content = path.read_bytes()
    raw_hash = sha256_bytes(content)
    embedded_count = content.count(b"data:image/") + content.count(b"data:font/")
    decoded = content.decode("utf-8", errors="replace")
    raw_prefix = decoded[:500_000]

    try:
        soup = BeautifulSoup(decoded, "lxml")
        parsing_status = "success"
        title = extract_title(soup)
        source_url = extract_original_url(soup, raw_prefix)
        saved_date = extract_saved_date(soup, raw_prefix)
        text = extract_main_text(soup)
    except Exception as exc:  # continue the batch for malformed sources
        parsing_status = "failed"
        title = source_url = saved_date = text = ""
        notes.append(f"parsing failure: {type(exc).__name__}: {exc}")

    text_length = len(text)
    short_threshold = 1500 if source == "SSO" else 500
    if parsing_status == "failed":
        extraction_status = "failed"
    elif text_length == 0:
        extraction_status = "empty"
        notes.append("no main text extracted")
    elif text_length < short_threshold:
        extraction_status = "suspiciously_short"
        notes.append(f"main text shorter than {short_threshold} characters")
    else:
        extraction_status = "success"

    if not title:
        notes.append("missing HTML title")
    elif title_filename_mismatch(path.name, title):
        notes.append("possible filename/title mismatch")
    if not source_url:
        notes.append("missing original source URL")
    if embedded_count >= 100:
        notes.append(f"excessive embedded resources ({embedded_count})")
    if b"<html" not in content[:100_000].lower():
        notes.append("unexpected document type or missing html element")

    legal_fields = {
        "legal_title_present": "not_applicable",
        "substantive_legal_provisions_present": "not_applicable",
        "section_numbers_detectable": "not_applicable",
        "schedules_present": "not_applicable",
        "empty_viewer_shell": "not_applicable",
        "sso_toc_provision_count": "not_applicable",
        "sso_captured_provision_count": "not_applicable",
        "sso_toc_schedule_count": "not_applicable",
        "sso_captured_schedule_count": "not_applicable",
        "legal_content_coverage_status": "not_applicable",
    }
    if source == "SSO":
        legal_fields = legal_diagnostics(title, text, path.stem)
        legal_fields.update(legal_capture_coverage(soup))
        if legal_fields["legal_title_present"] == "false":
            notes.append("expected legal title not detected")
        if legal_fields["substantive_legal_provisions_present"] == "false":
            notes.append("substantive legal provisions not confirmed")
        if legal_fields["empty_viewer_shell"] == "true":
            notes.append("possible empty viewer shell")
        if legal_fields["legal_content_coverage_status"] != "complete":
            notes.append(
                "SSO capture coverage: "
                f"{legal_fields['legal_content_coverage_status']} "
                f"(provisions {legal_fields['sso_captured_provision_count']}/"
                f"{legal_fields['sso_toc_provision_count']}; schedules "
                f"{legal_fields['sso_captured_schedule_count']}/"
                f"{legal_fields['sso_toc_schedule_count']})"
            )

    review = bool(notes) or extraction_status != "success"
    normalized_hash = sha256_bytes(normalize_for_hash(text).encode("utf-8")) if text else ""
    return AuditRecord(
        file_id=preferred_file_id(path.name),
        filename=path.name,
        source_organization=source,
        actual_html_title=title,
        original_source_url=source_url,
        saved_date=saved_date,
        file_size_bytes=len(content),
        extracted_main_text_length=text_length,
        sha256_file_hash=raw_hash,
        normalized_content_sha256=normalized_hash,
        parsing_status=parsing_status,
        content_extraction_status=extraction_status,
        suspected_duplicate_status="none",
        embedded_resource_count=embedded_count,
        recommended_filename=path.name,
        downstream_action="keep",
        duplicate_of="",
        review_status="pending" if review else "not_required",
        requires_manual_review=str(review).lower(),
        notes="; ".join(notes),
        **legal_fields,
    )


def discover_files(raw_root: Path) -> list[tuple[Path, str]]:
    discovered: list[tuple[Path, str]] = []
    for source, directory in SOURCE_DIRECTORIES.items():
        source_dir = raw_root / directory
        if not source_dir.exists():
            continue
        for path in sorted(source_dir.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.casefold() in {".html", ".htm"}:
                discovered.append((path, source))
    return discovered


def mark_duplicates(records: list[AuditRecord]) -> None:
    raw_groups: dict[str, list[AuditRecord]] = defaultdict(list)
    content_groups: dict[str, list[AuditRecord]] = defaultdict(list)
    for record in records:
        raw_groups[record.sha256_file_hash].append(record)
        if record.normalized_content_sha256:
            content_groups[record.normalized_content_sha256].append(record)

    def resolve_group(group: list[AuditRecord], duplicate_type: str) -> None:
        canonical = sorted(group, key=lambda item: (item.file_id, item.filename))[0]
        for record in group:
            record.suspected_duplicate_status = duplicate_type
            record.review_status = "resolved"
            record.requires_manual_review = "false"
            if record is canonical:
                decision = "canonical copy retained for downstream processing"
            else:
                record.downstream_action = "exclude_exact_duplicate"
                record.duplicate_of = canonical.file_id
                decision = f"exclude downstream; duplicate of {canonical.file_id}"
            record.notes = "; ".join(filter(None, [record.notes, decision]))

    for group in raw_groups.values():
        if len(group) > 1:
            resolve_group(group, "exact_raw_file")
    for group in content_groups.values():
        if len(group) > 1 and all(
            record.suspected_duplicate_status == "none" for record in group
        ):
            resolve_group(group, "exact_normalized_content")


def apply_manual_review_decisions(records: list[AuditRecord]) -> None:
    decisions = {
        "H03": {
            "recommended_filename": "H03_Application for an HDB Flat Eligibility (HFE) Letter.html",
            "decision": "reviewed: use the verified HFE Letter title downstream; preserve the raw filename",
        },
        "H06": {
            "decision": "reviewed: MOP is substantive core content; retain the descriptive filename",
        },
        "C02": {
            "decision": "reviewed: content covers factors controlling CPF housing usage; retain the filename",
        },
        "IR01": {
            "decision": "reviewed: embedded SingleFile assets are deferred to HTML cleaning",
        },
        "IR02": {
            "decision": "reviewed: embedded SingleFile assets are deferred to HTML cleaning",
        },
    }
    for record in records:
        decision = decisions.get(record.file_id)
        if not decision:
            continue
        record.recommended_filename = decision.get(
            "recommended_filename", record.recommended_filename
        )
        record.review_status = "resolved"
        record.requires_manual_review = "false"
        record.notes = "; ".join(filter(None, [record.notes, decision["decision"]]))


def ensure_unique_ids(records: list[AuditRecord]) -> None:
    groups: dict[str, list[AuditRecord]] = defaultdict(list)
    for record in records:
        groups[record.file_id].append(record)
    for group in groups.values():
        if len(group) > 1:
            for record in group:
                name_hash = sha256_bytes(record.filename.encode("utf-8"))[:8].upper()
                record.file_id = f"{record.file_id}_{name_hash}"
                record.notes = "; ".join(
                    filter(None, [record.notes, "ID disambiguated with raw hash"])
                )


def audit_files(files: Iterable[tuple[Path, str]]) -> list[AuditRecord]:
    records = [audit_file(path, source) for path, source in files]
    ensure_unique_ids(records)
    mark_duplicates(records)
    apply_manual_review_decisions(records)
    return records


def write_inventory(records: list[AuditRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def build_summary(records: list[AuditRecord]) -> dict[str, object]:
    source_counts = Counter(record.source_organization for record in records)
    parsed = sum(record.parsing_status == "success" for record in records)
    manual_review = sum(record.requires_manual_review == "true" for record in records)
    duplicates = sum(record.suspected_duplicate_status != "none" for record in records)
    excluded = sum(record.downstream_action != "keep" for record in records)
    found_groups: dict[str, set[str]] = defaultdict(set)
    for record in records:
        group = filename_group(record.filename)
        if group:
            found_groups[record.source_organization].add(group)
    missing = {
        source: sorted(EXPECTED_GROUPS[source] - found_groups[source])
        for source in EXPECTED_GROUPS
    }
    return {
        "total_files": len(records),
        "files_per_source": dict(sorted(source_counts.items())),
        "successfully_parsed_files": parsed,
        "files_requiring_manual_review": manual_review,
        "potential_duplicate_files": duplicates,
        "files_excluded_from_downstream": excluded,
        "review_status_counts": dict(
            sorted(Counter(record.review_status for record in records).items())
        ),
        "missing_expected_document_groups": missing,
    }


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument(
        "--output", type=Path, default=Path("reports/file_inventory.csv")
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    files = discover_files(args.raw_root)
    if not files:
        raise SystemExit(f"No HTML files found under {args.raw_root}")
    records = audit_files(files)
    write_inventory(records, args.output)
    summary = build_summary(records)
    summary["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    summary["inventory_path"] = str(args.output)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
