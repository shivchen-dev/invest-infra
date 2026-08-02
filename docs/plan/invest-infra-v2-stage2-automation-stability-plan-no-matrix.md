# invest-infra V2 第二阶段执行计划：自动化运行与稳定性

> 仓库：`shivchen-dev/invest-infra`  
> 基线提交：`d48f8592d00918db8264e79a3c73ce8f4ba5d9b5`  
> 阶段主题：从“手动可运行”升级到“每日自动、可观测、可补跑”  
> 通知：本阶段暂不接入 Matrix  
> 建设原则：先关闭第一阶段遗留问题，再增加最小自动化和运维能力，不扩展策略与 AI。

---

## 1. 阶段定位

第一阶段已经形成：

```text
CifangQuant / fixture_dev
→ ETF 主数据
→ ETF 日行情
→ Input Snapshot
→ Candidate Pool
→ Published Result
→ API 查询
```

第二阶段不再扩展数据模型和策略规则，重点解决：

```text
如何自动运行
如何判断该不该运行
如何知道运行是否成功
如何发现数据是否过期
如何补跑失败日期
如何验证整条链路长期稳定
```

第二阶段完成后的目标链路：

```text
交易日收盘后自动触发
        ↓
运行前检查
        ↓
personal_etf_daily_job
        ↓
数据完整性检查
        ↓
Candidate Pool 发布
        ↓
Pipeline Run 状态记录
        ↓
API 查询新鲜度、运行状态和结果变化
        ↓
失败日期可手动补跑
```

---

## 2. 本阶段目标

完成后系统应具备：

1. 每个工作日收盘后自动触发一次每日 Job。
2. 非交易日或 Provider 尚无当日数据时安全跳过。
3. 同一交易日不并发执行多个正式运行。
4. 可查询最新运行状态和失败原因。
5. 可查询数据新鲜度和缺失数量。
6. 可比较相邻已发布 Candidate Pool。
7. 可手动补跑一个日期或一段日期。
8. CI 在真实 PostgreSQL 中验证完整 fixture 链路。
9. 真实 CifangQuant 运行有脱敏验收记录。
10. 连续运行至少 10 个交易日。

---

## 3. 本阶段明确不做

暂不建设：

- Matrix 通知；
- 邮件或企业微信；
- AI 分析；
- AI 生成策略；
- 分钟级实时监控；
- 完整 FQIR；
- 回测平台；
- 新闻和财报；
- 多 Provider 自动切换；
- Redis、Kafka、Celery；
- Kubernetes；
- 多用户权限；
- 通用告警平台；
- 复杂前端管理后台；
- 自动交易。

---

## 4. 实施顺序

建议拆分为 5 个 PR：

```text
PR-01 第一阶段收尾与验收门禁
PR-02 自动 Schedule 与运行前检查
PR-03 运行状态和数据新鲜度
PR-04 Candidate Pool Diff 与补跑工具
PR-05 全链路 E2E 和连续运行验收
```

依赖关系：

```text
PR-01
  ↓
PR-02
  ↓
PR-03
  ↓
PR-04
  ↓
PR-05
```

---

# 5. PR-01：第一阶段收尾与验收门禁

## 5.1 目标

关闭第一阶段尚未完全满足的验收条件，确保自动化建立在稳定手动链路上。

## 5.2 主数据使用分区日期

当前日行情、Snapshot 和 Candidate Pool 使用 Dagster partition date，但主数据链仍可能使用系统当天日期。

修改：

```python
as_of = date.fromisoformat(context.partition_key)
```

涉及：

```text
etf_instruments_raw
etf_instruments
```

要求：

- 历史补跑时整条链路使用同一业务日期；
- 不再使用 `date.today()` 作为主数据请求业务日期；
- fixture 与 CifangQuant Request Key 使用同一日期语义。

