"""Build the multi-benchmark landing page without rewriting release artifacts."""
import json
from pathlib import Path


def build(root):
    index=json.loads((root/'benchmarks/index.json').read_text())
    lines=['# DS V4.1 评测数据：原生 Harness 与直接 API 基线','',
        '记录 DeepSeek V4.1 在不同 benchmark 上的逐题得分、正误与 token。原生 harness 对比和直接 API 基线分开发布。',
        '不同 benchmark 和实验版本独立保存；后续结果继续追加，不覆盖历史发布。','',
        '|Benchmark|任务 × Harness|二元标签|说明与数据|','|---|---:|---:|---|']
    for r in index:
        name={'terminal-bench-2.0':'Terminal-Bench 2.0','tau2-bench':'tau2-bench'}.get(r['benchmark'],r['benchmark'])
        lines.append(f"|{name}|{r['tasks']} × {len(r['harnesses'])} = {r['rows']}|{r['scored_rows']}|"
                     f"[{r['release_id']}](benchmarks/{r['relative_path']}/README.md)|")
    lines+=['','Terminal/tau2 使用 Ark 模型别名 `deepseek-v4.1-flash-economy`、temperature=0 和各 harness 原生上下文管理，未指定统一压缩阈值。',
        '这两组 Claude/Codex/DSH 使用 Coding Plan，Pi/ZCode 使用 Agent Plan。',
        'MRCR 使用 DeepSeek 官方 API 的 `deepseek-flash`，完整上下文直接调用，不压缩。各实验预算和评分规则分别见说明。','']
    for r in index:
        summaries=json.loads((root/'benchmarks'/r['relative_path']/'summary.json').read_text())
        if r['benchmark']=='mrcr':
            s=summaries
            path=f"benchmarks/{r['relative_path']}"
            lines += ['## MRCR：直接 API，分层 200 题','',
                f"**{s['samples']}/200 完成**。官方平均相似度得分 **{s['mean_score']:.2%}**；严格全文匹配 **{s['exact_correct']}/200（{s['exact_match_rate']:.2%}）**。",
                f"部分得分 {s['partial_score']} 题、零分 {s['zero_score']} 题。",
                f"已记录输入 **{s['prompt_tokens']:,}**、输出 **{s['completion_tokens']:,}**，合计 **{s['total_tokens']:,} token**。",
                '201 次请求中 1 次连接异常未返回 usage，重试后 200 题均完成；未知用量未估算，总 token 为已观测下界。',
                '按 needle 数量 × 长度桶共 24 层比例抽样，seed=20261030；不上传任务正文、答案、模型输出或失败案例。','',
                f'[详细报告]({path}/README.md) · [逐题 CSV]({path}/samples.csv) · [JSONL]({path}/samples.jsonl) · [固定抽样清单]({path}/subset-manifest.json)','']
            continue
        name={'terminal-bench-2.0':'Terminal-Bench 2.0','tau2-bench':'tau2-bench'}.get(r['benchmark'],r['benchmark'])
        lines += [f'## {name}','',
            '|Harness|成功 / 已评分|成功率|Harness 已观测 token|API 等价 USD*|',
            '|---|---:|---:|---:|---:|']
        for s in summaries:
            lines.append(f"|{s['harness_name']}|{s['correct']}/{s['scored_samples']}|{s['success_rate_scored']:.2%}|"
                         f"{s['total_tokens']:,}|${s['payg_known_start_time_estimate_usd']:.4f}|")
        total=sum(s['total_tokens'] for s in summaries)
        dollars=sum(s['payg_known_start_time_estimate_usd'] for s in summaries)
        lines+=['',f'主 harness 合计 **{total:,} token**，已知 token 的按量等价估算 **${dollars:.4f}**。']
        if r['benchmark']=='tau2-bench':
            e2e=sum(s['end_to_end_tokens'] for s in summaries)
            e2e_cost=sum(s['end_to_end_payg_known_start_time_estimate_usd'] for s in summaries)
            lines += [f'**无整题时间上限**，官方 orchestrator 最多 200 步、10 次工具错误；airline 50、retail 114、telecom 114。',
                f'模拟用户/评判器分别计量，包含它们的总消耗为 **{e2e:,} token**、API 等价约 **${e2e_cost:.4f}**。',
                '五组均为 278/278；其中 29 条是原生正常提前结束的零分标签，单独标记，区别于官方轨迹评分。']
        if r['benchmark']=='terminal-bench-2.0':
            lines += ['每题 agent 预算 **1200 秒**。Pi 有 1 题 exit 137 未评分，保留空标签；全题集已解决比例为 37/89。']
        lines += ['',f"[逐样本 CSV](benchmarks/{r['relative_path']}/samples.csv) · "
            f"[JSONL](benchmarks/{r['relative_path']}/samples.jsonl) · "
            f"[同题正误矩阵](benchmarks/{r['relative_path']}/task-matrix.csv) · "
            f"[Router 数据](benchmarks/{r['relative_path']}/router-data.csv)",'']
    lines += ['## 费用与计量','',
        '**美元是按公开 token 单价、缓存命中与请求开始时间近似折算的 API 等价成本，不是实际套餐账单。**',
        'Terminal/tau2 各组存在部分计量不完整记录；费用只覆盖已知 token。完整费率、汇率及假设保存在对应 release 的 `pricing.json`。MRCR 仅发布已记录 token，不推算费用。',
        '官方峰谷按完成时间划分，现有日志只可靠保留开始时间，因此另提供全闲时/全高峰统一费率重算。',
        '主 token 包含所有尝试；比较最终一次执行可使用 `final_attempt_token`。模拟用户/评判器不计入主 token。','',
        '## 复用','',
        '[字段说明](docs/DATA_FORMAT.md) · [追加 benchmark](docs/ADDING_BENCHMARKS.md) · [机器可读目录](benchmarks/index.json)','',
        '只需 Python 标准库即可读取与校验：','',
        '```python','import json','from pathlib import Path',
        'catalog = json.loads(Path("benchmarks/index.json").read_text())',
        'release = next(r for r in catalog if r["benchmark"] == "tau2-bench")',
        'p = Path("benchmarks") / release["relative_path"] / "samples.jsonl"',
        'rows = [json.loads(line) for line in p.open()]',
        'usable = [r for r in rows if r["router_eligible_complete_tokens"]]',
        'pairs = [(r["task_id"], r["harness"], r["token"], r["success"]) for r in usable]',
        '```','',
        '`python tools/validate_release.py` 验证已发布数据的请求、样本、汇总与文件校验和。',
        '按 `benchmark, task_id` 划分训练/测试，同题五组必须放在同一分区；不能把空标签改为 0。','',
        '## 使用与引用','',
        '欢迎复用导出的实验测量数据，请引用仓库 URL、release 和固定 commit，见 [CITATION.cff](CITATION.cff)。',
        '本仓库不重新授权上游任务、答案或 harness 代码；它们遵循各自原始许可。',
        '数据包不含任务正文、标准答案、模型对话、凭证或完整评测环境。','',
        '**English:** Sample-level evaluation data for DeepSeek V4.1 Flash: native-harness comparisons and direct-API baselines.',
        'Terminal-Bench 2.0, tau2-bench and MRCR are separate releases with different budgets and scoring policies.',
        'Tokens include all attempts and cache reads; simulator/judge usage is separate. Costs are known-token PAYG equivalents, not invoices.']
    (root/'README.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':
    build(Path(__file__).resolve().parents[1])
