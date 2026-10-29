"""Real SQLite MLflow integration with fake inference: no model API calls."""

import csv
import json
from pathlib import Path

import pytest
import yaml

from agents.supervisor import ablation
from agents.supervisor.compute_metrics import ProcessMeasurement
from agents.supervisor.experiment_tracking import effective_params, flatten, publish_grades


@pytest.fixture
def tracking_config(tmp_path, monkeypatch):
    config = yaml.safe_load(ablation.CONFIG_FILE.read_text())
    config['experiment_tracking'] = {
        'enabled': False,
        'tracking_uri': 'sqlite:///' + str(tmp_path / 'mlflow.db'),
        'artifact_directory': str(tmp_path / 'artifacts'),
        'experiment_name': 'offline-integration-tests',
        'memory_sampling_interval_seconds': 0.01,
    }
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(ablation, 'CONFIG_FILE', path)
    monkeypatch.delenv('MLFLOW_TRACKING_URI', raising=False)
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
    assert flatten({'llm': {'max_output_tokens': 100, 'api_key': 'secret'}})['config.llm.api_key'] == '[REDACTED]'
    assert flatten({'llm': {'max_output_tokens': 100}})['config.llm.max_output_tokens'] == '100'


def test_real_mlflow_run_metrics_parameters_artifacts_and_grades(tmp_path, tracking_config):
    pytest.importorskip('mlflow')
    from mlflow import MlflowClient
    config, _ = tracking_config
    out = tmp_path / 'evaluation'
    records = ablation.run_experiment(questions(), out, '2026-10-29', pipeline='graph',
                                     answer_fn=fake_answer, mlflow=True, run_name='fixture-only')
    link = json.loads((out / 'mlflow.json').read_text())
    client = MlflowClient(tracking_uri=link['tracking_uri'])
    parent = client.get_run(link['parent_run_id'])
    assert parent.info.status == 'FINISHED'
    assert parent.data.params['config.llm.model'] == config['llm']['model']
    assert 'A_baseline.mean_local_cpu_seconds' in parent.data.metrics
    assert 'B_decomposition.mean_local_rss_peak_mb' in parent.data.metrics
    assert len(link['children']) == len(records) == 2
    setup_ids = set()
    for record in records:
        child = client.get_run(record['mlflow_run_id'])
        setup_ids.add(child.data.params['setup_id'])
        assert child.info.status == 'FINISHED'
        assert child.data.tags['mlflow.parentRunId'] == parent.info.run_id
        assert child.data.params['effective.supervisor.decompose'] == str(ablation.VARIANTS[record['variant']]).lower()
        assert child.data.params['effective.self_check.llm_check'] == 'true'
        assert child.data.params['config.agents.policy_top_k'] == str(config['agents']['policy_top_k'])
        assert child.data.metrics['model_calls'] == 2
        assert child.data.metrics['stage.policy_assessor.calls'] == 2
        assert child.data.metrics['local_cpu_seconds'] >= 0
        assert child.data.metrics['local_rss_peak_mb'] > 0
        assert 'result.json' in [a.path for a in client.list_artifacts(child.info.run_id)]
    assert len(setup_ids) == 2
    assert 'configuration.json' in [a.path for a in client.list_artifacts(parent.info.run_id)]
    with (out / 'grading_blind.csv').open() as stream:
        grades = list(csv.DictReader(stream))
    for grade in grades:
        for metric in ablation.GRADES:
            grade[metric] = '1'
    ablation.write_csv(out / 'graded.csv', grades, list(grades[0]))
    scores = ablation.score_experiment(out, out / 'graded.csv')
    publish_grades(out, out / 'graded.csv', scores)
    assert client.get_run(parent.info.run_id).data.metrics['A_baseline.quality.correctness'] == 1
    assert all(client.get_run(child).data.metrics['quality.completeness'] == 1 for child in link['children'].values())
    with (out / 'comparison.csv').open() as stream:
        comparison = list(csv.DictReader(stream))
    assert all(float(r['quality_correctness']) == 1 for r in comparison)
    assert all(float(r['mean_local_cpu_seconds']) >= 0 for r in comparison)


def test_config_change_stops_further_inference_and_marks_batch_failed(tmp_path, tracking_config):
    pytest.importorskip('mlflow')
    from mlflow import MlflowClient
    config, config_path = tracking_config
    calls = []
    def changed(*args, **kwargs):
        calls.append(args[0])
        result = fake_answer(*args, **kwargs)
        new_config = {**config, 'self_check': {'llm_check': False, 'max_retries': 0}}
        config_path.write_text(yaml.safe_dump(new_config))
        return result
    out = tmp_path / 'changed'
    with pytest.raises(RuntimeError, match='changed during inference'):
        ablation.run_experiment(questions(), out, '2026-10-29', answer_fn=changed, mlflow=True)
    assert len(calls) == 1
    assert len((out / 'runs.jsonl').read_text().splitlines()) == 1
    link = json.loads((out / 'mlflow.json').read_text())
    assert MlflowClient(tracking_uri=link['tracking_uri']).get_run(link['parent_run_id']).info.status == 'FAILED'


def test_pipeline_errors_keep_quality_denominator_and_failed_child(tmp_path, tracking_config):
    pytest.importorskip('mlflow')
    from mlflow import MlflowClient
    def failed(question, **kwargs):
        kwargs['usage_log'].append({'step':'router', 'input_tokens':10, 'output_tokens':2})
        raise RuntimeError('fixture failure')
    out = tmp_path / 'failed'
    records = ablation.run_experiment(questions(), out, '2026-10-29', answer_fn=failed, mlflow=True)
    link = json.loads((out / 'mlflow.json').read_text())
    client = MlflowClient(tracking_uri=link['tracking_uri'])
    assert all(client.get_run(r['mlflow_run_id']).info.status == 'FAILED' for r in records)
    assert all(r['compute']['local_cpu_seconds'] >= 0 and r['usage_incomplete'] for r in records)
    assert client.get_run(link['parent_run_id']).info.status == 'FINISHED'


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


def test_missing_price_rates_are_unknown_not_free(tmp_path, tracking_config):
    config, path = tracking_config
    config['llm'].pop('pricing')
    path.write_text(yaml.safe_dump(config))
    records = ablation.run_experiment(questions(), tmp_path / 'unknown-price',
                                     '2026-10-29', answer_fn=fake_answer, mlflow=False)
    assert all(r['cost_usd'] is None and r['usage_incomplete'] for r in records)
