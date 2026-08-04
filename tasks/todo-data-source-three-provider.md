# TODO: 三个行情源接入（planned-only）

**状态**：de-scoped。`eastmoney` / `sina` / `tonghuashun` 在当前 slice 中
不是 selectable runtime Provider；详见
`tasks/plan-data-source-three-provider.md`。

## 当前 slice 已完成

- [x] 删除 unimplemented standalone skeleton 包：
      `apps/pipeline/src/invest_pipeline/adapters/eastmoney`、
      `adapters/sina`、`adapters/tonghuashun`。
- [x] 删除对应的配置单元测试：
      `test_eastmoney_config.py` / `test_sina_config.py` /
      `test_tonghuashun_config.py`。
- [x] 从 `invest_pipeline.provider_catalog` 移除 `EASTMONEY` /
      `SINA` / `TONGHUASHUN` 声明与导出；新增
      `EASTMONEY_SINA_TONGHUASHUN_NOTE` 记录 de-scope 说明。
- [x] 从 `invest_pipeline.provider_quality.ETF_DAILY_BAR_REGISTRY`
      移除三源注册项。
- [x] 更新 `test_provider_catalog` / `test_provider_routing_selection`
      / `test_provider_quality` 以断言只保留 runtime Provider
      （`fixture_dev` / `cifangquant` / `akshare` / `rsscast` /
      `quicktiny_mcp`）。
- [x] 更新 plan / todo 文档语言。

## Planned-only（未来 ADR 重启前不会实施）

- [ ] Provider catalog / factory / routing：eastmoney、sina、
      tonghuashun（planned-only；catalog / factory 当前不注册三源）
- [ ] 东方财富 adapter + tests（planned-only）
- [ ] 新浪 adapter + tests（planned-only）
- [ ] 同花顺 adapter + tests（planned-only）
- [ ] Coverage 接线与离线报告（planned-only）
- [ ] ARC 独立 diff review、测试和工作树验收

## Sina / Eastmoney 作为 AkShare 内部上游

三源的公开历史行情接口在 V2 中继续作为 AkShare 聚合库的内部上游：

- `ak.fund_etf_hist_sina`（新浪）由 `AkshareClient.fetch_fund_etf_hist_sina`
  作为首选路径调用，对应 `BarSource.provider_key="sina"`。
- `ak.fund_etf_hist_em`（东方财富）由
  `AkshareClient.fetch_fund_etf_hist_em` 作为 fallback 调用，对应
  `BarSource.provider_key="eastmoney"`。
- 同花顺（同花顺 iFinD / 10jqka）目前没有对应的开源历史行情
  endpoint 在 V2 中作为 AkShare 内部上游使用。

Akshare 适配器的 Sina-first / Eastmoney-fallback 测试
（`test_akshare_adapter.AkshareSinaPriorityTest`）保持不变。