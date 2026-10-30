# 后续 benchmark 发布方式

1. 固定模型、温度、任务版本、harness/adapter 版本、预算、工具与压缩策略，分配新的 `release_id`。
2. 写入 `benchmarks/<benchmark>/<release_id>/`。沿用 [DATA_FORMAT.md](DATA_FORMAT.md) 的 `task_id, harness, token, success` 契约。
3. 同时记录原始标签来源、所有尝试、请求 usage、计量完整性和来源哈希；没有评分的样本保留 null。
4. 独立写清该 benchmark 的时间/轮次预算、模拟用户/评判器以及它们是否计入主 token。不能沿用 Terminal 的标签规则作隐含默认。
5. 费用保留价格版本、币种、单位、时间条件、汇率及账单/估算区别，不因费率更新而静默覆盖旧发布。
6. 为 `benchmarks/index.json` 增加记录，并在根 README 增加链接。不要覆盖其他 benchmark 或旧 release。
7. 运行本地数据校验、检查待提交文件及来源，生成 `SHA256SUMS` 后提交。不要提交 `.env`、完整运行目录或含凭证的原始配置。

当前 Terminal 导出器（Python 3.11+，只使用标准库）：

```bash
python tools/export_terminal.py \
  --source-root /path/to/HarnessCompressionBench \
  --output-root .
python tools/build_terminal_report.py
python tools/validate_release.py
```

导出器需要本机原始结果；复用已发布数据只需要克隆本仓库，不需要原评测环境/API。
`build_terminal_report.py` 生成图表需要 matplotlib，数据和校验脚本本身不依赖它。
SHA256 来源文件指纹是审计标识；未公开的原始日志不能仅靠哈希从本仓库恢复。
当前导出脚本和文档是发布工具，不是原实验环境的完整镜像。历史实现以 `experiments.json` 指纹为准。

tau2 导出（只读，不启动正式测评）：

```bash
python tools/export_tau2.py \
  --source-root /path/to/HarnessCompressionBench \
  --tau-root /path/to/tau2-bench \
  --output-root .
python tools/build_tau2_report.py
python tools/build_index_report.py
python tools/validate_release.py
```

生成图表的环境依赖见 `tools/requirements-report.txt`。
根 README 由 `build_index_report.py` 根据 `benchmarks/index.json` 及每个 release 的汇总生成，
支持同时保留多个 benchmark；单个 benchmark 的报告工具不应删除其他 benchmark 的入口。
