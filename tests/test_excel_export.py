"""Check actual XLSX cells/formulas/styles with zip/XML; no model calls."""

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

pytest.importorskip('xlsxwriter')

from agents.supervisor.excel_export import export_workbook, load_sources

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def cells(path, sheet=1):
    with ZipFile(path) as archive:
        strings = [''.join(node.itertext()) for node in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('x:si', NS)]
        root = ET.fromstring(archive.read(f'xl/worksheets/sheet{sheet}.xml'))
    result = {}
    for cell in root.findall('.//x:c', NS):
        value = cell.findtext('x:v', namespaces=NS)
        if cell.get('t') == 's': value = strings[int(value)]
        elif cell.get('t') == 'b': value = value == '1'
        result[cell.get('r')] = {'value': value, 'formula': cell.findtext('x:f', namespaces=NS), 'type': cell.get('t')}
    return result, root


@pytest.fixture
def experiment(tmp_path):
    directory = tmp_path / 'experiment'
    directory.mkdir()
    config = {'llm': {'model':'fixture-model','temperature':0.2,'seed':42,
                      'pricing':{'input_per_1m':2.5,'output_per_1m':15},'api_key':'never export me'},
              'supervisor':{'decompose':True}, 'self_check':{'llm_check':True,'max_retries':1},
              'agents':{'policy_top_k':5}}
    manifest = {'variants':{'A_baseline':False,'B_decomposition':True}, 'pipeline':'graph',
                'today':'2026-10-29','question_set_sha256':'fixture','config':config}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    records=[]
    for index, variant in enumerate(manifest['variants'], 1):
        records.append({'question_id':'Q1','question':'=1+1 is literal user text','variant':variant,'repeat':1,
            'review_id':str(index),'seconds':index,'cost_usd':0.0004*index,'usage_incomplete':False,
            'compute':{'local_cpu_seconds':0.1*index,'local_rss_peak_mb':100*index},
            'bundle':{'usage':[{'step':'router','input_tokens':100*index,'output_tokens':10*index}],
                      'answer':{'answer':'Fixture answer'},'agent_errors':{}}})
    (directory / 'runs.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
    return directory


def test_three_sheets_cached_totals_and_pending_scores(experiment, tmp_path):
    path=export_workbook([experiment],tmp_path/'report.xlsx')
    with ZipFile(path) as archive:
        root=ET.fromstring(archive.read('xl/workbook.xml'))
        assert [s.get('name') for s in root.findall('x:sheets/x:sheet',NS)]==['Comparison','Parameters','Calls']
        assert 'never export me' not in archive.read('xl/sharedStrings.xml').decode()
    values, root=cells(path)
    assert float(values['F7']['value'])==0.0004
    assert float(values['F8']['value'])==0.0008
    assert float(values['F10']['value'])==pytest.approx(0.0012)
    assert values['D7']['value']=='Pending'
    assert values['D7']['formula'].startswith('IF(SUMPRODUCT')
    assert root.find('x:sheetViews/x:sheetView/x:pane',NS).get('ySplit')=='6'
    assert root.find('x:autoFilter',NS) is not None
    call_values,_=cells(path,3)
    assert call_values['W7']['value']=='=1+1 is literal user text'
    assert call_values['W7']['formula'] is None
    assert float(call_values['K7']['value'])==0.0004
    assert "'Parameters'!" in call_values['K7']['formula']


def test_full_parameter_snapshot_includes_applied_override(experiment,tmp_path):
    path=export_workbook([experiment],tmp_path/'parameters.xlsx')
    values,_=cells(path,2)
    rows=[]
    for address, item in values.items():
        if address.startswith('C') and item['value']=='config.supervisor.decompose':
            row=address[1:]
            rows.append((values['D'+row]['value'], values['E'+row]['value']))
    assert rows==[(True,False),(True,True)]
    assert any(c['value']=='config.llm.temperature' for c in values.values())


def test_reviewed_grades_populate_quality_formula_caches(experiment,tmp_path):
    (experiment/'reviewed_grades.json').write_text(json.dumps({'1':{'correctness':1,'completeness':0.5},
                                                           '2':{'correctness':0.5,'completeness':1}}))
    path=export_workbook([experiment],tmp_path/'graded.xlsx')
    values,_=cells(path)
    assert float(values['D7']['value'])==1
    assert float(values['E7']['value'])==0.5
    assert values['N7']['value']=='Pending'


def test_historical_trace_does_not_invent_model_or_compute(tmp_path):
    trace=tmp_path/'trace.json'
    trace.write_text(json.dumps({'question':'Recorded question','decompose':True,'variant':'B_decomposition',
        'routing':{'route':'both'},'usage':[{'step':'router','input_tokens':10,'output_tokens':2}],
        'cost_usd':0.000055,'seconds':2,'answer':{'answer':'Recorded answer'}}))
    path=export_workbook([],tmp_path/'historical.xlsx',traces=[trace])
    values,_=cells(path)
    assert values['I7']['value']==values['J7']['value']=='Unknown'
    assert values['P7']['value']=='Partial historical trace'
    assert float(values['F7']['value'])==0.000055
    params,_=cells(path,2)
    row=next(k[1:] for k,v in params.items() if k.startswith('C') and v['value']=='config.llm.model')
    assert params.get('E'+row,{}).get('value') in (None,'')


def test_duplicate_sources_are_rejected(experiment):
    with pytest.raises(ValueError,match='Duplicate'):
        load_sources([experiment,experiment])


def test_export_uses_only_saved_parameters_not_current_config(experiment,tmp_path):
    path=export_workbook([experiment],tmp_path/'snapshot.xlsx')
    values,_=cells(path,2)
    assert any(v['value']=='fixture-model' for v in values.values())
    assert not any(v['value']=='gpt-5.4-2026-03-05' for v in values.values())
