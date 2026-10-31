"""Formatted .xlsx for a stage-review directory (agents.supervisor.diagnostics);
never performs model inference, only reads what's already on disk.

Combines, for human review in one workbook:
- review.csv: the reviewer's sheet (grades start blank; judge_* columns are
  the gated judge_tools prepass, if it was run with --judge-scores)
- diagnostics.json: per-execution stage checks (routing, coverage, recall,
  policy decision, diagnostic flags)
- runs.jsonl (read from the ablation run directory, stage_dir's parent):
  per-stage (router/price/policy/synthesis/self_check) token usage and cost
- optionally, the ungated judge scores from scripts/judge_ablation_answers.py

The workbook uses Summary and Review, plus Agentic Details only when recorded
tasks or usage exist. Checks and judge scores share Review; task questions and
stage usage share Agentic Details. No empty judge/detail tabs are created.

Correctness and retrieval-recall numbers stay "Pending"/"Unknown" until a
human has graded Review and the references are verified -- this workbook
reports what's known now, it does not grade or verify anything itself.

Usage:
    python -m agents.supervisor.stage_review_excel \
        evaluation/ablation/new_questions_v1/stage_review \
        --llm-judge-scores evaluation/ablation/new_questions_v1_llm_judge_scores.json \
        --out evaluation/ablation/new_questions_v1/stage_review/review.xlsx
"""

import argparse
import csv
import json
import math
import textwrap
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.supervisor.router import estimate_cost_usd

GRADE_COLUMNS = ("evidence_relevance", "faithfulness", "correctness", "completeness",
                 "appropriate_abstention")
NOTE_COLUMNS = ("what_went_well", "what_went_wrong", "recommended_fix", "reviewer_notes")


def require_writer():
    try:
        import xlsxwriter
    except ImportError as error:
        raise RuntimeError("Excel export needs: python -m pip install -r requirements-experiments.txt") from error
    return xlsxwriter


def _read_review_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _read_diagnostics_rows(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["review_id"]: row for row in data["rows"]}


def _read_llm_judge_scores(path):
    if path is None:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("scores", {}), data.get("errors", []), data.get("model"), data.get("max_score")


def _read_runs(run_dir):
    """review_id -> {question_id, variant, totals, usage (per-stage list)}."""
    path = Path(run_dir) / "runs.jsonl"
    runs = {}
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            record = json.loads(line)
            bundle = record.get("bundle") or {}
            runs[record["review_id"]] = {
                "question_id": record["question_id"], "variant": record["variant"],
                "category": record.get("category"),
                "input_tokens": record.get("input_tokens") or 0,
                "output_tokens": record.get("output_tokens") or 0,
                "model_calls": record.get("model_calls") or 0,
                "cost_usd": record.get("cost_usd") or 0.0,
                "usage": bundle.get("usage") or [],
                "question": record.get("question", bundle.get("question", "")),
                "bundle": bundle,
            }
    return runs


