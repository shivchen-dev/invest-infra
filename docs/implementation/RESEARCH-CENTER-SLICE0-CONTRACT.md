# Research Center Slice 0 合同

> 合同版本：1.0.0
> 状态：FROZEN_FOR_SLICE_1
> 冻结日期：2026-08-15
> 上位计划：`docs/plan/invest-infra-central-research-visualization-mvp-plan-v1.0.md`
> 执行清单：`tasks/central-research-visualization-mvp-todo.md`

## 1. 冻结范围

本合同冻结中心投研首页的最小问题集、`ResearchCenterResponse v1` 外部 Interface、市场字段来源以及状态和时间语义。Slice 1 只实现市场状态，不改变现有资源端点，不引入写操作、模拟数据或新数据库对象。

## 2. 页面与问题

`/dashboard` 是唯一中心首页。其他页面保留详情职责，不复制为第二个首页。

| 首页问题 | v1 区段 | Slice 1 来源 | 详情入口 |
|---|---|---|---|
| 数据截至何时，是否缺失？ | `market.data_freshness` | `DataFreshnessQueryService` | `/operations` |
| 市场有哪些可验证事实？ | `market.breadth` | `MarketBreadthQueryService` | `/market` |
| 候选与外部观察处于什么状态？ | `capabilities.opportunities` | Slice 2 前为 `deferred` | `/candidate-pool`、`/opportunity-radar` |
| 研究事项处于什么状态？ | `capabilities.research` | Slice 2 前为 `deferred` | `/research/history` |
| 策略或纪律是否发生变化？ | `capabilities.strategy`、`capabilities.discipline` | 合同未冻结时为 `unavailable` | `/strategy`、`/discipline` |
| 交付链是否正常？ | `capabilities.delivery` | Slice 3 前为 `deferred` | `/automation` |

首页只显示摘要和单一详情链接。现有详情页继续持有完整列表、历史和诊断信息。

## 3. Module 与 Seam

`Research Center Read Model` 是一个深 Module。

- 外部 Seam：`GET /api/v1/research-center`。
- 外部 Interface：单个版本化 `ResearchCenterResponse`。
- Implementation：组合现有 `MarketBreadthQueryService` 与 `DataFreshnessQueryService`；后续区段按独立 Slice 加入。
- Adapter：现有 Reader/Repository 保持不变；没有第二种实现时不新增假想 port。
- Web 只依赖该响应和现有详情路由，不读取数据库、共享目录或宿主机路径。

## 4. `ResearchCenterResponse v1`

以下 JSON 固定字段名、嵌套关系和状态语义；Python/TypeScript 的具体类型声明在 Slice 1 实现。

```json
{
  "schema_version": "1.0.0",
  "generated_at": "2026-08-15T13:00:00Z",
  "state": "available",
  "market": {
    "state": "available",
    "as_of_date": "2026-08-15",
    "quality_status": "complete",
    "freshness_status": "fresh",
    "breadth": {
      "snapshot_id": "...",
      "algorithm_version": "2.0.0",
      "scope_type": "ashare_universe",
      "scope_key": "ashare_active_universe_v1",
      "observations": [
        {
          "key": "advancing_ratio",
          "value": "0.60000000",
          "unit": "ratio",
          "observed_date": "2026-08-15",
          "source_kind": "analytics",
          "source_ref": "market_breadth:2.0.0",
          "quality_status": "complete"
        }
      ]
    },
    "data_freshness": {
      "state": "available",
      "checked_at": "2026-08-15T13:00:00Z",
      "latest_published_trade_date": "2026-08-15",
      "universe_count": 100,
      "daily_bar_count": 100,
      "missing_count": 0,
      "status": "fresh"
    }
  },
  "capabilities": {
    "opportunities": {"state": "deferred", "reason": "slice_2_not_implemented"},
    "research": {"state": "deferred", "reason": "slice_2_not_implemented"},
    "delivery": {"state": "deferred", "reason": "slice_3_not_implemented"},
    "strategy": {"state": "unavailable", "reason": "strategy_iteration_contract_not_frozen"},
    "discipline": {"state": "unavailable", "reason": "position_discipline_contract_not_frozen"}
  }
}
```

### 4.1 顶层状态

`state` 只允许：

- `available`：市场广度与数据新鲜度均成功读取；
- `partial`：两者仅有一个成功（包括另一个来源缺失或受控失败），或任一成功来源自身为 `partial/stale/missing/failed`；
- `unavailable`：两个市场来源都没有可展示结果；
- `failed`：两个市场来源均发生受控查询错误；响应不得包含内部异常、连接信息或路径。

顶层状态不表示市场好坏、研究结论或交易建议。

