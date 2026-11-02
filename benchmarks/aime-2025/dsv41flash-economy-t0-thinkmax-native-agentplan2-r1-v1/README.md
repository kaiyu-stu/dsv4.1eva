# AIME 2025：五组原生 harness

30题 × 5组，全部评分完成。DeepSeek V4.1 Flash Economy，Agent Plan 2，temperature=0、thinking enabled、reasoning effort=max，每请求最多131072输出 tokens，每题 CLI 超时1800秒。无工具，各 harness 原生默认上下文管理，没有统一压缩阈值。

| Harness | 正确 / 已评分 | 正确率 | 所有尝试已观测 token | 采纳 attempt token | 用量完整题数 |
|---|---:|---:|---:|---:|---:|
| claude | 19/30 | 63.33% | 168,708 | 168,708 | 30/30 |
| codex | 20/30 | 66.67% | 262,985 | 262,985 | 30/30 |
| dsh | 27/30 | 90.00% | 735,805 | 410,344 | 30/30 |
| pi | 30/30 | 100.00% | 332,702 | 332,702 | 30/30 |
| zcode | 21/30 | 70.00% | 242,820 | 242,820 | 29/30 |

输入 token 已包含缓存命中，不重复相加；completion 已包含 reasoning，不重复加。总量包含失败和重试的已记录用量；缺 usage 不推算，因此总量可能是已知下界。final_attempt 指最终评分实际采用的 attempt，按恢复指针定位，未必是时间最新的一次。未将套餐消耗换算成实际账单。

DSH 早期非流式传输超时产生多次重试；后续流式适配修复后的原生输出与历史账本保留。两条结果从已有原生 attempt 对齐恢复，均不冒充新调用。ZCode 有1次 HTTP429 未返回 usage，明确保留缺失标记。DSML-only 原生最终文本按无可解析答案记0，不筛选掉错误结果。

`samples` 为逐题分数和 token，`requests` 为全部原始请求的数值账本，`attempts` 为全部尝试及被采纳标记，`task-matrix` 为同题五路矩阵。每表均有 CSV/JSONL。`selection.json` 不含题目和答案；`experiment.json` 保存白名单参数及 harness 版本；来源哈希在 `provenance/source-files.json`。

没有新增 API 调用，没有发布题目正文、标准答案、模型输出、原始失败轨迹或凭证。
