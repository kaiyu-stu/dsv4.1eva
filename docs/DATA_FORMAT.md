# 数据格式与复用约定 / Data contract

本仓库按 `benchmarks/<benchmark>/<release_id>/` 保存实验。后续 benchmark 使用独立目录；
`benchmarks/index.json` 是机器可读目录。不同基座、预算、压缩设置或标签规则使用不同 release，不能混合。
每个 release 至少提供 `samples.csv`、`samples.jsonl`、`summary.json`、`experiments.json`、说明文档和数据来源指纹。

## 通用字段

|字段|含义|
|---|---|
|`benchmark`, `release_id`|数据集及本次实验版本|
|`model`, `harness`, `plan`|请求的模型别名、harness 标识、服务套餐路径|
|`task_id`|跨 harness 对齐及划分训练集的主键；Terminal 为原任务名，tau2 为 `domain/original_task_id`|
|`audit_id`, `run_id`|本地任务散列及实验标识，用于来源追溯|
|`status`|实验原始状态；`completed` 不表示答对|
|`success`|二元标签：1 成功，0 失败；JSON null / CSV 空白为无标签|
|`label`, `score`|可读标签及原始分数；本轮已评分样本分数为 0 或 1|
|`label_source`, `termination_reason`|标签规则及退出原因，区分评分失败、超时置零、未评分退出|
|`token`, `total_tokens`|所有尝试累计的已观测输入、缓存读取、缓存创建和输出 token 总数，两字段相等|
|`input_tokens`|**非缓存输入** token，已经扣除缓存命中，不能再减一次缓存|
|`cache_read_input_tokens`|命中缓存的输入 token|
|`cache_creation_input_tokens`|代理记录的缓存创建 token；本轮全为 0，不是显式缓存存储时长|
|`total_input_tokens`|非缓存输入 + 缓存读取 + 缓存创建|
|`output_tokens`|provider usage 中的输出总量，含模型计入输出的 reasoning；不能再叠加原生 thinking 计数|
|`accounting_complete`|严格计量标记：每个请求都有开始、结束、input/output usage 且响应完整|
|`usage_missing_requests`|缺少 input/output usage 的请求数量|
|`unfinished_requests`|缺少 finish 记录的请求数量|
|`incomplete_requests`|响应未完整结束的请求数量，含缺少 finish 的请求；与前两项可能重叠，不能相加当作缺口请求数|
|`source_accounting_complete`, `source_accounting_gaps`|实验原导出的标记，保留以便追溯；新发布的严格标记可能更保守|
|`source_export_total_tokens`, `token_reconciliation_delta`|历史导出总量及本次按账本重算的增量；不改写历史文件|
|`attempts_count`, `final_attempt_id`|实际启动次数及最终尝试标识，**不是 pass@k**|
|`final_attempt_token`, `prior_attempt_tokens`|最终尝试 token / 较早尝试 token；两者相加等于 `token`|
|`final_attempt_accounting_complete`|仅最终尝试是否计量完整|
|`final_agent_execution_sec`|最终尝试的 Harbor agent 阶段耗时；没有值表示没有可靠测量|
|`total_attempt_wall_time_sec`|有 trial 起止时间的全部尝试总耗时，含环境及评分阶段，不能视为纯推理时间|
|`verifier_reward`, `verifier_completed`, `final_exception_type`|最终 Harbor 原始评分和执行证据；可与预算标签不同|
|`compaction_events_observed`, `compaction_observation`|现有记录捕获的显式摘要压缩次数和记录来源；0 不证明无裁剪/无任何上下文管理|
|`compression_policy`, `compression_threshold_tokens`|原生默认策略；本轮不人为设置压缩阈值，阈值为空|
|`router_eligible_label`|本条是否有 0/1 标签|
|`router_eligible_complete_tokens`|有 0/1 标签且全部尝试 token 计量完整|
|`in_common_scored_subset`|该题五组均有二元标签|
|`in_common_complete_token_subset`|该题五组均有二元标签且全部 token 计量完整|

## 费用字段

`payg_known_start_time_estimate_cny/usd` 是**已观测 token 的按量付费等价成本估算**，按请求开始时间近似划分峰谷。
`payg_known_all_offpeak_cny/usd`、`payg_known_all_peak_cny/usd` 把同一组已观测 token 全部按闲时/高峰费率重算。
`final_attempt_payg_known_start_time_estimate_usd` 只统计最终尝试。

`actual_billed_usd` 恒为空：没有套餐账单及实验分摊依据，不能从 token 反推真实支出。
存在计量缺口时，所有费用仅覆盖已知 token；两种时段场景**不是完整账单的上下界**。
费用不含硬件、电费、税费、汇兑点差、显式缓存存储或其他未记录服务。

## 其他文件

