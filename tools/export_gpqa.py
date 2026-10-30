"""Export GPQA measurement metadata; retain native errors and label API recovery."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import shutil

HARNESSES = ['claude', 'codex', 'dsh', 'pi', 'zcode']
FIELDS = ['prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens']
RELEASE = 'deepseek-flash-t0-native-notools-q198-r1-s0-v1'


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def tables(base, name, rows):
    (base/(name+'.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    with (base/(name+'.csv')).open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def export(source, root):
    base = root/'benchmarks/gpqa-diamond'/RELEASE
    base.mkdir(parents=True, exist_ok=True)
    sources = {}

    def load(path):
        data = path.read_bytes()
        sources[str(path.relative_to(source))] = hashlib.sha256(data).hexdigest()
        return json.loads(data)

    samples, requests, configs = [], [], {}
    selection_reference = None
    canonical_answers = {}
    for h in HARNESSES:
        run = source/'runs'/f'gpqa-diamond-deepseek-flash-native-notools-t0-disabled-q198-r1-s0-v1-{h}'
        config = load(run/'experiment.json')
        selection = load(run/'selection.json')
        if selection_reference is None:
            selection_reference = selection
        assert selection == selection_reference
        assert len(selection) == 198 and [s['source_row'] for s in selection] == list(range(198))
        assert all(s['repeat'] == 1 for s in selection)
        configs[h] = {k:config[k] for k in ['model', 'base_url', 'temperature', 'thinking', 'max_output_tokens',
            'timeout', 'n_repeats', 'seed', 'num_questions', 'dataset_sha256', 'cli_version', 'protocol_files_sha256']}
        journal = run/'requests.jsonl'
        data = journal.read_bytes()
        sources[str(journal.relative_to(source))] = hashlib.sha256(data).hexdigest()
        events = [json.loads(l) for l in data.decode().splitlines() if l.strip()]
        starts = {e['request_id']:e for e in events if e['event'] == 'start'}
        finishes = {e['request_id']:e for e in events if e['event'] == 'finish'}
        assert starts.keys() == finishes.keys()
        grouped = defaultdict(list)
        for rid, start in starts.items():
            end = finishes[rid]; usage = end.get('usage') or {}
            assert end['http_status'] == 200 and usage
            assert start['temperature'] == 0 and start['thinking'] == 'disabled' and start['tools_forwarded'] == 0
            row = dict(harness=h, task_id=start['sample_id'], request_id=rid,
                started_at_unix=start['time'], finished_at_unix=end['time'],
                http_status=end['http_status'], finish_reason=end['finish_reason'],
                usage_present=True, **{k:usage[k] for k in FIELDS},
                system_tokens_o200k=start['system_tokens_o200k'], native_tools_count=start['native_tools_count'],
                tools_forwarded=start['tools_forwarded'])
            assert row['total_tokens'] == row['prompt_tokens'] + row['completion_tokens']
            assert row['prompt_tokens'] == row['prompt_cache_hit_tokens'] + row['prompt_cache_miss_tokens']
            requests.append(row); grouped[row['task_id']].append(row)
        for s in selection:
            sid = s['sample_id']; folder = run/'samples'/sid
            result = load(folder/'result.json'); reqs = grouped[sid]
            recovered = result['status'] != 'completed'
            score = result.get('score'); letter = result.get('extracted_answer')
            scoring_source = result.get('answer_source', 'native_final')
            if recovered:
                assert h in ['codex', 'pi'] and len(reqs) == 1
                raw = load(folder/'wire'/reqs[-1]['request_id']/'chat-response.json')
                answer = raw['choices'][0]['message'].get('content') or ''
                stream = sorted(folder.glob('attempts/*/stream.jsonl'))[-1]
                sources[str(stream.relative_to(source))] = hashlib.sha256(stream.read_bytes()).hexdigest()
                native = [json.loads(l) for l in stream.read_text().split('\n') if l.strip()]
                if h == 'codex':
                    assert any('missing field `reasoning_tokens`' in e.get('message', '') for e in native)
                    emitted = [e['item'].get('text', '') for e in native
                        if e.get('type') == 'item.completed' and e.get('item', {}).get('type') == 'agent_message']
                    scoring_source = 'recorded_native_text_after_responses_schema_error'
                else:
                    emitted = [''.join(b.get('text', '') for b in e['message'].get('content', []))
                        for e in native if e.get('type') == 'message_end' and e.get('message', {}).get('role') == 'assistant'
                        and e['message'].get('stopReason') == 'stop']
                    scoring_source = 'recorded_native_message_without_agent_end'
                assert any(t.strip() == answer.strip() for t in emitted), (h, sid)
                match = re.search(config['answer_pattern'], answer)
                letter = match.group(1) if match else None
                score = int(letter == result['correct_answer'])
            assert score in (0, 1)
            canonical_answers[h, sid] = s['permutation']['ABCD'.index(letter.upper())] if letter and letter.upper() in 'ABCD' else None
            samples.append(dict(task_id=sid, question_id=s['question_id'], source_row=s['source_row'],
                repeat=1, domain=s['domain'], subdomain=s['subdomain'], harness=h,
                native_checkpoint_status=result['status'], native_returncode=result.get('native_returncode'),
                score=score, success=score, label='correct' if score else 'incorrect',
                scoring_source=scoring_source, recovered_from_recorded_text=recovered,
                parse_failed=letter is None, model_requests=len(reqs), extra_model_requests=len(reqs)-1,
                output_truncated=any(q['finish_reason'] == 'length' for q in reqs),
                **{k:sum(q[k] for q in reqs) for k in FIELDS}, token=sum(q['total_tokens'] for q in reqs),
                accounting_complete=True, compression_calls=0))
    summary = []
    for h in HARNESSES:
        rows = [r for r in samples if r['harness'] == h]
        summary.append(dict(harness=h, samples=len(rows), scored_samples=len(rows), correct=sum(r['score'] for r in rows),
            accuracy=sum(r['score'] for r in rows)/len(rows),
            native_checkpoint_statuses=dict(Counter(r['native_checkpoint_status'] for r in rows)),
            native_returncodes=dict(Counter(str(r['native_returncode']) for r in rows)),
            recovered_from_recorded_text=sum(r['recovered_from_recorded_text'] for r in rows),
            model_requests=sum(r['model_requests'] for r in rows),
            output_truncated_samples=sum(r['output_truncated'] for r in rows),
            parse_failures=sum(r['parse_failed'] for r in rows),
            **{k:sum(r[k] for r in rows) for k in FIELDS}, accounting_complete=True))
    matrix = []
    lookup = {(r['harness'],r['task_id']):r for r in samples}
    for s in selection_reference:
        row = dict(task_id=s['sample_id'], source_row=s['source_row'], domain=s['domain'])
        for h in HARNESSES:
            r = lookup[h, s['sample_id']]
            row.update({h+'_success':r['success'], h+'_token':r['token'], h+'_recovered':r['recovered_from_recorded_text']})
        matrix.append(row)
    pairwise = []
    for a,b in combinations(HARNESSES,2):
        pairs = [(lookup[a,s['sample_id']],lookup[b,s['sample_id']]) for s in selection_reference]
        pairwise.append(dict(harness_a=a,harness_b=b,
            both_correct=sum(x['score'] == y['score'] == 1 for x,y in pairs),
            both_wrong=sum(x['score'] == y['score'] == 0 for x,y in pairs),
            only_a_correct=sum(x['score'] == 1 and y['score'] == 0 for x,y in pairs),
            only_b_correct=sum(x['score'] == 0 and y['score'] == 1 for x,y in pairs),
            same_valid_answer=sum(canonical_answers[a,s['sample_id']] is not None and
                canonical_answers[a,s['sample_id']] == canonical_answers[b,s['sample_id']] for s in selection_reference)))
    tables(base,'samples',samples); tables(base,'requests',requests)
    tables(base,'task-matrix',matrix); tables(base,'pairwise',pairwise)
    dump(base/'summary.json',summary)
    dump(base/'experiment.json',dict(harness_configs=configs, same_selection_and_option_order_verified=True,
        selection_file_sha256=hashlib.sha256((source/'runs/gpqa-diamond-deepseek-flash-native-notools-t0-disabled-q198-r1-s0-v1-claude/selection.json').read_bytes()).hexdigest(),
        option_order_policy='random.Random(0), one permutation per CSV row; identical across harnesses',
        tools_forwarded=False, compression=False, primary_metric='single-answer accuracy, official simple-evals first regex match',
        raw_reasoning_token_breakdown='not reported; unknown, never inferred from transport compatibility defaults'))
    dump(base/'provenance/source-files.json',sources)
    dump(base/'provenance/recovery.json',dict(original_checkpoints_modified=False, new_model_requests=0,
        recovered_codex=195,recovered_pi=1,
        verification='Recorded native assistant text equals stored upstream content after outer whitespace stripping',
        codex_fix='Responses output_tokens_details.reasoning_tokens requires an integer; missing upstream detail receives transport-only compatibility default 0',
        validation='Real pinned Codex CLI returned native success on mocked upstream response lacking reasoning breakdown; no paid API call',
        raw_reasoning_usage='Unreported, unknown; compatibility integer is not an observed upstream measurement'))
    lines = ['# GPQA Diamond：198 题，每题一次，五组原生 Harness','',
        'DeepSeek 官方 API `deepseek-flash`，temperature=0、thinking=disabled，每次请求输出上限 4096 tokens；各组并发 3。',
        '从 CSV 第 0 行开始覆盖全部 198 题，seed=0，各组题目和选项顺序逐条相同。保留原生系统提示，无工具，无压缩。',
        '评分使用 OpenAI simple-evals 提示模板与首个 Answer: A/B/C/D 正则匹配；不重复、不投票。', '',
        '|Harness|已评分|正确|正确率|输入 tokens|输出 tokens|总 tokens|缓存命中输入|请求数|从已有文本恢复评分|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"|{r['harness']}|{r['scored_samples']}|{r['correct']}|{r['accuracy']:.2%}|{r['prompt_tokens']:,}|{r['completion_tokens']:,}|{r['total_tokens']:,}|{r['prompt_cache_hit_tokens']:,}|{r['model_requests']}|{r['recovered_from_recorded_text']}|")
    lines += ['', '输入包含缓存命中，不重复相加；总量包含原生自动续写的全部调用。所有上游请求 HTTP 200，均保存完整 usage。没有按 token 单价推算实际账单。', '',
        '## 协议异常与评分恢复', '',
        'Codex 有 195 次在收到回答文本后，因 Responses 适配器缺少必需的 reasoning_tokens 字段而退出。3 次触及输出上限的作答已被原脚本按截断文本评分。',
        'Pi 有 1 次已收到正常结束的 assistant message，但缺少脚本期待的 agent_end 事件，未写入最终评分。',
        '本发布核验这些样本的原生 CLI 已输出文本与保存的 API 回答完全一致（仅忽略外侧空白），按同一官方正则恢复评分；没有重新调用模型，也未改写原始 checkpoint。',
        '因此表中是已生成答案的正确率，不是 CLI 无故障完成率。samples 明确保留 native_checkpoint_status、native_returncode、scoring_source 与 recovered_from_recorded_text。涉及恢复的 Codex 结果不宜直接解释为稳定的原生端到端完成成绩。',
        '本地适配器已修复 Responses 必需整数的兼容默认值。该默认 0 只服务传输协议，不表示上游实测 reasoning tokens=0；计量始终使用原始 DeepSeek usage。', '',
        '## 数据', '',
        '- `samples.csv/jsonl`：990 条逐题分数、原生状态、恢复标记与完整 token。',
        '- `requests.csv/jsonl`：每个实际 API 请求的时间、用量、缓存与结束原因。',
        '- `task-matrix.csv/jsonl`：同题五组正误与 token 对照。',
        '- `pairwise.csv/jsonl`：两两都对、都错及独有答对。',
        '- `experiment.json`：版本、参数、数据哈希与跨组顺序校验。',
        '- `provenance/source-files.json`、`SHA256SUMS`：来源与发布文件校验和。', '',
        '只发布测量元数据；不含题目正文、标准答案、模型回答、错误堆栈、凭证或原始失败轨迹。恢复标记保留在元数据中，防止隐藏基础设施问题。']
    (base/'README.md').write_text('\n'.join(lines)+'\n')
    (base/'SHA256SUMS').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(base))+'\n'
        for p in sorted(base.rglob('*')) if p.is_file() and p.name!='SHA256SUMS'))
    # Preserve the previously completed pilot as a separate release.
    pilot = root/'benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q10-r10-s0-v1'
    pilot.mkdir(parents=True,exist_ok=True)
    for name in ['report.md','summary.json','per-question.csv','pairwise.csv','sample-metrics.csv']:
        shutil.copyfile(source/'results/gpqa-diamond-five-harness-t0-q10-r10-s0-v1'/name,pilot/name)
    shutil.copyfile(pilot/'report.md',pilot/'README.md')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=p.parse_args()
    export(args.source_root.resolve(),args.repo_root.resolve())