### 4.2 市场区段

`market.state` 只允许 `available | partial | unavailable | failed`。缺失 Market Breadth 快照必须表示为 `unavailable`，不得生成零值。某一子来源失败时，另一子来源仍可返回，区段状态为 `partial`。

Slice 1 的 Web 卡片替换首页现有的 Data Freshness/Metrics 重复展示，但不删除其资源端点或其他详情页消费者。HTTP 请求失败与成功响应中的 `state="failed"` 都呈现失败语义，但前者使用通用 Error State，后者仍展示可用的受控响应信息。

Market Breadth 只透传已注册 observation；Slice 1 不重新计算指标，不改变单位，不创建评分。合法 key 以快照内容为准，当前实现包括：

- `advancing_ratio`、`declining_ratio`、`above_ma20_ratio`；
- v2 快照可增加 `above_ma60_ratio`、`new_high_ratio`、`new_low_ratio`。

新响应将既有 `observation_key` 映射为合同字段 `key`，`source_ref` 原值透传。`checked_at` 与本次聚合响应的 `generated_at` 使用同一 UTC 生成时刻。市场广度和数据新鲜度各保留一个详情链接；能力区段在 Slice 1 响应中保留，但不在市场卡片中渲染。

### 4.3 能力区段

`deferred` 表示已有承接 Slice，但尚未进入本响应；`unavailable` 表示业务合同或权威来源尚未冻结。两者都不得附带模拟 payload。能力区段不参与 Slice 1 顶层 `state` 计算。

## 5. 来源映射

| 响应字段 | 权威来源 | 转换规则 |
|---|---|---|
| `generated_at` | API UTC wall clock | 仅表示响应生成时刻 |
| `market.as_of_date` | Market Breadth `as_of_date`，缺失时回退 `latest_published_trade_date` | 不使用浏览器时间 |
| `market.quality_status` | Market Breadth `quality_status` | 原值透传 |
| `market.freshness_status` | Market Breadth `freshness_status` | 原值透传，不与数据管道 status 混用 |
| `market.breadth.*` | `MarketBreadthQueryService.get_latest()` | 保留快照身份、算法、scope、单位和来源 |
| `market.data_freshness.*` | `DataFreshnessQueryService.get_freshness(None)` | 保留五态 vocabulary 与计数 |

Slice 1 不直接调用已有 HTTP 端点做服务内 fan-out；聚合 Module 复用 Application Readers/Services。

## 6. 时间语义

- `generated_at`：响应在 API 中生成的 UTC 时间；不是数据观察时间。
- `as_of_date`：市场快照所代表的交易日。
- `observed_date`：单项 observation 的真实观察日期。
- `checked_at`：数据新鲜度结果生成时间，对应现有 `DataFreshnessResponse.as_of`。
- `latest_published_trade_date`：最近已发布数据所属交易日。

禁止用 `generated_at` 掩盖陈旧的 `as_of_date/observed_date`。

## 7. 质量与新鲜度

- Market Breadth `quality_status` 与 `freshness_status` 保留领域原值；
- Data Freshness `status` 固定为 `fresh | partial | stale | missing | failed`；
- 聚合 `state` 只描述响应可用程度；
- Web 必须同时展示来源、日期和状态，不得仅用颜色表达；
- `null`、`unavailable`、`missing` 与数值 `0` 含义不同，不得互换。

## 8. 错误与安全

- 单来源 404 转换为对应子区段 `unavailable`，不使整个响应 404；
- 单来源受控查询错误转换为子区段 `failed`，另一来源仍可展示；
- 未知程序错误由统一 HTTP 错误边界处理，不在成功响应中返回异常文本；
- 响应禁止出现数据库连接串、凭据、宿主机路径、共享目录路径或原始异常 repr；
- 端点保持 GET-only，浏览器不得通过本 Module 发起业务写入。

## 9. Slice 1 验收合同

- Application 测试覆盖双来源成功、Breadth 缺失、Freshness 部分/陈旧、单来源错误和双来源不可用；
- API 测试覆盖响应版本、GET-only、404 降级、500 脱敏和无路径泄漏；
- Web 覆盖 loading、available、partial、stale、unavailable、failed；
- OpenAPI client 无 drift，TypeScript typecheck、Web build 与全量回归通过；
- 真实环境展示真实快照，或准确展示 `unavailable` 原因。

## 10. 冻结决策

- `/dashboard` 保持唯一中心首页；
- Slice 1 只实现市场区段；
- 不替换现有资源端点，不新增数据库对象；
- 不包含回测、收益、买卖、策略批准或仓位动作；
- Slice 2–5 不得借本合同提前扩张。
