"""Export MRCR scores and usage metadata, without prompts, answers or responses."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics

RELEASE = 'deepseek-flash-t0-direct-stratified200-s20261030-v1'
RUN = 'mrcr-deepseek-flash-api-t0-disabled-stratified200-s20261030-v1'
TOKEN_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens',
                'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens')


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def table(base, name, rows):
    (base/f'{name}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    with (base/f'{name}.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def stats(values):
    ordered = sorted(values)
    return dict(min=min(values), mean=statistics.mean(values), median=statistics.median(values),
                p90=ordered[max(0, (len(ordered)*90+99)//100-1)],
                p95=ordered[max(0, (len(ordered)*95+99)//100-1)], max=max(values))


def aggregate(rows):
    return dict(samples=len(rows), exact_correct=sum(r['success'] for r in rows),
        exact_incorrect=sum(1-r['success'] for r in rows),
        partial_score=sum(0<r['score']<1 for r in rows), zero_score=sum(r['score']==0 for r in rows),
        mean_score=statistics.mean(r['score'] for r in rows),
        exact_match_rate=statistics.mean(r['success'] for r in rows),
        **{k:sum(r[k] for r in rows) for k in TOKEN_FIELDS},
        complete_accounting_samples=sum(r['accounting_complete'] for r in rows))


def export(source, root):
    run = source/'runs'/RUN
    base = root/'benchmarks/mrcr'/RELEASE
    base.mkdir(parents=True, exist_ok=True)
    sources = {}

    def read(path):
        content = path.read_bytes()
        sources[str(path.relative_to(source))] = hashlib.sha256(content).hexdigest()
        return json.loads(content)

    config = read(run/'experiment.json')
    selection = read(run/'selection.json')
    manifest = read(source/'manifests/mrcr-stratified200-seed20261030.json')
    journal_path = run/'requests.jsonl'
    sources[str(journal_path.relative_to(source))] = hashlib.sha256(journal_path.read_bytes()).hexdigest()
    events = [json.loads(line) for line in journal_path.read_text().splitlines() if line.strip()]
    starts = {e['request_id']:e for e in events if e['event']=='start'}
    finishes = {e['request_id']:e for e in events if e['event']=='finish'}
    assert starts.keys()==finishes.keys(), 'In-flight requests: wait for completion before exporting'
    requests = []
    for request_id, start in starts.items():
        finish = finishes[request_id]
        usage = finish.get('usage') or {}
        requests.append(dict(request_id=request_id, task_id=start['sample_id'],
            status=finish['status'], started_at_unix=start['time'], finished_at_unix=finish['time'],
            seconds=finish['time']-start['time'], usage_present=bool(usage),
            **{k:usage.get(k) for k in TOKEN_FIELDS}))
    request_groups = defaultdict(list)
    for request in requests:
        request_groups[request['task_id']].append(request)
    samples = []
    for row in selection:
        folder = run/'samples'/row['sample_id']
        result = read(folder/'result.json')
        assert result['status']=='completed'
        group = request_groups[row['sample_id']]
        attempt_statuses = []
        for path in sorted((folder/'attempts').glob('*/result.json')):
            attempt_statuses.append(read(path)['status'])
        assert len(attempt_statuses)==len(group)
        samples.append(dict(task_id=row['sample_id'], harness='direct_api', model=config['model'],
            needles=row['needles'], context_bin=row['bin'], source_file=row['file'], source_row=row['row'],
            status=result['status'], score=result['score'], success=int(result['exact_match']),
            label='correct' if result['exact_match'] else 'incorrect',
            score_category='full' if result['score']==1 else 'zero' if result['score']==0 else 'partial',
            prompt_tokens_o200k=row['prompt_tokens_o200k'], answer_tokens_o200k=row['answer_tokens_o200k'],
            **{k:sum(q[k] or 0 for q in group) for k in TOKEN_FIELDS},
            token=sum(q['total_tokens'] or 0 for q in group),
            requests=len(group), retries=max(0,len(group)-1),
            usage_missing_requests=sum(not q['usage_present'] for q in group),
            accounting_complete=all(q['usage_present'] for q in group),
            final_attempt_total_tokens=result['usage']['total_tokens'],
            final_attempt_seconds=result['seconds'], observed_request_seconds=sum(q['seconds'] for q in group),
            finish_reason=result['finish_reason'], output_truncated=result['output_truncated'],
            compression_calls=0, summary_input_tokens=0, summary_output_tokens=0))
    assert len(samples)==200 and len({r['task_id'] for r in samples})==200
    summary = dict(aggregate(samples), model=config['model'], track=config['track'],
        model_requests=len(requests), usage_missing_requests=sum(not r['usage_present'] for r in requests),
        accounting_gaps=0, accounting_complete=all(r['usage_present'] for r in requests),
        recorded_request_statuses=dict(Counter(r['status'] for r in requests)),
        output_truncated_samples=sum(r['output_truncated'] for r in samples),
        input_tokens_o200k=sum(r['prompt_tokens_o200k'] for r in samples),
        cache_hit_rate=sum(r['prompt_cache_hit_tokens'] for r in samples)/sum(r['prompt_tokens'] for r in samples),
        token_statistics={k:stats([r[k] for r in samples]) for k in TOKEN_FIELDS},
        final_latency_seconds=stats([r['final_attempt_seconds'] for r in samples]),
        billing_note='Recorded API usage only; one failed request has unknown usage. No price or bill inferred.',
        primary_metric='mean_score: official prefix guard followed by SequenceMatcher ratio',
        binary_label='success = strict full-string exact match, supplemental to official score')
    grouped = {}
    for field in ('needles','context_bin','score_category'):
        keys = sorted({r[field] for r in samples},
            key=(lambda value: int(value.split('k')[0])) if field=='context_bin' else None)
        grouped[field] = {str(key):aggregate([r for r in samples if r[field]==key])
                          for key in keys}
    grouped['stratum'] = {f'{n}needle/{b}':aggregate([r for r in samples if r['needles']==n and r['context_bin']==b])
        for n in (2,4,8) for b in [f'{2**i}k-{2**(i+1)}k' for i in range(2,10)]}
    table(base, 'samples', samples)
    table(base, 'requests', requests)
    dump(base/'summary.json', summary)
    dump(base/'grouped-summary.json', grouped)
    dump(base/'subset-manifest.json', manifest)
    config.pop('subset_manifest', None)
    config['subset_manifest'] = 'subset-manifest.json'
    dump(base/'experiment.json', config)
    for relative in ('scripts/run_mrcr_deepseek.py','scripts/test_mrcr_deepseek.py'):
        path=source/relative
        sources[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    dump(base/'provenance/source-files.json', sources)
    lines = ['# MRCR：DeepSeek Flash，分层 200 题，完整上下文 API 基线','',
        '**200/200 完成**。官方平均相似度得分 **62.43%**；严格全文匹配 **80/200（40.00%）**。',
        '102 题部分得分、18 题零分。严格匹配失败 120 题中包含上述部分得分题，不能把官方得分误写为二元正确率。','',
        '## 设置与可复现性','',
        '- API：`https://api.deepseek.com`，模型请求名 `deepseek-flash`；不是 Ark 路由。',
        '- temperature=0、thinking=disabled、max_tokens=4096、并发 3、单次请求 timeout=600 秒。',
        '- 原始 user/assistant 历史直接发送，无追加系统提示词、工具或检索，不使用 harness/ACON 压缩。',
        '- 原始 2,400 题；按 o200k 分桶及 prompt ≤1,000,000 的容量筛选后，2,368 题可选。',
        '- 按 2/4/8 needle × 8 个长度桶，共 24 层按题量比例无放回抽 200 题，每层 8–9 题。',
        '- 固定 seed=20261030；最大余数法分配题量，样本 ID、各层数量及数据 SHA-256 见抽样清单。',
        '- 长度分桶为全部消息 content 的 o200k tokens 加标准答案 tokens；API 用量采用 DeepSeek 返回值。',
        '- 评分先检查模型输出是否以要求的随机前缀开头，否则 0 分；去掉前缀后以 SequenceMatcher 比较。',
        '- 不裁剪空白，不自动修复前缀。二元 `success` 仅表示输出与标准答案逐字符完全相同。',
        '- 输出截断 0 题；已完成的零分/错误题不重跑。一次连接异常重试成功，最终所有题目均已评分。','',
        '[OpenAI 官方数据集与评分示例](https://huggingface.co/datasets/openai/mrcr)。官方示例未显式设置温度、输出上限或 thinking；这些是本实验参数。','',
        '## Token 与请求计量','',
        '|统计项|值|','|---|---:|']
    metrics = [('已记录 API 请求',summary['model_requests']),('返回 usage 的请求',summary['model_requests']-summary['usage_missing_requests']),
        ('未返回 usage 的异常请求',summary['usage_missing_requests']),('输入 token（含缓存命中）',summary['prompt_tokens']),
        ('缓存命中输入 token',summary['prompt_cache_hit_tokens']),('非缓存输入 token',summary['prompt_cache_miss_tokens']),
        ('输出 token',summary['completion_tokens']),('合计 token',summary['total_tokens']),
        ('逐题输入 o200k token 总和',summary['input_tokens_o200k'])]
    lines += [f'|{label}|{value:,}|' for label,value in metrics]
    lines += ['',f"缓存命中比例 **{summary['cache_hit_rate']:.2%}**；每题平均已记录 token **{summary['total_tokens']/200:,.2f}**。",
        '**这些用量是 API 已观测下界**：201 次请求包含 200 次成功和 1 次未返回 usage 的连接异常，异常请求是否计费及用量未知，不能按 0 token 断言。',
        '200 个最终成功响应均有 usage；199 题全部尝试计量完整，1 题的历史异常尝试缺失 usage。不存在未闭合的请求日志。',
        '缓存命中属于输入 token 的一部分，不能再次累加。未获取实际账单或匹配本次官方 API 的费率，不从 Ark 套餐价格推算费用。',
        '本实验不压缩，因此摘要模型调用、摘要输入和摘要输出均为 0；不存在可比较的压缩前后 token 节省。',
        'o200k 输入是离线 content 统计，DeepSeek prompt_tokens 是 API 计量，二者不应混用。','',
        '|每题 token|最小|均值|中位数|P90|P95|最大|','|---|---:|---:|---:|---:|---:|---:|']
    for field in ('prompt_tokens','completion_tokens','total_tokens'):
        s=summary['token_statistics'][field]
        lines.append('|'+field+'|'+'|'.join(f'{s[k]:,.2f}' for k in ('min','mean','median','p90','p95','max'))+'|')
    lines += ['', 'P90/P95 使用 nearest-rank；逐题 token 汇总所有已知尝试，缺失 usage 不进行估算。','', '## 分组结果','']
    for name, field in [('按 needle 数量','needles'),('按上下文长度','context_bin'),('按得分类别','score_category'),('24 个分层','stratum')]:
        lines += [f'### {name}','','|分组|题数|严格正确 / 错误|部分分 / 零分|官方均分|严格匹配率|输入 token|输出 token|总 token|',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for key,s in grouped[field].items():
            lines.append(f"|{key}|{s['samples']}|{s['exact_correct']} / {s['exact_incorrect']}|{s['partial_score']} / {s['zero_score']}|{s['mean_score']:.2%}|{s['exact_match_rate']:.2%}|{s['prompt_tokens']:,}|{s['completion_tokens']:,}|{s['total_tokens']:,}|")
        lines.append('')
    lines += ['## 数据文件与字段','',
        '- [samples.csv](samples.csv) / [samples.jsonl](samples.jsonl)：200 题逐题分数、二元正误、长度、输入/输出/缓存 token、重试与计量完整性。',
        '- [requests.csv](requests.csv) / [requests.jsonl](requests.jsonl)：201 次请求的时间、状态与 usage 数值；未知 usage 为 null。',
        '- [summary.json](summary.json) / [grouped-summary.json](grouped-summary.json)：整体、分组和分位数统计。',
        '- [subset-manifest.json](subset-manifest.json) / [experiment.json](experiment.json)：固定抽样与无凭证的实验参数。',
        '- [provenance/source-files.json](provenance/source-files.json) / [SHA256SUMS](SHA256SUMS)：私有来源文件指纹与公开文件校验和。','',
        '`score` 为官方相似度得分；`success` / `label` 为严格全文匹配正误；`token` = `total_tokens` 为所有已知尝试用量。',
        '`prompt_cache_hit_tokens` + `prompt_cache_miss_tokens` = `prompt_tokens`；总用量 = 输入 + 输出。',
        '`accounting_complete=false` 表示存在未知用量；不应将其作为完整成本标签训练 router。',
        '`prompt_tokens_o200k` / `answer_tokens_o200k` 只用于数据分桶和复现，不表示计费。',
        '`final_attempt_seconds` 是最后成功调用耗时；`observed_request_seconds` 是逐请求耗时之和，不是并发运行的墙钟时间。',
        '题目 ID、正误与评分覆盖全部 200 题；不包含任何题目正文、标准答案、模型回答、原始失败案例、HTTP 错误正文或密钥。','',
        '## 导出与校验','',
        '```bash','python tools/export_mrcr.py --source-root /path/to/HarnessCompressionBench',
        'python tools/build_index_report.py','python tools/validate_release.py','```','',
        '这组是官方方式的直接 API 基线，不能当作五种 harness 的对比结果，也没有压缩策略差异可供比较。']
    (base/'README.md').write_text('\n'.join(lines)+'\n')
    (base/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(base)}\n'
        for p in sorted(base.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
    index_path=root/'benchmarks/index.json'
    index=json.loads(index_path.read_text())
    record=dict(benchmark='mrcr', release_id=RELEASE, model=config['model'], relative_path=f'mrcr/{RELEASE}',
        tasks=200, harnesses=['direct_api'], rows=200, scored_rows=200, status='finished',
        primary_metric='mean_score', track='direct_api_uncompressed')
    index=[r for r in index if not (r['benchmark']=='mrcr' and r['release_id']==RELEASE)]+[record]
    dump(index_path,index)
    print(f'Exported {base}: 200 samples, {len(requests)} requests, {summary["total_tokens"]:,} known tokens')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    export(args.source_root.resolve(),args.output_root.resolve())
