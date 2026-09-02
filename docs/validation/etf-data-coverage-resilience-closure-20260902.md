# ETF 数据覆盖与 Provider 韧性收口验收记录

> 验收日期：2026-09-02
> 结论：`PASS / CLOSED`
> 权威计划：`docs/plan/invest-infra-etf-data-coverage-resilience-plan-v1.0.md`

## 1. 验收范围

本记录只关闭 BaoStock ETF 日线备用源垂直切片，包括数据指纹、最小 Adapter、合同加固、
明确瞬态故障 fallback、运行配置和部署验证。不包含多年历史回填、回测、更多 Provider、
Candidate 策略业务闭环或自动交易。

## 2. 实现证据

| Commit | 交付内容 |
|---|---|
| `8544d46` | CandidatePool `market_data_fingerprint`，覆盖 Domain、Repository/UoW、Migration 和 Pipeline |
| `8f7b70e` | BaoStock ETF 日线 Adapter |
| `54fa8c1` | 错误分类、配置、映射和客户端合同加固 |
| `126abf8` | 仅在明确瞬态故障时启用 BaoStock fallback |
| `123abf4` | 对齐 ETF job-selection 测试基线 |
| `4a1a704` | 将 personal universe 配置打入 Pipeline 镜像 |
| `e9755c2` | API 策略 artifact 只读挂载；属于同期部署缺陷收口，不改变数据 Provider 语义 |

验收时仓库 `HEAD` 与 `origin/main` 对齐于 `e9755c2`。以上提交均已进入主干；工作树中
另有与本计划无关的用户/其他任务改动，未纳入本验收。

## 3. 自动与真实数据验证

- Domain、Storage、Migration 聚焦回归：96 passed；
- Pipeline、Adapter、Fallback、Job 聚焦回归：167 passed；
- job-selection 基线修复：20 passed，Ruff 与 diff 检查通过；
- 16/16 ETF 满足当前 60/61 交易日运行窗口；
- 三轮真实调用内容 hash 一致；
- `510300` 与 AkShare/Sina 的 OHLCV、成交额逐值一致；
- 不完整数据、单位/日期/契约错误不触发 fallback，并保持 fail closed；
- 失败运行不生成可发布快照或 CandidatePool；
- 数据指纹支持重复执行幂等判断。

真实 Provider 探针与限制记录：
`docs/research/baostock-etf-provider-probe-2026-09-02.md`。

## 4. 部署与运行验证

- AgentOA 部署工作流 `ses_39138523878e017f` 完成 Dagster 修复部署；
- Pipeline 运行环境可导入 BaoStock 0.9.3，开关为 true；
- `personal-universe.yaml` 位于运行镜像内并与版本控制内容 hash 一致；
- Universe loader 成功加载 version 1、16 只标的；
- Definitions 导入成功，Dagster HTTP 健康；
- API、Web、PostgreSQL 未因 Pipeline 部署被重建；
- 当日 16:10 旧镜像运行在采集前由预检安全阻断，未写入业务数据。

## 5. 完成定义对照

| 条件 | 结果 |
|---|---|
| BaoStock 准入有真实探针支持 | PASS |
| 最小 Adapter 满足现有 Provider 契约 | PASS |
| 真实链路、故障和幂等验收 | PASS |
| 无默认值、静默降级或共享上游伪装 | PASS |
| 历史回填和新数据源未被隐式授权 | PASS |

计划完成定义第 1 项已满足，因此数据层 P0 可正式关闭。

## 6. 非阻塞后续观察

下一正常交易日自然调度需观察：AkShare 正常时不进入 BaoStock；只有明确瞬态传输错误
才 fallback；错误时继续 fail closed；重复运行的数据指纹和发布结果保持一致。

该观察用于确认运行稳定性，不属于本计划原始关闭 Gate。若发现回归，按独立缺陷处理，
不得在本计划下扩建历史数据仓库、通用 Provider 编排或额外 MCP。

## 7. 已知限制

- BaoStock 适合当前日常运行窗口，不支持多年 ETF 历史重建；
- WorkBuddy 金融 MCP 的单源风险和会话注入稳定性属于策略执行数据能力问题，不影响本地
  ETF Provider 切片完成判定；
- 数据层关闭不代表 Stage 4D、两阶段候选发现或决策反馈闭环完成。
