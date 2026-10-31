"""Reusable Excel reports from saved results; never performs model inference."""

import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from agents.supervisor.experiment_metadata import effective_params, snapshot_settings

GRADES = ('correctness', 'completeness', 'groundedness', 'appropriate_abstention')


def require_writer():
    try:
        import xlsxwriter
    except ImportError as error:
        raise RuntimeError('Excel export needs: python -m pip install -r requirements-experiments.txt') from error
    return xlsxwriter


def _flatten(value, prefix='config'):
    result = {}
    for key, item in snapshot_settings(value).items():
        name = f'{prefix}.{key}'
        if isinstance(item, dict):
            result.update(_flatten(item, name))
        else:
            result[name] = json.dumps(item) if isinstance(item, list) else item
    return result


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _read_grades(directory):
    saved = directory / 'reviewed_grades.json'
    if saved.exists():
        rows = json.loads(saved.read_text())
    elif (directory / 'graded.csv').exists():
        with (directory / 'graded.csv').open(encoding='utf-8-sig', newline='') as stream:
            raw = list(csv.DictReader(stream))
        rows = {r['review_id']: r for r in raw}
        if len(rows) != len(raw):
            raise ValueError('Duplicate review IDs in graded.csv')
    else:
        return {}
    clean = {}
    for review_id, row in rows.items():
        clean[review_id] = {}
        for metric in GRADES:
            if row.get(metric) in ('', None):
                continue
            value = float(row[metric])
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f'Invalid {metric} grade for {review_id}')
            clean[review_id][metric] = value
    return clean


def load_sources(run_dirs=(), traces=()):
    """Resolve typed source data without replacing missing historical settings."""
    groups = []
    seen = set()
    for value in run_dirs:
        directory = Path(value).resolve()
        if directory in seen:
            raise ValueError(f'Duplicate experiment source: {directory}')
        seen.add(directory)
        manifest = json.loads((directory / 'manifest.json').read_text())
        records = [json.loads(line) for line in (directory / 'runs.jsonl').read_text().splitlines() if line.strip()]
        grades = _read_grades(directory)
        for variant in manifest['variants']:
            selected = [r for r in records if r['variant'] == variant]
            if not selected:
                continue
            key = hashlib.sha256(f'{directory}:{variant}'.encode()).hexdigest()[:16]
            effective = effective_params(manifest['config'], manifest['pipeline'], manifest['variants'][variant])
            overrides = {'config.supervisor.decompose': manifest['variants'][variant],
                         'config.self_check.llm_check': effective['effective.self_check.llm_check'] == 'true',
                         'config.self_check.max_retries': int(effective['effective.self_check.max_retries'])}
            requested = _flatten(manifest['config'])
            applied = {**requested, **overrides}
            for name, item in {'pipeline': manifest['pipeline'], 'query_date': manifest['today'],
                               'setup_id': effective['setup_id'], 'question_set_sha256': manifest['question_set_sha256'],
                               'git_commit': manifest.get('environment', {}).get('git_commit', 'unknown')}.items():
                applied['runtime.' + name] = item
            applied.update(_flatten(manifest.get('environment', {}), 'environment'))
            applied.update(_flatten(manifest.get('fingerprints', {}), 'source_sha256'))
            groups.append({'key': key, 'label': directory.name, 'variant': variant, 'source': str(directory),
                           'snapshot': 'Saved manifest', 'requested': requested, 'applied': applied,
                           'records': selected, 'grades': grades})
    for value in traces:
        path = Path(value).resolve()
        if path in seen:
            raise ValueError(f'Duplicate trace source: {path}')
        seen.add(path)
        bundle = json.loads(path.read_text())
        variant = bundle.get('variant', 'Historical trace')
        requested = {k: None for k in ('config.llm.model', 'config.llm.temperature', 'config.llm.seed',
            'config.llm.max_output_tokens', 'config.llm.pricing.input_per_1m',
            'config.llm.pricing.output_per_1m', 'config.agents.policy_top_k',
            'config.self_check.max_retries')}
        applied = {**requested, 'observed.decompose': bundle.get('decompose'),
                   'observed.route': bundle.get('routing', {}).get('route'),
                   'observed.price_approach': (bundle.get('price_result') or {}).get('approach'),
                   'observed.retry_cycles': bundle.get('attempts'), 'observed.query_date': bundle.get('today')}
        usage = bundle.get('usage', [])
        record = {'question_id': path.stem, 'question': bundle.get('question', ''), 'variant': variant,
                  'repeat': 1, 'bundle': bundle, 'seconds': bundle.get('seconds'),
                  'cost_usd': bundle.get('cost_usd'), 'compute': {}, 'error': None,
                  'usage_incomplete': not usage or bool(bundle.get('agent_errors')) or any(
                      u.get('input_tokens') is None or u.get('output_tokens') is None for u in usage)}
        groups.append({'key': hashlib.sha256(str(path).encode()).hexdigest()[:16],
                       'label': path.stem, 'variant': variant, 'source': str(path),
                       'snapshot': 'Partial historical trace', 'requested': requested,
                       'applied': applied, 'records': [record], 'grades': {}})
    if not groups:
        raise ValueError('Provide at least one saved experiment directory or --trace JSON')
    return groups


