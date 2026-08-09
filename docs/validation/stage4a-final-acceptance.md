# Stage 4A Final Acceptance Report

> 版本：v1.1
> 基线：`d0b3a65`（本报告初版实现与文档基线）
> 验收范围：Stage 4A Final Closure Sprint
> 状态：Closure Sprint completed; production-style seeded API/Web acceptance remains explicitly pending

## 1. 结论摘要

Stage 4A 的 Evidence Foundation、Research Run、Fake Runner、Research API
只读契约和 Web 消费契约已经完成代码级验收。当前证据足以支持继续维护
Stage 4A，不需要重新规划。

本轮 Web Playwright 使用 deterministic route fixtures，验证浏览器对冻结
API envelope 的消费，不启动 FastAPI 或 PostgreSQL。真实 API 由 FastAPI
TestClient / storage tests 验证。因此，本报告不把 contract-seam E2E
表述为完整部署环境的 API+Web 联调。

## 2. 验收结果

| 项目 | 结果 | 证据 |
|---|---|---|
| Domain 全量测试收集 | PASS | `952 passed` |
| Evidence Pack hash / 幂等 / 历史保留 | PASS | domain `42 passed`；storage mock `18 passed`；evidence integration `12 passed` |
| Factor Snapshot | PASS | `etf_market_state_daily` v1.0.0，8 个因子 |
| AI / Evidence 分离 | PASS | domain、API serialization/service tests |
| Fake JiuwenSwarm Runner 应用链路 | PASS | pipeline targeted tests `80 passed` |
| Research API endpoint contract | PASS | `apps/api/tests/test_research_endpoints.py`：`6 passed` |
| Web contract-seam E2E | PASS | `apps/web`: `pnpm test:e2e`，`2 passed` |
| 真实 API + Web Case 联调 | PASS | 隔离 PostgreSQL + API `8100` + Web `3101`，Case workspace 浏览器验证通过 |
| Web typecheck | PASS | `apps/web`: `pnpm typecheck` |
| OpenWiki API inventory | PASS | 已与 8 个实际只读路由对齐 |

## 3. Evidence Foundation 验证

已验证的领域链路为：

```text
Research Case → Evidence Pack → Evidence Item → Factor Observation → Hash
```

已验证：相同业务输入产生稳定 hash；相同 pack 可幂等写入；业务输入变化
产生新 hash；不同 revision 不覆盖历史 pack；运行时元数据不参与 pack hash。

本轮因子集合实际为 8 个，而不是早期草案中的 9 个：

- `return_20d`
- `return_60d`
- `distance_ma20`
- `distance_ma60`
- `realized_volatility_20d`
- `max_drawdown_60d`
- `avg_turnover_amount_20d`
- `data_completeness_60d`

因子只表达确定性事实，不生成 buy/sell，也不写入 AI 结论。

## 4. Fake Runner 与结果分离

应用层 Fake Runner 测试覆盖正常完成、重放、重复 session、超时不确定、
adapter failure、持久化冲突和 reconciliation。正常链路验证 ready → running
→ succeeded，且 result 与 request/session identity 绑定。

Research Result 独立持久化；Evidence、Factor、Data Quality 与 stance、
confidence、thesis、risk、disagreement 分离，AI 结果不能修改 Evidence。

## 5. Research API Contract

当前冻结的实际只读路由为：

- `GET /api/v1/research-cases`
- `GET /api/v1/research-cases/{case_id}`
- `GET /api/v1/research-cases/{case_id}/evidence`
- `GET /api/v1/research-cases/{case_id}/workspace`
- `GET /api/v1/research-dashboard`
- `GET /api/v1/research-runs`
- `GET /api/v1/research-runs/{run_id}`
- `GET /api/v1/research-runs/{run_id}/result`

路由实现、`apps/api/openapi.json`、端点测试、OpenWiki API overview 已对齐。
测试同时覆盖分页参数、404/422、只读方法限制和安全错误边界。

## 6. Web 验收边界

`apps/web/e2e/research-cockpit.e2e.ts` 使用精确路径匹配的 Playwright fixtures
覆盖 Research history 与 case workspace。未安装 catch-all；未覆盖的路径、
写请求或新请求仍会暴露为真实网络错误。

因此已确认：

- Web 可消费当前冻结 response envelope；
- 页面可渲染且无横向溢出；
- 页面无 console error；
- 不依赖本地数据库状态。

本轮已补做隔离环境联调，记录如下：

- 数据库：`invest_stage4a`，迁移至 `20260807_0014`；
- Case ID：`11111111-1111-4111-8111-111111111111`；
- Evidence Pack ID：`fc22a8ae-14e8-47f9-af6e-bd9442a79952`；
- Pack Hash：`737e32847a78c5504883626915a94efd456b21a48c8cc40ba5a426fd8606ee30`；
- Factor 数量：8；
- Run ID：`cccccccc-cccc-4ccc-8ccc-cccccccccccc`；
- Result ID：`dddddddd-dddd-4ddd-8ddd-dddddddddddd`；
- 真实 API：Cases、Case detail、Evidence、Workspace、Dashboard、Runs、Run detail、Result 均返回 200；
- 真实 Web：History 与 Case workspace 返回对应 API 200，Case report 可见，console errors 为 0，390px viewport 无横向溢出。
- Web 截图：[stage4a-case-workspace.png](assets/stage4a-case-workspace.png)。

Dashboard 页面本身还会请求其他未 seeded 的非 Research 资源，产生 404；因此
Dashboard 本轮只记 API 200，不宣称整个 Dashboard 页面无错误通过。

## 7. 剩余关闭条件

Stage 4A 可以进入最终关闭评审。正式归档前仍需完成以下治理性收口：

1. 保存真实 Web 截图和完整测试输出；
2. 确认无 Provider Key 泄漏、workspace 路径越界和 agent 直连数据库。

在上述环境级证据完成前，不启动 Stage 4B 的市场智能数据层实现；可以继续
进行必要的验收准备和缺口补齐。