如果 Provider 的主数据接口实际上不支持历史时点，仍将 partition date 作为审计 `as_of`，并在 ADR 中说明其语义是“本次运行面向的业务日期”，而不是保证 Provider 返回历史快照。

## 5.3 PostgreSQL Fixture E2E

新增：

```text
tests/e2e/test_personal_daily_pipeline_postgres.py
```

或放入现有 pipeline integration 目录。

测试流程：

```text
空 PostgreSQL
→ alembic upgrade head
→ fixture_dev personal daily run
→ 验证 raw evidence
→ 验证 instruments
→ 验证 daily bars
→ 验证 snapshot
→ 验证 candidate pool
→ 验证 latest API
→ 同日再次运行
→ 验证幂等
```

必须验证：

- `raw.provider_requests` 有主数据和日行情请求；
- `raw.provider_attempts` 有成功 attempt；
- `raw.provider_batches` 有成功 batch；
- `core.instruments` 包含个人 ETF 池；
- `core.daily_bars` 有当日行情；
- `analytics.input_snapshots` 有当日 Snapshot；
- Candidate Pool Run 状态为 `published`；
- Candidate Pool Items 数量等于 Snapshot row count；
- 同日第二次运行不增加相同 DailyBar revision；
- 相同自然键不重复创建 Candidate Pool Run；
- API 返回该 published Run。

## 5.4 真实 CifangQuant 验收记录

新增：

```text
docs/validation/stage1-real-cifang-acceptance.md
```

记录：

- 验收提交 SHA；
- 执行时间；
- 业务交易日；
- Provider Key；
- 主数据数量；
- 个人池数量；
- 日行情数量；
- Snapshot ID；
- Candidate Pool Run ID；
- included / excluded 数量；
- 同日第二次执行结果；
- latest API 摘要。

不得记录：

- API Key；
- 请求头；
- 完整原始响应；
- 敏感 URL 参数。

## 5.5 ADR-0011 状态

确认以下事项后，将 ADR 更新为：

```text
Accepted for personal deployment
```

确认项：

- 个人使用授权；
- API 访问方式；
- 基本限频；
- `adjustment=none` 语义；
- 凭据通过环境变量注入；
- 自动运行频率不超过配额。

如果授权仍未确认，则第二阶段 Schedule 只能使用 fixture，真实 CifangQuant 继续保持手动运行。

## 5.6 最小 Runbook

新增：

```text
docs/runbooks/cifang-auth-failure.md
docs/runbooks/reprocess-trade-date.md
```

每份只包含：

- 症状；
- 检查命令；
- 修复步骤；
- 重跑命令；
- 成功验证。

## 5.7 验收标准

- [ ] 主数据链使用 partition date。
- [ ] PostgreSQL Fixture E2E 通过。
- [ ] 同日重跑幂等。
- [ ] 真实 Cifang 验收记录已归档。
- [ ] ADR-0011 状态与实际使用一致。
- [ ] 两份最小 Runbook 可执行。
- [ ] `make test` 全部通过。

---

# 6. PR-02：自动 Schedule 与运行前检查

## 6.1 目标

建立一个安全的自动运行入口。

自动化原则：

```text
可以安全跳过
不能重复运行
失败可以手动补跑
不能因自动化改变已有业务结果
```

## 6.2 Dagster Schedule

新增：

```text
personal_etf_daily_schedule
```

建议时间：

```text
周一至周五 16:10 Asia/Shanghai
```

原因：

- 避开 15:00 刚收盘的数据延迟；
- 给 Provider 留出数据更新窗口；
- 个人日线策略不需要更早执行。

注册到：

```text
apps/pipeline/src/invest_pipeline/definitions.py
```

## 6.3 Schedule 行为

Schedule 只负责生成 RunRequest，不负责业务计算。

伪代码：

