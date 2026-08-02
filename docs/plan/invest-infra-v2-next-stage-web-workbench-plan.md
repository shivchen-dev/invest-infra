# invest-infra V2 下一阶段执行计划：Web 数据工作台

> 仓库：`shivchen-dev/invest-infra`
> 基线提交：`55ebfed2bb0b457cd05fcf124cec42f1919bf869`
> 阶段主题：Web 数据展示与个人投研使用体验
> 通知方案：不接入 Matrix、邮件或其他聊天频道
> 建设原则：保持 V2 原有 Pipeline → PostgreSQL → FastAPI → React 架构，Web 只读，不承担数据采集、策略计算和任务编排。

## 核实记录（2026-08-02）

核实基线：`55ebfed`（当前 `main`）。结论如下：

- API 已具备 Candidate Pool、Candidate Pool Diff、Data Freshness、Pipeline Run latest 和 ETF 主数据/日行情只读端点，但 Candidate Pool Diff 仍比较全部 item，Data Freshness 仍按全市场活跃标的统计，Candidate Pool 展示字段尚未完成；这些正是本计划 API PR-1 / PR-2 的待办。
- Pipeline Run 当前没有 `GET /api/v1/pipeline-runs?limit=&offset=` 历史列表端点，需要在 PR-2 补齐。
- Web 当前仍为单页标的表格，继续使用旧路径 `/v1/instruments`；Dashboard、Candidate Pool、ETF 详情、Operations、统一 API Client 和 Web 测试尚未实施。
- 当前仓库未发现 Redux、Zustand、大型图表库、WebSocket、BFF 或 Web 写操作，与本阶段“不做”约束一致。

因此，本文件作为下一阶段正式执行计划；API PR-1 / PR-2 是 Web 开发的前置门槛，当前不应直接宣称 Web 阶段完成。

---

## 1. 阶段定位

当前 V2 已经具备：

```text
CifangQuant / fixture_dev
→ ETF 主数据
→ ETF 日行情
→ Input Snapshot
→ Candidate Pool
→ Published Result
→ Pipeline Run / Data Freshness / Diff API
```

下一阶段不继续增加通知系统，也不扩展策略和 AI。

本阶段只解决：

```text
如何在 Web 中快速判断数据是否正常
如何查看最新候选池
如何查看新增、保留、移出变化
如何查看 ETF 行情和排除原因
如何查看每日任务运行状态
```

最终形成：

```text
Dagster Pipeline
        ↓
PostgreSQL
        ↓
FastAPI 只读 API
        ↓
React Web 数据工作台
```

---

## 2. 当前 Web 状态

当前 Web 端仍是初始骨架：

- 只有一个标的主数据表；
- 只调用一个 instruments API；
- API 地址仍使用旧路径 `/v1/instruments`；
- 未展示 Candidate Pool；
- 未展示 Data Freshness；
- 未展示 Pipeline Run；
- 未展示 Candidate Pool Diff；
- 未展示 ETF 日行情；
- 没有错误恢复和空状态设计；
- 没有 Web 单元测试。

现有技术栈：

```text
React 19
TypeScript
Vite
TanStack React Query
```

本阶段继续使用现有技术栈。

可以新增：

```text
react-router-dom
vitest
@testing-library/react
@testing-library/jest-dom
```

不引入：

- Redux；
- Zustand；
- Next.js；
- 大型 UI 框架；
- 图表平台；
- 微前端；
- BFF；
- WebSocket；
- SSR。

---

## 3. 本阶段目标

完成后，Web 首页应能直接回答：

1. 最新业务交易日是什么；
2. 数据状态是 fresh、partial、stale、missing 还是 failed；
3. 个人 ETF 池有多少只；
4. 日行情覆盖多少只；
5. 最新候选池有多少只；
6. 哪些 ETF 新增、保留或移出；
7. 每只 ETF 为什么入选或被排除；
8. 最新 Pipeline Run 是否成功；
9. 指定 ETF 最近一段时间行情如何；
10. 数据来自哪个 Provider 和哪个 revision。