- `requests.csv/jsonl`：一行一个代理请求，保留请求/尝试 ID、UTC 开始时间、HTTP 状态、usage、完整性和计费场景；无 prompt、回答或工具参数。
  `usage_present` 检查 input/output 是否存在；无 usage 的 token 在请求行为空，不伪造为实际消耗 0。
  聚合金额中的 0 只表示该请求没有可计价的**已知** token。
  `request_path`、`upstream_path`、`protocol_adapter` 记录协议路径；`start_record_present`、`finish_record_present` 标记日志配对。
- `attempts.csv/jsonl`：一行一次任务执行，含最终/早期尝试标记、起止时间、执行异常、verifier reward、任务 checksum 和独立 token/费用。
  `native_*` 字段原样保留 Harbor 原生汇总，跨 harness 语义可能不同，不覆盖代理账本。
  `native_reported_cost_usd_unverified` 是 harness/Harbor 自报费用，可能使用其他模型费率，**未用于本仓库费用估算**。
- `task-matrix.csv`：一题一行，各 harness 的正误、token、退出原因和费用并排排列。
- `tasks.csv`：官方任务的类别、难度、资源、原始预算、instruction/task.toml 指纹。正文及答案不在本发布包。
- `pairwise-correctness.csv`：两两共同已评分题中的四种正误组合。
- `analysis.json`：五组共同已评分/完整计量子集、正误分歧题、全超时题及账本对账修正。
- `experiments.json`：白名单配置、CLI 版本和**实验当时记录的**实现哈希。
- `provenance/`：来源文件 SHA256、导出信息、适配修复前后配置的脱敏快照。
- `SHA256SUMS`：相对 release 目录的文件校验和，不包含自身。

CSV 使用 UTF-8，列表/字典单元格使用 JSON；布尔值为 `True/False`。JSONL 保留类型，更适合程序读取。
token 为计数，时间为秒或带 UTC 时区的 ISO 8601；费用为 CNY/USD，费率为每百万 token。
缺失值不等于 0，尤其不能对 `success` 使用 `fillna(0)`。

## Router 训练

最简输入是 `router-data.csv` 中 `(task_id, harness, token, success)`。主 `token` 包含基础设施重试的历史消耗；
研究单次 harness 执行效率可改用 `final_attempt_token`，并检查对应的完整性标记。该选择应写入训练配置。
超时的 `success=0` 是本轮 1200 秒预算下的标签；五组都超时的题仍可用于成本回归/失败预测，
但仅凭全零标签无法识别“哪个 harness 能答对”。不能把这轮标签解释为无限预算能力。

按 **task_id** 划分 train/validation/test，同一题的五个 harness 记录必须在同一分区，避免泄漏。
优先报告五组共同已评分子集；公平比较精确 token 时另报五组共同完整计量子集及选择偏差。
不要只挑成功题、不要把多次基础设施重试称为独立重复测量，也不要用当前单轮成绩估计 pass@k。

## tau2 补充字段和规则

tau2 使用 `task_id=domain/original_task_id`，保留 `domain`、`original_task_id`、`sample_id`、`trial`。
`original_task_id` 在多个 domain 中可重复；`sample_id` 是本地稳定样本散列。
主 token、分项 token 与主费用只包含 harness。`simulator_*` 和 `judge_*` 为同结构的独立聚合，
例如 `simulator_total_tokens`、`judge_model_requests`、`simulator_accounting_complete`、
`judge_payg_known_start_time_estimate_usd`。
`end_to_end_tokens` 相加三种角色；`end_to_end_payg_known_start_time_estimate_usd` 为三种角色已知 token 的估算总额。
`end_to_end_accounting_complete` 要求三者都完整；不需要 judge 的 0 次调用视为不适用且计量完整，
由 `judge_applicable=false` 区分，不误记为缺失。

`official_evaluation_present` / `official_reward` 标记是否有官方轨迹评价；`score` 等于官方 reward。
`label_source=native_early_exit_zero` 的正常提前结束按本实验规则记 0，但没有官方 reward，所以 score 保持 null。
`success=0` 与 `score=null` 在此组合下并不矛盾。其余标签通过 `int(reward == 1.0)` 得到。
`final_native_turns` 是原生 CLI 启动/续接次数，不等于 orchestrator 步数或模型请求次数。
`final_simulation_duration_sec` 仅为最终模拟轨迹的记录时长，包含模拟用户等待，不是纯推理时间。

`attempts` 中 `simulation_*`、assistant/user/tool message count 只公开轨迹存在性、长度、时间和退出原因；
`official_success/official_reward`、`db_match/db_reward`、action checks 数量仅为无内容的评分摘要，
不包含隐藏断言、参考动作、原始场景或对话。
`requests.role` 是 `model`（harness）、`simulator`、`judge`。
请求使用样本散列区分，再根据请求开始时间匹配最近一次尝试的创建时间；缺少可靠匹配时导出报错。
`provenance/implementation-updates` 保留实验运行期间的实现指纹变更，不能仅凭最终哈希推断每条样本的完整适配历史。

tau2 没有整题时间上限，仍有 200 步、10 次工具错误上限及单次请求/传输超时；Terminal 为 1200 秒。
两个 benchmark 的预算与失败规则独立，不能跨 benchmark 直接解释成功率。
