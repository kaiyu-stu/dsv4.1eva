"""Independently reconcile the published tau2 release without private source files."""
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path

TOKENS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
HARNESSES = ('claude', 'codex', 'dsh', 'pi', 'zcode')
ROLES = ('model', 'simulator', 'judge')


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def close(a, b):
    assert abs(a-b) < 1e-8, (a, b)


def usage(row, requests, pricing):
    for role in ROLES:
        selected = [r for r in requests if r['role'] == role]
        prefix = '' if role == 'model' else role+'_'
        for key in TOKENS:
            assert row[prefix+key] == sum(r[key] or 0 for r in selected)
        assert row[prefix+'total_tokens'] == sum(row[prefix+k] for k in TOKENS)
        assert row[prefix+'model_requests'] == len(selected)
        complete = all(r['accounting_complete'] for r in selected) and (bool(selected) or role == 'judge')
        assert row[prefix+'accounting_complete'] == complete
        for field in ('payg_known_start_time_estimate_cny', 'payg_known_all_offpeak_cny', 'payg_known_all_peak_cny'):
            close(row[prefix+field], sum(r[field] for r in selected))
            close(row[prefix+field.replace('_cny', '_usd')], row[prefix+field]/float(pricing['fx']['cny_per_usd']))
    assert row['end_to_end_tokens'] == sum(row[p+'total_tokens'] for p in ('', 'simulator_', 'judge_'))
    assert row['end_to_end_accounting_complete'] == all(row[p+'accounting_complete'] for p in ('', 'simulator_', 'judge_'))
    close(row['end_to_end_payg_known_start_time_estimate_usd'], sum(row[p+'payg_known_start_time_estimate_usd'] for p in ('', 'simulator_', 'judge_')))