def agent_questions(run):
    """Actual focused questions/attempts; earlier attempts never borrow later evidence."""
    bundle = run.get("bundle", {})
    records = bundle.get("task_results")
    if records is None:
        records = [{"task": {"id": agent, "agent": agent, "question": run.get("question", "")},
                    "result": bundle.get(agent + "_result"), "attempt": None}
                   for agent in ("price", "policy") if bundle.get(agent + "_result") is not None]
    by_id = {entry["task"]["id"]: entry for entry in records}
    planned = {task["id"]: task for task in bundle.get("routing", {}).get("tasks", [])}
    planned.update({key: record["task"] for key, record in by_id.items()})
    steps = [step for step in bundle.get("steps", []) if step.get("step") in ("price_agent", "policy_agent")]
    if not steps:
        steps = [{"step": entry["task"]["agent"] + "_agent", "task_id": entry["task"]["id"],
                  "attempt": entry.get("attempt") or 1, "error": entry.get("error")}
                 for entry in records]
    attempts, rows = {}, []
    last = {step.get("task_id", step["step"].removesuffix("_agent")): index
            for index, step in enumerate(steps)}
    for index, step in enumerate(steps):
        agent = step["step"].removesuffix("_agent")
        task_id = step.get("task_id", agent)
        attempts[task_id] = attempts.get(task_id, 0) + 1
        attempt = step.get("attempt", attempts[task_id])
        entry = by_id.get(task_id, {})
        task = planned.get(task_id, {"agent": agent, "question": run.get("question", "")})
        final = index == last[task_id] and (entry.get("attempt") in (None, attempt))
        result = (entry.get("result") or {}) if final else {}
        policy = result.get("retrieval", result)
        candidates = policy.get("retrieved_evidence")
        supplied = policy.get("evidence")
        searches = []
        for event in result.get("trace", []):
            if event.get("step") == "REQUERY" and event.get("query"):
                searches.append(event["query"] + (" (rewrite rejected)" if event.get("accepted") is False else ""))
            if event.get("step") == "DECOMPOSE_QUERY":
                searches.extend(event.get("queries", []))
        error = step.get("error") or (entry.get("error") if final else None)
        rows.append({"task_id": task_id, "agent": agent, "attempt": attempt,
            "question": task.get("question", "Not recorded"),
            "required_elements": "\n".join(task.get("required_elements", [])) or "Not recorded",
            "decision": step.get("decision") or result.get("decision") or
                ("ERROR" if error else "COMPLETED" if result else "Not recorded"),
            "reason": step.get("reason") or result.get("reason") or result.get("note") or "Not recorded",
            "searches": "\n".join(dict.fromkeys(searches)) or ("None recorded" if final else "Not recorded for this attempt"),
            "candidate_ids": ", ".join(item.get("chunk_id", "Unknown ID") for item in candidates)
                if candidates is not None else "Unknown" if agent == "policy" else "N/A",
            "supplied_ids": ", ".join(item.get("chunk_id", "Unknown ID") for item in supplied)
                if supplied is not None else "Unknown" if agent == "policy" else "N/A",
            "error": error or "", "seconds": step.get("seconds", entry.get("seconds") if final else None)})
    for task_id, task in planned.items():
        if task_id not in last:
            rows.append({"task_id": task_id, "agent": task["agent"], "attempt": "",
                "question": task["question"], "required_elements": "\n".join(task.get("required_elements", [])),
                "decision": "NOT EXECUTED / NOT RECORDED", "reason": "No execution result in the saved trace",
                "searches": "Unknown", "candidate_ids": "Unknown", "supplied_ids": "Unknown", "error": "", "seconds": None})
    return rows


def _mean(values):
    values = [v for v in values if isinstance(v, (int, float))]
    return round(sum(values) / len(values), 3) if values else None


def citation_precision(run):
    """(valid, invalid, precision/10 or None). A pure count, not a judgement:
    valid cited passage numbers over everything the model attempted to cite,
    reconstructed from synthesis's check_citations() output (the final valid
    list plus its recorded invalid_citation events). A duplicate attempt at
    an already-valid number leaves no trace in either and is not counted."""
    answer = (run.get("bundle") or {}).get("answer") or {}
    valid = len(answer.get("cited") or [])
    invalid = sum(1 for e in answer.get("events") or [] if e.get("code") == "invalid_citation")
    attempted = valid + invalid
    precision = round(valid / attempted * 10, 1) if attempted else None
    return valid, invalid, precision


