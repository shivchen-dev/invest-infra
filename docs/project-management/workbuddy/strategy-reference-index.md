# 策略与能力覆盖参考

## 当前策略身份

当前两条策略的 key、version、artifact hash 以共享目录 `strategy-index.json` 作为查找索引，但发布任务时必须重新读取 invest-infra 正式 active API。

`sector-strength-ranking` 收窄方案仅保留 Industry/Concept，并暂停 Area 与 `zgb/R-A3`。该方案尚未形成并激活新的不可变 StrategyVersion；当前 active v2.0.0 不得原地改写，也不得用测试 profile 代替正式身份。

## 当前覆盖结论

当前 ARC 准入结论见 `docs/research/sector-dataset-source-admission-20260905.md`：

- `Gate B2A = BLOCKED`；
- `sector-ranking = research_only`：westock 有 Industry/Concept 字段，但缺可信显式 `as_of`、完整分页和频控/许可证据；
- `sector-constituents = research_only`：westock symbol 失真，其他工具存在截断、静默排除或分类体系不一致；
- 当前内部 Provider 没有可运行的 Sector Dataset 路径；TDX 日线已完成不代表板块能力可用；
- 当前不批准预采集，不允许正式 Candidate 生成。

因此，当前只能发布针对单一阻塞证据的定向探针任务，不能继续发布完整 sector DataBundle 或生产采集任务。

## 版本规则

- 新报告使用新的日期/run 目录；
- JSON 是机器权威，Markdown 是人工摘要；
- 报告 hash 必须写入共享 coverage index；
- 任何覆盖结论必须能回溯到 capability probes。
