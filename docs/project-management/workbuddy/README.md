# WorkBuddy 协作资料入口

## 权威分层

| 内容 | 权威位置 | 用途 |
|---|---|---|
| WorkBuddy 原始/运行交付物 | `Z:\\workbuddy\\strategy\\results\\<run>.ready` | 机器摄取与不可变证据 |
| 当前参考索引 | `Z:\\workbuddy\\strategy\\reference\\` | WorkBuddy、ARC、AgentOA 查找当前版本 |
| 团队说明与审阅入口 | 本目录 | 团队成员查看规则、状态和发布流程 |
| 正式策略事实 | invest-infra active StrategyVersion API | 不以共享目录副本替代 |

## 当前参考

- 共享目录索引：`Z:\\workbuddy\\strategy\\reference\\README.md`
- 策略索引：`Z:\\workbuddy\\strategy\\reference\\strategy-index.json`
- 覆盖索引：`Z:\\workbuddy\\strategy\\reference\\coverage-index.json`
- 当前 ARC 准入报告：`docs/research/sector-dataset-source-admission-20260905.md`
- 当前 WorkBuddy 证据：`Z:\\workbuddy\\strategy\\results\\sector-coverage-gap-closure-20260904-v2.ready\\` 与 `industry-concept-coverage-remediation-20260904.ready\\`

当前 Gate B2A 结论为 `BLOCKED`。`sector-ranking` 和 `sector-constituents` 均仅为 `research_only`，不得进入正式 evaluator、预采集或 Candidate 生成。

## 更新流程

```text
WorkBuddy 生成新版本 ready 目录
  → ARC 校验 JSON、hash、合同和状态
  → ARC 更新共享 reference 索引
  → ARC 更新本目录索引说明
  → AgentOA 任务引用已验证版本
```

历史 `ready` 目录不覆盖、不删除、不改写。索引只指向已核验资料；发现索引与文件 hash 不一致时，停止发布并重新核验。