```python
@dg.schedule(
    job=personal_etf_daily_job,
    cron_schedule="10 16 * * 1-5",
    execution_timezone="Asia/Shanghai",
)
def personal_etf_daily_schedule(context):
    trade_date = context.scheduled_execution_time.date()

    return dg.RunRequest(
        run_key=f"personal-etf-daily:{trade_date.isoformat()}",
        partition_key=trade_date.isoformat(),
        tags={
            "trade_date": trade_date.isoformat(),
            "trigger_type": "schedule",
        },
    )
```

使用稳定 `run_key`，避免同一计划时间重复创建相同运行。

## 6.4 运行前检查

新增一个最小 Preflight Service：

```text
apps/pipeline/src/invest_pipeline/daily_preflight.py
```

输入：

```text
trade_date
provider
personal universe
```

输出：

```python
@dataclass(frozen=True)
class DailyPreflightResult:
    decision: str  # run / skip / fail
    reason: str
```

检查：

1. 日期不能在未来；
2. 周末直接 skip；
3. 个人 ETF 池必须可加载；
4. Provider 配置必须完整；
5. 当日已存在成功 published Run 时 skip；
6. 当日已有 running Run 时 fail 或 skip；
7. Provider 数据为空时：
   - 可识别为“数据尚未就绪”则 skip；
   - 鉴权、契约错误则 fail。

第一版不建设完整交易日历服务。

## 6.5 跳过语义

区分：

```text
skip_non_business_day
skip_already_published
skip_data_not_ready
```

跳过不能标记为失败。

对于正常跳过，优先在 Schedule 不产生 RunRequest，或者由专用 preflight op 返回 skipped metadata。

## 6.6 单运行保护

同一交易日、同一 Job：

```text
只允许一个 active run
```

第一版使用两层保护：

1. Schedule `run_key`；
2. `ops.pipeline_runs` 查询当前 `running` 记录。

不引入 Redis 锁或分布式锁服务。

## 6.7 自动运行配置

新增：

```env
INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false
```

默认关闭。

只有完成 Stage 1 Closure 后才设置为：

```env
INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=true
```

## 6.8 测试

覆盖：

- 周一至周五生成 RunRequest；
- 周末 skip；
- 相同日期 run_key 稳定；
- 已 published 时 skip；
- 已 running 时不重复运行；
- Provider 未启用时 fail；
- 个人池配置错误时 fail；
- 自动 Schedule 默认关闭；
- 测试不访问真实网络。

## 6.9 验收标准

- [ ] Schedule 已注册。
- [ ] 默认关闭。
- [ ] 能按 Asia/Shanghai 16:10 触发。
- [ ] 周末不会运行。
- [ ] 同日不会重复创建正式运行。
- [ ] 已发布日期自动跳过。
- [ ] 数据未就绪与真实错误可区分。
- [ ] 不使用 Matrix。

---

# 7. PR-03：运行状态与数据新鲜度

## 7.1 目标

让使用者无需查看数据库即可判断：

```text
系统最近是否运行
数据是否是最新交易日
哪一步失败
候选池是否已发布
```

## 7.2 Pipeline Run API

新增：

```text
GET /api/v1/pipeline-runs/latest
GET /api/v1/pipeline-runs/{run_id}
```

查询范围：

```text
personal_etf_daily_job
```

latest 返回：

```json
{
  "id": "uuid",
  "job_key": "personal_etf_daily_job",
  "partition_key": "2026-08-03",
  "trigger_type": "schedule",
  "status": "succeeded",
  "started_at": "...",
  "finished_at": "...",
  "error_code": null,
  "error_summary": null
}
```

## 7.3 Pipeline Run 审计要求

自动运行必须写入：

```text
ops.pipeline_runs
```

生命周期：

```text
running
→ succeeded
→ failed
```

正常跳过时，第一版推荐 Schedule 不生成 RunRequest，因此不创建 Pipeline Run，不扩展现有状态机。

## 7.4 数据新鲜度 Service

新增：

```text
apps/api/src/invest_api/services/data_freshness.py
```

计算：

