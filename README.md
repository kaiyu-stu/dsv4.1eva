# DS V4.1 评测数据：原生 Harness 与直接 API 基线

记录 DeepSeek V4.1 在不同 benchmark 上的逐题得分、正误与 token。原生 harness 对比和直接 API 基线分开发布。
不同 benchmark 和实验版本独立保存；后续结果继续追加，不覆盖历史发布。

|Benchmark|任务 × Harness|二元标签|说明与数据|
|---|---:|---:|---|
|Terminal-Bench 2.0|89 × 5 = 445|444|[dsv41flash-economy-t0-native-1200-v1](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/README.md)|
|tau2-bench|278 × 5 = 1390|1390|[dsv41flash-economy-t0-native-notimelimit-v3-dialogue](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/README.md)|
|mrcr|200 × 1 = 200|200|[deepseek-flash-t0-direct-stratified200-s20261030-v1](benchmarks/mrcr/deepseek-flash-t0-direct-stratified200-s20261030-v1/README.md)|
|GPQA Diamond|198 × 5 = 990|990（含 196 条已有文本恢复评分）|[单次完整集](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1/README.md)|
|GPQA Diamond 试跑|10 × 10 × 6 = 600|600|[五组 harness 与直接 API 对照](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q10-r10-s0-v1/README.md)|

Terminal/tau2 使用 Ark 模型别名 `deepseek-v4.1-flash-economy`、temperature=0 和各 harness 原生上下文管理，未指定统一压缩阈值。
这两组 Claude/Codex/DSH 使用 Coding Plan，Pi/ZCode 使用 Agent Plan。
MRCR 使用 DeepSeek 官方 API 的 `deepseek-flash`，完整上下文直接调用，不压缩。各实验预算和评分规则分别见说明。

## Terminal-Bench 2.0

|Harness|成功 / 已评分|成功率|Harness 已观测 token|API 等价 USD*|
|---|---:|---:|---:|---:|
|Claude Code|35/89|39.33%|48,513,862|$1.6105|
|Codex|43/89|48.31%|55,791,414|$1.6416|
|DeepSeek Harness|32/89|35.96%|44,894,171|$1.4786|
|Pi|37/88|42.05%|30,958,097|$1.1455|
|ZCode|32/89|35.96%|48,772,944|$2.2590|

主 harness 合计 **228,930,488 token**，已知 token 的按量等价估算 **$8.1352**。
每题 agent 预算 **1200 秒**。Pi 有 1 题 exit 137 未评分，保留空标签；全题集已解决比例为 37/89。

[逐样本 CSV](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/samples.csv) · [JSONL](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/samples.jsonl) · [同题正误矩阵](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/task-matrix.csv) · [Router 数据](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/router-data.csv)

## tau2-bench

|Harness|成功 / 已评分|成功率|Harness 已观测 token|API 等价 USD*|
|---|---:|---:|---:|---:|
|Claude Code|251/278|90.29%|44,328,775|$1.0174|
|Codex|238/278|85.61%|57,890,341|$1.0501|
|DeepSeek Harness|237/278|85.25%|39,489,860|$0.8560|
|Pi|252/278|90.65%|41,963,696|$1.0514|
|ZCode|242/278|87.05%|49,799,314|$1.4508|

主 harness 合计 **233,471,986 token**，已知 token 的按量等价估算 **$5.4257**。
**无整题时间上限**，官方 orchestrator 最多 200 步、10 次工具错误；airline 50、retail 114、telecom 114。
模拟用户/评判器分别计量，包含它们的总消耗为 **302,080,004 token**、API 等价约 **$7.3517**。
五组均为 278/278；其中 29 条是原生正常提前结束的零分标签，单独标记，区别于官方轨迹评分。

[逐样本 CSV](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/samples.csv) · [JSONL](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/samples.jsonl) · [同题正误矩阵](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/task-matrix.csv) · [Router 数据](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/router-data.csv)

## MRCR：直接 API，分层 200 题

**200/200 完成**。官方平均相似度得分 **62.43%**；严格全文匹配 **80/200（40.00%）**。
部分得分 102 题、零分 18 题。
已记录输入 **37,506,477**、输出 **76,837**，合计 **37,583,314 token**。
201 次请求中 1 次连接异常未返回 usage，重试后 200 题均完成；未知用量未估算，总 token 为已观测下界。
按 needle 数量 × 长度桶共 24 层比例抽样，seed=20261030；不上传任务正文、答案、模型输出或失败案例。

