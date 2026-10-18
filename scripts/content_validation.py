"""Validate that cleaning preserved evidence for the supplied general questions.

This is a data-preservation check, not a RAG or model evaluation. The two HDB
reference documents contain overlapping question sets, so the newer consolidated
coverage document is used for the 30 HDB questions. The CPF document contributes
another 30 questions whose source mappings are explicitly treated as candidates.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from scripts.html_cleaning import clone_and_remove_noise, normalize_text, select_main_container
except ModuleNotFoundError:  # Support direct execution as scripts/content_validation.py.
    from html_cleaning import clone_and_remove_noise, normalize_text, select_main_container


WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
SOURCE_DIRECTORIES = {"HDB": "hdb", "CPF": "cpf", "SSO": "sso", "IRAS": "iras"}
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
    "for", "from", "how", "i", "if", "in", "is", "it", "my", "of", "on",
    "or", "the", "this", "to", "using", "what", "when", "which", "who",
    "with", "your",
}
QUESTION_EXPANSIONS = {
    "joint": "co-owner co-owners jointly",
    "spouse": "co-owner co-owners household",
    "turning 55": "aged 55 retirement account full retirement sum",
    "after age 55": "aged 55 retirement account full retirement sum",
    "shortfall": "market value top up cash",
    "home protection scheme": "HPS required cover",
    "remaining lease": "youngest buyer age 95",
    "bank loan": "financial institution loan",
    "stamp duty": "BSD ABSD purchase price market value",
    "cash proceeds": "selling price outstanding loan CPF refunds accrued interest",
}


@dataclass
class Question:
    reference_set: str
    question_id: str
    question: str
    reference_coverage: str
    candidate_document_ids: list[str]
    reference_evidence: str = ""
    reference_note: str = ""


@dataclass
class ValidationRow:
    validation_id: str
    reference_set: str
    question_id: str
    question: str
    reference_coverage: str
    candidate_document_ids: str
    cleaned_documents_found: str
    selected_document_id: str
    selected_block_id: str
    evidence_excerpt: str
    raw_evidence_token_coverage: str
    cleaning_preservation_result: str
    answerability_note: str


def element_text(element: ET.Element) -> str:
    # Word may split a cell across runs and line breaks without literal spaces
    # in itertext(), e.g. "C05" + "Interpretation". Separating w:t nodes keeps
    # source identifiers parseable while normalize_text removes excess spacing.
    return normalize_text(
        " ".join(node.text or "" for node in element.findall(".//w:t", WORD_NS))
    )


def docx_xml(path: Path) -> ET.Element:
    with zipfile.ZipFile(path) as archive:
        return ET.fromstring(archive.read("word/document.xml"))


def docx_paragraphs(path: Path) -> list[str]:
    root = docx_xml(path)
    body = root.find("w:body", WORD_NS)
    if body is None:
        return []
    return [element_text(node) for node in body.findall("w:p", WORD_NS)]


def docx_table_rows(path: Path) -> list[list[str]]:
    root = docx_xml(path)
    rows: list[list[str]] = []
    for table in root.findall(".//w:tbl", WORD_NS):
        for row in table.findall("w:tr", WORD_NS):
            rows.append([element_text(cell) for cell in row.findall("w:tc", WORD_NS)])
    return rows


def source_ids(value: str) -> list[str]:
    if not value or value.casefold().startswith("no sufficient"):
        return []
    identifiers: list[str] = []
    aliases = {
        "couples and families": "H01",
        "singles": "H02",
    }
    for part in value.split(";"):
        folded = part.casefold()
        for label, identifier in aliases.items():
            if label in folded:
                if identifier not in identifiers:
                    identifiers.append(identifier)
        matches = re.finditer(
            r"\b([HC]\d{2})(?:[_-]([A-Z]))?(?=_|[^A-Za-z0-9]|$)",
            part,
            flags=re.I,
        )
        for match in matches:
            identifier = match.group(1).upper()
            if match.group(2):
                identifier += f"_{match.group(2).upper()}"
            if identifier == "H09_C":
                identifier = "H05_B"
            if identifier not in identifiers:
                identifiers.append(identifier)
    return identifiers


def field_value(segment: list[str], prefix: str) -> str:
    return next(
        (line.split(":", 1)[1].strip() for line in segment if line.startswith(prefix)),
        "",
    )


def load_hdb_questions(path: Path) -> list[Question]:
    paragraphs = [value for value in docx_paragraphs(path) if value]
    starts = [index for index, value in enumerate(paragraphs) if re.match(r"^Q\d{2}\s", value)]
    questions: list[Question] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(paragraphs)
        segment = paragraphs[start:end]
        match = re.match(r"^(Q\d{2})\s+(.+)$", segment[0])
        if not match:
            continue
        identifier, text = match.groups()
        coverage = field_value(segment, "Local coverage:") or "UNSPECIFIED"
        candidates = source_ids(field_value(segment, "Existing supporting file(s):"))
        evidence_line = next(
            (line for line in segment if line.startswith("Evidence excerpt")), ""
        )
        evidence = evidence_line.split(":", 1)[1].strip() if ":" in evidence_line else ""
        note = " ".join(
            line for line in segment if line.startswith(("Gap:", "User information needed:"))
        )
        if identifier == "Q25":
            candidates = ["IR01", "IR02"]
            coverage = "Full (current corpus includes IRAS BSD and ABSD pages)"
            note = "The older reference predates the IRAS pages now present in the local corpus."
        elif identifier == "Q29":
            candidates = []
            coverage = "Not covered"
        questions.append(
            Question("HDB_30Q", identifier, text, coverage, candidates, evidence, note)
        )
    return questions


def load_cpf_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    for cells in docx_table_rows(path):
        if len(cells) < 3 or not re.fullmatch(r"Q\d{2}", cells[0]):
            continue
        identifier, text, candidate_text = cells[:3]
        candidates = source_ids(candidate_text)
        # The reference labels its mappings as candidates rather than verified proof.
        # These two additions are directly supported by the current supplied corpus.
        if identifier == "Q04" and "C03" not in candidates:
            candidates.append("C03")
        if identifier == "Q23" and "C02_A" not in candidates:
            candidates.append("C02_A")
        questions.append(
            Question(
                "CPF_30Q",
                identifier,
                text,
                "Reference mapping only",
                candidates,
                reference_note=candidate_text,
            )
        )
    return questions


def query_tokens(question: Question) -> Counter[str]:
    query = f"{question.question} {question.reference_evidence}"
    folded = question.question.casefold()
    for phrase, expansion in QUESTION_EXPANSIONS.items():
        if phrase in folded:
            query += f" {expansion}"
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", query.casefold())
        if len(token) > 1 and token not in STOP_WORDS
    ]
    return Counter(tokens)


def block_score(block: dict[str, Any], query: Counter[str]) -> float:
    text_tokens = Counter(re.findall(r"[a-z0-9]+", block["text"].casefold()))
    return sum(
        (2.0 if len(token) >= 5 else 1.0) * min(count, text_tokens[token])
        for token, count in query.items()
    )


def best_evidence(
    question: Question, documents: dict[str, dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], str, str, float]:
    query = query_tokens(question)
    choices: list[tuple[float, str, dict[str, Any]]] = []
    for document_id in question.candidate_document_ids:
        document = documents.get(document_id)
        if not document:
            continue
        for block in document["blocks"]:
            score = block_score(block, query)
            if score:
                choices.append((score, document_id, block))
    if not choices:
        return None, "", "", 0.0
    score, document_id, block = max(choices, key=lambda item: item[0])
    return block, document_id, block["block_id"], score


def token_set(value: str) -> set[str]:
    value = re.sub(r"\]\([^)]*\)", "]", value)
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def raw_selected_text(
    document: dict[str, Any], inventory: dict[str, dict[str, str]], raw_root: Path
) -> str:
    row = inventory[document["document_id"]]
    path = raw_root / SOURCE_DIRECTORIES[row["source_organization"]] / row["filename"]
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_bytes(), "lxml")
    container = select_main_container(soup, row["source_organization"])
    if container is None:
        return ""
    cleaned = clone_and_remove_noise(container, row["source_organization"])
    return normalize_text(cleaned.get_text(" ", strip=True))


def answerability_note(question: Question) -> str:
    folded = question.reference_coverage.casefold()
    if question.reference_set == "CPF_30Q":
        return (
            "The CPF reference defines candidate retrieval sources, not a verified answer score; "
            "this row confirms that the mapped evidence survived cleaning."
        )
    if "not covered" in folded:
        return "The required transaction dataset is absent from the supplied local corpus; this is not a cleaning loss."
    if "partial" in folded:
        return (
            "Available evidence survived cleaning, but the reference identifies a source, cross-policy, "
            "or user-input limitation."
        )
    return "The reference assesses local coverage as full and the mapped evidence survived cleaning."


def validate(
    questions: list[Question],
    documents: dict[str, dict[str, Any]],
    inventory: dict[str, dict[str, str]],
    raw_root: Path,
) -> list[ValidationRow]:
    rows: list[ValidationRow] = []
    raw_cache: dict[str, str] = {}
    for question in questions:
        found = [identifier for identifier in question.candidate_document_ids if identifier in documents]
        block, document_id, block_id, score = best_evidence(question, documents)
        coverage = 0.0
        evidence = ""
        if block and document_id:
            evidence = normalize_text(block["text"]).replace("\n", " ")[:500]
            if document_id not in raw_cache:
                raw_cache[document_id] = raw_selected_text(documents[document_id], inventory, raw_root)
            evidence_tokens = token_set(block["text"])
            raw_tokens = token_set(raw_cache[document_id])
            coverage = len(evidence_tokens & raw_tokens) / len(evidence_tokens) if evidence_tokens else 0.0

        if not question.candidate_document_ids:
            result = "SOURCE_GAP_NOT_CLEANING_FAILURE"
        elif not found:
            result = "MISSING_CANDIDATE_DOCUMENT"
        elif not block or score <= 0 or coverage < 0.85:
            result = "REVIEW_REQUIRED"
        else:
            result = "PASS"
        rows.append(
            ValidationRow(
                validation_id=f"{question.reference_set}_{question.question_id}",
                reference_set=question.reference_set,
                question_id=question.question_id,
                question=question.question,
                reference_coverage=question.reference_coverage,
                candidate_document_ids=";".join(question.candidate_document_ids),
                cleaned_documents_found=";".join(found),
                selected_document_id=document_id,
                selected_block_id=block_id,
                evidence_excerpt=evidence,
                raw_evidence_token_coverage=f"{coverage:.4f}" if block else "",
                cleaning_preservation_result=result,
                answerability_note=answerability_note(question),
            )
        )
    return rows


def write_csv(rows: list[ValidationRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(ValidationRow.__dataclass_fields__)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def write_summary(rows: list[ValidationRow], path: Path) -> None:
    results = Counter(row.cleaning_preservation_result for row in rows)
    hdb_coverage = Counter()
    for row in rows:
        if row.reference_set != "HDB_30Q":
            continue
        folded = row.reference_coverage.casefold()
        if "not covered" in folded:
            hdb_coverage["source_gap"] += 1
        elif "partial" in folded:
            hdb_coverage["partial"] += 1
        else:
            hdb_coverage["full"] += 1
    text = f"""# Cleaning Content Validation Summary