---

## 4. 阶段范围

### 4.1 必须完成

1. 修复 Web 使用的旧 API 路径。
2. 修正 Candidate Pool Diff 的业务语义。
3. 修正 Data Freshness 的个人标的池统计口径。
4. 丰富 Candidate Pool API 的展示字段。
5. 建立统一 TypeScript API Client。
6. 建立 Web Dashboard。
7. 建立 Candidate Pool 详情视图。
8. 建立 ETF 行情详情视图。
9. 建立 Pipeline Run 状态视图。
10. 完成响应式布局。
11. 增加最小 Web 测试。
12. 更新 Docker Compose 和运行文档。
13. 使用 fixture 数据完成前后端 E2E 验收。
14. 在真实 CifangQuant 验收完成后验证真实数据展示。

### 4.2 明确不做

本阶段不建设：

- Matrix 或其他通知；
- Web 中手动触发 Pipeline；
- Web 中编辑个人 ETF 池；
- Web 中编辑 Candidate Pool 参数；
- Web 中开启或关闭 Dagster Schedule；
- 用户登录和多用户权限；
- 自动交易；
- 实时分钟行情；
- WebSocket；
- AI 分析；
- 新闻和财报；
- 完整回测；
- 复杂图表库；
- 通用 BI 平台；
- 手机 App。

---

# 5. 开发前置修正

Web 开发前，必须先修正三个 API 读模型问题。

## 5.1 Candidate Pool Diff 只比较入选标的

当前 Candidate Pool 每个输入 ETF 都会生成一条 item：

```text
included = true
或
included = false
```

现有 Diff 比较的是全部 item 的 `instrument_id`。

如果个人 ETF 池没有变化，结果会一直显示全部标的 retained，这不是候选池变化，而是输入池变化。

### 修正规则

Diff 必须只比较：

```text
included = true
```

的标的。

```python
def _included_instrument_id_set(items) -> set[UUID]:
    return {
        item.instrument_id.value
        for item in items
        if item.included
    }
```

修正后：

```text
added
= 今天入选、昨天未入选

retained
= 今天和昨天都入选

removed
= 昨天入选、今天未入选
```

### 验收

- [ ] 只比较 included items。
- [ ] 排除项不出现在 retained。
- [ ] 无上一 Run 时，当前入选项全部为 added。
- [ ] 当前全部排除时，上一入选项全部为 removed。
- [ ] API 测试覆盖四种变化场景。

## 5.2 Data Freshness 使用个人 Snapshot 口径

当前 `universe_count` 统计全部活跃标的，不一定等于个人 ETF 池。

### 修正口径

优先使用当前交易日 Snapshot：

```text
analytics.input_snapshots.row_count
```

建议顺序：

1. 找到 expected_trade_date 对应的 Snapshot；
2. `universe_count = snapshot.row_count`；
3. 如果没有当日 Snapshot，使用最近 published Candidate Pool 的 `input_row_count`；
4. 都不存在时，`universe_count = 0`。

日行情覆盖数只统计 Snapshot 中的 Instrument IDs。

### 修正状态判断

继续使用：

```text
failed
missing
stale
partial
fresh
```

但 `partial` 必须基于：

```text
snapshot instrument count
vs
snapshot instruments with daily bars
```

### 验收

- [ ] universe_count 等于个人 Snapshot row_count。
- [ ] daily_bar_count 只统计 Snapshot 标的。
- [ ] missing_count 不受全市场 ETF 影响。
- [ ] Fixture E2E 中 freshness 为 fresh。
- [ ] 缺失一只行情时 freshness 为 partial。

## 5.3 Candidate Pool API 增加展示字段

当前 Candidate Pool 返回 UUID 和策略判断，但缺少 Web 展示需要的主数据和运行元数据。

建议增加：

