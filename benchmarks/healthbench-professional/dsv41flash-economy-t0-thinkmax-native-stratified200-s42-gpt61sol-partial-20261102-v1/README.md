# HealthBench Professional：200 题，五组原生 harness（未完成快照）

仅发布逐题数值得分、用量、状态与来源哈希；不包含题目、医生回答、rubric 正文、模型输出、思考或失败轨迹。

|Harness|已评分 / 200|主分|模型全部尝试 token|裁判 token|
|---|---:|---:|---:|---:|
|claude|200/200|37.04%|2,510,710|1,172,508|
|codex|200/200|33.90%|2,290,606|987,782|
|dsh|157/200|40.75%|3,916,154|853,740|
|pi|200/200|42.49%|1,346,287|1,206,520|
|zcode|198/200|39.73%|3,069,340|1,163,392|

本快照 955/1000 条已评分，DSH 缺 43 条、ZCode 缺 2 条；未评分保留 null，不当作零分。
主分是各题长度校正分平均后裁剪至 [0,1]，不是二元正确率。原始分、逐题校正分均保存；逐题分允许负数或超过 1。
校正公式：raw - 0.0147 × ((回答字符数 - 2000) / 500)。
200/525 按 use_case 比例分层，seed=42：consult 90、research 56、writing 54。每题一次，温度 0，thinking enabled，max 推理，单请求输出上限 131072、整题超时 1800 秒。
五组作答均为 Ark Coding Plan 的 deepseek-v4.1-flash-economy，保留原生系统提示，禁用工具，不启用 ACON。
裁判为第三方 api.dreamger.cc 的 gpt-6.1-sol，Responses、low 推理；沿用官方 rubric 提示和公式。此配置不同于官方 GPT-5.4 裁判，不能称为官方原配置复现；返回模型名由网关报告，无法独立核验后端身份。
Claude 2 条、Codex 24 条从首次完整上游响应恢复，未重新生成。保留原生失败及恢复标记；已评分不等于原生 CLI 正常完成。
五组共同已评分题数 157；公平比较可使用 analysis.json 的 common_subset_scores。原始各组分母不同，不能直接当作完整集排名。
grader-requests 单独保存裁判请求用量；模型 token 包含失败和重试，不包含裁判。
评分参考：https://github.com/openai/simple-evals/blob/main/healthbench_eval.py
数据卡：https://huggingface.co/datasets/openai/healthbench-professional/blob/main/README.md

输入 token 已包含缓存命中；prompt_cache_hit_tokens + prompt_cache_miss_tokens = prompt_tokens。缺失 usage 为未知，汇总仅是已观测下界，不推算实际费用。
未做明确摘要调用，不把完整输入 token 等同于压缩前后 token；native context 设置不能据此推导压缩节省。
字段：samples 为逐题，requests 为逐请求，task-matrix 为同题五组对比，analysis 为共同题集与两两分歧，experiments 为无密钥的配置白名单，provenance 为私有源文件哈希。
