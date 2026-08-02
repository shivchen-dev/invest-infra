# invest-infra V2 个人版快速落地实施方案

> 仓库：`shivchen-dev/invest-infra`
> 基线提交：`a917c041a35b8e378d07d6968e396d3cadb06e25`
> 通知通道：Matrix
> 目标：基于当前 V2 已有能力，尽快形成每天可用的个人 ETF 研究闭环。
> 原则：复用已有实现，不继续扩展底层框架，不引入消息队列、微服务和复杂平台。

---

## 1. 当前进度

当前 V2 已具备：

- CifangQuant 真实 ETF Provider Adapter；
- Provider Request / Attempt / Batch 证据模型；
- ETF 主数据 Pipeline；
- ETF 日行情 Pipeline；
- `core.daily_bars` 和 revision；
- `core.latest_daily_bars`；
- Input Snapshot；
- 最小 Candidate Pool 纯函数；
- Candidate Pool 持久化；
- ETF 与 Candidate Pool 只读 API；
- CifangQuant 受控 Smoke 命令；
- Domain、Storage、Pipeline、API 测试基础。

因此下一步不再继续建设抽象层，而是补齐：

```text
真实 Provider 运行接线
→ 个人 ETF 标的池
→ 每日采集
→ Snapshot
→ Candidate Pool
→ 发布
→ Matrix 通知
→ 简单查询
```

---

## 2. 本阶段目标

完成后，每个交易日自动执行：

```text
个人 ETF 标的池
        ↓
CifangQuant 主数据和日行情
        ↓
PostgreSQL revision
        ↓
Input Snapshot
        ↓
最小 Candidate Pool
        ↓
新增 / 保留 / 移出比较
        ↓
Matrix 每日摘要
```

使用者应能看到：

- 当日采集状态；
- ETF 候选池；
- 新增候选；
- 保留候选；
- 移出候选；
- 排除原因；
- 数据缺失；
- 运行失败提醒。

---

## 3. 首期边界

| 项目 | 首期范围 |
|---|---|
| 用户 | 单用户 |
| 标的 | 20～100 只 ETF |
| 市场 | SSE / SZSE |
| Provider | CifangQuant |
| 数据频率 | 日线 |
| 复权 | `none` |
| 策略 | 一套最小候选池 |
| 通知 | Matrix |
| 存储 | PostgreSQL |
| 编排 | Dagster |
| API | FastAPI |
| 部署 | Docker Compose 单机 |

本阶段不做：

- 分钟级实时盯盘；
- 多 Provider 自动切换；
- Redis、Kafka、Celery；
- Kubernetes；
- AI 生成策略；
- 完整 FQIR；
- 完整回测平台；
- 自动交易；
- 多用户权限；
- 通用消息中心；
- 新闻、财报和 LOF 套利；
- 复杂前端管理后台。

---

## 4. 实施顺序

建议分为 5 个 PR：

```text
PR-01 真实 CifangQuant 运行接线
PR-02 个人标的池与每日 Job
PR-03 Candidate Pool 计算与发布
PR-04 Matrix 通知
PR-05 查询、运行手册与稳定性验收
```

---

# 5. PR-01：真实 CifangQuant 运行接线

## 5.1 目标

将已经实现并通过测试的 CifangQuant Adapter 接入正式 Dagster Assets。

不再修改 Provider 协议，不新增第二个 Provider。

## 5.2 配置

```env
INVEST_ENVIRONMENT=personal
INVEST_PIPELINE_PROVIDER_KEY=cifangquant
INVEST_PIPELINE_CIFANG_ENABLED=true
INVEST_PIPELINE_CIFANG_API_KEY=***
```

约束：

- `fixture_dev` 只允许 test/dev；
- personal 环境选择 fixture 时启动失败；
- API Key 只从环境变量读取；
- 日志、数据库、异常消息不得包含 API Key。

## 5.3 Provider Factory

运行时只保留：

```text
fixture_dev
cifangquant
```

通过：

```text
INVEST_PIPELINE_PROVIDER_KEY
```

选择。

不实现自动 fallback。

## 5.4 Dagster Assets

现有资产：

```text
etf_instruments_raw
etf_instruments
etf_daily_bars_raw
etf_daily_bars
```

统一通过 Provider Factory 获取 Provider。

Asset 内不要直接构造具体 Provider。

## 5.5 失败处理

真实 Provider 失败时：

- 保存失败 ProviderAttempt；
- 不创建成功 ProviderBatch；
- 不写入 core 表；
- Asset 失败；
- Pipeline Run 标记失败；
- 错误信息脱敏。

## 5.6 验收

