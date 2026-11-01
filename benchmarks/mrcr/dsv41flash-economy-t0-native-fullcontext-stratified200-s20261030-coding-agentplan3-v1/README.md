# MRCR：200 题，五组原生 harness（Coding Plan + Agent Plan 续跑）

仅发布逐题数值得分、用量、状态与来源哈希；不包含题目、医生回答、rubric 正文、模型输出、思考或失败轨迹。

|Harness|已评分 / 200|主分|模型全部尝试 token|裁判 token|
|---|---:|---:|---:|---:|
|claude|200/200|69.12%|37,785,405|0|
|codex|200/200|67.16%|38,446,069|0|
|dsh|200/200|69.62%|37,608,873|0|
|pi|200/200|67.65%|37,677,866|0|
|zcode|200/200|72.41%|37,874,229|0|

五组均为 200/200。主分为官方前缀检查后的 SequenceMatcher 相似度；success 为补充的严格全文匹配，部分得分也可能有价值。
按 needle 数量 × 长度桶 24 层抽样，seed=20261030；温度 0、thinking disabled、单请求输出上限 4096、超时 1800 秒、无工具。原始历史在网关注入，不测原生会话压缩。
先用 Coding Plan，额度耗尽后用 Agent Plan 第三组凭证续跑；模型别名均为 deepseek-v4.1-flash-economy。每题标记 generation_provider，各组继承题数和新增题数不同，套餐端点差异可能影响比较；不应归因于单一变量。
请求表合并原 Coding Plan 和 Agent Plan 两份账本，各仅一次。继承结果不重复计量，原目录失败请求和重试也入账。不要只采用续跑目录 summary 的 token，它不含旧请求。
by_provider 给出不同题集的分组均值，不能将其解释为两个 provider 的受控对照。
此发布独立于之前 DeepSeek 官方 API deepseek-flash 的 200 题直接调用基线。
评分参考：https://huggingface.co/datasets/openai/mrcr/blob/main/README.md

输入 token 已包含缓存命中；prompt_cache_hit_tokens + prompt_cache_miss_tokens = prompt_tokens。缺失 usage 为未知，汇总仅是已观测下界，不推算实际费用。
未做明确摘要调用，不把完整输入 token 等同于压缩前后 token；native context 设置不能据此推导压缩节省。
字段：samples 为逐题，requests 为逐请求，task-matrix 为同题五组对比，analysis 为共同题集与两两分歧，experiments 为无密钥的配置白名单，provenance 为私有源文件哈希。