def validate(base):
    samples, requests, attempts = [read(base/f'{name}.jsonl') for name in ('samples', 'requests', 'attempts')]
    pricing = json.loads((base/'pricing.json').read_text())
    assert len(samples) == 1390 and len(requests) == 34595 and len(attempts) == 1406
    lookup = {(s['harness'], s['task_id']): s for s in samples}
    assert len(lookup) == len(samples)
    by_task, groups, attempt_groups = defaultdict(dict), defaultdict(list), defaultdict(list)
    assert len({(r['harness'], r['role'], r['request_id']) for r in requests}) == len(requests)
    for r in requests:
        key = r['harness'], r['task_id']
        assert key in lookup and r['role'] in ROLES
        groups[key].append(r)
        attempt_groups[*key, r['attempt_id']].append(r)
        assert r['model'] == 'deepseek-v4.1-flash-economy' and r['temperature'] == 0
        assert all(r[k] is None or isinstance(r[k], int) and r[k] >= 0 for k in TOKENS)
        assert r['accounting_complete'] == bool(r['start_record_present'] and r['finish_record_present'] and r['response_complete'] and r['usage_present'])
        if r['total_tokens'] is not None:
            assert r['total_tokens'] == sum(r[k] or 0 for k in TOKENS)
        elif r['accounting_complete']:
            raise AssertionError('Missing total for complete request')
        expected = sum(Decimal(str(rate))*(r[k] or 0) for k, rate in pricing[r['tariff_using_start_time']].items())/Decimal(1_000_000)
        close(r['payg_known_start_time_estimate_cny'], float(expected))
        close(r['payg_known_all_peak_cny'], 2*r['payg_known_all_offpeak_cny'])
    finals, attempt_counts = {}, Counter()
    for a in attempts:
        key = a['harness'], a['task_id']
        attempt_counts[key] += 1
        usage(a, attempt_groups[*key, a['attempt_id']], pricing)
        if a['is_final_attempt']:
            assert key not in finals
            finals[key] = a
    assert len(finals) == 1390
    early = 0
    for key, s in lookup.items():
        by_task[s['task_id']][s['harness']] = s
        assert s['task_id'] == s['domain']+'/'+s['original_task_id']
        assert s['status'] == 'completed' and s['success'] in (0, 1)
        assert s['label'] == ('correct' if s['success'] else 'incorrect')
        assert s['trial'] == 0 and s['seed'] == 300 and s['max_steps'] == 200
        assert s['compression_policy'] == 'native_defaults' and s['compression_threshold_tokens'] is None and s['timeout_sec'] is None
        assert s['actual_billed_usd'] is None and s['router_eligible_label']
        assert s['router_eligible_complete_tokens'] == s['accounting_complete']
        usage(s, groups[key], pricing)
        assert s['token'] == s['total_tokens'] == s['source_export_total_tokens']
        assert s['token_reconciliation_delta'] == 0
        assert s['simulator_total_tokens'] == s['source_simulator_tokens']
        assert s['judge_total_tokens'] == s['source_judge_tokens']
        assert s['judge_applicable'] == bool(s['judge_model_requests'])
        a = finals[key]
        assert s['attempts_count'] == attempt_counts[key]
        assert s['final_attempt_id'] == a['attempt_id']
        assert s['final_attempt_token'] == a['total_tokens']
        assert s['token'] == s['final_attempt_token']+s['prior_attempt_tokens']
        assert s['score'] == s['official_reward'] == a['official_reward']
        if s['termination_reason'] == 'harness_early_exit':
            early += 1
            assert s['success'] == 0 and s['score'] is None
            assert s['label_source'] == 'native_early_exit_zero'
            assert not s['official_evaluation_present'] and a['returncode'] == 0 and not a['timed_out']
        else:
            assert s['official_evaluation_present'] and s['success'] == int(s['official_reward'] == 1)
            assert s['label_source'] == 'official_evaluation_reward_equals_one'
    assert early == 29 and len(by_task) == 278 and all(set(v) == set(HARNESSES) for v in by_task.values())
    complete = {t for t, v in by_task.items() if all(s['accounting_complete'] for s in v.values())}
    e2e = {t for t, v in by_task.items() if all(s['end_to_end_accounting_complete'] for s in v.values())}
    assert len(complete) == 263 and len(e2e) == 253
    analysis = json.loads((base/'analysis.json').read_text())
    for field, expected in [('common_scored_tasks', set(by_task)), ('common_complete_token_tasks', complete), ('common_complete_end_to_end_token_tasks', e2e)]:
        assert set(analysis[field]) == expected
    for s in samples:
        assert s['in_common_scored_subset'] and s['in_common_complete_token_subset'] == (s['task_id'] in complete)
    disagreements = {t for t, v in by_task.items() if len({s['success'] for s in v.values()}) > 1}
    assert len(disagreements) == 81 and set(analysis['tasks_with_correctness_disagreement']) == disagreements
    assert len(analysis['tasks_all_five_correct']) == 190 and len(analysis['tasks_all_five_incorrect']) == 7
    assert analysis['tasks_any_correct'] == 271 and not analysis['token_reconciliations']
    for filename in ('summary.json', 'domain-summary.json'):
        for summary in json.loads((base/filename).read_text()):
            rows = [s for s in samples if s['harness'] == summary['harness'] and ('domain' not in summary or s['domain'] == summary['domain'])]
            req = [r for r in requests if r['harness'] == summary['harness'] and ('domain' not in summary or r['domain'] == summary['domain'])]
            assert summary['selected_samples'] == summary['scored_samples'] == len(rows)
            assert summary['correct'] == sum(s['success'] for s in rows)
            assert summary['samples_with_complete_tokens'] == sum(s['accounting_complete'] for s in rows)
            usage(summary, req, pricing)
    for h in HARNESSES:
        assert Counter(s['domain'] for s in samples if s['harness'] == h) == {'airline': 50, 'retail': 114, 'telecom': 114}
    experiments = json.loads((base/'experiments.json').read_text())
    assert len(experiments) == 5
    assert len({e['tau_source_sha256'] for e in experiments}) == len({e['tau_data_sha256'] for e in experiments}) == 1
    for name, data in [('samples', samples), ('requests', requests), ('attempts', attempts)]:
        with (base/f'{name}.csv').open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == len(data)
        for c, j in zip(rows, data):
            for key, value in j.items():
                expected = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else '' if value is None else str(value)
                assert c[key] == expected, (name, key)
    with (base/'task-matrix.csv').open() as f:
        matrix = list(csv.DictReader(f))
    assert len(matrix) == 278
    for row in matrix:
        for h in HARNESSES:
            s = lookup[h, row['task_id']]
            assert int(row[h+'_success']) == s['success'] and int(row[h+'_token']) == s['token']
    with (base/'pairwise-correctness.csv').open() as f:
        pairs = list(csv.DictReader(f))
    assert len(pairs) == 10
    for row in pairs:
        a, b = row['harness_a'], row['harness_b']
        for field, x, y in [('both_correct', 1, 1), ('only_a_correct', 1, 0), ('only_b_correct', 0, 1), ('both_incorrect', 0, 0)]:
            assert int(row[field]) == sum(v[a]['success'] == x and v[b]['success'] == y for v in by_task.values())
    for name in ('source-files.json', 'benchmark-source-files.json'):
        hashes = json.loads((base/'provenance'/name).read_text())
        assert hashes and all(not Path(p).is_absolute() and '..' not in Path(p).parts for p in hashes)
        assert all(len(v['sha256']) == 64 and v['bytes'] >= 0 for v in hashes.values())
    checked = set()
    for line in (base/'SHA256SUMS').read_text().splitlines():
        expected, relative = line.split('  ', 1)
        assert not Path(relative).is_absolute() and '..' not in Path(relative).parts
        assert hashlib.sha256((base/relative).read_bytes()).hexdigest() == expected, relative
        checked.add(relative)
    assert checked == {str(p.relative_to(base)) for p in base.rglob('*') if p.is_file() and p.name != 'SHA256SUMS'}
    print(f'PASS tau2: {len(samples)} labels, {len(requests)} requests, {len(attempts)} attempts; 1361 official / 29 early-exit; 263 model / 253 end-to-end common complete tasks')
