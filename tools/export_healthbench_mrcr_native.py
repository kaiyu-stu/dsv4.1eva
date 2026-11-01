"""Publish numeric metadata only; never publish benchmark or model text."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
from pathlib import Path
import statistics

from export_mrcr import dump, table

HARNESSES = ['claude','codex','dsh','pi','zcode']
RELEASES = {
    'healthbench-professional':'dsv41flash-economy-t0-thinkmax-native-stratified200-s42-gpt61sol-partial-20261102-v1',
    'mrcr':'dsv41flash-economy-t0-native-fullcontext-stratified200-s20261030-coding-agentplan3-v1',
}
TOKENS = ['prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens']
JUDGE_TOKENS = ['input_tokens','output_tokens','total_tokens','cache_hit_input_tokens']


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().split('\n') if line.strip()] if path.exists() else []


def mean(rows,key):
    values = [r[key] for r in rows if r[key] is not None]
    return statistics.mean(values) if values else None


def export(source,root,benchmark):
    health = benchmark=='healthbench-professional'
    release = RELEASES[benchmark]
    base = root/'benchmarks'/benchmark/release
    base.mkdir(parents=True,exist_ok=True)
    sources = {}

    def fingerprint(path):
        sources[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()

    def load(path):
        fingerprint(path)
        return json.loads(path.read_text())

    def journal(run,harness,stage,kind='model'):
        path = run/('judge-requests.jsonl' if kind=='grader' else 'requests.jsonl')
        if not path.exists():return []
        fingerprint(path)
        events = read_jsonl(path)
        starts = {e['request_id']:e for e in events if e['event']=='start'}
        finishes = {e['request_id']:e for e in events if e['event']=='finish'}
        output = []
        for rid in sorted(starts.keys()|finishes.keys()):
            start,end = starts.get(rid,{}),finishes.get(rid,{})
            meta = start or end
            usage = end.get('usage') or {}
            fields = JUDGE_TOKENS if kind=='grader' else TOKENS
            item = dict(harness=harness,task_id=meta['sample_id'],request_id=rid,stage=stage,
                kind=kind,model=meta.get('model'),started_at_unix=start.get('time'),
                finished_at_unix=end.get('time'),http_status=end.get('http_status'),
                finish_reason=end.get('finish_reason'),transport_error_type=end.get('error_type'),
                start_record_present=bool(start),finish_record_present=bool(end),
                usage_present=bool(usage),accounting_complete=bool(start and end and usage),
                criterion_index=meta.get('criterion_index'),
                returned_model=end.get('returned_model'),
                **{k:usage.get(k) for k in fields})
            if kind=='model':
                item.update(temperature=meta.get('temperature'),thinking=meta.get('thinking'),
                    reasoning_effort=meta.get('reasoning_effort'),max_output_tokens=meta.get('max_tokens'),
                    reasoning_tokens=((usage.get('completion_tokens_details') or {}).get('reasoning_tokens')),
                    native_system_tokens_o200k=meta.get('system_tokens_o200k'),
                    native_input_tokens_o200k=meta.get('input_tokens_o200k'),tools_forwarded=meta.get('tools_forwarded'))
            output.append(item)
        return output

    configs,samples,requests,judges = {},[],[],[]
    selection_ref = None
    for h in HARNESSES:
        name = (f'healthbench-professional-ark-codingplan1-dsv41flash-economy-t0-thinkmax-r1-native-v1-subset200-seed42-{h}'
            if health else f'mrcr-agentplan3-continuation-t0-fullcontext-subset200-s20261030-v1-{h}')
        run = source/'runs'/name
        config = load(run/'experiment.json')
        selection = load(run/'selection.json')
        if selection_ref is None:selection_ref=selection
        assert selection==selection_ref and len(selection)==200
        allowed = ['model','ark_base_url','temperature','thinking','reasoning_effort','max_output_tokens',
            'timeout','n_repeats','tools','compression_policy','cli_version','dataset_sha256',
            'sampling','track','input_policy','history_policy','system_policy','implementation_sha256',
            'official_grader_sha256','length_adjustment_center','length_adjustment_penalty_per_500_chars']
        configs[h] = {k:config[k] for k in allowed if k in config}
        if health:
            configs[h]['grader'] = {k:v for k,v in config['grader'].items() if k!='api_key_env'}
            model_requests = journal(run,h,'codingplan')
            grader_requests = journal(run,h,'third_party_grader','grader')
        else:
            original = source/config['source_run']
            old_config = load(original/'experiment.json')
            configs[h]['original_codingplan'] = {k:old_config[k] for k in allowed if k in old_config}
            model_requests = journal(original,h,'codingplan')+journal(run,h,'agentplan3')
            grader_requests = []
        requests.extend(model_requests);judges.extend(grader_requests)
        model_groups,judge_groups = defaultdict(list),defaultdict(list)
        for q in model_requests:model_groups[q['task_id']].append(q)
        for q in grader_requests:judge_groups[q['task_id']].append(q)
        for row in selection:
            sid = row['sample_id'];folder = run/'samples'/sid
            result_path = folder/'result.json'
            result = load(result_path) if result_path.exists() else {}
            scored = result.get('status')=='completed'
            group = model_groups[sid];jg = judge_groups[sid]
            item = dict(task_id=sid,harness=h,model=config['model'],status='completed' if scored else 'unscored',
                score=result.get('length_adjusted_score') if health else result.get('score'),
                success=None if health or not scored else int(result['exact_match']),
                binary_label_available=not health and scored,
                answer_source=result.get('answer_source'),native_returncode=result.get('native_returncode'),
                output_truncated=result.get('output_truncated'),
                **{k:sum(q[k] or 0 for q in group) for k in TOKENS},
                token=sum(q['total_tokens'] or 0 for q in group),requests=len(group),
                usage_missing_requests=sum(not q['usage_present'] for q in group),
                accounting_gaps=sum(not(q['start_record_present'] and q['finish_record_present']) for q in group),
                accounting_complete=bool(group) and all(q['accounting_complete'] for q in group),
                grader_requests=len(jg),grader_input_tokens=sum(q['input_tokens'] or 0 for q in jg),
                grader_output_tokens=sum(q['output_tokens'] or 0 for q in jg),
                grader_total_tokens=sum(q['total_tokens'] or 0 for q in jg),
                grader_accounting_complete=all(q['accounting_complete'] for q in jg),
                explicit_compression_calls=0,compression_measurement='No ACON; native default context settings; no summary model was configured')
            if health:
                generation_path = folder/'generation.json'
                generation = load(generation_path) if generation_path.exists() else {}
                prediction_path = folder/'prediction.json'
                prediction = load(prediction_path) if prediction_path.exists() else {}
                recovery = prediction.get('recovery') or {}
                item.update(source_row=row['source_row'],dataset_id=row['dataset_id'],use_case=row['use_case'],
                    type=row['type'],difficulty=row['difficulty'],specialty=row['specialty'],
                    raw_score=result.get('raw_score'),response_characters=result.get('response_characters'),
                    rubric_items=result.get('rubric_items'),
                    original_generation_status=generation.get('status'),
                    original_error_type=generation.get('error_type'),
                    recovered=bool(recovery),recovery_policy=recovery.get('policy'),
                    recovery_request_id=recovery.get('request_id'),
                    recovery_raw_response_sha256=recovery.get('raw_response_sha256'),
                    generation_provider='codingplan',inherited=False)
            else:
                assert scored and isinstance(result.get('score'),(int,float))
                if result.get('inherited_from'):
                    inherited_path = source/result['inherited_from']
                    fingerprint(inherited_path)
                    assert sources[str(inherited_path.relative_to(source))]==result['inherited_sha256']
                item.update(needles=row['needles'],context_bin=row['bin'],source_file=row['file'],source_row=row['row'],
                    prompt_tokens_o200k=row['prompt_tokens_o200k'],answer_tokens_o200k=row['answer_tokens_o200k'],
                    generation_provider=result['generation_provider'],inherited=bool(result.get('inherited_from')),
                    inherited_result_sha256=result.get('inherited_sha256'),final_seconds=result.get('seconds'))
            samples.append(item)
    summaries = []
    for h in HARNESSES:
        rows = [r for r in samples if r['harness']==h];done=[r for r in rows if r['status']=='completed']
        summary = dict(harness=h,selected=len(rows),scored=len(done),unscored=len(rows)-len(done),
            mean_score=max(0,min(1,mean(done,'score'))) if health else mean(done,'score'),
            **{k:sum(r[k] for r in rows) for k in TOKENS},
            grader_total_tokens=sum(r['grader_total_tokens'] for r in rows),
            requests=sum(r['requests'] for r in rows),grader_requests=sum(r['grader_requests'] for r in rows),
            usage_missing_requests=sum(r['usage_missing_requests'] for r in rows),
            accounting_gaps=sum(r['accounting_gaps'] for r in rows),
            by_provider={k:dict(samples=len(g),mean_score=mean(g,'score')) for k in sorted({r['generation_provider'] for r in done})
                if (g := [r for r in done if r['generation_provider']==k])})
        if health:
            summary.update(raw_score=mean(done,'raw_score'),recovered=sum(r['recovered'] for r in rows),
                original_generation_failures=sum(r['original_generation_status']=='generation_error' for r in rows))
        else:
            summary.update(exact_correct=sum(r['success'] for r in done),exact_match_rate=mean(done,'success'),
                inherited=sum(r['inherited'] for r in rows))
        summaries.append(summary)
    task_ids = [r['sample_id'] for r in selection_ref]
    sample_map = {(r['harness'],r['task_id']):r for r in samples}
    matrix = []
    for sid in task_ids:
        item = dict(task_id=sid)
        for h in HARNESSES:
            r=sample_map[h,sid]
            for k in ['score','success','token','status','answer_source']:item[f'{h}_{k}']=r[k]
        matrix.append(item)
    common = [sid for sid in task_ids if all(sample_map[h,sid]['status']=='completed' for h in HARNESSES)]
    comparisons=[]
    for a,b in combinations(HARNESSES,2):
        ids = [sid for sid in task_ids if all(sample_map[h,sid]['status']=='completed' for h in [a,b])]
        diffs = [sample_map[a,sid]['score']-sample_map[b,sid]['score'] for sid in ids]
        pair = dict(harness_a=a,harness_b=b,shared_scored=len(ids),a_higher=sum(d>1e-12 for d in diffs),
            b_higher=sum(d< -1e-12 for d in diffs),equal=sum(abs(d)<=1e-12 for d in diffs),
            mean_absolute_score_difference=statistics.mean(abs(d) for d in diffs))
        if not health:
            pair.update(both_exact_correct=sum(sample_map[a,s]['success']==sample_map[b,s]['success']==1 for s in ids),
                both_not_exact=sum(sample_map[a,s]['success']==sample_map[b,s]['success']==0 for s in ids),
                exact_match_disagreement=sum(sample_map[a,s]['success']!=sample_map[b,s]['success'] for s in ids))
        comparisons.append(pair)
    analysis = dict(common_scored_tasks=common,common_scored_count=len(common),
        common_subset_scores={h:max(0,min(1,mean([sample_map[h,s] for s in common],'score'))) if health else mean([sample_map[h,s] for s in common],'score') for h in HARNESSES},
        pairwise=comparisons)
    table(base,'samples',samples);table(base,'requests',requests);table(base,'task-matrix',matrix)
    if health:table(base,'grader-requests',judges)
    dump(base/'summary.json',summaries);dump(base/'analysis.json',analysis)
    dump(base/'experiments.json',configs);dump(base/'subset-manifest.json',selection_ref)
    dump(base/'provenance/source-files.json',sources)
    title = 'HealthBench Professional：200 题，五组原生 harness（未完成快照）' if health else 'MRCR：200 题，五组原生 harness（Coding Plan + Agent Plan 续跑）'
    lines = [f'# {title}','',
        '仅发布逐题数值得分、用量、状态与来源哈希；不包含题目、医生回答、rubric 正文、模型输出、思考或失败轨迹。','',
        '|Harness|已评分 / 200|主分|模型全部尝试 token|裁判 token|',
        '|---|---:|---:|---:|---:|']
    for s in summaries:lines.append(f"|{s['harness']}|{s['scored']}/200|{s['mean_score']:.2%}|{s['total_tokens']:,}|{s['grader_total_tokens']:,}|")
    if health:
        lines += ['', '本快照 955/1000 条已评分，DSH 缺 43 条、ZCode 缺 2 条；未评分保留 null，不当作零分。',
            '主分是各题长度校正分平均后裁剪至 [0,1]，不是二元正确率。原始分、逐题校正分均保存；逐题分允许负数或超过 1。',
            '校正公式：raw - 0.0147 × ((回答字符数 - 2000) / 500)。',
            '200/525 按 use_case 比例分层，seed=42：consult 90、research 56、writing 54。每题一次，温度 0，thinking enabled，max 推理，单请求输出上限 131072、整题超时 1800 秒。',
            '五组作答均为 Ark Coding Plan 的 deepseek-v4.1-flash-economy，保留原生系统提示，禁用工具，不启用 ACON。',
            '裁判为第三方 api.dreamger.cc 的 gpt-6.1-sol，Responses、low 推理；沿用官方 rubric 提示和公式。此配置不同于官方 GPT-5.4 裁判，不能称为官方原配置复现；返回模型名由网关报告，无法独立核验后端身份。',
            'Claude 2 条、Codex 24 条从首次完整上游响应恢复，未重新生成。保留原生失败及恢复标记；已评分不等于原生 CLI 正常完成。',
            f"五组共同已评分题数 {len(common)}；公平比较可使用 analysis.json 的 common_subset_scores。原始各组分母不同，不能直接当作完整集排名。",
            'grader-requests 单独保存裁判请求用量；模型 token 包含失败和重试，不包含裁判。',
            '评分参考：https://github.com/openai/simple-evals/blob/main/healthbench_eval.py',
            '数据卡：https://huggingface.co/datasets/openai/healthbench-professional/blob/main/README.md']
    else:
        lines += ['', '五组均为 200/200。主分为官方前缀检查后的 SequenceMatcher 相似度；success 为补充的严格全文匹配，部分得分也可能有价值。',
            '按 needle 数量 × 长度桶 24 层抽样，seed=20261030；温度 0、thinking disabled、单请求输出上限 4096、超时 1800 秒、无工具。原始历史在网关注入，不测原生会话压缩。',
            '先用 Coding Plan，额度耗尽后用 Agent Plan 第三组凭证续跑；模型别名均为 deepseek-v4.1-flash-economy。每题标记 generation_provider，各组继承题数和新增题数不同，套餐端点差异可能影响比较；不应归因于单一变量。',
            '请求表合并原 Coding Plan 和 Agent Plan 两份账本，各仅一次。继承结果不重复计量，原目录失败请求和重试也入账。不要只采用续跑目录 summary 的 token，它不含旧请求。',
            'by_provider 给出不同题集的分组均值，不能将其解释为两个 provider 的受控对照。',
            '此发布独立于之前 DeepSeek 官方 API deepseek-flash 的 200 题直接调用基线。',
            '评分参考：https://huggingface.co/datasets/openai/mrcr/blob/main/README.md']
    lines += ['', '输入 token 已包含缓存命中；prompt_cache_hit_tokens + prompt_cache_miss_tokens = prompt_tokens。缺失 usage 为未知，汇总仅是已观测下界，不推算实际费用。',
        '未做明确摘要调用，不把完整输入 token 等同于压缩前后 token；native context 设置不能据此推导压缩节省。',
        '字段：samples 为逐题，requests 为逐请求，task-matrix 为同题五组对比，analysis 为共同题集与两两分歧，experiments 为无密钥的配置白名单，provenance 为私有源文件哈希。','']
    (base/'README.md').write_text('\n'.join(lines))
    checks = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(base)}" for p in sorted(base.rglob('*')) if p.is_file() and p.name!='SHA256SUMS']
    (base/'SHA256SUMS').write_text('\n'.join(checks)+'\n')
    index_path=root/'benchmarks/index.json';index=json.loads(index_path.read_text())
    index=[r for r in index if r['release_id']!=release]
    index.append(dict(benchmark=benchmark,release_id=release,relative_path=f'{benchmark}/{release}',
        model='deepseek-v4.1-flash-economy',tasks=200,harnesses=HARNESSES,rows=len(samples),
        scored_rows=sum(s['scored'] for s in summaries),status='partial_snapshot' if health else 'finished',
        binary_labels_available=not health,primary_metric='length_adjusted_score' if health else 'mean_score',
        track='native_no_tools_reference_grading' if health else 'native_fullcontext_codingplan_agentplan3_continuation',
        snapshot_date='2026-11-02'))
    dump(index_path,index)
    print(benchmark,[(s['harness'],s['scored'],round(s['mean_score'],6),s['total_tokens']) for s in summaries])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    for benchmark in RELEASES:export(args.source_root,args.output_root,benchmark)
