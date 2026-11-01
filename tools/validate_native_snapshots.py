"""Validate metadata, score formulas and accounting without private datasets."""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
TOKENS=['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']
HARNESSES=['claude','codex','dsh','pi','zcode']


def read(path):
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()]


def validate(base):
    health=base.parent.name=='healthbench-professional'
    samples=read(base/'samples.jsonl');requests=read(base/'requests.jsonl')
    judges=read(base/'grader-requests.jsonl') if health else []
    summary=json.loads((base/'summary.json').read_text())
    analysis=json.loads((base/'analysis.json').read_text())
    assert len(samples)==1000 and len({(r['harness'],r['task_id']) for r in samples})==1000
    assert len({r['task_id'] for r in samples})==200
    assert len({(r['harness'],r['stage'],r['request_id']) for r in requests})==len(requests)
    groups,jgroups=defaultdict(list),defaultdict(list)
    for q in requests:
        groups[q['harness'],q['task_id']].append(q)
        if q['usage_present']:
            assert q['total_tokens']==q['prompt_tokens']+q['completion_tokens']
            assert q['prompt_tokens']==q['prompt_cache_hit_tokens']+q['prompt_cache_miss_tokens']
        assert q['accounting_complete']==bool(q['start_record_present'] and q['finish_record_present'] and q['usage_present'])
    for q in judges:
        jgroups[q['harness'],q['task_id']].append(q)
        if q['usage_present']:assert q['total_tokens']==q['input_tokens']+q['output_tokens']
    for r in samples:
        g=groups[r['harness'],r['task_id']];jg=jgroups[r['harness'],r['task_id']]
        for k in TOKENS:assert r[k]==sum(q[k] or 0 for q in g)
        assert r['token']==r['total_tokens']==r['prompt_tokens']+r['completion_tokens']
        assert r['grader_total_tokens']==sum(q['total_tokens'] or 0 for q in jg)
        assert r['accounting_complete']==(bool(g) and all(q['accounting_complete'] for q in g))
        if health:
            assert r['success'] is None and not r['binary_label_available']
            if r['status']=='completed':
                expected=r['raw_score']-.0147*((r['response_characters']-2000)/500)
                assert abs(r['score']-expected)<1e-10
            else:assert r['score'] is None and r['raw_score'] is None
            if r['recovered']:
                assert r['answer_source']=='recovered_first_complete_upstream_response'
                assert r['original_generation_status']=='generation_error'
                assert r['recovery_policy']=='first_complete_upstream_response_by_request_start'
        else:
            assert r['status']=='completed' and 0<=r['score']<=1 and r['success'] in [0,1]
            assert r['generation_provider'] in ['codingplan','agentplan3']
            assert r['inherited']==(r['generation_provider']=='codingplan')
    expected=[200,200,157,200,198] if health else [200]*5
    for h,n in zip(HARNESSES,expected):
        rows=[r for r in samples if r['harness']==h];done=[r for r in rows if r['status']=='completed']
        s=next(s for s in summary if s['harness']==h)
        assert len(done)==n==s['scored'] and s['selected']==200 and s['unscored']==200-n
        score=statistics.mean(r['score'] for r in done)
        if health:score=max(0,min(1,score))
        assert abs(s['mean_score']-score)<1e-12
        for k in TOKENS:assert s[k]==sum(r[k] for r in rows)
        if health:assert s['recovered']==sum(r['recovered'] for r in rows)
        else:assert s['exact_correct']==sum(r['success'] for r in rows)
    scored={h:{r['task_id'] for r in samples if r['harness']==h and r['status']=='completed'} for h in HARNESSES}
    common=set.intersection(*scored.values())
    assert common==set(analysis['common_scored_tasks']) and len(common)==analysis['common_scored_count']
    for p in analysis['pairwise']:
        assert p['shared_scored']==len(scored[p['harness_a']]&scored[p['harness_b']])
        assert p['a_higher']+p['b_higher']+p['equal']==p['shared_scored']
        if not health:assert p['both_exact_correct']+p['both_not_exact']+p['exact_match_disagreement']==200
    tables={'samples':samples,'requests':requests,'task-matrix':read(base/'task-matrix.jsonl')}
    if health:tables['grader-requests']=judges
    for name,rows in tables.items():
        with (base/f'{name}.csv').open() as f:csvrows=list(csv.DictReader(f))
        assert len(csvrows)==len(rows)
        for c,j in zip(csvrows,rows):
            for k,v in j.items():assert c[k]==('' if v is None else str(v))
    for line in (base/'SHA256SUMS').read_text().splitlines():
        digest,relative=line.split('  ',1)
        assert hashlib.sha256((base/relative).read_bytes()).hexdigest()==digest
    for f in base.rglob('*.json*'):
        value=json.loads(f.read_text()) if f.suffix=='.json' else read(f)
        def check(obj):
            if isinstance(obj,dict):
                forbidden={'response','content','messages','prompt','answer','physician_response','rubric_items_text','criterion_text','reasoning_content','api_key','authorization'}
                assert not forbidden.intersection(obj)
                for v in obj.values():check(v)
            elif isinstance(obj,list):
                for v in obj:check(v)
        check(value)
    print(f'PASS {base.relative_to(ROOT)}: {len(samples)} rows, {sum(s["scored"] for s in summary)} scores, {len(requests)} model / {len(judges)} grader requests')


if __name__=='__main__':
    for record in json.loads((ROOT/'benchmarks/index.json').read_text()):
        if record.get('track') in ['native_no_tools_reference_grading','native_fullcontext_codingplan_agentplan3_continuation']:
            validate(ROOT/'benchmarks'/record['relative_path'])