def export_workbook(stage_dir, out, *, llm_judge_scores=None):
    writer = require_writer()
    stage_dir = Path(stage_dir)
    review_rows = _read_review_csv(stage_dir / "review.csv")
    diagnostics = _read_diagnostics_rows(stage_dir / "diagnostics.json")
    runs = _read_runs(stage_dir.parent)
    manifest_path = stage_dir.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    pricing = manifest.get("config", {}).get("llm", {}).get("pricing", {})
    pricing_known = all(isinstance(pricing.get(key), (int, float)) and
                        not isinstance(pricing[key], bool) and math.isfinite(pricing[key]) and pricing[key] >= 0
                        for key in ("input_per_1m", "output_per_1m"))
    llm_scores, llm_errors, llm_model, llm_max = ({}, [], None, None)
    if llm_judge_scores is not None:
        llm_scores, llm_errors, llm_model, llm_max = _read_llm_judge_scores(llm_judge_scores)

    out = Path(out).resolve()
    if out.suffix.lower() != ".xlsx":
        raise ValueError("Excel output must use the .xlsx extension")
    out.parent.mkdir(parents=True, exist_ok=True)

    book = writer.Workbook(str(out), {"strings_to_formulas": False, "strings_to_urls": False})
    book.set_properties({"title": "AskGov stage review", "author": "Kay, Cooper and Ed",
                         "comments": "Exported from a saved stage-review run; no model inference performed."})
    book.formats[0].set_font_name("Arial")
    sheet_names = ["Summary", "Review"]
    if any(run["usage"] or agent_questions(run) for run in runs.values()):
        sheet_names.append("Agentic Details")
    sheets = {name: book.add_worksheet(name) for name in sheet_names}
    fmt = {
        "title": book.add_format({"bold": True, "font_size": 18, "font_color": "#FFFFFF", "bg_color": "#18334D", "valign": "vcenter"}),
        "note": book.add_format({"font_color": "#526479", "font_size": 10, "text_wrap": True, "valign": "vcenter"}),
        "header": book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#254D70", "text_wrap": True, "valign": "vcenter"}),
        "wrap": book.add_format({"font_size": 10, "text_wrap": True, "valign": "top"}),
        "num": book.add_format({"font_size": 10, "num_format": "#,##0", "valign": "top"}),
        "decimal": book.add_format({"font_size": 10, "num_format": "0.00", "valign": "top"}),
        "usd": book.add_format({"font_size": 10, "num_format": "$0.000000", "valign": "top"}),
        "blank": book.add_format({"font_size": 10, "bg_color": "#FFF8E6", "text_wrap": True, "valign": "top"}),
        "bad": book.add_format({"font_size": 10, "bg_color": "#FCE4E4", "valign": "top"}),
        "total": book.add_format({"bold": True, "bg_color": "#DCEAF5", "top": 1, "top_color": "#A9BFD0"}),
        "total_usd": book.add_format({"bold": True, "bg_color": "#DCEAF5", "num_format": "$0.000000",
                                      "top": 1, "top_color": "#A9BFD0"}),
    }
    for style in fmt.values():
        style.set_font_name("Arial")
    timestamp = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y-%m-%d %H:%M SGT")

    def header(sheet, title, columns, note, n_cols_frozen=2):
        end = len(columns) - 1
        sheet.hide_gridlines(2)
        sheet.set_default_row(25)
        sheet.merge_range(0, 0, 0, end, title, fmt["title"])
        sheet.set_row(0, 34)
        sheet.merge_range(1, 0, 1, end, f"AskGov SG stage review • {stage_dir} • {timestamp}", fmt["note"])
        sheet.merge_range(2, 0, 3, end, note, fmt["note"])
        sheet.set_row(2, 23)
        sheet.set_row(3, 23)
        sheet.set_row(4, 9)
        sheet.write_row(5, 0, columns, fmt["header"])
        sheet.set_row(5, 42)
        sheet.freeze_panes(6, n_cols_frozen)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, 5)

    # Review, diagnostic checks and judge context share one execution table.
    review = sheets["Review"]
    labels = [("review_id", "Review ID", 16), ("question_id", "Question ID", 12),
              ("variant", "Variant", 18), ("category", "Category", 14),
              ("question", "Question", 55), ("answer", "Answer", 85),
              ("actual_route", "Route", 12), ("decisions", "Policy decision", 28)]
    if llm_scores or llm_errors:
        labels.append(("llm_score", "Ungated judge score", 16))
    gated = any(r.get("judge_total_score") or r.get("judge_reason") for r in review_rows)
    if gated:
        labels.append(("judge_total_score", "Gated judge score", 16))
    labels += list(zip(GRADE_COLUMNS,
        ("Evidence relevance", "Faithfulness", "Correctness", "Completeness", "Appropriate abstention"),
        (16, 14, 14, 14, 18)))
    labels += list(zip(NOTE_COLUMNS, ("What went well", "What went wrong", "Recommended fix", "Reviewer notes"), (32, 32, 32, 32)))
    detail_start = len(labels)
    labels += [("expected_route", "Expected route", 14), ("routing_correct", "Routing correct", 14),
               ("coverage_status", "Policy coverage", 16), ("reference_verified", "Reference verified", 15),
               ("reference_candidate_recall", "Candidate recall", 14), ("reference_supplied_recall", "Supplied recall", 14),
               ("diagnostic_flags", "Diagnostic flags", 35), ("execution_error", "Execution error", 40),
               ("policy_reasons", "Policy assessment reasons", 70),
               ("citations_valid", "Citations valid", 13), ("citations_invalid", "Citations invalid", 14),
               ("citation_precision", "Citation precision (/10)", 18)]
    if llm_scores or llm_errors:
        labels += [("llm_evidence_support", "Judge: evidence support", 15),
                   ("llm_policy_currency", "Judge: policy currency", 15),
                   ("llm_citation_relevance", "Judge: citation relevance", 15),
                   ("llm_unsupported_claims", "Judge: unsupported claims", 15),
                   ("llm_appropriate_abstention", "Judge: appropriate abstention", 15),
                   ("llm_reason", "Ungated judge reason / error", 55),
                   ("llm_cost", "Judge cost USD", 16), ("llm_latency", "Judge latency s", 14)]
    if gated:
        labels.append(("judge_reason", "Gated judge reason", 55))
    header(review, "REVIEW • questions, stage checks and answer quality", [label for _, label, _ in labels],
           "One row per execution. Shaded grades/notes are for human review (0 / 0.5 / 1; blank = pending; NA = not applicable). "
           "Judge scores are context, not verified grades. Citation precision is a plain count (valid ÷ attempted "
           "citations), not a judgement call. Expand the grouped columns on the right for diagnostic/judge details.")
    for col, (_, _, width) in enumerate(labels):
        review.set_column(col, col, width, fmt["wrap"],
                          {"hidden": True, "level": 1} if col >= detail_start else None)
    review.set_column(0, 0, 16, fmt["wrap"], {"hidden": True})
    llm_error_by_id = {e.get("review_id"): e.get("reason", "Unknown error") for e in llm_errors}
    for row, r in enumerate(review_rows, 6):
        diag = diagnostics.get(r["review_id"], {})
        judged = llm_scores.get(r["review_id"], {})
        run = runs.get(r["review_id"], {})
        n_valid, n_invalid, precision = citation_precision(run)
        details = {**diag, **r,
            "decisions": "\n".join(f"{o.get('task_id', 'policy')}: {o.get('decision') or 'Unknown'}"
                                    for o in diag.get("policy_outcomes", [])) or "Not run / not recorded",
            "policy_reasons": "\n".join(f"{o.get('task_id', 'policy')}: {o.get('reason') or 'No reason recorded'}"
                                        for o in diag.get("policy_outcomes", [])),
            "diagnostic_flags": "\n".join(diag.get("diagnostic_flags", [])) or "None recorded",
            "citations_valid": n_valid, "citations_invalid": n_invalid,
            "citation_precision": precision if precision is not None else "NA (no citations attempted)",
            "llm_score": judged.get("total_score", "Skipped" if r["review_id"] in llm_error_by_id else "Pending"),
            "llm_reason": judged.get("reason") or llm_error_by_id.get(r["review_id"], ""),
            "llm_evidence_support": judged.get("evidence_support"),
            "llm_policy_currency": judged.get("policy_currency"),
            "llm_citation_relevance": judged.get("citation_relevance"),
            "llm_unsupported_claims": judged.get("unsupported_claims"),
            "llm_appropriate_abstention": judged.get("appropriate_abstention"),
            "llm_cost": judged.get("usage", {}).get("cost_usd"), "llm_latency": judged.get("latency_seconds")}
        values = []
        for col, (key, _, _) in enumerate(labels):
            value = details.get(key)
            if key in ("reference_candidate_recall", "reference_supplied_recall", "routing_correct") and value is None:
                value = "Unknown"
            if key == "expected_route" and not value:
                value = "Unverified"
            if key in GRADE_COLUMNS and value not in (None, "", "NA"):
                value = float(value)
            style = fmt["blank"] if key in GRADE_COLUMNS + NOTE_COLUMNS else fmt["wrap"]
            if value is None or value == "":
                review.write_blank(row, col, None, style)
            else:
                review.write(row, col, value, style)
            values.append(value)
        lines = max(sum(max(1, len(textwrap.wrap(part, max(8, int(width * .95)))))
                        for part in str(value or "").split("\n"))
                    for value, (_, _, width) in zip(values[:detail_start], labels[:detail_start]))
        review.set_row(row, min(409, max(45, lines * 13 + 10)))
    if review_rows:
        review.autofilter(5, 0, 5 + len(review_rows), len(labels) - 1)

    # Focused agent questions and per-stage usage stay together in one detail sheet.
    if "Agentic Details" in sheets:
        detail = sheets["Agentic Details"]
        columns = ["Review ID", "Question ID", "Variant", "Original question", "Task ID", "Agent", "Attempt",
                   "Question sent to agent", "Required answer elements", "Decision", "Reason", "Follow-up search queries",
                   "Candidate chunk IDs", "Supplied chunk IDs", "Execution error", "Seconds"]
        widths = [16, 12, 18, 52, 15, 12, 10, 60, 45, 18, 70, 48, 28, 28, 40, 12]
        header(detail, "AGENTIC DETAILS • questions sent to agents and execution usage", columns,
               "One row per recorded price/policy task attempt. Original questions and focused agent questions are kept separate. "
               "Follow-up queries come from policy traces. Unknown means not recorded; earlier attempts do not borrow later evidence. "
               "The usage table below includes router, synthesis and self-check calls as well.", n_cols_frozen=3)
        for col, width in enumerate(widths):
            detail.set_column(col, col, width, fmt["wrap"])
        detail.set_column(0, 0, 16, fmt["wrap"], {"hidden": True})
        row = 6
        for r in review_rows:
            run = runs.get(r["review_id"])
            if run is None:
                continue
            for task in agent_questions(run):
                values = [r["review_id"], run["question_id"], run["variant"], run["question"],
                          task["task_id"], task["agent"], task["attempt"], task["question"], task["required_elements"],
                          task["decision"], task["reason"], task["searches"], task["candidate_ids"], task["supplied_ids"],
                          task["error"], task["seconds"]]
                detail.write_row(row, 0, values, fmt["wrap"])
                lines = max(sum(max(1, len(textwrap.wrap(part, max(8, int(width * .95)))))
                                for part in str(value or "").split("\n")) for value, width in zip(values, widths))
                detail.set_row(row, min(409, max(45, lines * 13 + 10)))
                row += 1
        if row > 6:
            detail.autofilter(5, 0, row - 1, len(columns) - 1)
        else:
            detail.write(row, 0, "No focused agent execution details recorded.", fmt["note"])
            row += 1
        row += 2
        detail.merge_range(row, 0, row, 11, "USAGE BY EXECUTION AND STAGE • totals are not extra calls", fmt["header"])
        row += 1
        usage_columns = ["Review ID", "Question ID", "Variant", "Category", "Stage", "Task ID", "Attempt",
                         "Calls", "Input tokens", "Output tokens", "Total tokens", "Execution cost USD"]
        detail.write_row(row, 0, usage_columns, fmt["header"])
        detail.set_row(row, 35)
        row += 1
        for r in review_rows:
            run = runs.get(r["review_id"])
            if run is None:
                continue
            for entry in run["usage"]:
                incoming, outgoing = entry.get("input_tokens"), entry.get("output_tokens")
                detail.write_row(row, 0, [r["review_id"], run["question_id"], run["variant"], run["category"],
                    entry.get("step", ""), entry.get("task_id", ""), entry.get("attempt", ""), entry.get("calls", 1),
                    incoming if incoming is not None else "Unknown", outgoing if outgoing is not None else "Unknown",
                    incoming + outgoing if incoming is not None and outgoing is not None else "Unknown", ""], fmt["wrap"])
                row += 1
            detail.write_row(row, 0, [r["review_id"], run["question_id"], run["variant"], run["category"], "TOTAL", "", "",
                run["model_calls"], run["input_tokens"], run["output_tokens"], run["input_tokens"] + run["output_tokens"],
                run["cost_usd"]], fmt["total"])
            detail.write_number(row, 11, run["cost_usd"], fmt["total_usd"])
            row += 1

    # ---------------- Summary sheet ----------------
    summary = sheets["Summary"]
    by_variant_category = {}
    for diag in diagnostics.values():
        key = (diag["variant"], diag["category"])
        by_variant_category.setdefault(key, []).append(diag["review_id"])
    review_by_id = {r["review_id"]: r for r in review_rows}
    review_excel_rows = {r["review_id"]: index for index, r in enumerate(review_rows, 7)}
    review_columns = {key: writer.utility.xl_col_to_name(index) for index, (key, _, _) in enumerate(labels)}

    def numeric_grade(review_id, column):
        value = review_by_id.get(review_id, {}).get(column, "")
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    columns = ["Variant", "Category", "Executions", "Unique questions", "Human-graded (any field)",
              "Mean correctness", "Policy ANSWER_READY", "Policy ABSTAIN",
              "Mean candidate recall", "Mean supplied recall", "Mean citation precision (/10)",
              "Ungated judge avg (/{})".format(llm_max or "?"),
              "Input tokens", "Output tokens", "Total tokens", "Cost USD"]
    header(summary, "SUMMARY • evaluation results and usage", columns,
           "\"Human-graded\"/\"Mean correctness\" read the Review sheet — blank until reviewed, not a quality "
           "score yet. Mean candidate/supplied recall need verified references (Docs/stage_evaluation.md) and "
           "read \"Unknown\" until then. Policy ANSWER_READY/ABSTAIN counts are available now, as a retrieval "
           "proxy that needs no reference. Mean citation precision is a plain count (valid ÷ attempted "
           "citations), excluding executions that attempted none. Ungated judge avg comes from the judge "
           "context in Review; treat it the same as the other unreviewed reads.", n_cols_frozen=0)
    widths = [16, 14, 11, 16, 18, 15, 17, 13, 18, 17, 20, 20, 13, 13, 12, 12]
    for index, width in enumerate(widths):
        summary.set_column(index, index, width, fmt["wrap"])
    graded_ids = {r["review_id"] for r in review_rows if any(r.get(c, "").strip() for c in GRADE_COLUMNS)}
    row = 6
    for (variant, category), review_ids in sorted(by_variant_category.items()):
        graded = sum(1 for rid in review_ids if rid in graded_ids)
        correctness = _mean([numeric_grade(rid, "correctness") for rid in review_ids])
        decisions = [o.get("decision") for rid in review_ids
                    for o in diagnostics[rid].get("policy_outcomes") or []]
        candidate_recall = _mean([diagnostics[rid].get("reference_candidate_recall") for rid in review_ids])
        supplied_recall = _mean([diagnostics[rid].get("reference_supplied_recall") for rid in review_ids])
        judge_totals = [llm_scores[rid]["total_score"] for rid in review_ids if rid in llm_scores]
        judge_avg = _mean(judge_totals)
        precisions = [citation_precision(runs[rid])[2] for rid in review_ids if rid in runs]
        mean_precision = _mean(precisions)
        input_tokens = sum(runs[rid]["input_tokens"] for rid in review_ids if rid in runs)
        output_tokens = sum(runs[rid]["output_tokens"] for rid in review_ids if rid in runs)
        cost = sum(runs[rid]["cost_usd"] for rid in review_ids if rid in runs)
        summary.write_row(row, 0, [
            variant, category, len(review_ids),
            len({diagnostics[rid]["question_id"] for rid in review_ids}),
            graded, correctness if correctness is not None else "Pending",
            decisions.count("ANSWER_READY"), decisions.count("ABSTAIN"),
            candidate_recall if candidate_recall is not None else "Unknown",
            supplied_recall if supplied_recall is not None else "Unknown",
            mean_precision if mean_precision is not None else "NA (no citations attempted)",
            judge_avg if judge_avg is not None else "(no judge scores)",
            input_tokens, output_tokens, input_tokens + output_tokens, round(cost, 6),
        ], fmt["wrap"])
        grade_ranges = [f"'Review'!${review_columns[GRADE_COLUMNS[0]]}${review_excel_rows[rid]}:"
                        f"${review_columns[GRADE_COLUMNS[-1]]}${review_excel_rows[rid]}"
                        for rid in review_ids]
        graded_formula = '=SUM(' + ','.join(f'--(COUNT({ref})+COUNTIF({ref},"NA")>0)' for ref in grade_ranges) + ')'
        summary.write_formula(row, 4, graded_formula, fmt["num"], graded)
        correctness_refs = ','.join(f"'Review'!${review_columns['correctness']}${review_excel_rows[rid]}"
                                    for rid in review_ids)
        summary.write_formula(row, 5, f'=IFERROR(AVERAGE({correctness_refs}),"Pending")',
                              fmt["decimal"], correctness if correctness is not None else "Pending")
        row += 1
    summary.autofilter(5, 0, row - 1, len(columns) - 1)

    # ---- Tokens by stage, across all executions ----
    stage_header_row = row + 2
    stage_columns = ["Variant", "Stage", "Calls", "Input tokens", "Output tokens", "Total tokens", "Cost USD"]
    summary.merge_range(stage_header_row, 0, stage_header_row, len(stage_columns) - 1,
                        "TOKENS BY STAGE • summed across all executions", fmt["header"])
    summary.write_row(stage_header_row + 1, 0, stage_columns, fmt["header"])
    by_stage = {}
    for r in review_rows:
        run = runs.get(r["review_id"])
        if run is None:
            continue
        for entry in run["usage"]:
            key = (run["variant"], entry.get("step", ""))
            by_stage.setdefault(key, []).append(entry)
    row = stage_header_row + 2
    for (variant, step), entries in sorted(by_stage.items()):
        input_tokens = sum(e.get("input_tokens") or 0 for e in entries)
        output_tokens = sum(e.get("output_tokens") or 0 for e in entries)
        calls = sum(e.get("calls", 1) for e in entries)
        complete_tokens = all(e.get("input_tokens") is not None and e.get("output_tokens") is not None for e in entries)
        stage_cost = round(estimate_cost_usd(entries, pricing), 6) if pricing_known and complete_tokens else "Unknown"
        summary.write_row(row, 0, [variant, step, calls, input_tokens, output_tokens,
                                   input_tokens + output_tokens, stage_cost], fmt["wrap"])
        row += 1

    summary.activate()
    book.close()
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_dir", type=Path, help="A stage-review directory (has review.csv, diagnostics.json)")
    parser.add_argument("--llm-judge-scores", type=Path, default=None,
                        help="Output of scripts/judge_ablation_answers.py, to include alongside the review columns")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    path = export_workbook(args.stage_dir, args.out, llm_judge_scores=args.llm_judge_scores)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
