# DS V4.1 原生 Harness 评测数据

记录同一模型在不同原生 harness、不同 benchmark 上的任务结果及 token 开销，供 harness 对比和 router 训练复用。
当前发布 Terminal-Bench 2.0；后续 benchmark 按独立版本目录追加。

|Benchmark|模型|任务 × Harness|可用二元标签|数据|
|---|---|---:|---:|---|
|Terminal-Bench 2.0|DeepSeek-V4.1-Flash-Economy|89 × 5 = 445|444|[本轮说明及逐题数据](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/README.md)|

|Harness|正误已评分|成功率（已评分）|已观测 token|严格计量完整题|API 等价美元估算*|
|---|---:|---:|---:|---:|---:|
|Claude Code|35/89|39.33%|48,513,862|75/89|$1.6105|
|Codex|43/89|48.31%|55,791,414|86/89|$1.6416|
|DeepSeek Harness|32/89|35.96%|44,894,171|80/89|$1.4786|
|Pi|37/88|42.05%|30,958,097|78/89|$1.1455|
|ZCode|32/89|35.96%|48,772,944|79/89|$2.2590|

五组累计已观测 **228,930,488 token**，按开始时间近似折算 **$8.1352**。

注：**美元为公开按量单价的等价成本估算，不是实际套餐账单。** 所有组都存在部分计量不完整记录，
金额只覆盖已知 token。Pi 有 1 题因 exit 137 未评分，空标签保留；37/89 的全题集已解决比例为 41.57%。

设置：模型别名 `deepseek-v4.1-flash-economy`，temperature=0，原生上下文管理，未指定压缩阈值，
每题 agent 预算 **1200 秒**。Claude/Codex/DSH 使用 Coding Plan，Pi/ZCode 使用 Agent Plan。
Terminal 的预算与后续 benchmark 独立，不能套用后续 tau2 的无时间上限设置。

数据入口：

- [逐样本 CSV](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/samples.csv) / [JSONL](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/samples.jsonl)：正误、分项 token、费用、失败原因、重试与质量标记。
- [Router 四元组及质量字段](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/router-data.csv)：`task_id, harness, token, success`。
- [89 题 × 5 组正误矩阵](benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/task-matrix.csv)：同题跨 harness 对齐。
- [字段及计量说明](docs/DATA_FORMAT.md)、[追加 benchmark](docs/ADDING_BENCHMARKS.md)、[机器可读目录](benchmarks/index.json)。

## 复用示例

```python
import json
from pathlib import Path

p = Path("benchmarks/terminal-bench-2.0/dsv41flash-economy-t0-native-1200-v1/samples.jsonl")
rows = [json.loads(line) for line in p.open()]
training_rows = [r for r in rows if r["router_eligible_complete_tokens"]]
# 包含成功和失败；不把 null 标签变为 0。按 task_id 划分训练/测试。
pairs = [(r["task_id"], r["harness"], r["token"], r["success"]) for r in training_rows]
```

只需 Python 标准库即可读取数据和校验：`python tools/validate_release.py`。
本轮五组共同已评分 88 题，其中共同完整计量 55 题。对比精确 token 时请另报共同完整子集。
主 token 包含所有尝试；若研究最终一次执行，使用 `final_attempt_token` 并检查其计量标记。

## 使用与引用

欢迎复用本仓库导出的实验测量数据，请引用本仓库 URL、对应 release 和固定 commit；引用信息见 [CITATION.cff](CITATION.cff)。
本仓库不重新授权上游 benchmark 任务、答案或 harness 代码；它们遵循各自原始许可。
本次发布不包含任务正文、标准答案、模型对话、密钥及完整运行环境。

**English:** Sample-level native-harness evaluation data for DeepSeek V4.1 Flash Economy.
Terminal-Bench 2.0: 89 tasks, 5 harnesses, 444 binary outcomes and one unscored row.
Tokens include cache reads and all attempts. Costs are known-token PAYG equivalents, not subscription invoices.
See the per-release documentation and quality flags before comparing or training routers.