- 最新 published Candidate Pool 交易日；
- 个人 ETF 池数量；
- 当日日行情覆盖数量；
- 缺失数量；
- 最新 Snapshot ID；
- 最新 Pipeline Run 状态；
- 数据状态。

返回状态：

```text
fresh
partial
stale
missing
failed
```

## 7.5 数据新鲜度 API

新增：

```text
GET /api/v1/data-freshness
```

示例：

```json
{
  "as_of": "2026-08-03",
  "latest_published_trade_date": "2026-08-03",
  "universe_count": 7,
  "daily_bar_count": 7,
  "missing_count": 0,
  "candidate_count": 5,
  "snapshot_id": "uuid",
  "pipeline_run_id": "uuid",
  "pipeline_status": "succeeded",
  "status": "fresh"
}
```

## 7.6 状态规则

建议：

```text
fresh:
  最新 published trade_date 是预期交易日
  且 daily_bar_count == universe_count

partial:
  有 published 结果
  但存在 no_data 或缺失行情

stale:
  最新 published trade_date 早于预期交易日

missing:
  没有任何 published 结果

failed:
  最新正式 Pipeline Run 失败
  且没有该日期 published 结果
```

“预期交易日”第一版可以由查询参数 `expected_trade_date` 提供；默认使用最近一个周一至周五日期。

暂不建设节假日日历服务。

## 7.7 Candidate Pool 结果中的 no_data

新鲜度统计必须区分：

- Provider 完全未返回；
- 日行情未写入；
- Calculator 输出 `no_data`。

不得因为 Candidate Pool 仍可发布就把缺失行情视为完整成功。

## 7.8 测试

覆盖：

- fresh；
- partial；
- stale；
- missing；
- failed；
- Pipeline Run latest；
- Run 不存在 404；
- API 只读；
- 数据库异常返回标准 500，不暴露 SQL。

## 7.9 验收标准

- [ ] latest Pipeline Run 可查询。
- [ ] 指定 Run 可查询。
- [ ] 数据新鲜度可查询。
- [ ] 缺失行情能显示。
- [ ] 失败原因经过脱敏。
- [ ] API 不触发 Pipeline。
- [ ] 不新增前端页面。

---

# 8. PR-04：Candidate Pool Diff 与补跑工具

## 8.1 目标

在不发送通知的前提下，提供：

- 结果变化查询；
- 单日补跑；
- 日期区间顺序回补。

## 8.2 Candidate Pool Diff

新增服务：

```python
@dataclass(frozen=True)
class CandidatePoolDiff:
    current_run_id: UUID
    previous_run_id: UUID | None
    added: tuple[CandidateSummary, ...]
    retained: tuple[CandidateSummary, ...]
    removed: tuple[CandidateSummary, ...]
```

比较：

```text
当前 published Run
vs
前一个更早的 published Run
```

按 `instrument_id` 比较。

## 8.3 Diff API

新增：

```text
GET /api/v1/candidate-pool/{run_id}/diff
```

可选：

```text
GET /api/v1/candidate-pool/latest/diff
```

返回：

```json
{
  "trade_date": "2026-08-03",
  "previous_trade_date": "2026-07-31",
  "added": [],
  "retained": [],
  "removed": []
}
```

本阶段只提供查询，不推送 Matrix。

## 8.4 单日补跑

保留：

```bash
make personal-daily-run TRADE_DATE=2026-08-03
```

新增更明确别名：

```bash
make reprocess-date TRADE_DATE=2026-08-03
```

两者调用同一 CLI。

## 8.5 区间回补

新增：

```bash
make personal-backfill \
  START_DATE=2026-07-01 \
  END_DATE=2026-07-31
```

实现为顺序运行：

```text
逐日
→ 周末跳过
→ 成功继续
→ 失败默认停止
```

第一版不做并发回补。

## 8.6 Backfill CLI

建议：

```text
apps/pipeline/src/invest_pipeline/personal_backfill_cli.py
```