```text
symbol
name
exchange
run_id
algorithm_key
algorithm_version
parameter_set_key
included_count
excluded_count
published_at
snapshot_id
```

推荐响应：

```json
{
  "run_id": "uuid",
  "trade_date": "2026-08-01",
  "algorithm_key": "personal_etf_candidate_pool",
  "algorithm_version": "1.0.0",
  "parameter_set_key": "personal-default",
  "snapshot_id": "uuid",
  "content_hash": "...",
  "row_count": 42,
  "included_count": 8,
  "excluded_count": 34,
  "published_at": "...",
  "items": [
    {
      "instrument_id": "uuid",
      "symbol": "510300",
      "name": "沪深300ETF",
      "exchange": "SSE",
      "included": true,
      "rank": 1,
      "total_score": null,
      "metrics": {
        "turnover": "1530000000"
      },
      "rule_results": [],
      "exclusion_reasons": []
    }
  ]
}
```

API 应在服务端完成 Instrument Join，Web 不应逐项请求 instruments API。

---

# 6. 推荐页面结构

本阶段采用四个主要路由：

```text
/dashboard
/candidate-pool
/etf/:instrumentId
/operations
```

根路径重定向到 `/dashboard`。

---

# 7. 页面一：Dashboard

## 7.1 目标

作为每日默认页面，一屏判断系统状态和候选结果。

## 7.2 页面结构

```text
顶部导航
数据状态 Banner
KPI Cards
候选池变化
最新候选
最新运行
```

## 7.3 数据状态 Banner

调用：

```text
GET /api/v1/data-freshness
```

状态显示：

| 状态 | 显示 |
|---|---|
| fresh | 数据已更新 |
| partial | 数据部分缺失 |
| stale | 数据未更新到预期日期 |
| missing | 尚无发布结果 |
| failed | 最新任务失败 |

展示：

```text
预期交易日
最新发布日期
标的池数量
行情覆盖数量
缺失数量
最后检查时间
```

## 7.4 KPI Cards

四张卡片：

```text
个人 ETF 数
当日行情覆盖
候选数
最新 Run 状态
```

## 7.5 候选池变化

调用：

```text
GET /api/v1/candidate-pool/latest/diff
```

展示：

```text
新增
保留
移出
```

每项显示：

```text
symbol
name
今日排名
```

## 7.6 最新候选

展示前 10 名：

```text
排名
代码
名称
交易所
成交额
状态
```

点击进入 ETF 详情。

## 7.7 最新运行

调用：

```text
GET /api/v1/pipeline-runs/latest
```

展示：

```text
业务日期
状态
触发方式
开始时间
结束时间
耗时
错误摘要
```

---

# 8. 页面二：Candidate Pool

## 8.1 目标

完整展示当日每只 ETF 的策略判断。

## 8.2 顶部摘要

展示：

```text
交易日
Run ID
Snapshot ID
算法版本
参数集
输入数
入选数
排除数
发布时间
```

## 8.3 Tab

```text
入选
排除
全部
```

默认显示入选。

## 8.4 入选表

字段：

```text
排名
代码
名称
交易所
成交额
成交量
收盘价
```

## 8.5 排除表

字段：

```text
代码
名称
交易所
主要排除原因
观测值
阈值
```

中文映射：

```text
no_data       → 无当日行情
suspended     → 当日停牌
invalid_price → 收盘价无效
low_volume    → 成交量不足
low_amount    → 成交额不足
```

保留原始 code 供调试。

## 8.6 搜索和过滤

支持：

```text
代码或名称搜索
交易所过滤
入选状态过滤
排除原因过滤
```

个人池规模较小，首期在前端过滤。

## 8.7 行展开

展开内容：

```text
metrics
rule_results
exclusion_reasons
instrument_id
```

---

# 9. 页面三：ETF 行情详情

## 9.1 数据来源

主数据：

```text
GET /api/v1/etf/instruments
```

日行情：

```text
GET /api/v1/etf/daily-bars
```

## 9.2 默认范围