- [ ] fixture 模式测试继续通过。
- [ ] personal 模式可以构造 Cifang Provider。
- [ ] 未显式启用时拒绝网络访问。
- [ ] API Key 缺失时立即失败。
- [ ] `make provider-smoke` 成功。
- [ ] 主数据 Asset 可使用真实 Provider。
- [ ] 日行情 Asset 可使用真实 Provider。
- [ ] 凭据不出现在日志和数据库。

---

# 6. PR-02：个人标的池与每日 Job

## 6.1 个人标的池

新增：

```text
config/personal-universe.yaml
```

示例：

```yaml
version: 1

groups:
  broad_market:
    - 510300
    - 510500
    - 159915

  technology:
    - 588000
    - 588080

  overseas:
    - 513050
    - 513100

enabled_groups:
  - broad_market
  - technology
  - overseas
```

首期使用 YAML，不建立标的管理数据库。

## 6.2 加载规则

加载后：

1. 去除空值；
2. 去重；
3. 校验六位代码；
4. 与 `core.instruments` 对齐；
5. 解析 SSE/SZSE；
6. 任意标的不存在时阻止正式运行。

建议输出：

```python
@dataclass(frozen=True)
class PersonalUniverse:
    version: int
    symbols: tuple[str, ...]
    content_hash: str
```

## 6.3 每日 Job

新增：

```text
personal_etf_daily_job
```

执行顺序：

```text
sync_etf_instruments
→ resolve_personal_universe
→ sync_etf_daily_bars
→ etf_input_snapshot
```

Job 接受显式：

```text
trade_date
```

禁止在核心流程使用 `date.today()` 推断交易日。

## 6.4 手动命令

```bash
make daily-run TRADE_DATE=2026-08-01
```

## 6.5 回补命令

```bash
make daily-backfill   START_DATE=2026-07-01   END_DATE=2026-07-31
```

第一版顺序回补，不做并发优化。

## 6.6 验收

- [ ] YAML 标的池可加载。
- [ ] 重复标的自动去重。
- [ ] 不存在标的时失败。
- [ ] 每日 Job 接收明确交易日。
- [ ] 同一日期重跑幂等。
- [ ] 回补可以逐日执行。
- [ ] 日行情写入 `core.daily_bars`。
- [ ] revision 保持有效。
- [ ] Input Snapshot 使用当日个人标的池。

---

# 7. PR-03：Candidate Pool 计算与发布

## 7.1 目标

使用现有最小 Candidate Pool Calculator 生成每日候选池。

第一版继续使用已有规则：

- 无行情排除；
- 停牌排除；
- 无效价格排除；
- 低成交量排除；
- 低成交额排除；
- 按成交额确定性排名。

不增加复杂因子。

## 7.2 参数配置

新增：

```text
config/candidate-pool-personal.yaml
```

示例：

```yaml
algorithm_key: personal_etf_candidate_pool
algorithm_version: 1.0.0
parameter_set_key: personal-default

eligibility:
  min_volume: 100000
  min_amount: 10000000

selection:
  max_candidates: 10
```

全部参数必须进入 parameter hash。

## 7.3 计算服务

建议服务：

```python
class CalculatePersonalCandidatePool:
    def execute(
        self,
        snapshot_id: UUID,
        policy: CandidatePoolPolicy,
    ) -> CandidatePoolRun:
        ...
```

执行步骤：

1. 读取 Input Snapshot；
2. 读取对应 DailyBar；
3. 调用纯函数 Calculator；
4. 保存 CandidatePoolRun；
5. 保存全部 CandidatePoolItems；
6. 校验完整性；
7. 转为 validated；
8. 发布为当前结果。

## 7.4 简化发布规则

个人版使用：

```text
输入数 > 0
+ 每个输入都有判断
+ rank 连续
+ 计算无异常
→ published
```

继续沿用：

```text
calculated → validated → published
```

## 7.5 结果比较

新增：

```python
@dataclass(frozen=True)
class CandidatePoolDiff:
    added: tuple[CandidatePoolItem, ...]
    retained: tuple[CandidatePoolItem, ...]
    removed: tuple[CandidatePoolItem, ...]
```

比较当前 published run 与上一交易日 published run。

无上一结果时：

```text
added = 当前全部候选
retained = 空
removed = 空
```

## 7.6 验收

- [ ] 使用真实行情计算。
- [ ] 相同 Snapshot 和参数结果一致。
- [ ] 每个输入 ETF 有唯一结果。
- [ ] 排除项有原因。
- [ ] rank 唯一且连续。
- [ ] Run 可发布。
- [ ] latest API 只返回 published。
- [ ] 能计算新增、保留、移出。

