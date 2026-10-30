# GPQA Diamond：198 题，每题一次，五组原生 Harness

DeepSeek 官方 API `deepseek-flash`，temperature=0、thinking=disabled，每次请求输出上限 4096 tokens；各组并发 3。
从 CSV 第 0 行开始覆盖全部 198 题，seed=0，各组题目和选项顺序逐条相同。保留原生系统提示，无工具，无压缩。
评分使用 OpenAI simple-evals 提示模板与首个 Answer: A/B/C/D 正则匹配；不重复、不投票。

|Harness|已评分|正确|正确率|输入 tokens|输出 tokens|总 tokens|缓存命中输入|请求数|从已有文本恢复评分|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
|claude|198|153|77.27%|356,214|129,116|485,330|239,744|212|0|
|codex|198|144|72.73%|903,131|69,478|972,609|709,376|198|195|
|dsh|198|152|76.77%|72,902|165,580|238,482|512|198|0|
|pi|198|146|73.74%|142,839|157,374|300,213|50,688|198|1|
|zcode|198|149|75.25%|435,132|152,867|587,999|249,088|211|0|

输入包含缓存命中，不重复相加；总量包含原生自动续写的全部调用。所有上游请求 HTTP 200，均保存完整 usage。没有按 token 单价推算实际账单。

## 协议异常与评分恢复

Codex 有 195 次在收到回答文本后，因 Responses 适配器缺少必需的 reasoning_tokens 字段而退出。3 次触及输出上限的作答已被原脚本按截断文本评分。
Pi 有 1 次已收到正常结束的 assistant message，但缺少脚本期待的 agent_end 事件，未写入最终评分。
本发布核验这些样本的原生 CLI 已输出文本与保存的 API 回答完全一致（仅忽略外侧空白），按同一官方正则恢复评分；没有重新调用模型，也未改写原始 checkpoint。
因此表中是已生成答案的正确率，不是 CLI 无故障完成率。samples 明确保留 native_checkpoint_status、native_returncode、scoring_source 与 recovered_from_recorded_text。涉及恢复的 Codex 结果不宜直接解释为稳定的原生端到端完成成绩。
本地适配器已修复 Responses 必需整数的兼容默认值。该默认 0 只服务传输协议，不表示上游实测 reasoning tokens=0；计量始终使用原始 DeepSeek usage。

## 数据

- `samples.csv/jsonl`：990 条逐题分数、原生状态、恢复标记与完整 token。
- `requests.csv/jsonl`：每个实际 API 请求的时间、用量、缓存与结束原因。
- `task-matrix.csv/jsonl`：同题五组正误与 token 对照。
- `pairwise.csv/jsonl`：两两都对、都错及独有答对。
- `experiment.json`：版本、参数、数据哈希与跨组顺序校验。
- `provenance/source-files.json`、`SHA256SUMS`：来源与发布文件校验和。

只发布测量元数据；不含题目正文、标准答案、模型回答、错误堆栈、凭证或原始失败轨迹。恢复标记保留在元数据中，防止隐藏基础设施问题。
