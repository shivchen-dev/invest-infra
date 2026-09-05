# AgentOA 任务发布规则

发布前检查：

1. 从正式 active API 读取策略 key/version/hash；
2. 查共享 `coverage-index.json`，确认字段覆盖和未解决缺口；
3. 任务只声明 WorkBuddy 的数据获取职责，不包含评分、StageResult、Candidate 或准入决策；
4. 明确日期、as_of、数据范围、允许 connector、fallback、交付文件和 SHA-256；
5. 明确无法满足时必须 `BLOCKED`，禁止使用旧报告、模拟数据或猜测补齐；
6. 通过 AgentOA 发布后，ARC 独立核对任务内容、交付物、hash 和投研系统读回结果。

当前推荐顺序：

```text
Ranking 显式 as_of / 全集 / 分页 / 限频定向探针
  + Constituent 单一分类体系 / 完整 symbol / snapshot date 定向探针
  → ARC 验收
  → 每个 Dataset 分别作 admit / research_only / reject
  → 仅 admit 后生成新 DataRequest 或预采集切片
  → ARC 归档并运行 evaluator
```

当前 Gate B2A 为 `BLOCKED`。禁止发布完整 DataBundle、批量预采集或 Candidate 生成任务；不得用多工具静默拼接、墙钟推断 `as_of` 或旧报告替代准入证据。