默认最近 60 个自然日。

可选：

```text
30 日
60 日
120 日
自定义范围
```

## 9.3 展示内容

主数据：

```text
代码
名称
交易所
状态
上市日期
跟踪指数
分类
```

行情概览：

```text
最新收盘价
涨跌额
涨跌幅
成交量
成交额
revision
Provider
```

## 9.4 图表

第一版使用简单 SVG 收盘价折线。

不引入大型图表库。

## 9.5 日行情表

字段：

```text
日期
开盘
最高
最低
收盘
昨收
成交量
成交额
状态
revision
```

revision > 1 时显示“已修订”。

---

# 10. 页面四：Operations

## 10.1 目标

只读查看每日任务和数据状态。

## 10.2 内容

```text
最新 Pipeline Run
Data Freshness
Candidate Pool 发布状态
最近失败摘要
补跑命令提示
```

建议增加：

```text
GET /api/v1/pipeline-runs?limit=20&offset=0
```

字段：

```text
业务日期
状态
触发方式
开始
结束
耗时
错误代码
Run ID
```

## 10.3 不增加写操作

Web 不提供：

```text
重新运行按钮
启用 Schedule 按钮
修改 Provider 按钮
补跑按钮
```

失败时只展示命令：

```bash
make reprocess-date TRADE_DATE=YYYY-MM-DD CONFIRM_NETWORK=1
```

---

# 11. Web API Client

## 11.1 修复旧路径

当前：

```text
/v1/instruments
```

改为：

```text
/api/v1/etf/instruments
```

## 11.2 目录

```text
apps/web/src/api/
├── client.ts
├── types.ts
├── instruments.ts
├── candidatePool.ts
├── dataFreshness.ts
└── pipelineRuns.ts
```

## 11.3 基础 Client

```typescript
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(
      body?.detail ?? `Request failed: ${response.status}`,
      response.status,
      body?.detail,
    );
  }

  return response.json() as Promise<T>;
}
```

## 11.4 React Query Keys

```typescript
export const queryKeys = {
  freshness: ["data-freshness"] as const,
  latestCandidatePool: ["candidate-pool", "latest"] as const,
  latestCandidateDiff: ["candidate-pool", "latest", "diff"] as const,
  latestPipelineRun: ["pipeline-runs", "latest"] as const,
  instruments: (filters: object) => ["instruments", filters] as const,
  dailyBars: (instrumentId: string, start: string, end: string) =>
    ["daily-bars", instrumentId, start, end] as const,
};
```

## 11.5 刷新策略

```text
Data Freshness        60 秒
Latest Pipeline Run   60 秒
Candidate Pool        5 分钟
ETF Daily Bars        不自动刷新
```

不使用 WebSocket。

---

# 12. Web 目录建议

```text
apps/web/src/
├── api/
├── components/
│   ├── AppShell.tsx
│   ├── StatusBanner.tsx
│   ├── MetricCard.tsx
│   ├── EmptyState.tsx
│   ├── ErrorState.tsx
│   └── LoadingState.tsx
├── features/
│   ├── dashboard/
│   ├── candidatePool/
│   ├── instruments/
│   └── operations/
├── pages/
│   ├── DashboardPage.tsx
│   ├── CandidatePoolPage.tsx
│   ├── EtfDetailPage.tsx
│   └── OperationsPage.tsx
├── App.tsx
├── main.tsx
└── styles.css
```

---

# 13. UI 设计原则

## 13.1 个人投研优先

首页强调：

```text
是否更新
今天选了什么
哪些发生变化
哪些数据缺失
```

## 13.2 状态颜色

```text
fresh    绿色
partial  黄色
stale    橙色
missing  灰色
failed   红色
```

颜色同时配文字和图标。

## 13.3 数字格式

```text
1530000000 → 15.30 亿
12560000   → 1256 万
3.456700   → 3.4567
```

## 13.4 响应式

桌面：

```text
KPI 四列
候选池双栏
宽表格
```