[详细报告](benchmarks/mrcr/deepseek-flash-t0-direct-stratified200-s20261030-v1/README.md) · [逐题 CSV](benchmarks/mrcr/deepseek-flash-t0-direct-stratified200-s20261030-v1/samples.csv) · [JSONL](benchmarks/mrcr/deepseek-flash-t0-direct-stratified200-s20261030-v1/samples.jsonl) · [固定抽样清单](benchmarks/mrcr/deepseek-flash-t0-direct-stratified200-s20261030-v1/subset-manifest.json)

## GPQA Diamond：完整 198 题，每题一次

五组共 **990 次作答**。DeepSeek 官方 API `deepseek-flash`，温度 0、thinking 关闭；同题五组的选项排列完全一致。
禁用工具，保留各自系统提示；每次模型请求最多输出 4096 tokens，原生自动续写单独计量。

|Harness|答案正确 / 198|正确率|输入 tokens|输出 tokens|总 tokens|
|---|---:|---:|---:|---:|---:|
|Claude Code|153|77.27%|356,214|129,116|485,330|
|Codex|144|72.73%|903,131|69,478|972,609|
|DSH|152|76.77%|72,902|165,580|238,482|
|Pi|146|73.74%|142,839|157,374|300,213|
|ZCode|149|75.25%|435,132|152,867|587,999|

**此表是已生成答案的正确率，不是 CLI 无故障完成率。** Codex 的 195 条因本地 Responses 协议字段缺失而退出，Pi 的 1 条缺少最终 agent_end 事件；已核验原生已输出文本与保存 API 回答一致并恢复评分，未重新调用模型。原始状态与恢复标记全部保留。
所有 API 请求均返回完整 usage；总量 **2,584,633 tokens**，包含自动续写和缓存命中输入。未发布失败轨迹或模型回答。

[完整配置与异常说明](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1/README.md) · [逐题正误与 token](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1/samples.csv) · [逐请求用量](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1/requests.csv) · [同题矩阵](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q198-r1-s0-v1/task-matrix.csv)

之前的 [10 题 × 10 次试跑](benchmarks/gpqa-diamond/deepseek-flash-t0-native-notools-q10-r10-s0-v1/README.md) 独立保存，包含直接 API 基线，不与单次完整集混算。

## 费用与计量

**美元是按公开 token 单价、缓存命中与请求开始时间近似折算的 API 等价成本，不是实际套餐账单。**
Terminal/tau2 各组存在部分计量不完整记录；费用只覆盖已知 token。完整费率、汇率及假设保存在对应 release 的 `pricing.json`。MRCR 仅发布已记录 token，不推算费用。
官方峰谷按完成时间划分，现有日志只可靠保留开始时间，因此另提供全闲时/全高峰统一费率重算。
主 token 包含所有尝试；比较最终一次执行可使用 `final_attempt_token`。模拟用户/评判器不计入主 token。

## 复用

[字段说明](docs/DATA_FORMAT.md) · [追加 benchmark](docs/ADDING_BENCHMARKS.md) · [机器可读目录](benchmarks/index.json)

只需 Python 标准库即可读取与校验：

```python
import json
from pathlib import Path
catalog = json.loads(Path("benchmarks/index.json").read_text())
release = next(r for r in catalog if r["benchmark"] == "tau2-bench")
p = Path("benchmarks") / release["relative_path"] / "samples.jsonl"
rows = [json.loads(line) for line in p.open()]
usable = [r for r in rows if r["router_eligible_complete_tokens"]]
pairs = [(r["task_id"], r["harness"], r["token"], r["success"]) for r in usable]
```

`python tools/validate_release.py` 验证已发布数据的请求、样本、汇总与文件校验和。
按 `benchmark, task_id` 划分训练/测试，同题五组必须放在同一分区；不能把空标签改为 0。

## 使用与引用

欢迎复用导出的实验测量数据，请引用仓库 URL、release 和固定 commit，见 [CITATION.cff](CITATION.cff)。
本仓库不重新授权上游任务、答案或 harness 代码；它们遵循各自原始许可。
数据包不含任务正文、标准答案、模型对话、凭证或完整评测环境。

**English:** Sample-level evaluation data for DeepSeek V4.1 Flash: native-harness comparisons and direct-API baselines.
Terminal-Bench 2.0, tau2-bench and MRCR are separate releases with different budgets and scoring policies.
Tokens include all attempts and cache reads; simulator/judge usage is separate. Costs are known-token PAYG equivalents, not invoices.