---

# 8. PR-04：Matrix 通知

## 8.1 目标

将每日候选池变化和任务失败发送到现有 Matrix 房间。

只实现 Matrix，不建设多渠道通知平台。

## 8.2 配置

```env
INVEST_MATRIX_ENABLED=true
INVEST_MATRIX_HOMESERVER=https://matrix.example.com
INVEST_MATRIX_ACCESS_TOKEN=***
INVEST_MATRIX_ROOM_ID=!roomid:example.com
INVEST_MATRIX_USER_ID=@invest-bot:example.com
```

Access Token：

- 只允许环境变量注入；
- 不允许 CLI 参数；
- 不写日志；
- 不写数据库错误详情。

## 8.3 最小接口

```python
class MatrixNotifier:
    def send_text(
        self,
        message: str,
        *,
        transaction_id: str,
    ) -> MatrixDeliveryResult:
        ...
```

```python
@dataclass(frozen=True)
class MatrixDeliveryResult:
    event_id: str
    transaction_id: str
```

## 8.4 幂等键

成功摘要：

```text
candidate-pool:{trade_date}:{candidate_pool_run_id}
```

失败通知：

```text
pipeline-failed:{pipeline_run_id}
```

相同事件重试时使用同一个 transaction ID。

## 8.5 每日消息

```text
📊 ETF 候选池｜2026-08-01

数据状态
• 标的池：42
• 行情成功：41
• 缺失：1
• 候选数：8

新增
• 510300 沪深300ETF｜排名 1
• 159915 创业板ETF｜排名 4

移出
• 588000 科创50ETF
  原因：成交额低于阈值

保留
• 510500 中证500ETF｜排名 2

运行状态：成功
Snapshot：a3f81c2d
Run ID：6f...
```

内容限制：

- added 全量；
- removed 全量；
- retained 最多 10 条；
- 详细结果通过 API 查看。

## 8.6 失败消息

```text
🚨 ETF 每日任务失败

交易日：2026-08-01
阶段：etf_daily_bars_raw
错误类型：authentication
Run ID：...
```

不得发送：

- API Key；
- Matrix Token；
- 完整 Provider 响应；
- 敏感 URL；
- 完整异常堆栈。

## 8.7 通知失败处理

Matrix 发送失败时：

- Candidate Pool 保持 published；
- 不回滚业务结果；
- 记录通知失败；
- 支持手动重发。

## 8.8 发送记录

可以先用结构化日志。

若需要数据库去重，再新增：

```text
ops.notification_deliveries
```

最小字段：

```text
id
event_key
transaction_id
status
attempt_count
provider_event_id
error_summary
created_at
sent_at
```

不建立模板管理、用户订阅和多渠道路由。

## 8.9 测试

使用 MockTransport 验证：

- 成功发送；
- 401/403 不重试；
- 429 有限重试；
- 5xx 有限重试；
- timeout 有限重试；
- Token 不泄漏；
- transaction ID 稳定；
- 消息格式正确。

## 8.10 验收

- [ ] Matrix 测试消息可发送。
- [ ] 每日摘要可发送。
- [ ] 故障消息可发送。
- [ ] 相同结果不重复通知。
- [ ] Token 不泄漏。
- [ ] Matrix 失败不影响发布。
- [ ] 支持指定 Run 重发。

---

# 9. PR-05：查询与稳定性验收

## 9.1 API

保留现有：

```text
GET /api/v1/etf/instruments
GET /api/v1/etf/daily-bars
GET /api/v1/candidate-pool/latest
```

补充：

```text
GET /api/v1/pipeline-runs/latest
GET /api/v1/data-freshness
GET /api/v1/candidate-pool/{run_id}/diff
```

本阶段不新增写操作 API。

## 9.2 数据新鲜度

示例：

```json
{
  "trade_date": "2026-08-01",
  "universe_count": 42,
  "daily_bar_count": 41,
  "missing_count": 1,
  "candidate_count": 8,
  "status": "partial",
  "last_success_at": "2026-08-01T16:05:12+08:00"
}
```

## 9.3 页面

首期可继续使用：

- Dagster UI；
- FastAPI `/docs`；
- 现有 React 骨架。

若增加页面，只增加一个“个人 ETF 每日页”：

- 交易日；
- 数据新鲜度；
- 当前候选；
- 新增和移出；
- 排除原因；
- 最近运行状态。

## 9.4 Schedule

新增 Dagster Schedule：

```text
周一至周五 16:10 Asia/Shanghai
```

节假日或无数据时：

- 标记 skipped；
- 不发送失败通知。

## 9.5 Makefile