移动端：

```text
KPI 两列
表格横向滚动
候选项卡片化
```

---

# 14. API 实施顺序

## API PR-1：候选池读模型修正

- Diff 只比较 included；
- Candidate Pool item 加 symbol/name/exchange；
- Latest 增加 run metadata；
- Diff 返回展示字段；
- 更新 API 测试。

## API PR-2：新鲜度和运行历史

- Freshness 使用 Snapshot 口径；
- 日行情覆盖只统计 Snapshot IDs；
- 增加 Pipeline Run list endpoint；
- 更新 API 测试和 OpenAPI。

---

# 15. Web 实施顺序

## Web PR-1：前端基础与 Dashboard

- 修复 API Base 和路径；
- 拆分 API Client；
- 增加 Router；
- 增加 AppShell；
- 增加 Data Freshness；
- 增加 KPI；
- 增加 Latest Run；
- 增加 Latest Candidate 摘要。

## Web PR-2：Candidate Pool 页面

- 入选、排除、全部 Tab；
- 搜索与过滤；
- 排除原因中文化；
- Candidate Pool Diff；
- 行展开详情；
- ETF 详情跳转。

## Web PR-3：ETF 详情与 Operations

- ETF 主数据；
- 日行情表；
- 简单收盘价 SVG；
- Pipeline Run 历史；
- Runbook 提示；
- 响应式布局；
- 空状态和错误状态。

---

# 16. 总体 PR 计划

共 5 个 PR：

```text
PR-01 修正 Candidate Pool Web 读模型
PR-02 修正 Data Freshness 并增加 Pipeline Run 历史
PR-03 Web 基础与 Dashboard
PR-04 Candidate Pool 页面
PR-05 ETF 详情、Operations、测试和文档
```

依赖：

```text
PR-01 ─┐
       ├→ PR-03 → PR-04 → PR-05
PR-02 ─┘
```

---

# 17. Issue 拆分

建议 12 个 Issue：

1. Candidate Pool Diff 仅比较 included items。
2. Candidate Pool API 增加 Instrument 展示字段。
3. Candidate Pool API 增加 Run 元数据。
4. Data Freshness 改为 Snapshot 口径。
5. 增加 Pipeline Run 列表 API。
6. 重构 Web API Client 并修复旧路径。
7. 建立 Web AppShell 和 Router。
8. 实现 Dashboard。
9. 实现 Candidate Pool 页面。
10. 实现 ETF 日行情详情页。
11. 实现 Operations 页面。
12. 增加 Web 测试和运行文档。

---

# 18. 测试计划

## 18.1 API 测试

覆盖：

- Diff 只比较入选项；
- 新增、保留、移出；
- Candidate Pool Instrument Join；
- Freshness Snapshot 口径；
- partial 状态；
- Pipeline Run 分页；
- SQLAlchemy 错误脱敏。

## 18.2 Web 单元测试

新增 Vitest，覆盖：

- API Client 正常和错误响应；
- StatusBanner 五种状态；
- Dashboard loading/error/empty/success；
- Candidate Pool 入选和排除过滤；
- 排除原因中文映射；
- ETF 详情空数据；
- Operations 失败状态。

## 18.3 CI

```bash
pnpm typecheck
pnpm test --run
pnpm build
```

当前 CI 没有可用的 Web test 命令，本阶段新增后恢复测试步骤。

## 18.4 轻量 E2E

Fixture PostgreSQL E2E 后：

1. 启动 API；
2. 启动 Web Preview；
3. 确认 Web 静态页面可访问；
4. 确认 API CORS；
5. 不引入 Playwright。

---

# 19. 真实数据与阶段门禁

Web 开发可以立即使用 fixture 数据。

正式声明 Web 可用于真实个人数据前，必须完成：

- 真实 CifangQuant Stage 1 验收；
- API 授权与限频确认；
- 同日重跑幂等；
- 至少开始 10 日影子运行；
- Data Freshness 与真实数据一致；
- Candidate Pool Diff 业务语义修正。

