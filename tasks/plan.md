# DC-2 ETF Profile 第一切片

## 范围

落地 ETF Profile 的领域契约与 PostgreSQL 持久化基础，不伪造 Provider 数据，
暂不扩展指数、成分股、持仓、API 或 Web。

## 有序任务

- [x] 定义 `EtfProfile` 领域模型及字段校验。
- [x] 增加 `core.etf_profiles` 迁移、SQLAlchemy 模型和 Repository upsert/read。
- [x] 增加领域、存储和迁移链 focused tests。
- [x] 接入 AkShare Profile 读取、字段映射和三层证据写入。
- [x] 独立验收真实 Profile 采集切片。

## 验收

- [x] 必填标识、费率、规模和日期字段按契约校验。
- [x] 同一 `instrument_id` 幂等 upsert，不产生重复 Profile。
- [x] migration chain、focused tests 和 architecture check 通过；Ruff 未新增违规（保留既有 baseline I001/E501）。

## 边界说明（替代旧"已验证阻塞"）

- 2026-08-05 受控只读冒烟已确认两条静态 Profile 通道作为本切片 Provider：
  - `fund_name_em` 返回 27,414 行。
  - `fund_etf_spot_em` 返回 1,565 行。
- 边界：`fund_etf_fund_info_em(fund=...)` 仍为历史 NAV 通道，不得作为 `EtfProfile` 字段来源；
  NAV 维持 `fund_etf_fund_daily_em` 专用路径，不回填 `core.etf_profiles`。
- 未经验证的字段保持 `None`：manager、benchmark、inception、fees、AUM；其中 AUM 不接受用"总市值"（total market value）等价替代。
- 本切片范围之外：API/Web/Dagster 接线、指数、成分股、持仓暂不扩展。

---

# Implementation Plan: Stage 3 Completion

## Scope

Close the locally executable remainder of the stability and personal-use stage, while recording external blockers without fabricating acceptance results.

## Phase 1: Baseline and test gaps

- [x] Run the full repository test/architecture baseline with the current working tree.
- [x] Add the smallest useful Web unit-test setup and tests for the implemented read-only pages/API states.
- [x] Verify Web typecheck and production build after the test setup.

## Phase 2: Database and operational verification

- [x] Run migration-chain and PostgreSQL Fixture E2E checks when Docker/PostgreSQL is available.
- [x] Verify schedule/preflight behavior and document exact remaining runtime prerequisites.
- [ ] Refresh current-stage documentation and remove stale acceptance claims.

## Phase 3: External acceptance blockers

- [ ] Perform authorized CifangQuant acceptance only after credentials, contract evidence, and rate-limit/cutoff decisions are supplied.
- [ ] Run and record the 10-trading-day shadow window.

## Acceptance

- Local tests and builds pass.
- No external acceptance is marked complete without evidence.
- Documentation distinguishes implemented code, verified behavior, and blocked external work.