```bash
make provider-smoke
make daily-run TRADE_DATE=2026-08-01
make daily-backfill START_DATE=2026-07-01 END_DATE=2026-07-31
make matrix-test
make matrix-resend RUN_ID=<uuid>
```

## 9.6 Runbook

新增：

```text
docs/runbooks/personal-daily-run.md
docs/runbooks/cifang-auth-failure.md
docs/runbooks/matrix-delivery-failure.md
docs/runbooks/reprocess-trade-date.md
```

## 9.7 稳定性验证

连续运行至少：

```text
10 个交易日
```

验收：

- 日任务成功率 ≥ 90%；
- 重跑不重复写业务数据；
- Matrix 无重复消息；
- 每天能生成 published 候选池；
- 失败日期可以单独补跑；
- 凭据无泄漏。

---

# 10. 每日完整流程

```text
1. Dagster Schedule 触发
2. 创建 Pipeline Run
3. 加载 personal-universe.yaml
4. 同步 ETF 主数据
5. 校验个人标的池
6. 获取日行情
7. 写 Provider evidence
8. 写 core.daily_bars
9. 创建 Input Snapshot
10. 计算 Candidate Pool
11. 保存全部 items
12. 发布 Candidate Pool
13. 读取上一交易日结果
14. 生成 added / retained / removed
15. 格式化 Matrix 消息
16. 发送 Matrix
17. 完成 Pipeline Run
```

---

# 11. Issue 拆分

建议控制为 14 个 Issue：

1. CifangQuant 接入 Provider Factory。
2. 真实 Provider 接入主数据 Asset。
3. 真实 Provider 接入日行情 Asset。
4. 增加 personal-universe.yaml。
5. 实现 PersonalUniverse Loader。
6. 实现 personal_etf_daily_job。
7. 增加 daily-run 和 backfill 命令。
8. 完善 Candidate Pool 计算服务。
9. 实现 Candidate Pool 发布。
10. 实现 Candidate Pool Diff。
11. 实现 Matrix Client。
12. 实现 Matrix 每日摘要与故障通知。
13. 增加 data-freshness API。
14. 完成 Runbook 和 10 日验收。

---

# 12. Definition of Done

## 数据

- [ ] 个人 ETF 池配置可用。
- [ ] 真实主数据可采集。
- [ ] 真实日行情可采集。
- [ ] DailyBar revision 正常。
- [ ] Input Snapshot 正常。
- [ ] 缺失数据可识别。

## 候选池

- [ ] 使用真实数据计算。
- [ ] 结果确定性。
- [ ] 每个输入 ETF 有判断结果。
- [ ] latest 只返回 published。
- [ ] 能计算新增、保留、移出。

## Matrix

- [ ] 每日摘要可发送。
- [ ] 故障消息可发送。
- [ ] 相同结果不重复通知。
- [ ] 通知失败不回滚业务结果。
- [ ] Token 不泄漏。

## 使用

- [ ] 有单日运行命令。
- [ ] 有历史补跑命令。
- [ ] 有 Provider Smoke 命令。
- [ ] 有 Matrix 测试命令。
- [ ] API 能查询最新结果。
- [ ] 连续运行 10 个交易日。

---

# 13. 防止过度工程化

本阶段严格限制：

1. 不增加第二个真实 Provider。
2. 不增加 Redis、Kafka、Celery。
3. 不拆微服务。
4. 不建立通用通知平台。
5. 不建立复杂规则引擎。
6. 不实现 AI 生成 Python 策略。
7. 不实现分钟行情。
8. 不实现全市场扫描。
9. 不建设复杂权限。
10. 不建设完整管理后台。
11. 不增加第二个数据库。
12. 不重写已有稳定模块。
13. 每个新增抽象必须有当前调用方。
14. 每个 PR 必须形成可运行增量。

---

# 14. 后续阶段

个人版稳定后再评估：

## 第二阶段

```text
大盘择时
T+5 / T+20 信号回看
候选池历史变化
简单参数调整
```

## 第三阶段

```text
AI 研究解释
新闻与行情联合分析
更完整策略规则
```

暂不承诺：

```text
分钟盯盘
LOF 套利
自动交易
多用户 SaaS
```

---

# 15. 最终交付形态

第一阶段完成后，个人使用流程为：

```text
每天 16:10 自动运行
        ↓
Matrix 收到候选池摘要
        ↓
通过 API 或简单页面查看详情
        ↓
异常时根据 Run ID 补跑
```

最终核心成果：

> V2 每个交易日能够基于真实 CifangQuant 行情生成可追踪的 ETF 候选池，并通过 Matrix 稳定发送新增、保留、移出和故障摘要。