def export_workbook(run_dirs, output, *, traces=(), _sheet_order=None):
    writer = require_writer()
    groups = load_sources(run_dirs, traces)
    output = Path(output).resolve()
    if output.suffix.lower() != '.xlsx':
        raise ValueError('Excel output must use the .xlsx extension')
    output.parent.mkdir(parents=True, exist_ok=True)
    book = writer.Workbook(str(output), {'strings_to_formulas': False, 'strings_to_urls': False})
    book.set_properties({'title': 'AskGov experiment comparison', 'author': 'Edward',
                         'comments': 'Exported from saved results; no model inference performed.'})
    book.set_calc_mode('auto')
    book.formats[0].set_font_name('Arial')
    sheets = {name: book.add_worksheet(name) for name in (_sheet_order or ('Comparison', 'Parameters', 'Calls'))}
    fmt = {
        'title': book.add_format({'bold': True, 'font_size': 18, 'font_color': '#FFFFFF', 'bg_color': '#18334D', 'valign': 'vcenter'}),
        'note': book.add_format({'font_color': '#526479', 'font_size': 10, 'text_wrap': True, 'valign': 'vcenter'}),
        'header': book.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#254D70', 'text_wrap': True, 'valign': 'vcenter'}),
        'text': book.add_format({'font_size': 10, 'valign': 'top'}),
        'wrap': book.add_format({'font_size': 10, 'text_wrap': True, 'valign': 'top'}),
        'num': book.add_format({'font_size': 10, 'num_format': '#,##0', 'valign': 'top'}),
        'decimal': book.add_format({'font_size': 10, 'num_format': '0.00', 'valign': 'top'}),
        'usd': book.add_format({'font_size': 10, 'num_format': '$0.000000', 'valign': 'top'}),
        'total': book.add_format({'bold': True, 'bg_color': '#DCEAF5', 'num_format': '#,##0', 'top': 1, 'top_color': '#A9BFD0'}),
        'total_usd': book.add_format({'bold': True, 'bg_color': '#DCEAF5', 'num_format': '$0.000000', 'top': 1, 'top_color': '#A9BFD0'}),
        'warn': book.add_format({'bg_color': '#FFF0CE', 'font_color': '#775214'}),
    }
    for style in fmt.values():
        style.set_font_name('Arial')
    timestamp = datetime.now(ZoneInfo('Asia/Singapore')).strftime('%Y-%m-%d %H:%M SGT')

    def header(sheet, title, columns, note):
        end = len(columns) - 1
        sheet.hide_gridlines(2)
        sheet.set_default_row(25)
        sheet.merge_range(0, 0, 0, end, title, fmt['title'])
        sheet.set_row(0, 34)
        sheet.merge_range(1, 0, 1, end, f'AskGov SG • saved-result export • {timestamp}', fmt['note'])
        sheet.merge_range(2, 0, 3, end, note, fmt['note'])
        sheet.set_row(2, 23)
        sheet.set_row(3, 23)
        sheet.set_row(4, 9)
        sheet.write_row(5, 0, columns, fmt['header'])
        sheet.set_row(5, 42)
        sheet.freeze_panes(6, 2)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(0, 5)

    params = sheets['Parameters']
    header(params, 'PARAMETERS • requested and applied',
           ['Experiment', 'Variant', 'Parameter', 'Requested', 'Applied / recorded', 'Notes', 'Setup key'],
           'These are saved snapshots, not live configuration controls. Blank historical settings were not recorded; changing this workbook does not change config.yaml.')
    params.set_column('A:A', 27, fmt['wrap']); params.set_column('B:B', 21, fmt['wrap'])
    params.set_column('C:C', 47, fmt['wrap']); params.set_column('D:E', 34, fmt['wrap'])
    params.set_column('F:F', 48, fmt['wrap']); params.set_column('G:G', 20, fmt['text'], {'hidden': True})
    param_rows = {}
    row = 6
    for group in groups:
        for name in sorted(set(group['requested']) | set(group['applied'])):
            requested, applied = group['requested'].get(name), group['applied'].get(name)
            partial = group['snapshot'].startswith('Partial')
            note = ('Not recorded in the historical trace' if partial and applied is None else
                    'Observed in the saved trace' if partial else
                    'Runtime override / provenance' if name.startswith('runtime.') or requested != applied else 'Saved config snapshot')
            if not partial:
                requested = '(unset / default)' if name in group['requested'] and requested is None else requested
                applied = '(unset / default)' if name in group['applied'] and applied is None else applied
            params.write_row(row, 0, [group['label'], group['variant'], name, requested, applied, note, group['key']], fmt['wrap'])
            if _number(requested): params.write_number(row, 3, requested, fmt['decimal'])
            if _number(applied): params.write_number(row, 4, applied, fmt['decimal'])
            params.set_row(row, min(240, max(30, 14 * max(
                math.ceil(len(str(value or '')) / width) for value, width in
                ((group['label'],27),(group['variant'],21),(name,47),(requested,34),(applied,34),(note,48))))))
            param_rows[(group['key'], name)] = row + 1
            row += 1
    params.autofilter(5, 0, row - 1, 6)

    calls = sheets['Calls']
    columns = ['Setup key', 'Question ID', 'Repeat', 'Stage', 'Task ID', 'Attempt', 'Model calls',
               'Input tokens', 'Output tokens', 'Total tokens', 'Calculated stage USD', 'Run start',
               'Recorded run USD', 'Wall seconds', 'CPU seconds', 'Peak RSS MB', 'Incomplete usage',
               'Correctness score', 'Completeness score', 'Groundedness score', 'Abstention score',
               'Outcome', 'Original question', 'Final answer', 'Source', 'Notes']
    header(calls, 'CALLS • stages, retries and question results', columns,
           'One row per reported usage entry; an entry can aggregate multiple calls. Run totals, compute, grades, question and answer appear only on the first row of each run. Stage USD uses saved pricing; Unknown means no measurement.')
    calls.set_column('A:B', 22, fmt['wrap']); calls.set_column('C:C', 9, fmt['num'])
    calls.set_column('D:E', 21, fmt['wrap']); calls.set_column('F:J', 13, fmt['num'])
    calls.set_column('K:K', 17, fmt['usd']); calls.set_column('L:L', 10, fmt['num'], {'hidden': True})
    calls.set_column('M:M', 18, fmt['usd']); calls.set_column('N:U', 15, fmt['decimal'])
    calls.set_column('V:V', 22, fmt['wrap']); calls.set_column('W:X', 65, fmt['wrap'])
    calls.set_column('Y:Z', 48, fmt['wrap'])
    row = 6
    for group in groups:
        for record in group['records']:
            bundle = record.get('bundle', {})
            usage = bundle.get('usage', record.get('partial_usage', [])) or [{}]
            grade = group['grades'].get(record.get('review_id'), {})
            stage_counts = {}
            outcome = ('Failed' if record.get('error') else 'Completed with errors' if bundle.get('agent_errors') else
                       'Weak review' if bundle.get('self_check', {}).get('verdict') == 'weak' else 'Completed')
            for index, entry in enumerate(usage):
                first = index == 0
                stage = entry.get('step', 'No reported usage')
                stage_counts[stage] = stage_counts.get(stage, 0) + 1
                values = [group['key'], record.get('question_id', ''), record.get('repeat', 1), stage,
                          entry.get('task_id'), entry.get('attempt', stage_counts[stage]),
                          entry.get('calls', 1) if entry else None, entry.get('input_tokens'), entry.get('output_tokens'), None, None,
                          int(first), record.get('cost_usd') if first else None,
                          record.get('seconds') if first else None,
                          record.get('compute', {}).get('local_cpu_seconds') if first else None,
                          record.get('compute', {}).get('local_rss_peak_mb') if first else None,
                          int(record.get('usage_incomplete', True)) if first else None,
                          *[grade.get(metric) if first else None for metric in GRADES],
                          outcome if first else None, record.get('question', bundle.get('question')) if first else None,
                          record.get('answer', bundle.get('answer', {}).get('answer')) if first else None,
                          group['source'], record.get('error') or ('Original parameter snapshot/compute/grades unavailable' if group['snapshot'].startswith('Partial') else '') if first else None]
                calls.write_row(row, 0, values, fmt['text'])
                for col in range(6, 21):
                    if _number(values[col]): calls.write_number(row, col, values[col], fmt['usd'] if col in (10, 12) else fmt['num'] if col in (6, 7, 8, 11, 16) else fmt['decimal'])
                rr = row + 1
                tokens = sum(entry.get(k) or 0 for k in ('input_tokens', 'output_tokens')) if any(entry.get(k) is not None for k in ('input_tokens','output_tokens')) else 'Unknown'
                calls.write_formula(row, 9, f'=IF(COUNT(H{rr}:I{rr})=0,"Unknown",SUM(H{rr}:I{rr}))', fmt['num'], tokens)
                in_row = param_rows.get((group['key'], 'config.llm.pricing.input_per_1m'))
                out_row = param_rows.get((group['key'], 'config.llm.pricing.output_per_1m'))
                in_rate = group['applied'].get('config.llm.pricing.input_per_1m')
                out_rate = group['applied'].get('config.llm.pricing.output_per_1m')
                if in_row and out_row:
                    formula = f'=IF(AND(ISNUMBER(H{rr}),ISNUMBER(I{rr}),ISNUMBER(\'Parameters\'!$E${in_row}),ISNUMBER(\'Parameters\'!$E${out_row})),ROUND((H{rr}*\'Parameters\'!$E${in_row}+I{rr}*\'Parameters\'!$E${out_row})/1000000,6),"Unknown")'
                    cached = round(((entry.get('input_tokens') or 0)*in_rate + (entry.get('output_tokens') or 0)*out_rate)/1e6, 6) if all(_number(v) for v in (in_rate,out_rate,entry.get('input_tokens'),entry.get('output_tokens'))) else 'Unknown'
                    calls.write_formula(row, 10, formula, fmt['usd'], cached)
                calls.set_row(row, min(409, max(40, 14 * max(
                    sum(max(1,math.ceil(len(line)/width)) for line in str(values[col] or '').split('\n'))
                    for col,width in ((1,22),(22,65),(23,65),(24,48),(25,48))))))
                # Narratives are wrapped; run-level fields appear once, not on every stage.
                for col in (22, 23, 24, 25):
                    if values[col] is not None: calls.write(row, col, values[col], fmt['wrap'])
                row += 1
    calls.autofilter(5, 0, row - 1, 25)
    end = row

    comparison = sheets['Comparison']
    headers = ['Experiment', 'Variant', 'Runs', 'Correctness score', 'Completeness score', 'Recorded API USD',
               'Mean API USD', 'Mean wall s', 'Mean CPU s', 'Mean peak MB', 'Model calls', 'Tokens',
               'Incomplete runs', 'Groundedness score', 'Abstention score', 'Parameter snapshot', 'Review state', 'Setup key']
    header(comparison, 'EXPERIMENT COMPARISON • quality and cost', headers,
           'Scores range from 0 to 1; Pending means not all runs are graded, and Unknown means no measurement. Costs are configured-rate estimates. CPU/RSS describe the local Python process, not provider hardware. Historical traces may have partial settings.')
    comparison.set_column('A:A', 31, fmt['wrap']); comparison.set_column('B:B', 22, fmt['wrap'])
    comparison.set_column('C:C', 9, fmt['num']); comparison.set_column('D:E', 15, fmt['decimal'])
    comparison.set_column('F:G', 18, fmt['usd']); comparison.set_column('H:J', 15, fmt['decimal'])
    comparison.set_column('K:M', 14, fmt['num']); comparison.set_column('N:O', 16, fmt['decimal'])
    comparison.set_column('P:Q', 28, fmt['wrap']); comparison.set_column('R:R', 20, fmt['text'], {'hidden': True})
    for index, group in enumerate(groups, 6):
        records = group['records']
        rr = index + 1
        key_ref = f'$R{rr}'
        key_range = f"'Calls'!$A$7:$A${end}"
        start_range = f"'Calls'!$L$7:$L${end}"
        comparison.write_row(index, 0, [group['label'], group['variant']], fmt['wrap'])
        comparison.write(index, 15, group['snapshot'], fmt['wrap'])
        comparison.write(index, 16, 'Weak review present' if any(r.get('bundle', {}).get('self_check', {}).get('verdict') == 'weak' for r in records) else 'See Calls', fmt['wrap'])
        comparison.write(index, 17, group['key'], fmt['text'])
        comparison.write_formula(index, 2, f'=COUNTIFS({key_range},{key_ref},{start_range},1)', fmt['num'], len(records))
        def average(col, source_col, values):
            ref = f"'Calls'!${source_col}$7:${source_col}${end}"
            cached_values = [v for v in values if _number(v)]
            cached = sum(cached_values)/len(cached_values) if cached_values else 'Unknown'
            average_formula = f'IFERROR(AVERAGEIFS({ref},{key_range},{key_ref},{start_range},1),"Unknown")'
            if col in (3,4,13,14):
                cached = cached if len(cached_values) == len(records) else 'Pending'
                average_formula = f'IF(SUMPRODUCT(({key_range}={key_ref})*({start_range}=1)*ISNUMBER({ref}))=C{rr},{average_formula},"Pending")'
            comparison.write_formula(index, col, '=' + average_formula, fmt['usd'] if col == 6 else fmt['decimal'], cached)
        for col, source_col, metric in ((3,'R','correctness'),(4,'S','completeness'),(13,'T','groundedness'),(14,'U','appropriate_abstention')):
            average(col, source_col, [group['grades'].get(r.get('review_id'), {}).get(metric) for r in records])
        average(6,'M',[r.get('cost_usd') for r in records]); average(7,'N',[r.get('seconds') for r in records])
        average(8,'O',[r.get('compute',{}).get('local_cpu_seconds') for r in records])
        average(9,'P',[r.get('compute',{}).get('local_rss_peak_mb') for r in records])
        costs=[r['cost_usd'] for r in records if _number(r.get('cost_usd'))]
        comparison.write_formula(index,5,f'=IF(SUMPRODUCT(({key_range}={key_ref})*({start_range}=1)*ISNUMBER(\'Calls\'!$M$7:$M${end}))=0,"Unknown",SUMIF({key_range},{key_ref},\'Calls\'!$M$7:$M${end}))',fmt['usd'],sum(costs) if costs else 'Unknown')
        for col, source_col, cached in (
            (10,'G',sum(u.get('calls',1) for r in records for u in r.get('bundle',{}).get('usage',r.get('partial_usage',[])))),
            (11,'J',sum((u.get('input_tokens') or 0)+(u.get('output_tokens') or 0) for r in records for u in r.get('bundle',{}).get('usage',r.get('partial_usage',[])))),
            (12,'Q',sum(bool(r.get('usage_incomplete',True)) for r in records))):
            if col in (10, 11):
                ref = f"'Calls'!${source_col}$7:${source_col}${end}"
                observed = any((entry if col == 10 else any(entry.get(k) is not None for k in ('input_tokens','output_tokens')))
                    for record in records for entry in record.get('bundle',{}).get('usage',record.get('partial_usage',[])))
                formula = f'=IF(SUMPRODUCT(({key_range}={key_ref})*ISNUMBER({ref}))=0,"Unknown",SUMIF({key_range},{key_ref},{ref}))'
                comparison.write_formula(index,col,formula,fmt['num'],cached if observed else 'Unknown')
            else:
                comparison.write_formula(index,col,f'=SUMIF({key_range},{key_ref},\'Calls\'!${source_col}$7:${source_col}${end})',fmt['num'],cached)
        comparison.set_row(index, 48)
    last = 6 + len(groups)
    comparison.autofilter(5, 0, last - 1, 17)
    comparison.conditional_format(6,12,last-1,12,{'type':'cell','criteria':'>','value':0,'format':fmt['warn']})
    comparison.conditional_format(6,15,last-1,15,{'type':'text','criteria':'containing','value':'Partial','format':fmt['warn']})
    total_row = last + 1
    comparison.write(total_row,0,'ALL INCLUDED RUNS',fmt['total'])
    all_records = [record for group in groups for record in group['records']]
    all_usage = [entry for record in all_records
                 for entry in record.get('bundle',{}).get('usage',record.get('partial_usage',[]))]
    known_costs = [record['cost_usd'] for record in all_records if _number(record.get('cost_usd'))]
    totals = {2: len(all_records), 5: sum(known_costs) if known_costs else 'Unknown',
              10: sum(entry.get('calls',1) for entry in all_usage) if all_usage else 'Unknown',
              11: sum((entry.get('input_tokens') or 0)+(entry.get('output_tokens') or 0) for entry in all_usage) if any(entry.get(k) is not None for entry in all_usage for k in ('input_tokens','output_tokens')) else 'Unknown',
              12: sum(bool(record.get('usage_incomplete',True)) for record in all_records)}
    for col, cached in totals.items():
        letter=chr(65+col)
        formula = f'=SUM({letter}7:{letter}{last})'
        if col in (5,10,11):
            formula = f'=IF(COUNT({letter}7:{letter}{last})=0,"Unknown",SUM({letter}7:{letter}{last}))'
        comparison.write_formula(total_row,col,formula,fmt['total_usd'] if col==5 else fmt['total'],cached)
    comparison.activate()
    book.close()
    return output
