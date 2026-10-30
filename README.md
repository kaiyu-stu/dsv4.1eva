# DS V4.1 原生 Harness 评测数据

记录同一模型在不同原生 harness、不同 benchmark 上的逐题正误、token 与成本，供实验对比和 router 训练复用。
不同 benchmark 和实验版本独立保存；后续结果继续追加，不覆盖历史发布。

|Benchmark|任务 × Harness|二元标签|说明与数据|
|---|---:|---:|---|
|Terminal-Bench 2.0|89 × 5 = 445|444|[dsv41flash-economy-t0-native-1200-v1](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/README.md)|
|tau2-bench|278 × 5 = 1390|1390|[dsv41flash-economy-t0-native-notimelimit-v3-dialogue](benchmarks/tau2-bench/dsv41flash-economy-t0-native-notimelimit-v3-dialogue/README.md)|

模型别名 `deepseek-v4.1-flash-economy`，temperature=0，使用各 harness 原生上下文管理，未指定统一压缩阈值。
Claude/Codex/DSH 使用 Coding Plan，Pi/ZCode 使用 Agent Plan。各 benchmark 的预算与评分规则分别见说明。

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

## 费用与计量

**美元是按公开 token 单价、缓存命中与请求开始时间近似折算的 API 等价成本，不是实际套餐账单。**
所有组都存在部分计量不完整记录；费用只覆盖已知 token。完整费率、汇率及假设保存在各 release 的 `pricing.json`。
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

`python tools/validate_release.py` 验证两套发布数据的请求、执行、样本、汇总与文件校验和。
按 `benchmark, task_id` 划分训练/测试，同题五组必须放在同一分区；不能把空标签改为 0。

## 使用与引用

欢迎复用导出的实验测量数据，请引用仓库 URL、release 和固定 commit，见 [CITATION.cff](CITATION.cff)。
本仓库不重新授权上游任务、答案或 harness 代码；它们遵循各自原始许可。
数据包不含任务正文、标准答案、模型对话、凭证或完整评测环境。

**English:** Sample-level native-harness evaluation data for DeepSeek V4.1 Flash Economy.
Terminal-Bench 2.0 and tau2-bench are separate releases with different budgets and scoring policies.
Tokens include all attempts and cache reads; simulator/judge usage is separate. Costs are known-token PAYG equivalents, not invoices.