参数：

```text
--start-date
--end-date
--universe
--policy
--confirm-network
```

限制：

- 最大区间默认 90 天；
- start <= end；
- 不允许未来日期；
- 不并发运行；
- 使用现有 personal daily Job；
- 输出每个日期摘要。

## 8.7 幂等

回补依赖现有幂等规则：

- 相同 Provider Request 增加 Attempt，但不覆盖历史；
- 相同 DailyBar no-op；
- 内容变化增加 revision；
- 相同 Candidate Pool 自然键复用；
- 已 published 日期默认 skip。

可增加 `--force`，仅在明确需要重新采集时使用。

## 8.8 测试

覆盖：

- Diff added；
- Diff removed；
- Diff retained；
- 无上一 Run；
- 区间日期校验；
- 周末跳过；
- 已 published 跳过；
- 失败停止；
- 输出不包含 Token；
- 不访问真实网络。

## 8.9 验收标准

- [ ] Candidate Pool Diff 可查询。
- [ ] 单日补跑命令可用。
- [ ] 区间回补命令可用。
- [ ] 默认顺序执行。
- [ ] 已发布日期默认跳过。
- [ ] 可明确强制重跑。
- [ ] 不发送通知。

---

# 9. PR-05：全链路 E2E 与连续运行验收

## 9.1 目标

证明自动运行链路在测试和个人部署环境中稳定。

## 9.2 CI 新增 Job

新增：

```text
personal-daily-e2e
```

GitHub Actions 中启动 PostgreSQL 16：

```text
alembic upgrade head
→ fixture_dev personal daily run
→ 数据库断言
→ API 断言
→ 同日重跑
→ 幂等断言
```

## 9.3 CI 断言

至少包括：

```text
Provider Request ≥ 2
Provider Attempt ≥ 2
Provider Batch ≥ 2
Instrument count == universe count
DailyBar count == universe count
Snapshot row_count == universe count
CandidatePool Items == universe count
CandidatePool status == published
latest API run_id 正确
第二次运行 DailyBar revision 不增加
第二次运行 Candidate Pool 自然键不重复
```

## 9.4 Schedule 单元测试

CI 不等待真实时间。

直接测试：

- Schedule evaluation；
- RunRequest；
- run_key；
- partition_key；
- tags；
- enabled 开关；
- 周末跳过。

## 9.5 个人环境影子运行

先开启：

```text
自动 Schedule
+ 真实 CifangQuant
+ 不发送通知
```

连续运行至少：

```text
10 个交易日
```

每日人工或 API 检查：

- Pipeline Run；
- 数据新鲜度；
- Candidate Pool；
- 缺失行情；
- 是否重复运行。

## 9.6 运行记录

新增：

```text
docs/validation/stage2-shadow-run-log.md
```

每个交易日记录：

| 日期 | Run 状态 | 标的数 | 行情数 | 候选数 | 缺失 | 是否补跑 |
|---|---|---:|---:|---:|---:|---|

只记录摘要。

## 9.7 阶段通过指标

- 自动运行成功率 ≥ 90%；
- 失败日期全部可补跑；
- 无同日并发重复发布；
- 无相同内容 revision 增长；
- 无凭据泄漏；
- 数据新鲜度状态与实际一致；
- API 可查询每次运行；
- 10 个交易日中至少 9 天产生 published 结果。

## 9.8 验收标准

- [ ] CI E2E 全绿。
- [ ] Schedule 测试通过。
- [ ] 自动 Schedule 在个人环境启用。
- [ ] 连续 10 个交易日记录完成。
- [ ] 失败日期成功补跑。
- [ ] 无重复运行和重复发布。
- [ ] 无 Matrix 相关代码或配置进入运行链。

---

# 10. Issue 拆分

建议控制为 13 个 Issue：

