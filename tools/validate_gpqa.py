"""Validate published GPQA scores, per-request accounting and recovery flags."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1'
FIELDS = ['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']


def read(name):
    rows = [json.loads(line) for line in (BASE/(name+'.jsonl')).read_text().splitlines()]
    with (BASE/(name+'.csv')).open() as f:
        csv_rows = list(csv.DictReader(f))
    assert len(rows) == len(csv_rows)
    for r,c in zip(rows,csv_rows):
        assert c == {k:('' if v is None else str(v)) for k,v in r.items()}
    return rows


def main():
    samples,requests,matrix,pairs = [read(n) for n in ['samples','requests','task-matrix','pairwise']]
    assert len(samples) == 990 and len(matrix) == 198 and len(pairs) == 10
    assert len({(r['harness'],r['task_id']) for r in samples}) == 990
    assert len({(r['harness'],r['request_id']) for r in requests}) == len(requests)
    grouped = defaultdict(list)
    for q in requests:
        assert q['http_status'] == 200 and q['usage_present'] and q['tools_forwarded'] == 0
        assert q['total_tokens'] == q['prompt_tokens'] + q['completion_tokens']
        assert q['prompt_tokens'] == q['prompt_cache_hit_tokens'] + q['prompt_cache_miss_tokens']
        grouped[q['harness'],q['task_id']].append(q)
    for r in samples:
        group = grouped[r['harness'],r['task_id']]
        assert r['model_requests'] == len(group)
        assert r['score'] == r['success'] and r['score'] in (0,1)
        assert r['label'] == ('correct' if r['score'] else 'incorrect')
        assert r['recovered_from_recorded_text'] == (r['native_checkpoint_status'] == 'error')
        assert r['repeat'] == 1 and r['compression_calls'] == 0
        for key in FIELDS:
            assert r[key] == sum(q[key] for q in group)
        assert r['token'] == r['total_tokens']
    summary = json.loads((BASE/'summary.json').read_text())
    for s in summary:
        rows = [r for r in samples if r['harness'] == s['harness']]
        assert len(rows) == s['scored_samples'] == 198
        assert sorted(r['source_row'] for r in rows) == list(range(198))
        assert sum(r['score'] for r in rows) == s['correct']
        assert s['accuracy'] == s['correct']/198
        assert dict(Counter(r['native_checkpoint_status'] for r in rows)) == s['native_checkpoint_statuses']
        assert sum(r['recovered_from_recorded_text'] for r in rows) == s['recovered_from_recorded_text']
        for key in FIELDS:
            assert sum(r[key] for r in rows) == s[key]
    lookup = {(r['harness'],r['task_id']):r for r in samples}
    for m in matrix:
        for h in ['claude','codex','dsh','pi','zcode']:
            r = lookup[h,m['task_id']]
            assert (m[h+'_success'],m[h+'_token'],m[h+'_recovered']) == (r['success'],r['token'],r['recovered_from_recorded_text'])
    for p in pairs:
        a,b = p['harness_a'],p['harness_b']
        matched = [(lookup[a,m['task_id']],lookup[b,m['task_id']]) for m in matrix]
        assert p['both_correct'] == sum(x['score'] == y['score'] == 1 for x,y in matched)
        assert p['both_wrong'] == sum(x['score'] == y['score'] == 0 for x,y in matched)
        assert p['only_a_correct'] == sum(x['score'] == 1 and y['score'] == 0 for x,y in matched)
        assert p['only_b_correct'] == sum(x['score'] == 0 and y['score'] == 1 for x,y in matched)
        assert sum(p[k] for k in ['both_correct','both_wrong','only_a_correct','only_b_correct']) == 198
    for line in (BASE/'SHA256SUMS').read_text().splitlines():
        expected,filename = line.split('  ',1)
        assert hashlib.sha256((BASE/filename).read_bytes()).hexdigest() == expected
    print(f'PASS GPQA: {len(samples)} scores, {len(requests)} accounted requests, 196 explicitly recovered labels, {sum(q["total_tokens"] for q in requests):,} tokens.')


if __name__ == '__main__':
    main()
