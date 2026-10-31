"""Check the stage-review workbook has the right sheets and rows; no model calls."""

import csv
import json
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

pytest.importorskip("xlsxwriter")

from agents.supervisor.stage_review_excel import agent_questions, export_workbook

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SHEETS = ["Summary", "Review", "Agentic Details"]


def sheet_names(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("xl/workbook.xml"))
        return [s.get("name") for s in root.findall("x:sheets/x:sheet", NS)]


def row_count(path, sheet_index):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet_index}.xml"))
    rows = root.findall(".//x:row", NS)
    return int(rows[-1].get("r")) if rows else 0


@pytest.fixture
def stage_dir(tmp_path):
    run_dir = tmp_path
    directory = run_dir / "stage_review"
    directory.mkdir()
    review_rows = [
        {"review_id": "r1", "question_id": "1", "question": "Q1?", "answer": "A1.",
         "judge_total_score": "", "judge_reason": "", "evidence_relevance": "", "faithfulness": "",
         "correctness": "", "completeness": "", "appropriate_abstention": "",
         "what_went_well": "", "what_went_wrong": "", "recommended_fix": "", "reviewer_notes": ""},
        {"review_id": "r2", "question_id": "1", "question": "Q1?", "answer": "A1 alt.",
         "judge_total_score": "", "judge_reason": "", "evidence_relevance": "1", "faithfulness": "1",
         "correctness": "1", "completeness": "1", "appropriate_abstention": "1",
         "what_went_well": "", "what_went_wrong": "", "recommended_fix": "", "reviewer_notes": ""},
    ]
    with (directory / "review.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)

    diagnostics = {"rows": [
        {"review_id": "r1", "question_id": "1", "variant": "A_baseline", "category": "policy",
         "actual_route": "policy", "expected_route": None, "routing_correct": None,
         "coverage_status": "UNKNOWN", "reference_verified": False, "reference_candidate_recall": None,
         "reference_supplied_recall": None, "policy_outcomes": [{"decision": "ANSWER_READY"}],
         "diagnostic_flags": [], "execution_error": None},
        {"review_id": "r2", "question_id": "1", "variant": "B_decomposition", "category": "policy",
         "actual_route": "policy", "expected_route": None, "routing_correct": None,
         "coverage_status": "UNKNOWN", "reference_verified": False, "reference_candidate_recall": None,
         "reference_supplied_recall": None, "policy_outcomes": [{"decision": "ABSTAIN"}],
         "diagnostic_flags": ["no_reference_chunk_retrieved"], "execution_error": None},
    ]}
    (directory / "diagnostics.json").write_text(json.dumps(diagnostics))

    runs = [
        {"review_id": "r1", "question_id": "1", "variant": "A_baseline", "category": "policy",
         "input_tokens": 300, "output_tokens": 50, "model_calls": 2, "cost_usd": 0.001234,
         "bundle": {"usage": [{"step": "router", "input_tokens": 200, "output_tokens": 20},
                              {"step": "synthesis", "input_tokens": 100, "output_tokens": 30}]}},
        {"review_id": "r2", "question_id": "1", "variant": "B_decomposition", "category": "policy",
         "input_tokens": 400, "output_tokens": 60, "model_calls": 2, "cost_usd": 0.002345,
         "bundle": {"usage": [{"step": "router", "input_tokens": 250, "output_tokens": 25},
                              {"step": "synthesis", "input_tokens": 150, "output_tokens": 35}]}},
    ]
    (run_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs))

    llm_scores_path = tmp_path / "llm_judge_scores.json"
    llm_scores_path.write_text(json.dumps({
        "model": "fixture-judge", "max_score": 10,
        "scores": {"r1": {"question_id": "1", "variant": "A_baseline", "category": "policy",
                          "evidence_support": 2, "policy_currency": 2, "citation_relevance": 2,
                          "unsupported_claims": 2, "appropriate_abstention": 2, "total_score": 10,
                          "reason": "Fixture reason.", "usage": {"cost_usd": 0.001}, "latency_seconds": 1.0}},
        "errors": [{"review_id": "r2", "reason": "fixture_skip"}],
    }))
    return directory, llm_scores_path


def sheet_values(path, index):
    with ZipFile(path) as archive:
        strings = [''.join(node.itertext()) for node in ET.fromstring(
            archive.read("xl/sharedStrings.xml")).findall("x:si", NS)]
        root = ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
    values = {}
    for cell in root.findall('.//x:c', NS):
        value = cell.findtext('x:v', namespaces=NS)
        values[cell.get('r')] = strings[int(value)] if cell.get('t') == 's' else value
    return values


def test_three_sheets_keep_review_checks_judges_and_usage(stage_dir, tmp_path):
    directory, llm_scores_path = stage_dir
    path = export_workbook(directory, tmp_path / "review.xlsx", llm_judge_scores=llm_scores_path)
    assert sheet_names(path) == SHEETS
    # One combined row for every original review execution.
    assert row_count(path, 2) == 8
    review = sheet_values(path, 2)
    assert 'Ungated judge score' in review.values()
    assert 'Routing correct' in review.values()
    assert 'Policy coverage' in review.values()
    assert any('ABSTAIN' in str(value) for value in review.values())
    assert 'Fixture reason.' in review.values() and 'fixture_skip' in review.values()
    usage = sheet_values(path, 3)
    assert list(usage.values()).count('TOTAL') == 2
    assert list(usage.values()).count('router') == list(usage.values()).count('synthesis') == 2
    assert '0.001234' in usage.values() and '0.002345' in usage.values()


