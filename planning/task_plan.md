# v3.0 PreMarketFormatter 重构计划

## 项目信息
- **项目**：A股智能投研体系 - PreMarketFormatter v3.0 重构
- **文件**：`src/reports/formatters.py`
- **目标**：将 7-section 旧模板升级为 v3.0 11-section 统一模板

## v3.0 模板结构（11 sections）

| # | Section | 类型 | 数据来源 |
|---|---------|------|---------|
| 1 | 【WOA工作摘要】任务表格+置信度+风险+建议 | 新增 | `woa_summary` |
| 2 | ■ 今日市场概况（沪深300+情绪+来源标注） | 增强 | `market_overview` |
| 3 | ■ 今日主线预判 | 保留 | 现有 |
| 4 | ■ 因子信号（5类因子表格） | 重构 | `factors` |
| 5 | ■ ETF信号（Top5表格） | 保留 | `woa_etf_signals` |
| 6 | ■ 盘前异动（集合竞价） | 新增 | `auction_scan/wts` |
| 7 | ■ 宏观/事件面 | 新增 | `cls_news` (Medium) |
| 8 | ■ 风险提示（等级+VIX+地缘） | 增强 | `risks` |
| 9 | ■ 情景假设 | 保留 | `scenarios` |
| 10 | ■ 今日关注 | 保留 | `today_attention` |
| 11 | ■ 今日操作参考 | 保留 | `operation_ref` |

## 数据可用性矩阵

| 数据键 | 来源 | 格式 | 可用 |
|--------|------|------|------|
| `woa_summary` | fetch_memo | dict | ✅ |
| `market_overview.hs300` | fetch_memo | dict | ✅ |
| `factors` | fetch_memo | dict | ✅ |
| `woa_etf_signals` | fetch_memo | list | ✅ |
| `auction_scan` | market_data_cache | list | ✅ |
| `auction_wts` | market_data_cache | list | ✅ |
| `macro_events` | cls_news MCP | list | ❌ |
| `risks` | fetch_memo | dict | ✅ |
| `scenarios` | fetch_memo | list | ✅ |
| `today_attention` | fetch_memo | list | ✅ |

## 执行阶段

- [ ] 阶段1：WOA工作摘要（新增#1）
- [ ] 阶段2：今日市场概况增强（#2）
- [ ] 阶段3：盘前异动（新增#6）
- [x] 阶段4：因子信号表格（重构#4）
- [x] 阶段5：宏观/事件面（新增#7，Medium优先级）
- [x] 阶段6：整体美化+验收

## 验收标准

1. 11个section全部渲染（含空占位符）
2. 每个section有 `_source_tag()` 来源标注
3. 无投资建议语言（禁止词：买/卖/持有/做多/做空）
4. 报告可正常推送QQ

## 决策记录

| 日期 | 决策 | 原因 |
|------|------|------|
| 2026-06-10 | 宏观/事件面为Medium优先级，MCP未接入不影响基础验收 | cls_news MCP 待后续接入 |

## 进度记录

| 日期 | 阶段 | 状态 | 备注 |
|------|------|------|------|
| 2026-06-10 | 阶段1：WOA工作摘要 | ✅ 完成 | CCR 实施，语法+逻辑验证通过 |
| 2026-06-10 | 阶段2：今日市场概况增强 | ✅ 完成 | CCR 审计，3问题均已修复 |
| 2026-06-10 | 阶段3：盘前异动（新增#6） | ✅ 完成 | CCR 审计，5问题均已修复，含格式化bug修复 |
| 2026-06-10 | 阶段4：因子信号表格（重构#4） | ✅ 完成 | CCR 审计，4问题均已修复，memo主数据源+DB fallback |
| 2026-06-10 | 阶段5：宏观/事件面（新增#7） | ✅ 完成 | MCP未接入返回stub，占位结构已就绪 |
| 2026-06-10 | 阶段6：整体美化+验收 | ✅ 完成 | docstring更新+验收通过 |