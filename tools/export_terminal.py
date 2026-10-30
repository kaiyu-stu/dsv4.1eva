"""Build a credential-free, reproducible DS V4.1 Terminal release. No API calls."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import itertools
import json
from pathlib import Path
import statistics
import tomllib
from zoneinfo import ZoneInfo

BENCHMARK = 'terminal-bench-2.0'
MODEL = 'deepseek-v4.1-flash-economy'
RELEASE = 'dsv41flash-economy-t0-native-1200-v1'
HARNESS = {'claude': 'Claude Code', 'codex': 'Codex', 'dsh': 'DeepSeek Harness',
           'pi': 'Pi', 'zcode': 'ZCode'}
RUNS = {h: f'terminal-ark-{"codingplan1" if h in ("claude", "codex", "dsh") else "agentplan2"}'
        f'-dsv41flash-economy-t0-native-1200-responses-v1-{"deepseek" if h == "dsh" else h}'
        for h in HARNESS}
TOKEN_FIELDS = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
UTC = timezone.utc
PRICING = {
    'currency': 'CNY', 'unit': 'per million tokens', 'verified_date': '2026-10-30',
    'model': MODEL,
    'source': 'https://docs.volcengine.com/docs/ark/model-pricing?lang=zh',
    'plan_source': 'https://docs.volcengine.com/docs/ark/agent-plan-personal-faq?lang=zh',
    'offpeak': {'input_tokens': 0.80, 'cache_read_input_tokens': 0.016, 'output_tokens': 3.20},
    'peak': {'input_tokens': 1.60, 'cache_read_input_tokens': 0.032, 'output_tokens': 6.40},
    'peak_schedule': 'Asia/Shanghai, Monday-Friday [09:00,12:00) and [14:00,18:00)',
    'official_tariff_timestamp': 'request completion time',
    'available_timestamp': 'proxy request start time, copied into finish records; NOT completion time',
    'time_based_estimate': 'Use request start time as a documented approximation.',
    'fx': {'date': '2026-10-29', 'source': 'https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml',
           'usd_per_eur': '1.1130', 'cny_per_eur': '7.4144',
           'cny_per_usd': str(Decimal('7.4144') / Decimal('1.1130'))},
    'actual_billed_usd': None,
    'scope': 'PAYG-equivalent known-token estimate, not Coding/Agent Plan subscription spend',
    'excluded': ['unknown tokens', 'subscription allocation', 'hardware', 'electricity',
                 'taxes and FX spread', 'explicit cache storage'],
    'cache_note': 'Implicit cache read is priced separately; all exported cache-creation counts are zero.',
    'historical_price_note': 'Current public rates repriced over historical calls; no historical invoice is available.'}


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def table(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        for row in rows:
            w.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                        for k, v in row.items()})


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in rows))


def instant(timestamp):
    return datetime.fromtimestamp(timestamp, UTC).isoformat().replace('+00:00', 'Z') if timestamp else None


def epoch(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() if value else None


def duration(value):
    start, finish = epoch(value.get('started_at')), epoch(value.get('finished_at'))
    return round(finish - start, 6) if start is not None and finish is not None else None


def tariff(timestamp):
    dt = datetime.fromtimestamp(timestamp, ZoneInfo('Asia/Shanghai'))
    minute = dt.hour * 60 + dt.minute
    return 'peak' if dt.weekday() < 5 and (540 <= minute < 720 or 840 <= minute < 1080) else 'offpeak'


def cost(usage, period):
    if usage.get('cache_creation_input_tokens', 0):
        raise ValueError('Explicit cache creation requires a separate pricing policy')
    return sum(Decimal(str(PRICING[period][k])) * (usage.get(k) or 0)
               for k in PRICING[period]) / Decimal(1_000_000)


class Sources:
    def __init__(self, root):
        self.root, self.files = root, {}

    def read(self, path):
        raw = path.read_bytes()
        self.files[str(path.relative_to(self.root))] = {
            'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        return raw

    def json(self, path):
        return json.loads(self.read(path))

    def jsonl(self, path):
        # Never silently drop malformed source records.
        return [json.loads(line) for line in self.read(path).splitlines() if line.strip()]


def aggregate_requests(rows):
    totals = {key: sum((r.get(key) or 0) for r in rows) for key in TOKEN_FIELDS}
    totals['total_input_tokens'] = sum(totals[k] for k in TOKEN_FIELDS if k != 'output_tokens')
    totals['total_tokens'] = totals['total_input_tokens'] + totals['output_tokens']
    totals.update(model_requests=len(rows), usage_missing_requests=sum(not r['usage_present'] for r in rows),
                  unfinished_requests=sum(not r['finish_record_present'] for r in rows),
                  incomplete_requests=sum(not r['response_complete'] for r in rows),
                  accounting_complete=bool(rows) and all(r['accounting_complete'] for r in rows))
    for name in ('payg_known_start_time_estimate_cny', 'payg_known_all_offpeak_cny', 'payg_known_all_peak_cny'):
        totals[name] = round(sum(r[name] for r in rows), 10)
        totals[name.replace('_cny', '_usd')] = round(
            float(Decimal(str(totals[name])) / Decimal(PRICING['fx']['cny_per_usd'])), 10)
    return totals


def safe_experiment(e, harness, run_id):
    keep = ('model', 'cli_version', 'temperature', 'compression_policy', 'threshold_tokens',
            'upstream_protocol', 'harbor_agent_timeout_sec', 'container_setup_policy',
            'container_cpu_affinity_policy', 'codex_context_window', 'codex_auto_compact_token_limit',
            'pi_context_window', 'zcode_context_window', 'zcode_native_compact_buffer_tokens')
    result = {k: e[k] for k in keep if k in e}
    result.update(harness=harness, harness_name=HARNESS[harness], run_id=run_id,
                  plan='coding_plan' if harness in ('claude', 'codex', 'dsh') else 'agent_plan',
                  upstream=e.get('upstream'),
                  benchmark_commit=e['task_commits']['benchmarks/terminal-bench-2.0'],
                  recorded_fingerprints={k:v for k,v in e.items() if k.endswith('_sha256')
                                         or k in ('terminal_verifier_runtime_helpers', 'terminal_verifier_cache')})
    return result


def build(root, out):
    sources = Sources(root)
    base = out / 'benchmarks' / BENCHMARK / RELEASE
    samples, requests, attempts, experiments = [], [], [], []
    by_task = defaultdict(dict)
    for harness, rid in RUNS.items():
        run = root / 'runs' / rid
        experiment = sources.json(run / 'experiment.json')
        assert experiment['model'] == MODEL and experiment['temperature'] == 0
        assert experiment['compression_policy'] == 'native_defaults'
        assert experiment['harbor_agent_timeout_sec'] == 1200
        experiments.append(safe_experiment(experiment, harness, rid))
        source_rows = sources.jsonl(root / 'results' / rid / 'samples.jsonl')
        assert len(source_rows) == 89
        journals = sources.jsonl(run / 'model-requests.jsonl')
        starts, finishes = {}, {}
        for event in journals:
            if not event.get('path', '').split('?')[0].rstrip('/').endswith(
                    ('/messages', '/responses', '/responses/compact')):
                continue
            target = starts if event['event'] == 'start' else finishes
            if event['request_id'] in target:
                raise ValueError('Duplicate request record')
            target[event['request_id']] = event
        timelines = {}
        for original in source_rows:
            aid = original['audit_id']
            folder = run / 'samples' / BENCHMARK / aid
            checkpoint = sources.json(folder / 'result.json')
            assert checkpoint['success'] == original['success'] and checkpoint['status'] == original['status']
            dirs = sorted((folder / 'attempts').iterdir(), key=lambda p:int(p.name))
            timelines[aid] = dirs
            for i, attempt in enumerate(dirs):
                trial_files = list(attempt.glob('trial/*/result.json'))
                if len(trial_files) > 1:
                    raise ValueError('Ambiguous trial result')
                trial = sources.json(trial_files[0]) if trial_files else {}
                exception = trial.get('exception_info') or {}
                native = trial.get('agent_result') or {}
                rewards = (trial.get('verifier_result') or {}).get('rewards') or {}
                attempts.append(dict(benchmark=BENCHMARK, release_id=RELEASE, harness=harness,
                    task_id=original['sample_id'], attempt_id=attempt.name, attempt_index=i+1,
                    is_final_attempt=i == len(dirs)-1, started_at=trial.get('started_at'),
                    finished_at=trial.get('finished_at'), wall_time_sec=duration(trial),
                    agent_execution_sec=duration(trial.get('agent_execution') or {}),
                    verifier_execution_sec=duration(trial.get('verifier') or {}),
                    trial_result_present=bool(trial), exception_type=exception.get('exception_type'),
                    verifier_reward=rewards.get('reward'), task_checksum=trial.get('task_checksum'),
                    native_input_tokens=native.get('n_input_tokens'), native_cache_tokens=native.get('n_cache_tokens'),
                    native_output_tokens=native.get('n_output_tokens'),
                    native_reported_cost_usd_unverified=native.get('cost_usd')))
        run_requests = []
        for request_id in sorted(starts.keys() | finishes.keys()):
            start, finish = starts.get(request_id), finishes.get(request_id)
            event = finish or start
            aid = event['sample']
            if aid not in timelines:
                raise ValueError('Unmatched sample in request journal')
            original = next(s for s in source_rows if s['audit_id'] == aid)
            timestamp = (start or event)['time']
            dirs = timelines[aid]
            index = bisect_right([int(p.name)/1e9 for p in dirs], timestamp)-1
            if index < 0:
                raise ValueError('Request predates first attempt')
            usage = (finish or {}).get('usage') or {}
            present = all(k in usage for k in ('input_tokens', 'output_tokens'))
            row = dict(benchmark=BENCHMARK, release_id=RELEASE, harness=harness, task_id=original['sample_id'],
                audit_id=aid, request_id=request_id, attempt_id=dirs[index].name,
                started_at=instant(timestamp), request_path=event['path'].split('?')[0],
                upstream_path=event.get('upstream_path'), protocol_adapter=event.get('protocol_adapter'),
                model=event.get('model'), temperature=event.get('temperature'),
                http_status=(finish or {}).get('status'), error_type=(finish or {}).get('error_type'),
                start_record_present=start is not None, finish_record_present=finish is not None,
                response_complete=bool((finish or {}).get('complete')), usage_present=present,
                accounting_complete=bool(start and finish and present and finish.get('complete')),
                **{k: usage.get(k) if usage else None for k in TOKEN_FIELDS})
            for key in TOKEN_FIELDS:
                value = row[key]
                if value is not None and (not isinstance(value, int) or value < 0):
                    raise ValueError('Invalid token count')
            row['total_tokens'] = sum(row[k] or 0 for k in TOKEN_FIELDS) if usage else None
            period = tariff(timestamp)
            row['tariff_using_start_time'] = period
            for label, p in [('payg_known_start_time_estimate_cny', period),
                             ('payg_known_all_offpeak_cny', 'offpeak'), ('payg_known_all_peak_cny', 'peak')]:
                row[label] = float(cost(usage, p))
            run_requests.append(row)
        requests.extend(run_requests)
        sample_ledger = defaultdict(list)
        for row in run_requests:
            sample_ledger[row['audit_id']].append(row)
        for original in sorted(source_rows, key=lambda s:s['sample_id']):
            ledger = sample_ledger[original['audit_id']]
            usage = aggregate_requests(ledger)
            # A response may finish after an earlier export read the journal.
            # Publish the frozen journal recount and retain the old value for audit.
            scored = original['status'] == 'completed' and original['success'] in (0,1)
            final = next(a for a in reversed(attempts) if a['harness'] == harness
                         and a['task_id'] == original['sample_id'] and a['is_final_attempt'])
            termination = original.get('termination_reason') or (
                'verifier_reward' if final['verifier_reward'] is not None else 'unspecified')
            label_source = ('agent_timeout_zero_v2' if termination == 'agent_timeout' else
                            original.get('scoring_policy') or ('verifier_reward' if scored else 'unscored'))
            row = dict(benchmark=BENCHMARK, release_id=RELEASE, model=MODEL, harness=harness,
                run_id=rid, task_id=original['sample_id'], audit_id=original['audit_id'],
                plan=experiments[-1]['plan'], status=original['status'],
                success=original['success'] if scored else None,
                label='correct' if scored and original['success'] else 'incorrect' if scored else 'unscored',
                score=original.get('score'), label_source=label_source,
                termination_reason=termination, verifier_reward=final['verifier_reward'],
                verifier_completed=original.get('verifier_completed', final['verifier_reward'] is not None),
                final_exception_type=final['exception_type'], attempts_count=len(timelines[original['audit_id']]),
                final_attempt_id=final['attempt_id'], final_agent_execution_sec=final['agent_execution_sec'],
                total_attempt_wall_time_sec=round(sum(a['wall_time_sec'] or 0 for a in attempts
                    if a['harness'] == harness and a['task_id'] == original['sample_id']),6),
                **usage, token=usage['total_tokens'],
                source_accounting_complete=original['accounting_complete'],
                source_accounting_gaps=original['accounting_gaps'],
                source_export_total_tokens=original['total_tokens'],
                token_reconciliation_delta=usage['total_tokens']-original['total_tokens'],
                compaction_events_observed=original.get('compaction_events'),
                compaction_observation=original.get('compaction_observation'),
                compression_policy='native_defaults', compression_threshold_tokens=None,
                actual_billed_usd=None,
                router_eligible_label=scored,
                router_eligible_complete_tokens=scored and usage['accounting_complete'])
            samples.append(row)
            by_task[row['task_id']][harness] = row
        for path in sorted((run / 'experiment-history').glob('*/experiment-*.json')):
            old = sources.json(path)
            dump(base / 'provenance' / 'experiment-history' / harness / path.parent.name / path.name,
                 safe_experiment(old, harness, rid))
    assert len(by_task) == 89 and all(set(v) == set(HARNESS) for v in by_task.values())
    attempt_requests = defaultdict(list)
    for r in requests:
        attempt_requests[r['harness'], r['task_id'], r['attempt_id']].append(r)
    for a in attempts:
        a.update(aggregate_requests(attempt_requests[a['harness'],a['task_id'],a['attempt_id']]))
    final_attempts = {(a['harness'], a['task_id']):a for a in attempts if a['is_final_attempt']}
    for s in samples:
        final = final_attempts[s['harness'],s['task_id']]
        s['final_attempt_token'] = final['total_tokens']
        s['final_attempt_accounting_complete'] = final['accounting_complete']
        s['prior_attempt_tokens'] = s['token'] - final['total_tokens']
        s['final_attempt_payg_known_start_time_estimate_usd'] = final['payg_known_start_time_estimate_usd']
    common = {t for t,v in by_task.items() if all(x['success'] is not None for x in v.values())}
    complete = {t for t in common if all(x['accounting_complete'] for x in by_task[t].values())}
    for s in samples:
        s['in_common_scored_subset'] = s['task_id'] in common
        s['in_common_complete_token_subset'] = s['task_id'] in complete
    summaries = []
    for harness in HARNESS:
        rows = [r for r in samples if r['harness'] == harness]
        scored = [r for r in rows if r['success'] is not None]
        good = [r for r in rows if r['task_id'] in complete]
        sums = aggregate_requests([r for r in requests if r['harness'] == harness])
        summaries.append(dict(harness=harness, harness_name=HARNESS[harness], selected_samples=len(rows),
            scored_samples=len(scored), correct=sum(r['success'] for r in scored),
            incorrect=sum(r['success']==0 for r in scored), unscored=len(rows)-len(scored),
            success_rate_scored=sum(r['success'] for r in scored)/len(scored),
            solved_fraction_selected=sum(r['success'] for r in scored)/len(rows),
            agent_timeouts=sum(r['termination_reason']=='agent_timeout' for r in rows),
            verifier_timeouts=sum(r['termination_reason']=='verifier_timeout' for r in rows),
            samples_with_complete_tokens=sum(r['accounting_complete'] for r in rows),
            source_accounting_gaps=sum(r['source_accounting_gaps'] for r in rows),
            compaction_events_observed=sum(r['compaction_events_observed'] or 0 for r in rows),
            median_tokens=statistics.median(r['token'] for r in rows),
            mean_tokens=statistics.mean(r['token'] for r in rows),
            common_scored_samples=len(common), common_scored_correct=sum(r['success'] for r in rows if r['task_id'] in common),
            common_complete_samples=len(good), common_complete_correct=sum(r['success'] for r in good),
            common_complete_tokens=sum(r['token'] for r in good), **sums))
    matrix, tasks = [], []
    for task, values in sorted(by_task.items()):
        meta = sources.read(root / 'benchmarks' / BENCHMARK / task / 'task.toml')
        cfg = tomllib.loads(meta.decode())
        info, env = cfg['metadata'], cfg['environment']
        instruction = sources.read(root / 'benchmarks' / BENCHMARK / task / 'instruction.md')
        tasks.append(dict(task_id=task, category=info.get('category'), difficulty=info.get('difficulty'),
            tags=info.get('tags'), expert_time_estimate_min=info.get('expert_time_estimate_min'),
            junior_time_estimate_min=info.get('junior_time_estimate_min'),
            original_agent_timeout_sec=cfg.get('agent',{}).get('timeout_sec'),
            original_verifier_timeout_sec=cfg.get('verifier',{}).get('timeout_sec'),
            cpus=env.get('cpus'), memory=env.get('memory'), storage=env.get('storage'),
            docker_image=env.get('docker_image'), instruction_sha256=hashlib.sha256(instruction).hexdigest(),
            task_toml_sha256=hashlib.sha256(meta).hexdigest()))
        r = dict(task_id=task, all_five_scored=task in common,
                 all_five_tokens_complete=task in complete,
                 correct_harnesses=[h for h,s in values.items() if s['success']==1],
                 incorrect_harnesses=[h for h,s in values.items() if s['success']==0],
                 unscored_harnesses=[h for h,s in values.items() if s['success'] is None],
                 correctness_disagreement=any(s['success']==1 for s in values.values())
                     and any(s['success']==0 for s in values.values()),
                 all_five_agent_timeout=all(s['termination_reason']=='agent_timeout' for s in values.values()))
        for h,s in values.items():
            for k in ('success','token','accounting_complete','termination_reason','payg_known_start_time_estimate_usd'):
                r[f'{h}_{k}'] = s[k]
        matrix.append(r)
    pairs = []
    for a,b in itertools.combinations(HARNESS,2):
        valid = [v for v in by_task.values() if v[a]['success'] is not None and v[b]['success'] is not None]
        pairs.append(dict(harness_a=a,harness_b=b,common_scored=len(valid),
            both_correct=sum(v[a]['success']==1 and v[b]['success']==1 for v in valid),
            only_a_correct=sum(v[a]['success']==1 and v[b]['success']==0 for v in valid),
            only_b_correct=sum(v[a]['success']==0 and v[b]['success']==1 for v in valid),
            both_incorrect=sum(v[a]['success']==0 and v[b]['success']==0 for v in valid)))
    analysis = dict(tasks=89, sample_harness_rows=len(samples), scored_rows=sum(s['success'] is not None for s in samples),
        token_reconciliations=[{k:s[k] for k in ('harness','task_id','source_export_total_tokens',
            'total_tokens','token_reconciliation_delta')} for s in samples if s['token_reconciliation_delta']],
        common_scored_tasks=sorted(common), common_complete_token_tasks=sorted(complete),
        tasks_with_correctness_disagreement=[r['task_id'] for r in matrix if r['correctness_disagreement']],
        tasks_all_five_agent_timeout=[r['task_id'] for r in matrix if r['all_five_agent_timeout']],
        common_tasks_all_five_incorrect=[t for t in sorted(common) if all(s['success']==0 for s in by_task[t].values())],
        common_tasks_any_correct=sum(any(s['success']==1 for s in by_task[t].values()) for t in common))
    for name,rows in [('samples',samples),('requests',requests),('attempts',attempts)]:
        table(base / f'{name}.csv',rows)
        jsonl(base / f'{name}.jsonl',rows)
    for name,rows in [('harness-summary',summaries),('task-matrix',matrix),('tasks',tasks),('pairwise-correctness',pairs)]:
        table(base / f'{name}.csv',rows)
    router_keys = ('benchmark','release_id','model','harness','task_id','token','success',
                   'termination_reason','accounting_complete','router_eligible_label',
                   'router_eligible_complete_tokens','payg_known_start_time_estimate_usd',
                   'final_attempt_token','final_attempt_accounting_complete','prior_attempt_tokens')
    table(base / 'router-data.csv', [{k:s[k] for k in router_keys} for s in samples])
    dump(base / 'summary.json',summaries)
    dump(base / 'analysis.json',analysis)
    dump(base / 'pricing.json',PRICING)
    dump(base / 'experiments.json',experiments)
    dump(base / 'provenance' / 'source-files.json', sources.files)
    dump(base / 'provenance' / 'export.json',dict(schema_version='1.0',release_id=RELEASE,
        exported_at=datetime.now(UTC).isoformat(), source_file_count=len(sources.files),
        source_runs=RUNS, contains_model_prompts=False, contains_credentials=False,
        primary_tokens='All observed gateway request usage across all attempts, cache read included',
        strict_quality='Paired start/finish, present input/output usage, complete response for every request',
        source_quality='Original experiment accounting flags retained separately'))
    index_path = out / 'benchmarks' / 'index.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else []
    index = [r for r in index if (r['benchmark'],r['release_id']) != (BENCHMARK,RELEASE)]
    index.append(dict(benchmark=BENCHMARK,release_id=RELEASE,model=MODEL,
        relative_path=f'{BENCHMARK}/{RELEASE}',tasks=89,harnesses=list(HARNESS),rows=len(samples),
        scored_rows=analysis['scored_rows'],status='finished_with_one_unscored_sample'))
    dump(index_path,index)
    print(json.dumps({'release':str(base),'summaries':summaries,'analysis':analysis},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    args = parser.parse_args()
    build(args.source_root.resolve(),args.output_root.resolve())
