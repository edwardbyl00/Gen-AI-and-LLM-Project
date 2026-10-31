"""Local experiment metadata, measurements and comparisons; fake inference only."""

import json

import pytest
import yaml

from agents.supervisor import ablation
from agents.supervisor.compute_metrics import ProcessMeasurement
from agents.supervisor.experiment_metadata import effective_params, snapshot_settings


@pytest.fixture
def measurement_config(tmp_path, monkeypatch):
    config = yaml.safe_load(ablation.CONFIG_FILE.read_text())
    config['experiment_measurements'] = {'memory_sampling_interval_seconds': 0.01}
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(ablation, 'CONFIG_FILE', path)
    return config, path


def fake_answer(question, today, decompose, usage_log):
    usage_log.append({'step': 'policy_assessor', 'input_tokens': 100, 'output_tokens': 10, 'calls': 2})
    return {'question': question, 'today': today, 'variant': 'B_decomposition' if decompose else 'A_baseline',
            'answer': {'answer': 'Fixture answer', 'declined': False, 'sources': []},
            'routing': {'route': 'policy'}, 'usage': usage_log,
            'agent_errors': {}, 'steps': [], 'cost_usd': 0.0004}


def questions():
    return [{'question_id': 'fixture_1', 'question': 'Fixture question?', 'category': 'policy'}]


def test_effective_settings_override_requested_config():
    params = effective_params({'supervisor': {'decompose': True}, 'self_check': {'llm_check': True}}, 'supervisor', False)
    assert params['effective.supervisor.decompose'] == 'false'
    assert params['effective.self_check.llm_check'] == 'false'
    assert params['effective.self_check.max_retries'] == '0'
    assert snapshot_settings({'llm': {'max_output_tokens': 100, 'api_key': 'secret'}})['llm']['api_key'] == '[REDACTED]'
    assert snapshot_settings({'llm': {'max_output_tokens': 100}})['llm']['max_output_tokens'] == 100


def test_measurement_keeps_memory_unknown_if_sampling_unavailable():
    measurement = ProcessMeasurement()
    measurement.process = None
    with measurement:
        sum(range(10000))
    assert measurement.metrics['local_cpu_seconds'] >= 0
    assert measurement.metrics['local_rss_peak_mb'] is None


def test_quality_constrained_comparison_does_not_select_cheapest_bad_answer(tmp_path):
    rows = []
    for name, cost, quality, cpu in [('bad', 0.001, 0.2, 1), ('good', 0.01, 0.9, 2),
                                    ('dominated', 0.02, 0.9, 3), ('cpu_tradeoff', 0.015, 0.9, 1)]:
        rows.append({'setup_id': name, 'variant': 'B_decomposition', 'question_set_sha256': 'same',
                     'query_date': '2026-10-29', 'quality_correctness': quality,
                     'quality_completeness': quality, 'usage_incomplete_runs': 0,
                     'mean_cost_usd': cost, 'mean_seconds': 5, 'mean_local_cpu_seconds': cpu,
                     'mean_local_rss_peak_mb': 100})
    ablation.write_csv(tmp_path / 'comparison.csv', rows, list(rows[0]))
    compared = ablation.compare_experiments([tmp_path])
    by_name = {r['setup_id']: r for r in compared}
    assert not by_name['bad']['eligible']
    assert not by_name['dominated']['pareto_efficient']
    assert by_name['good']['pareto_efficient'] and by_name['cpu_tradeoff']['pareto_efficient']


def test_comparison_rejects_different_question_sets(tmp_path):
    rows = [{'question_set_sha256': 'first', 'query_date': '2026-10-29', 'mean_cost_usd': ''},
            {'question_set_sha256': 'second', 'query_date': '2026-10-29', 'mean_cost_usd': ''}]
    ablation.write_csv(tmp_path / 'comparison.csv', rows, list(rows[0]))
    with pytest.raises(ValueError, match='same question-set'):
        ablation.compare_experiments([tmp_path])


def test_missing_price_rates_are_unknown_not_free(tmp_path, measurement_config):
    config, path = measurement_config
    config['llm'].pop('pricing')
    path.write_text(yaml.safe_dump(config))
    records = ablation.run_experiment(questions(), tmp_path / 'unknown-price',
                                     '2026-10-29', answer_fn=fake_answer)
    assert all(r['cost_usd'] is None and r['usage_incomplete'] for r in records)


def test_local_batch_keeps_results_measurements_and_grading(tmp_path, measurement_config):
    out = tmp_path / 'local-evaluation'
    records = ablation.run_experiment(questions(), out, '2026-10-31', answer_fn=fake_answer)
    assert len(records) == 2
    assert all(r['compute']['local_cpu_seconds'] >= 0 for r in records)
    manifest = json.loads((out / 'manifest.json').read_text())
    assert manifest['memory_sampling_interval_seconds'] == 0.01
    assert 'git_commit' in manifest['environment']
    assert {r['variant'] for r in records} == set(ablation.VARIANTS)
    import csv
    with (out / 'grading_blind.csv').open(newline='') as stream:
        grades = list(csv.DictReader(stream))
    for row in grades:
        row.update({metric: '1' for metric in ablation.GRADES})
    ablation.write_csv(out / 'graded.csv', grades, list(grades[0]))
    scores = ablation.score_experiment(out, out / 'graded.csv')
    assert all(score['mean'] == 1 for score in scores['quality'])
    assert (out / 'comparison.csv').exists()


def test_config_change_stops_batch_after_saving_completed_record(tmp_path, measurement_config):
    config, path = measurement_config
    calls = []
    def changed(*args, **kwargs):
        calls.append(args[0])
        result = fake_answer(*args, **kwargs)
        config['supervisor']['decompose'] = not config['supervisor']['decompose']
        path.write_text(yaml.safe_dump(config))
        return result
    out = tmp_path / 'changed'
    with pytest.raises(RuntimeError, match='changed during inference'):
        ablation.run_experiment(questions(), out, '2026-10-31', answer_fn=changed)
    assert len(calls) == 1
    saved = [json.loads(line) for line in (out / 'runs.jsonl').read_text().splitlines()]
    assert len(saved) == 1 and saved[0]['config_changed'] is True


def test_failed_inference_retains_runs_and_reported_usage(tmp_path, measurement_config):
    def failed(question, **kwargs):
        kwargs['usage_log'].append({'step': 'router', 'input_tokens': 10, 'output_tokens': 2})
        raise RuntimeError('fixture failure')
    out = tmp_path / 'failed'
    records = ablation.run_experiment(questions(), out, '2026-10-31', answer_fn=failed)
    assert len(records) == 2
    assert all(r['error'] == 'RuntimeError: fixture failure' for r in records)
    assert all(r['input_tokens'] == 10 and r['usage_incomplete'] for r in records)
    assert all(r['compute']['local_cpu_seconds'] >= 0 for r in records)
    assert (out / 'grading_blind.csv').exists()
