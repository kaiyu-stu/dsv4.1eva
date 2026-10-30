"""Validate MRCR scores, per-request usage, sampling and published file hashes."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics


def validate(base):
    samples,requests=[[json.loads(line) for line in (base/f'{name}.jsonl').read_text().splitlines()]
                      for name in ('samples','requests')]
    summary=json.loads((base/'summary.json').read_text())
    manifest=json.loads((base/'subset-manifest.json').read_text())
    config=json.loads((base/'experiment.json').read_text())
    assert len(samples)==200 and len({r['task_id'] for r in samples})==200
    assert [r['task_id'] for r in samples]==manifest['sample_ids']==config['selection']
    assert manifest['sample_size']==200 and manifest['eligible_population_size']==2368
    assert len(requests)==201 and len({r['request_id'] for r in requests})==201
    assert sum(not r['usage_present'] for r in requests)==summary['usage_missing_requests']==1
    assert Counter(r['status'] for r in requests)=={'completed':200,'error':1}
    assert sum(r['success'] for r in samples)==summary['exact_correct']==80
    assert Counter(r['score_category'] for r in samples)=={'full':80,'partial':102,'zero':18}
    assert abs(statistics.mean(r['score'] for r in samples)-summary['mean_score'])<1e-12
    grouped=json.loads((base/'grouped-summary.json').read_text())
    tokens=('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')
    for r in samples:
        requests_for_task=[q for q in requests if q['task_id']==r['task_id']]
        assert r['status']=='completed' and r['success'] in (0,1) and 0<=r['score']<=1
        assert r['success']==int(r['score']==1)
        assert r['label']==('correct' if r['success'] else 'incorrect')
        assert r['token']==r['total_tokens']==r['prompt_tokens']+r['completion_tokens']
        assert r['prompt_tokens']==r['prompt_cache_hit_tokens']+r['prompt_cache_miss_tokens']
        assert r['requests']==len(requests_for_task)
        assert r['accounting_complete']==all(q['usage_present'] for q in requests_for_task)
        assert not r['output_truncated'] and r['compression_calls']==0
        for field in tokens:
            assert r[field]==sum(q[field] or 0 for q in requests_for_task)
    for field in tokens:
        assert sum(r[field] for r in samples)==summary[field]==sum(q[field] or 0 for q in requests)
    for field, groups in grouped.items():
        assert sum(s['samples'] for s in groups.values())==200
        for key,s in groups.items():
            rows=[r for r in samples if (f"{r['needles']}needle/{r['context_bin']}" if field=='stratum' else str(r[field]))==key]
            assert len(rows)==s['samples']
            assert sum(r['total_tokens'] for r in rows)==s['total_tokens']
            assert sum(r['success'] for r in rows)==s['exact_correct']
            assert abs(statistics.mean(r['score'] for r in rows)-s['mean_score'])<1e-12
    counts=Counter(f"{r['needles']}needle/{r['context_bin']}" for r in samples)
    assert dict(counts)==manifest['selected_by_stratum'] and len(counts)==24
    for name,rows in [('samples',samples),('requests',requests)]:
        with (base/f'{name}.csv').open() as f:
            csv_rows=list(csv.DictReader(f))
        assert len(csv_rows)==len(rows)
        for c,r in zip(csv_rows,rows):
            for key,value in r.items():
                assert c[key]==('' if value is None else str(value))
    forbidden={'response','answer','prompt','messages','error','headers','api_key','random_string_to_prepend'}
    assert not any(forbidden & r.keys() for r in samples+requests)
    for line in (base/'SHA256SUMS').read_text().splitlines():
        expected,relative=line.split('  ',1)
        assert hashlib.sha256((base/relative).read_bytes()).hexdigest()==expected,relative
    assert not any(Path(p).is_absolute() for p in json.loads((base/'provenance/source-files.json').read_text()))
    print(f'PASS MRCR: 200 scores, 80 exact matches, 201 requests, {summary["total_tokens"]:,} known tokens')


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    for record in json.loads((root/'benchmarks/index.json').read_text()):
        if record['benchmark']=='mrcr':
            validate(root/'benchmarks'/record['relative_path'])