1. 主数据 Assets 改用 partition date。
2. 增加 PostgreSQL Personal Daily E2E。
3. 归档真实 CifangQuant Stage 1 验收记录。
4. 更新 ADR-0011 个人部署状态。
5. 增加 Cifang 鉴权失败 Runbook。
6. 增加交易日补跑 Runbook。
7. 实现 Personal Daily Schedule。
8. 实现 Daily Preflight。
9. 增加 Pipeline Run 查询 API。
10. 增加 Data Freshness API。
11. 实现 Candidate Pool Diff。
12. 实现 Personal Backfill CLI。
13. 完成 10 个交易日影子运行验收。

---

# 11. 建议执行节奏

```text
第一步
关闭第一阶段遗留问题
        ↓
第二步
注册但默认关闭 Schedule
        ↓
第三步
实现 Pipeline Run 和 Freshness 查询
        ↓
第四步
实现 Diff 与 Backfill
        ↓
第五步
CI E2E
        ↓
第六步
开启真实自动 Schedule
        ↓
第七步
连续 10 个交易日影子运行
```

---

# 12. 通用 Definition of Done

## 代码

- [ ] 不引入 Matrix。
- [ ] 不引入新的基础设施。
- [ ] 不新增第二 Provider。
- [ ] API 保持只读。
- [ ] Schedule 只负责触发。
- [ ] 业务逻辑继续在 Service / Domain 中。
- [ ] 不使用系统时间替代业务 trade_date。

## 测试

- [ ] 单元测试通过。
- [ ] PostgreSQL E2E 通过。
- [ ] Migration 测试通过。
- [ ] API 测试通过。
- [ ] Schedule evaluation 测试通过。
- [ ] 普通 CI 不访问真实 Provider。

## 运行

- [ ] 自动运行默认可关闭。
- [ ] 同日不重复运行。
- [ ] 已发布日期默认跳过。
- [ ] 失败日期可补跑。
- [ ] 数据状态可查询。
- [ ] 错误摘要脱敏。

## 文档

- [ ] 自动运行说明完成。
- [ ] 补跑说明完成。
- [ ] 真实 Provider 验收记录完成。
- [ ] 影子运行记录完成。

---

# 13. 阶段停止条件

满足以下条件即结束第二阶段：

```text
自动 Schedule 已启用
+ 真实 CifangQuant 每日运行
+ Pipeline Run 可查询
+ 数据新鲜度可查询
+ Candidate Pool Diff 可查询
+ 失败日期可补跑
+ PostgreSQL E2E 进入 CI
+ 连续 10 个交易日稳定运行
```

之后再评估第三阶段：

```text
Matrix 通知
简单结果页面
T+5 / T+20 信号回看
大盘择时
```

---

# 14. 防止过度工程化

本阶段禁止：

1. 建设通用调度平台。
2. 建设通用通知中心。
3. 接入 Matrix。
4. 引入消息队列。
5. 引入 Redis 锁。
6. 引入完整交易所日历微服务。
7. 并发 Backfill。
8. 自动多 Provider fallback。
9. 重写 Candidate Pool 算法。
10. 建设完整前端管理台。
11. 建设 AI 模型层。
12. 增加分钟行情。
13. 增加多用户权限。
14. 为未来规模分库分表。

---

# 15. 最终交付形态

第二阶段完成后，系统的个人使用方式为：

```text
每个工作日 16:10 自动执行
        ↓
通过 /api/v1/pipeline-runs/latest 查看运行
        ↓
通过 /api/v1/data-freshness 查看数据状态
        ↓
通过 /api/v1/candidate-pool/latest 查看候选池
        ↓
通过 diff API 查看相对上一期的变化
        ↓
失败时使用 reprocess-date 或 personal-backfill 补跑
```

本阶段核心成果：

> V2 可以在不依赖 Matrix 通知的情况下，稳定地每日自动运行真实 ETF 数据链路，并提供运行状态、数据新鲜度、结果变化和补跑能力。