自动 Schedule 继续默认关闭：

```env
INVEST_PIPELINE_AUTO_SCHEDULE_ENABLED=false
```

真实验收通过前，Web 可以展示手动运行产生的数据。

---

# 20. 验收场景

## Fresh

```text
expected_trade_date = latest published date
daily_bar_count = snapshot row_count
latest pipeline run succeeded
```

Web 显示绿色“数据已更新”。

## Partial

```text
个人池 10 只
日行情 9 只
```

Web 显示黄色“缺失 1 只”，缺失 ETF 在 Candidate Pool 中显示 `no_data`。

## Stale

预期日期晚于最新发布日期时，显示橙色状态和最新发布日期。

## Failed

当日 Pipeline Run 失败且无 published Candidate Pool 时：

- 红色状态；
- 展示脱敏错误；
- 提供补跑命令。

## Candidate Diff

昨天：

```text
510300
510500
```

今天：

```text
510300
159915
```

Web：

```text
新增：159915
保留：510300
移出：510500
```

---

# 21. Definition of Done

## API

- [ ] Candidate Pool Diff 只比较入选项。
- [ ] Candidate Pool 返回 symbol/name/exchange。
- [ ] Candidate Pool 返回 Run 元数据。
- [ ] Data Freshness 使用 Snapshot 口径。
- [ ] Pipeline Run 历史可查询。
- [ ] API 错误不泄漏数据库信息。
- [ ] OpenAPI 与实现一致。

## Web

- [ ] 旧 API 路径已修复。
- [ ] Dashboard 可用。
- [ ] Candidate Pool 页面可用。
- [ ] ETF 详情页面可用。
- [ ] Operations 页面可用。
- [ ] loading/error/empty 状态完整。
- [ ] 桌面和移动端可用。
- [ ] Web 不包含写操作。
- [ ] Web 不包含聊天通知。

## 测试

- [ ] API 测试通过。
- [ ] Web typecheck 通过。
- [ ] Web 单元测试通过。
- [ ] Web build 通过。
- [ ] Fixture PostgreSQL E2E 通过。
- [ ] API CORS 验证通过。

## 文档

- [ ] Quickstart 增加 Web 启动步骤。
- [ ] OpenWiki 更新页面和 API。
- [ ] 记录真实数据验收门禁。
- [ ] Matrix 相关计划标记为取消或归档。

---

# 22. 防止过度工程化

本阶段禁止：

1. 引入 Redux。
2. 引入大型组件库。
3. 引入大型图表库。
4. 引入 WebSocket。
5. 引入 BFF。
6. 在 Web 中触发 Pipeline。
7. 在 Web 中编辑策略。
8. 在 Web 中编辑 Provider 凭据。
9. 建立多用户权限系统。
10. 建立通知系统。
11. 建立报表设计器。
12. 建立通用数据探索平台。
13. 建立实时行情推送。
14. 拆分新的前端应用。

---

# 23. 阶段停止条件

满足以下条件即结束本阶段：

```text
打开 Web
→ 能看数据是否最新
→ 能看最新候选池
→ 能看候选新增和移出
→ 能看每只 ETF 的排除原因
→ 能看 ETF 日行情
→ 能看最新任务状态
```

后续再评估：

```text
策略规则增强
大盘择时
T+5 / T+20 信号回看
AI 研究解释
```

---

# 24. 最终交付形态

日常使用：

```text
打开 Web Dashboard
        ↓
查看数据新鲜度
        ↓
查看新增 / 保留 / 移出
        ↓
进入 Candidate Pool 查看详细原因
        ↓
进入 ETF 详情查看历史行情
        ↓
出现失败时进入 Operations 查看 Run 状态
```

核心交付：

> 在不接入聊天频道通知、不改变 V2 分层架构的前提下，提供一个只读、清晰、可追踪的个人 ETF Web 数据工作台。
