"""Render the release tables and an optional matplotlib figure from public data."""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = 'dsv41flash-economy-t0-native-1200-v1'
BASE = ROOT / 'benchmarks' / 'terminal-bench-2.0' / RELEASE


def load(name):
    return json.loads((BASE / name).read_text())


def main():
    summary, analysis, pricing = load('summary.json'), load('analysis.json'), load('pricing.json')
    samples = [json.loads(x) for x in (BASE / 'samples.jsonl').read_text().splitlines()]
    rows = ['|Harness|正误已评分|成功率（已评分）|已观测 token|严格计量完整题|API 等价美元估算*|',
            '|---|---:|---:|---:|---:|---:|']
    for s in summary:
        rows.append(f"|{s['harness_name']}|{s['correct']}/{s['scored_samples']}|"
                    f"{s['success_rate_scored']:.2%}|{s['total_tokens']:,}|"
                    f"{s['samples_with_complete_tokens']}/89|${s['payg_known_start_time_estimate_usd']:.4f}|")
    total_tokens = sum(s['total_tokens'] for s in summary)
    total_usd = sum(s['payg_known_start_time_estimate_usd'] for s in summary)
    totals = f"五组累计已观测 **{total_tokens:,} token**，按开始时间近似折算 **${total_usd:.4f}**。"
    table = '\n'.join(rows)
    from build_index_report import build as build_index
    build_index(ROOT)
    report = f'''# Terminal-Bench 2.0 — {RELEASE}

本轮采集于 2026-10-27 至 2026-10-30，89 道任务、5 个 harness、445 行，444 个二元标签。
保留原实验标签，重新从冻结请求账本核算所有尝试的 token；结果未做挑题或补造标签。

{table}

{totals}

## 查看逐题结果

- [Claude Code](harnesses/claude.md)、[Codex](harnesses/codex.md)、[DSH](harnesses/dsh.md)、[Pi](harnesses/pi.md)、[ZCode](harnesses/zcode.md)：每题正误、分项 token、退出原因、费用和计量标记。
- [samples.csv](samples.csv) / [samples.jsonl](samples.jsonl)：完整长表；[router-data.csv](router-data.csv)：训练简表。
- [task-matrix.csv](task-matrix.csv)：每题五组并排；[pairwise-correctness.csv](pairwise-correctness.csv)：两两正误交集。
- [requests.csv](requests.csv) / [requests.jsonl](requests.jsonl)：逐请求账本；[attempts.csv](attempts.csv) / [attempts.jsonl](attempts.jsonl)：逐尝试执行证据和成本。
- [tasks.csv](tasks.csv)：任务类别、难度及资源；[experiments.json](experiments.json)：版本与配置指纹。
- [analysis.json](analysis.json)：共同子集、分歧题、全超时题、对账差异；[summary.json](summary.json)：可编程汇总。

## 实验和评分规则

请求模型别名 `deepseek-v4.1-flash-economy`，temperature=0；使用各原生 CLI 的执行循环和默认压缩策略，
没有强制 64k 压缩阈值。上下文容量元数据和 CLI 版本见配置；各 harness 的默认上下文管理并不相同。
没有服务端权重哈希，不能仅凭同一别名证明各套餐、各时间点的后端实现完全一致。
套餐路由、请求等待及适配修复是本次比较的限制。

每题 agent 上限 1200 秒；Harbor Docker 环境，任务资源与 verifier 预算以任务设置为基础。
为受限网络配置了国内 apt 镜像、缓存资源和离线 verifier 依赖。
原生不支持 Responses 的 CLI 使用 Messages→Responses 协议转换；Codex 原生使用 Responses。
实验中包含传输修复和断点重跑，相关配置哈希快照见 [provenance/experiment-history](provenance/experiment-history)。
CLI 版本为 Claude 2.1.301 / Codex 0.161.0 / DSH 0.2.1-rc.2 / Pi 1.3.0 / ZCode 0.16.9。
上游任务仓库 [harbor-framework/terminal-bench-2](https://github.com/harbor-framework/terminal-bench-2)，
记录的 commit 为 `69671fbaac6d67a7ef0dfec016cc38a64ef7a77c`；本地执行资产存在离线适配。
原任务 instruction/task.toml 的 SHA256 和实际 Harbor task checksum 分别保留，未声称本轮与官方榜单环境完全相同。

正常结束由 verifier reward 确定 0/1；agent 超时按实验规则置 0（`agent_timeout_zero_v2`）。
DSH 和 Pi 的 `pytorch-model-cli` 各有一条 verifier 超时置 0（`verifier_timeout_zero_v1`）。
Pi 的 `compile-compcert` 因 exit 137（SIGKILL）保持 `success=null`，不推断为模型错误，也不认定具体是 OOM。
本轮因此是 444 个标签，而不是 445 个。

任务 token 是所有已观测尝试的总消耗；最终标签来自最终执行。
基础设施失败后的重跑不是随机独立重复采样，也不是 pass@k。原生工具/调用策略保持各自行为。
显式摘要压缩事件的现有观测均为 0：可作为原生 harness 的预算内效率基线，不能据此给压缩算法排名，
也不能证明每个 harness 都没有内部裁剪。

## 费用如何计算

按 [火山方舟公开模型价格]({pricing['source']})（2026-10-30 核查）重算；单位 CNY / 1M token：

|时段|非缓存输入|缓存命中|输出|
|---|---:|---:|---:|
|闲时|0.80|0.016|3.20|
|高峰|1.60|0.032|6.40|

高峰为北京时间周一至周五 09:00–12:00、14:00–18:00，其余为闲时。
逐请求费用 = `(非缓存输入 × 输入单价 + 缓存读取 × 缓存单价 + 输出 × 输出单价) / 1,000,000`。
缓存已经与非缓存输入分开，不重复扣减或计费；本轮缓存创建记录均为 0。

官方按**请求完成时间**划分峰谷；现有代理 start/finish 记录中的 `time` 都是请求开始时间，
故 `payg_known_start_time_estimate_*` 仅以开始时间作近似。另提供全闲时、全高峰重算，便于统一价格比较。
价格为本次查到的公开价重算，不是经核验的历史账单价，也没有应用订阅活动优惠。

美元统一使用 [ECB 2026-10-29 汇率]({pricing['fx']['source']})：
EUR/USD = 1.1130，EUR/CNY = 7.4144，得到 1 USD = {float(pricing['fx']['cny_per_usd']):.10f} CNY。
这是跨币种展示换算，不是交易执行价；完整费率、汇率及来源见 [pricing.json](pricing.json)。

[官方套餐说明]({pricing['plan_source']})区分订阅额度/AFP 与按量单价。
**本实验使用套餐，因此无法从 token 得出实际支出的美元；`actual_billed_usd` 保持空值。**
计量不完整的费用仅覆盖已知 token，全闲时/全高峰场景也不是完整账单的上下界。
Harbor/harness 自报美元额可能套用其他费率，单独保留为 unverified，没有用于上述估算。

## 共同子集和 router 信息

五组共同已评分 **{len(analysis['common_scored_tasks'])}** 题；共同全部请求计量完整 **{len(analysis['common_complete_token_tasks'])}** 题。
有 **{len(analysis['tasks_with_correctness_disagreement'])}** 道题出现至少一组成功、另一组失败；
共同已评分题中 **{len(analysis['common_tasks_all_five_incorrect'])}** 道五组均失败，其中全题集中 **{len(analysis['tasks_all_five_agent_timeout'])}** 道五组均 agent 超时。
共同已评分题的事后“至少一组能成功”覆盖 {analysis['common_tasks_any_correct']}/{len(analysis['common_scored_tasks'])}；这是 oracle 覆盖率，不是训练好的 router 成绩。

![Common complete-accounting subset](figures/common-subset.png)

图仅使用五组共同完整计量的 55 题；选择完整计量子集可能有选择偏差，不能代替全题集结果。
独立可导出的 [SVG](figures/common-subset.svg) 同时提供。
字段、训练划分、主 token / 最终尝试 token 的选择见 [DATA_FORMAT](../../../docs/DATA_FORMAT.md)。

## 对账与来源

DSH 的 `write-compressor` 历史导出为 632,384 token；原始请求账本重算为 678,702，增加 **46,318**。
本发布使用账本重算值，保留 `source_export_total_tokens` 和 `token_reconciliation_delta`。
这说明历史导出与最终账本不同，不据此猜测具体写入竞态，也没有改写本地历史结果。

[provenance/source-files.json](provenance/source-files.json) 保存读取时原始文件的 SHA256 和长度，
支持持有原始日志的人核验。仓库只公开白名单指标，不包含对话、工具输入、标准答案或凭证。
`python tools/validate_release.py` 可在仓库根目录核验逐请求→逐尝试→逐样本→汇总的一致性。
`SHA256SUMS` 可在本目录用 `sha256sum -c SHA256SUMS` 校验。
'''
    (BASE / 'README.md').write_text(report)
    (BASE / 'harnesses').mkdir(exist_ok=True)
    for s in summary:
        h = s['harness']
        lines = [f"# {s['harness_name']} — 逐题结果", '',
            'token 为全部尝试累计；输入列为非缓存输入。美元为已知 token 的 PAYG 等价估算，非实际账单。',
            '计量“不完整”的记录仍保留原标签，但其 token/费用不是精确总量。', '',
            '|任务|success|退出原因|非缓存输入|缓存读取|输出|总 token|估算 USD|计量完整|尝试次数|',
            '|---|---:|---|---:|---:|---:|---:|---:|---|---:|']
        for r in samples:
            if r['harness'] != h:
                continue
            lines.append(f"|{r['task_id']}|{r['success'] if r['success'] is not None else 'null'}|"
                f"{r['termination_reason']}|{r['input_tokens']:,}|{r['cache_read_input_tokens']:,}|"
                f"{r['output_tokens']:,}|{r['token']:,}|{r['payg_known_start_time_estimate_usd']:.6f}|"
                f"{'是' if r['accounting_complete'] else '不完整'}|{r['attempts_count']}|")
        (BASE / 'harnesses' / f'{h}.md').write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    matplotlib.rcParams['svg.hashsalt'] = RELEASE
    import matplotlib.pyplot as plt
    names = [s['harness_name'].replace('DeepSeek Harness','DSH') for s in summary]
    common_rows = [[r for r in samples if r['harness']==s['harness'] and r['in_common_complete_token_subset']]
                   for s in summary]
    fig, axes = plt.subplots(1,3,figsize=(14,4.8))
    metrics = [([100*sum(r['success'] for r in rows)/len(rows) for rows in common_rows], 'Success rate (%)'),
               ([sum(r['token'] for r in rows)/len(rows)/1e6 for rows in common_rows], 'Mean observed tokens (million)'),
               ([sum(r['payg_known_start_time_estimate_usd'] for r in rows) for rows in common_rows],
                'Known-token PAYG equivalent (USD)')]
    for ax,(values,title) in zip(axes,metrics):
        bars = ax.bar(names,values,color=['#4c78a8','#f58518','#54a24b','#e45756','#b279a2'])
        ax.set_title(title,fontsize=10)
        ax.bar_label(bars,fmt='%.3f' if 'token' in title.lower() else '%.1f',padding=3,fontsize=9)
        ax.set_ylim(0,max(values)*1.22)
        ax.tick_params(axis='x',rotation=25)
        ax.grid(axis='y',alpha=.2)
        ax.set_axisbelow(True)
    fig.suptitle('Terminal-Bench 2.0 | DS V4.1 Flash Economy | Native harnesses',fontsize=13)
    fig.text(.5,.02,'Common subset: 55 tasks with scored outcomes and complete token accounting in all five harnesses.\n'
             '1200 s agent budget; temperature 0. Cost uses request-start tariff approximation, not plan invoices.',
             ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.1,1,.92])
    (BASE / 'figures').mkdir(exist_ok=True)
    fig.savefig(BASE / 'figures/common-subset.png',dpi=180)
    fig.savefig(BASE / 'figures/common-subset.svg',metadata={'Date':None})
    svg = BASE / 'figures/common-subset.svg'
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    plt.close(fig)
    # Checksum only the release artifacts; scripts/root docs have Git integrity.
    files = sorted(p for p in BASE.rglob('*') if p.is_file() and p.name != 'SHA256SUMS')
    (BASE / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest()+'  '+str(p.relative_to(BASE))+'\n' for p in files))


if __name__ == '__main__':
    main()
