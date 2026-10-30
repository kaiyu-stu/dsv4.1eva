"""Validate public benchmark tables independently of the private experiment files."""
from collections import defaultdict
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ('input_tokens','cache_read_input_tokens','cache_creation_input_tokens','output_tokens')


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def validate(base):
    samples, requests, attempts = [read(base / f'{name}.jsonl') for name in ('samples','requests','attempts')]
    summary = json.loads((base / 'summary.json').read_text())
    pricing = json.loads((base / 'pricing.json').read_text())
    assert len(samples)==445 and len({(r['task_id'],r['harness']) for r in samples})==445
    assert len({r['task_id'] for r in samples})==89
    assert sum(r['success'] is not None for r in samples)==444
    unscored = [r for r in samples if r['success'] is None]
    assert len(unscored)==1 and unscored[0]['harness']=='pi' and unscored[0]['task_id']=='compile-compcert'
    assert unscored[0]['termination_reason']=='agent_sigkill'
    assert len({(r['harness'],r['request_id']) for r in requests})==len(requests)
    groups, attempt_groups = defaultdict(list), defaultdict(list)
    for r in requests:
        groups[r['harness'],r['task_id']].append(r)
        attempt_groups[r['harness'],r['task_id'],r['attempt_id']].append(r)
        assert r['model']=='deepseek-v4.1-flash-economy' and r['temperature']==0
        assert r['accounting_complete']==bool(r['start_record_present'] and r['finish_record_present']
            and r['response_complete'] and r['usage_present'])
        if r['total_tokens'] is not None:
            assert r['total_tokens']==sum(r[k] or 0 for k in TOKENS)
        period = r['tariff_using_start_time']
        expected = sum(Decimal(str(rate))*(r[k] or 0) for k,rate in pricing[period].items())/Decimal(1_000_000)
        assert abs(float(expected)-r['payg_known_start_time_estimate_cny'])<1e-10
        assert abs(2*r['payg_known_all_offpeak_cny']-r['payg_known_all_peak_cny'])<1e-10
    for r in samples:
        g=groups[r['harness'],r['task_id']]
        for field in TOKENS:
            assert r[field]==sum(q[field] or 0 for q in g)
        assert r['token']==r['total_tokens']==sum(r[k] for k in TOKENS)
        assert r['token']==r['final_attempt_token']+r['prior_attempt_tokens']
        assert r['accounting_complete']==(bool(g) and all(q['accounting_complete'] for q in g))
        assert r['actual_billed_usd'] is None
        assert r['compression_threshold_tokens'] is None and r['compression_policy']=='native_defaults'
        assert r['router_eligible_label']==(r['success'] is not None)
        assert r['router_eligible_complete_tokens']==(r['success'] is not None and r['accounting_complete'])
        if r['success'] is None:assert r['label']=='unscored'
        else:
            assert r['success'] in (0,1) and r['score']==r['success']
            assert r['label']==('correct' if r['success'] else 'incorrect')
        for key in ('payg_known_start_time_estimate_cny','payg_known_all_offpeak_cny','payg_known_all_peak_cny'):
            assert abs(r[key]-sum(q[key] for q in g))<1e-8
            assert abs(r[key.replace('_cny','_usd')]-r[key]/float(pricing['fx']['cny_per_usd']))<1e-8
    finals={}
    for a in attempts:
        g=attempt_groups[a['harness'],a['task_id'],a['attempt_id']]
        assert a['total_tokens']==sum(q['total_tokens'] or 0 for q in g)
        if a['is_final_attempt']:
            assert (a['harness'],a['task_id']) not in finals
            finals[a['harness'],a['task_id']]=a
    assert len(finals)==445
    assert sum(a['total_tokens'] for a in attempts)==sum(r['token'] for r in samples)
    for s in summary:
        rows=[r for r in samples if r['harness']==s['harness']]
        scored=[r for r in rows if r['success'] is not None]
        assert len(rows)==89
        assert len(scored)==s['scored_samples'] and sum(r['success'] for r in scored)==s['correct']
        assert sum(r['token'] for r in rows)==s['total_tokens']
        assert sum(r['accounting_complete'] for r in rows)==s['samples_with_complete_tokens']
    analysis=json.loads((base / 'analysis.json').read_text())
    common={r['task_id'] for r in samples if r['in_common_scored_subset']}
    full={r['task_id'] for r in samples if r['in_common_complete_token_subset']}
    assert len(common)==88 and len(full)==55
    assert common==set(analysis['common_scored_tasks']) and full==set(analysis['common_complete_token_tasks'])
    for task in full:
        assert all(r['success'] is not None and r['accounting_complete'] for r in samples if r['task_id']==task)
    for name, data in [('samples',samples),('requests',requests),('attempts',attempts)]:
        with (base / f'{name}.csv').open() as f:
            rows=list(csv.DictReader(f))
        assert len(rows)==len(data)
        for c,j in zip(rows,data):
            for key,value in j.items():
                expected=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list)) else '' if value is None else str(value)
                assert c[key]==expected
    with (base / 'task-matrix.csv').open() as f:
        matrix=list(csv.DictReader(f))
    sample_map={(r['task_id'],r['harness']):r for r in samples}
    for r in matrix:
        for h in ('claude','codex','dsh','pi','zcode'):
            v=sample_map[r['task_id'],h]
            assert r[f'{h}_success']==('' if v['success'] is None else str(v['success']))
            assert int(r[f'{h}_token'])==v['token']
    source=json.loads((base / 'provenance/source-files.json').read_text())
    assert all(not Path(p).is_absolute() for p in source)
    for line in (base / 'SHA256SUMS').read_text().splitlines():
        expected,relative=line.split('  ',1)
        assert hashlib.sha256((base/relative).read_bytes()).hexdigest()==expected,relative
    print(f'PASS {base.relative_to(ROOT)}: {len(samples)} rows, {len(requests)} requests, '
          f'{len(attempts)} attempts, 444 labels, 88 shared scored / 55 shared complete tasks')


if __name__=='__main__':
    for record in json.loads((ROOT/'benchmarks/index.json').read_text()):
        if record['benchmark']=='terminal-bench-2.0':
            validate(ROOT/'benchmarks'/record['relative_path'])
        elif record['benchmark']=='tau2-bench':
            from validate_tau2 import validate as validate_tau2
            validate_tau2(ROOT/'benchmarks'/record['relative_path'])
        elif record['benchmark']=='mrcr':
            from validate_mrcr import validate as validate_mrcr
            validate_mrcr(ROOT/'benchmarks'/record['relative_path'])
