"""Export allowlisted tau2 measurements and role-separated usage; no model calls."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import re

from export_terminal import (HARNESS, MODEL, TOKEN_FIELDS, PRICING, Sources, aggregate_requests,
                             cost, dump, instant, jsonl, table, tariff)

BENCHMARK = 'tau2-bench'
RELEASE = 'dsv41flash-economy-t0-native-notimelimit-v3-dialogue'
RUNS = {h:f'tau2-ark-{"codingplan1" if h in ("claude","codex","dsh") else "agentplan2"}'
          f'-dsv41flash-economy-t0-native-notimelimit-v3-dialogue-{h}' for h in HARNESS}
ROLES = ('model','simulator','judge')


def prefixed_usage(rows):
    result = aggregate_requests([r for r in rows if r['role']=='model'])
    for role in ('simulator','judge'):
        selected = [r for r in rows if r['role']==role]
        usage = aggregate_requests(selected)
        if role=='judge' and not selected:
            # No NL assertion needs a judge: zero calls is not missing accounting.
            usage['accounting_complete'] = True
        result.update({role+'_'+k:v for k,v in usage.items()})
    result['end_to_end_tokens'] = result['total_tokens']+result['simulator_total_tokens']+result['judge_total_tokens']
    result['end_to_end_accounting_complete'] = (result['accounting_complete'] and
        result['simulator_accounting_complete'] and result['judge_accounting_complete'])
    result['end_to_end_payg_known_start_time_estimate_usd'] = round(sum(
        result[p+'payg_known_start_time_estimate_usd'] for p in ('','simulator_','judge_')),10)
    return result


def safe_experiment(e):
    p=e['profile']
    return dict(harness=e['harness'],cli_version=e['cli_version'],
        model=p['model'],temperature=p['temperature'],compression_policy=p['compression_policy'],
        plan='coding_plan' if e['harness'] in ('claude','codex','dsh') else 'agent_plan',
        upstream=p['ark_base_url'],domains=p['domains'],split=p['split'],num_trials=p['num_trials'],
        timeout_sec=p['timeout'],max_steps=p['max_steps'],max_errors=10,seed=p['seed'],
        simulator={k:v for k,v in p['simulator'].items() if k!='api_key_env'},
        judge=p['judge'],interface=e['interface'],token_scope=e['token_scope'],
        implementation_sha256=e['implementation_sha256'],tau_source_sha256=e['tau_source_sha256'],
        tau_data_sha256=e['tau_data_sha256'])


def build(root,out,tau_root):
    sources,tau_sources=Sources(root),Sources(tau_root)
    base=out/'benchmarks'/BENCHMARK/RELEASE
    samples,requests,attempts,experiments=[],[],[],[]
    checkpoints={}
    for h,rid in RUNS.items():
        run=root/'runs'/rid
        e=sources.json(run/'experiment.json')
        assert e['profile']['model']==MODEL and e['profile']['temperature']==0
        assert e['profile']['timeout'] is None and e['profile']['compression_policy']=='native_defaults'
        assert e['profile']['max_steps']==200 and e['profile']['seed']==300
        assert e['profile']['num_trials']==1 and e['profile']['split']=='base'
        experiments.append(safe_experiment(e))
        timelines={}
        for selected in e['samples']:
            sid=selected['sample_id']
            folder=run/'samples'/sid
            v=sources.json(folder/'result.json')
            assert v['status']=='completed' and v['success'] in (0,1)
            assert all(v[k]==selected[k] for k in ('domain','task_id','trial','sample_id'))
            checkpoints[h,sid]=v
            dirs=sorted((folder/'attempts').iterdir(),key=lambda p:int(p.name))
            timelines[sid]=dirs
            final_id=Path(v['attempt']).name
            assert final_id in {p.name for p in dirs}
            task_id=v['domain']+'/'+v['task_id']
            for a in dirs:
                execution=sources.json(a/'execution.json') if (a/'execution.json').exists() else {}
                simulation=sources.json(a/'simulation.json') if (a/'simulation.json').exists() else {}
                error=sources.json(a/'simulation-error.json') if (a/'simulation-error.json').exists() else {}
                evaluation=sources.json(a/'evaluation.json') if (a/'evaluation.json').exists() else {}
                reward=evaluation.get('reward') or {}
                db=reward.get('db_check') or {}
                checks=reward.get('action_checks')
                messages=simulation.get('messages') or []
                attempts.append(dict(benchmark=BENCHMARK,release_id=RELEASE,harness=h,domain=v['domain'],
                    task_id=task_id,original_task_id=v['task_id'],sample_id=sid,attempt_id=a.name,
                    is_final_attempt=a.name==final_id,attempt_created_at=instant(int(a.name)/1e9),
                    returncode=execution.get('returncode'),timed_out=execution.get('timed_out'),
                    native_turns=execution.get('native_turns'),simulation_present=bool(simulation),
                    simulation_termination=simulation.get('termination_reason'),
                    simulation_duration_sec=simulation.get('duration'),
                    simulation_message_count=len(messages) if simulation else None,
                    assistant_message_count=sum(m.get('role')=='assistant' for m in messages) if simulation else None,
                    user_message_count=sum(m.get('role')=='user' for m in messages) if simulation else None,
                    tool_message_count=sum(m.get('role')=='tool' for m in messages) if simulation else None,
                    simulation_error_type=error.get('error','').split(':',1)[0] or None,
                    evaluation_present=bool(evaluation),official_success=evaluation.get('success'),
                    official_reward=reward.get('reward'),db_match=db.get('db_match'),db_reward=db.get('db_reward'),
                    action_checks_count=len(checks) if checks is not None else None,
                    action_checks_matched=sum(c.get('action_match') is True for c in checks) if checks is not None else None))
        for role in ROLES:
            path=run/f'{role}-requests.jsonl'
            events=sources.jsonl(path) if path.exists() else []
            starts,finishes={},{}
            for event in events:
                if not event.get('path','').split('?')[0].rstrip('/').endswith(('/messages','/responses','/responses/compact')):
                    continue
                target=starts if event['event']=='start' else finishes
                assert event['request_id'] not in target
                target[event['request_id']]=event
            for request_id in sorted(starts.keys()|finishes.keys()):
                start,finish=starts.get(request_id),finishes.get(request_id)
                event=finish or start
                sid=event['sample'];v=checkpoints[h,sid];dirs=timelines[sid]
                timestamp=(start or event)['time']
                index=bisect_right([int(p.name)/1e9 for p in dirs],timestamp)-1
                assert index>=0
                usage=(finish or {}).get('usage') or {}
                row=dict(benchmark=BENCHMARK,release_id=RELEASE,harness=h,domain=v['domain'],
                    task_id=v['domain']+'/'+v['task_id'],sample_id=sid,role=role,request_id=request_id,
                    attempt_id=dirs[index].name,started_at=instant(timestamp),model=event.get('model'),
                    temperature=event.get('temperature'),request_path=event['path'].split('?')[0],
                    upstream_path=event.get('upstream_path'),protocol_adapter=event.get('protocol_adapter'),
                    http_status=(finish or {}).get('status'),error_type=(finish or {}).get('error_type'),
                    start_record_present=start is not None,finish_record_present=finish is not None,
                    response_complete=bool((finish or {}).get('complete')),
                    usage_present=all(k in usage for k in ('input_tokens','output_tokens')),
                    **{k:usage.get(k) if usage else None for k in TOKEN_FIELDS})
                row['accounting_complete']=bool(start and finish and row['usage_present'] and row['response_complete'])
                assert all(v is None or isinstance(v,int) and v>=0 for k,v in row.items() if k in TOKEN_FIELDS)
                row['total_tokens']=sum(row[k] or 0 for k in TOKEN_FIELDS) if usage else None
                period=tariff(timestamp);row['tariff_using_start_time']=period
                for key,p in [('payg_known_start_time_estimate_cny',period),
                              ('payg_known_all_offpeak_cny','offpeak'),('payg_known_all_peak_cny','peak')]:
                    row[key]=float(cost(usage,p))
                requests.append(row)
        updates=run/'implementation-updates.json'
        if updates.exists():
            dump(base/'provenance'/'implementation-updates'/f'{h}.json',sources.json(updates))
    groups,attempt_groups=defaultdict(list),defaultdict(list)
    for r in requests:
        groups[r['harness'],r['sample_id']].append(r)
        attempt_groups[r['harness'],r['sample_id'],r['attempt_id']].append(r)
    finals={}
    for a in attempts:
        a.update(prefixed_usage(attempt_groups[a['harness'],a['sample_id'],a['attempt_id']]))
        if a['is_final_attempt']:finals[a['harness'],a['sample_id']]=a
    for (h,sid),v in checkpoints.items():
        final=finals[h,sid];ledger=groups[h,sid];usage=prefixed_usage(ledger)
        if v['termination_reason']=='harness_early_exit':
            assert v['success']==0
        else:
            assert final['evaluation_present'] and final['official_success']==v['success']
        row=dict(benchmark=BENCHMARK,release_id=RELEASE,model=MODEL,harness=h,run_id=RUNS[h],
            task_id=v['domain']+'/'+v['task_id'],original_task_id=v['task_id'],domain=v['domain'],
            sample_id=sid,trial=v['trial'],plan='coding_plan' if h in ('claude','codex','dsh') else 'agent_plan',
            status=v['status'],success=v['success'],label='correct' if v['success'] else 'incorrect',
            score=final['official_reward'],label_source='native_early_exit_zero' if
                v['termination_reason']=='harness_early_exit' else 'official_evaluation_reward_equals_one',
            termination_reason=v['termination_reason'],failure_kind=v.get('failure_kind'),
            official_evaluation_present=final['evaluation_present'],official_reward=final['official_reward'],
            attempts_count=sum(a['harness']==h and a['sample_id']==sid for a in attempts),
            final_attempt_id=final['attempt_id'],final_attempt_token=final['total_tokens'],
            final_attempt_accounting_complete=final['accounting_complete'],
            final_native_turns=final['native_turns'],final_simulation_duration_sec=final['simulation_duration_sec'],
            **usage,token=usage['total_tokens'],prior_attempt_tokens=usage['total_tokens']-final['total_tokens'],
            source_export_total_tokens=v['token'],token_reconciliation_delta=usage['total_tokens']-v['token'],
            source_accounting_complete=v['accounting_complete'],source_accounting_gaps=v['accounting_gaps'],
            source_simulator_tokens=v['simulator_tokens'],source_judge_tokens=v['judge_tokens'],
            judge_applicable=usage['judge_model_requests']>0,
            compression_policy='native_defaults',compression_threshold_tokens=None,timeout_sec=None,
            max_steps=200,seed=300,router_eligible_label=True,
            router_eligible_complete_tokens=usage['accounting_complete'],actual_billed_usd=None)
        samples.append(row)
    samples.sort(key=lambda r:(list(HARNESS).index(r['harness']),r['domain'],r['original_task_id']))
    by_task=defaultdict(dict)
    for r in samples:by_task[r['task_id']][r['harness']]=r
    assert len(samples)==1390 and len(by_task)==278 and all(len(v)==5 for v in by_task.values())
    complete={task for task,v in by_task.items() if all(s['accounting_complete'] for s in v.values())}
    e2e_complete={task for task,v in by_task.items() if all(s['end_to_end_accounting_complete'] for s in v.values())}
    for s in samples:
        s['in_common_scored_subset']=True
        s['in_common_complete_token_subset']=s['task_id'] in complete
    summaries,domain_summaries=[],[]
    for h in HARNESS:
        for domain in (None,'airline','retail','telecom'):
            rows=[s for s in samples if s['harness']==h and (domain is None or s['domain']==domain)]
            req=[r for r in requests if r['harness']==h and (domain is None or r['domain']==domain)]
            summary=dict(harness=h,harness_name=HARNESS[h],selected_samples=len(rows),scored_samples=len(rows),
                correct=sum(s['success'] for s in rows),incorrect=sum(s['success']==0 for s in rows),unscored=0,
                success_rate_scored=sum(s['success'] for s in rows)/len(rows),
                native_early_exits=sum(s['termination_reason']=='harness_early_exit' for s in rows),
                samples_with_complete_tokens=sum(s['accounting_complete'] for s in rows),
                samples_with_complete_end_to_end_tokens=sum(s['end_to_end_accounting_complete'] for s in rows),
                common_complete_samples=sum(s['task_id'] in complete for s in rows),
                common_complete_correct=sum(s['success'] for s in rows if s['task_id'] in complete),
                **prefixed_usage(req))
            if domain is None:summaries.append(summary)
            else:domain_summaries.append(dict(domain=domain,**summary))
    matrix=[]
    for task,v in sorted(by_task.items()):
        first=next(iter(v.values()))
        row=dict(task_id=task,domain=first['domain'],original_task_id=first['original_task_id'],
            all_five_scored=True,all_five_tokens_complete=task in complete,
            correctness_disagreement=len({s['success'] for s in v.values()})>1,
            correct_harnesses=[h for h,s in v.items() if s['success']==1])
        for h,s in v.items():
            for k in ('success','token','accounting_complete','termination_reason','payg_known_start_time_estimate_usd'):
                row[h+'_'+k]=s[k]
        matrix.append(row)
    pairs=[]
    for a,b in itertools.combinations(HARNESS,2):
        pairs.append(dict(harness_a=a,harness_b=b,common_scored=278,
            both_correct=sum(v[a]['success']==1 and v[b]['success']==1 for v in by_task.values()),
            only_a_correct=sum(v[a]['success']==1 and v[b]['success']==0 for v in by_task.values()),
            only_b_correct=sum(v[a]['success']==0 and v[b]['success']==1 for v in by_task.values()),
            both_incorrect=sum(v[a]['success']==0 and v[b]['success']==0 for v in by_task.values())))
    tasks=[]
    for domain in ('airline','retail','telecom'):
        file=tau_root/'data/tau2/domains'/domain/'tasks.json'
        records={t['id']:t for t in tau_sources.json(file)}
        tau_sources.read(file.parent/'split_tasks.json')
        for task,values in sorted(by_task.items()):
            first=next(iter(values.values()))
            if first['domain']!=domain:continue
            original=first['original_task_id'];record=records[original]
            canonical=json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
            persona=re.search(r'\[PERSONA:([^\]]+)\]$',original)
            issue=re.match(r'\[([^\]]+)\]',original)
            tasks.append(dict(task_id=task,domain=domain,original_task_id=original,sample_id=first['sample_id'],
                split='base',trial=0,task_record_sha256=hashlib.sha256(canonical).hexdigest(),
                task_record_hash_format='UTF-8 JSON, sort_keys=True, ensure_ascii=False, separators=(comma,colon)',
                telecom_issue=issue.group(1) if issue else None,telecom_persona=persona.group(1) if persona else None))
    analysis=dict(tasks=278,sample_harness_rows=1390,scored_rows=1390,common_scored_tasks=sorted(by_task),
        common_complete_token_tasks=sorted(complete),common_complete_end_to_end_token_tasks=sorted(e2e_complete),
        tasks_with_correctness_disagreement=[r['task_id'] for r in matrix if r['correctness_disagreement']],
        tasks_all_five_correct=[task for task,v in by_task.items() if all(s['success']==1 for s in v.values())],
        tasks_all_five_incorrect=[task for task,v in by_task.items() if all(s['success']==0 for s in v.values())],
        tasks_any_correct=sum(any(s['success']==1 for s in v.values()) for v in by_task.values()),
        token_reconciliations=[{k:s[k] for k in ('harness','task_id','source_export_total_tokens',
            'total_tokens','token_reconciliation_delta')} for s in samples if s['token_reconciliation_delta']])
    for name,rows in [('samples',samples),('requests',requests),('attempts',attempts)]:
        table(base/f'{name}.csv',rows);jsonl(base/f'{name}.jsonl',rows)
    for name,rows in [('harness-summary',summaries),('domain-summary',domain_summaries),('task-matrix',matrix),
                      ('tasks',tasks),('pairwise-correctness',pairs)]:table(base/f'{name}.csv',rows)
    keys=('benchmark','release_id','model','harness','domain','task_id','original_task_id','token','success',
          'termination_reason','accounting_complete','router_eligible_complete_tokens','final_attempt_token',
          'final_attempt_accounting_complete','prior_attempt_tokens','simulator_total_tokens','judge_total_tokens',
          'payg_known_start_time_estimate_usd')
    table(base/'router-data.csv',[{k:s[k] for k in keys} for s in samples])
    dump(base/'summary.json',summaries);dump(base/'domain-summary.json',domain_summaries)
    dump(base/'analysis.json',analysis);dump(base/'experiments.json',experiments);dump(base/'pricing.json',PRICING)
    dump(base/'provenance/source-files.json',sources.files)
    dump(base/'provenance/benchmark-source-files.json',tau_sources.files)
    dump(base/'provenance/export.json',dict(schema_version='1.0',release_id=RELEASE,
        exported_at=datetime.now(timezone.utc).isoformat(),source_runs=RUNS,
        primary_token_scope='All harness API attempts only; simulator and judge are separate',
        raw_dialogues_included=False,reference_answers_included=False,credentials_included=False,
        source_hashes_identify='Frozen file bytes; source paths are relative to named source roots',
        optional_judge_quality='No judge calls means not applicable and accounting_complete=True'))
    index_path=out/'benchmarks/index.json';index=json.loads(index_path.read_text())
    index=[r for r in index if (r['benchmark'],r['release_id'])!=(BENCHMARK,RELEASE)]
    index.append(dict(benchmark=BENCHMARK,release_id=RELEASE,model=MODEL,relative_path=f'{BENCHMARK}/{RELEASE}',
        tasks=278,harnesses=list(HARNESS),rows=1390,scored_rows=1390,status='finished'))
    dump(index_path,index)
    print(json.dumps({'summary':summaries,'analysis_counts':{k:len(v) if isinstance(v,list) else v
        for k,v in analysis.items()},'requests':len(requests),'attempts':len(attempts)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--tau-root',type=Path,required=True)
    args=parser.parse_args()
    build(args.source_root.resolve(),args.output_root.resolve(),args.tau_root.resolve())