This is a data-preservation check, not a model or RAG evaluation. The two overlapping HDB reference files are consolidated into one 30-question set; the CPF reference contributes 30 additional questions.

## Result

- Unique general questions checked: {len(rows)}
- Cleaning preservation PASS: {results['PASS']}
- Source gaps unrelated to cleaning: {results['SOURCE_GAP_NOT_CLEANING_FAILURE']}
- Rows requiring cleaning review: {results['REVIEW_REQUIRED'] + results['MISSING_CANDIDATE_DOCUMENT']}
- HDB reference coverage after including the supplied IRAS pages: {hdb_coverage['full']} full, {hdb_coverage['partial']} partial, {hdb_coverage['source_gap']} source gap
- CPF rows remain labelled Reference mapping only because the supplied CPF document explicitly says its mappings are retrieval candidates rather than verified answer scores.

## Interpretation

A PASS means relevant evidence exists in the cleaned output and its tokens remain traceable to the corresponding raw HTML. It does not convert a reference source mapping into an answer-accuracy score. PARTIAL and source-gap conditions belong to the supplied corpus and cannot be repaired by cleaning alone.
"""
    path.write_text(text, encoding="utf-8")


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=Path("../Data/Raw"))
    parser.add_argument("--inventory", type=Path, default=Path("reports/file_inventory.csv"))
    parser.add_argument("--cleaned", type=Path, default=Path("data/cleaned/cleaned_documents.jsonl"))
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--output", type=Path, default=Path("reports/cleaning_content_validation.csv"))
    parser.add_argument(
        "--summary", type=Path, default=Path("reports/cleaning_content_validation_summary.md")
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    questions = load_hdb_questions(args.reference_root / "SSO" / "HDB_30Q_Coverage_Final.docx")
    questions.extend(load_cpf_questions(args.reference_root / "CPF" / "CPF_RAG_30_General_Questions.docx"))
    documents = {
        document["document_id"]: document
        for document in (
            json.loads(line) for line in args.cleaned.read_text(encoding="utf-8").splitlines()
        )
    }
    with args.inventory.open(encoding="utf-8", newline="") as handle:
        inventory = {row["file_id"]: row for row in csv.DictReader(handle)}
    rows = validate(questions, documents, inventory, args.raw_root)
    write_csv(rows, args.output)
    write_summary(rows, args.summary)
    result_counts = Counter(row.cleaning_preservation_result for row in rows)
    print(
        json.dumps(
            {
                "unique_questions": len(rows),
                "results": dict(sorted(result_counts.items())),
                "output": str(args.output),
                "summary": str(args.summary),
            },
            indent=2,
        )
    )
    return 1 if result_counts["REVIEW_REQUIRED"] or result_counts["MISSING_CANDIDATE_DOCUMENT"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
