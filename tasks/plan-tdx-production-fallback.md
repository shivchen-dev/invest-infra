# Stage 4B：TDX 生产日线降频方案

## 目标

降低生产环境对 Tushare 高频接口的依赖：通达信承担本地股票日线，Tushare 保留为低频股票主数据刷新与质量校验来源。

## 实施顺序

### Phase 1：TDX 日线独立可用

- [x] 支持 `vipdoc/bj/lday` 北交所文件与 `BJSE` 映射。
- [x] 增加 TDX 日线目录枚举，避免按日期读取时依赖 Tushare 提供 symbol universe。
- [x] 将 TDX 日线 fallback 接入真实 Dagster stock asset，并保留 evidence lineage。

### Phase 2：股票主数据低频缓存

#### Phase 2.1：最近成功快照复用（已完成）

- [x] 保留 `core.instruments` 为权威主数据缓存，由 `stock_instruments` 资产直接 upsert。
- [x] `stock_instruments` 资产在当前 attempt `status == "failed"`（含 Tushare 限流）或缺失时，复用最近一次 `succeeded` attempt 的 `response_payload_json`，通过 `reused_snapshot` / `source_as_of` / `source_request_id` metadata 透出，且不进入 skip 分支。

#### Phase 2.2：限流策略与刷新节奏（保守收口，已完成）

- [x] 失败/限流触发的快照复用：当前 request `failed`（含 Tushare 限流）时复用最近一次成功 snapshot；新增单测 `test_rate_limited_current_request_reuses_latest_earlier_success`（`StockInstrumentsSnapshotReuseTest`）锁住该不变量。
- [x] 本期不引入新的刷新节奏。
- [x] 本期不改 Dagster 调度频率。
- [x] 主动请求降频（proactive request reduction）需另立决策，不在本期收口范围内。

#### 持续约束

- [x] TDX 仅补充代码/市场发现，不伪造名称、上市状态等主数据字段；真实验收使用 market-qualified pairs，名称/上市状态仍由 `core.instruments` 负责。

### Phase 3：生产验收

- [x] 用真实 TDX 数据跑单日股票日线链路：2026-08-12 真实 `vipdoc` 数据发现 12,431 个 pairs，读取并生成 9,405 条日线；SSE/SZSE/BJSE 探针均成功。
- [x] 验证 Tushare 限流时日线仍可入库、主数据缓存不丢失：限流/失败快照复用合同测试通过；TDX fallback 真实写入 PostgreSQL evidence 三层，request/attempt/batch 均为 `succeeded`。
- [x] 验证沪深北交易所映射、证据链和失败可审计性：`raw.provider_requests.request_key` 长度 113（VARCHAR(128) 内），完整 pairs 保存在 `request_params`，batch `record_count=9405`，payload hash 已持久化；缺失/非法文件失败合同测试通过。

#### Phase 3 验收记录（2026-08-13）

- PostgreSQL 容器：`invest-infra-postgres-1`，迁移至 head。
- TDX 数据根目录：`/home/claw/windows-ltsc/shared/tdx-data`。
- 单日：`2026-08-12`；request key：`daily-bars-by-pairs-2026-08-12-2026-08-12-sha256-...`。
- 回归：TDX provider `58 passed`；fallback + Asset wiring `33 passed`；Ruff、`git diff --check` 通过。

## 约束

- 不删除 Tushare；它仍负责低频主数据刷新和交叉校验。
- 不把 TDX `.day` 文件推断出的信息扩展成未经验证的财务/估值数据。
- 每个阶段独立测试、独立提交，未完成能力保持显式关闭。