def test_works_without_llm_judge_scores(stage_dir, tmp_path):
    directory, _ = stage_dir
    path = export_workbook(directory, tmp_path / "review_no_judge.xlsx")
    assert sheet_names(path) == SHEETS
    assert 'Ungated judge score' not in sheet_values(path, 2).values()


def test_summary_reports_tokens_and_retrieval_proxy(stage_dir, tmp_path):
    directory, llm_scores_path = stage_dir
    path = export_workbook(directory, tmp_path / "review.xlsx", llm_judge_scores=llm_scores_path)
    with ZipFile(path) as archive:
        strings = [''.join(node.itertext())
                  for node in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("x:si", NS)]
    # Both the ANSWER_READY/ABSTAIN proxy and the per-stage token breakdown should appear somewhere.
    assert any(s == "router" for s in strings)
    assert any(s == "synthesis" for s in strings)
    assert any("TOKENS BY STAGE" in s for s in strings)


def test_focused_questions_requirements_searches_and_retries_are_retained():
    task = {'id': 'policy_1', 'agent': 'policy', 'question': 'Which grant rules apply?',
            'required_elements': ['Grant eligibility', 'Required conditions']}
    run = {'question': 'Which grants apply and what do flats cost?', 'bundle': {
        'routing': {'tasks': [task]},
        'task_results': [{'task': task, 'attempt': 2, 'result': {
            'decision': 'ANSWER_READY', 'reason': 'Recovered grant rule',
            'retrieved_evidence': [{'chunk_id': 'gold'}], 'evidence': [{'chunk_id': 'gold'}],
            'trace': [{'step': 'DECOMPOSE_QUERY', 'queries': ['resale grant eligibility']}]
        }}],
        'steps': [{'step': 'policy_agent', 'task_id': 'policy_1', 'attempt': 1,
                   'decision': 'ABSTAIN', 'reason': 'Missing rule'},
                  {'step': 'policy_agent', 'task_id': 'policy_1', 'attempt': 2,
                   'decision': 'ANSWER_READY', 'reason': 'Recovered grant rule'}]}}
    rows = agent_questions(run)
    assert len(rows) == 2 and [r['attempt'] for r in rows] == [1, 2]
    assert all(r['question'] == task['question'] for r in rows)
    assert rows[0]['decision'] == 'ABSTAIN' and rows[0]['reason'] == 'Missing rule'
    assert rows[0]['supplied_ids'] == 'Unknown'
    assert rows[1]['supplied_ids'] == 'gold'
    assert rows[1]['searches'] == 'resale grant eligibility'
    assert 'Required conditions' in rows[1]['required_elements']


def test_baseline_question_and_unexecuted_tasks_are_labeled_honestly():
    original = 'Original unsplit housing question'
    rows = agent_questions({'question': original, 'bundle': {
        'policy_result': {'decision': 'ABSTAIN', 'reason': 'No evidence', 'evidence': []},
        'steps': [{'step': 'policy_agent'}]}})
    assert rows[0]['question'] == original
    assert rows[0]['required_elements'] == 'Not recorded'
    assert rows[0]['decision'] == 'ABSTAIN'
    planned = agent_questions({'bundle': {'routing': {'tasks': [
        {'id': 'p', 'agent': 'policy', 'question': 'Planned question', 'required_elements': []}]}}})
    assert planned[0]['decision'] == 'NOT EXECUTED / NOT RECORDED'


def test_agent_questions_are_written_to_the_detail_sheet(stage_dir, tmp_path):
    directory, _ = stage_dir
    file = directory.parent / 'runs.jsonl'
    records = [json.loads(line) for line in file.read_text().splitlines()]
    records[1]['question'] = 'Original mixed question'
    records[1]['bundle']['task_results'] = [{'task': {
        'id': 'price_1', 'agent': 'price', 'question': '=literal focused query',
        'required_elements': ['Median price', 'Period']}, 'attempt': 1,
        'result': {'median_price': 123, 'note': 'Historical prices'}, 'error': None}]
    file.write_text('\n'.join(json.dumps(r) for r in records))
    path = export_workbook(directory, tmp_path / 'focused.xlsx')
    values = sheet_values(path, 3)
    assert 'Original mixed question' in values.values()
    assert '=literal focused query' in values.values()
    assert 'Median price\nPeriod' in values.values()
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('xl/worksheets/sheet3.xml'))
        cell = root.find('.//x:c[@r="H7"]', NS)
        assert cell is not None and cell.find('x:f', NS) is None


def test_empty_detail_sheet_is_omitted(stage_dir, tmp_path):
    directory, _ = stage_dir
    file = directory.parent / 'runs.jsonl'
    records = [json.loads(line) for line in file.read_text().splitlines()]
    for record in records:
        record['bundle']['usage'] = []
    file.write_text('\n'.join(json.dumps(r) for r in records))
    path = export_workbook(directory, tmp_path / 'minimal.xlsx')
    assert sheet_names(path) == ['Summary', 'Review']


def test_summary_grade_formulas_follow_the_review_cells(stage_dir, tmp_path):
    directory, _ = stage_dir
    path = export_workbook(directory, tmp_path / 'live_summary.xlsx')
    values = sheet_values(path, 1)
    assert values['E7'] == '0' and values['E8'] == '1'
    assert values['F7'] == 'Pending' and float(values['F8']) == 1
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        for address in ('E7', 'E8', 'F7', 'F8'):
            formula = root.find(f'.//x:c[@r="{address}"]/x:f', NS).text
            assert "'Review'!" in formula
