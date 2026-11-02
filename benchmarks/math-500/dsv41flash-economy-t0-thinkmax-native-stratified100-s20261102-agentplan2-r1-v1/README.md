# MATH-500 分层100题：五组原生 harness

100题 × 5组，全部评分完成。DeepSeek V4.1 Flash Economy，Agent Plan 2，temperature=0、thinking enabled、reasoning effort=max，每请求最多131072输出 tokens，每题 CLI 超时1800秒。无工具，各 harness 原生默认上下文管理，没有统一压缩阈值。

| Harness | 正确 / 已评分 | 正确率 | 所有尝试已观测 token | 采纳 attempt token | 用量完整题数 |
|---|---:|---:|---:|---:|---:|
| claude | 99/100 | 99.00% | 212,763 | 212,763 | 100/100 |
| codex | 99/100 | 99.00% | 526,279 | 526,279 | 100/100 |
| dsh | 99/100 | 99.00% | 140,734 | 140,734 | 100/100 |
| pi | 100/100 | 100.00% | 146,755 | 146,755 | 100/100 |
| zcode | 99/100 | 99.00% | 246,152 | 246,152 | 100/100 |

输入 token 已包含缓存命中，不重复相加；completion 已包含 reasoning，不重复加。总量包含失败和重试的已记录用量；缺 usage 不推算，因此总量可能是已知下界。final_attempt 指最终评分实际采用的 attempt，按恢复指针定位，未必是时间最新的一次。未将套餐消耗换算成实际账单。

从 MATH-500 按 subject×level 比例分层抽100题，seed=20261102，覆盖35层，每层至少1题。原始题集附带80 train /20 validation 的历史划分；此处发布的是原评测采样记录，后续 router 可另冻结新的 train/dev/test manifest。最后一个完整 boxed 答案用 math-verify 0.9.0 做等价判定。8题含原始 Asymptote 文本，没有渲染图片。

`samples` 为逐题分数和 token，`requests` 为全部原始请求的数值账本，`attempts` 为全部尝试及被采纳标记，`task-matrix` 为同题五路矩阵。每表均有 CSV/JSONL。`selection.json` 不含题目和答案；`experiment.json` 保存白名单参数及 harness 版本；来源哈希在 `provenance/source-files.json`。

没有新增 API 调用，没有发布题目正文、标准答案、模型输出、原始失败轨迹或凭证。
