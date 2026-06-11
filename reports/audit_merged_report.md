# 汇报模块综合审计报告 — 合并版

**合并范围**：architecture · datasource · logic · code_quality
**问题总数**：~52 项（去重后）
**审计日期**：2026-06-09
**合并日期**：2026-06-10
**最后核查**：2026-06-10（代码级验证）

---

## 一、问题总览

| 严重度 | 数量 | 核心问题 |
|--------|------|---------|
| 🔴 P0 | 4 | 节假日日历缺失、数据库占位、MCP Token 硬编码、IMAP 连接泄漏 |
| 🟡 P1 | 15 | 回溯不足、PreMarket 膨胀、耦合严重、QQ 无重试、异常处理过泛、im/al 降级失效 |
| 🟢 P2 | 13 | 缺抽象基类、sys.path 反模式、Formatters 膨胀、ETF 查询不一致、Token 硬编码 |
| 🔵 P3 | 5 | 中英文混注、导入顺序、类型注解不完整 |

---

## 二、🔴 P0 级（已修复 2 项，剩余 2 项未修复）

| # | 来源 | 问题 | 修复状态 | 验证方式 |
|---|------|------|---------|---------|
| P0-01 | logic | 节假日日历缺失 | ✅ **已修复**（`_load_holidays()` 惰性加载 2026-2027 节假日 + `HOLIDAYS_JSON` 环境变量覆盖） | 代码核查 `trading_day.py:13-85` |
| P0-02 | logic | db.py 数据库操作全部占位 | ✅ **已修复**（全部 6 个方法真实实现 + `init-db/06_market_reports.sql` 建表 DDL） | 代码核查 `db.py:21-136` |
| P0-03 | architecture | MCP Token 硬编码（`mcp_client.py:18`） | ❌ 未修复（`lb_00d0fa9c...` 仍硬编码） | 代码核查 |
| P0-04 | code_quality | IMAP 连接资源泄漏 | ❌ 未修复（属 advanced-daily-report 模块，非 reports 核心） | 非本模块 |

---

## 三、🟡 P1 级（15 项）

### 3.1 已修复（3 项 + 18 项 F 类格式问题）

| # | 来源 | 问题 | 修复状态 | 验证方式 |
|---|------|------|---------|---------|
| P1-01 | logic | 长假回溯上限 7 天不足 | ✅ **已修复**（→ 15 天，`trading_day.py`） | 代码核查 |
| P2-01 | logic | 交易阶段凌晨时段遗漏 | ✅ **已修复**（新增 `pre_market_before_open`） | 代码核查 |
| F-01~F-18 | code_quality | Formatters.py 18 项格式/对齐问题 | ✅ **已修复**（2026-06-07，Claude Code 完成） | `evaluation_reports/archive/progress.md` |

### 3.2 未修复（11 项）

| # | 来源 | 问题 | 文件 | 当前状态 |
|---|------|------|------|---------|
| P1-03 | logic | PreMarketReporter 膨胀（1105 行） | `modules/pre_market.py` | 1105 行，仍未拆分 |
| P1-04 | architecture | loader.pg 直接耦合 | `modules/*.py` + `market_data_cache.py` |仍 `from loader.pg import get_conn` |
| P1-05 | logic | 节后首日回退策略不健壮 | `modules/pre_market.py:303-314` |仍未增加深度检查 |
| P1-06 | logic | memo 解析正则脆弱，无单元测试 | `modules/pre_market.py:44-159` | 仍为正则硬编码，无测试 |
| P1-07 | logic | pre_market Step 2 代码重复 | `modules/pre_market.py:319-331` | 仍未删除重复声明 |
| P1-08 | logic | 数据流缺少完整性校验 | `report_engine.py:68-86` | 仍未在 format_report() 后检查有效板块 |
| P1-09 | logic | QQ 推送无重试机制 | `report_engine.py:150-159` | 仍无重试 + 文件兜底 |
| P1-10 | logic | `get_or_mcp()` 降级逻辑未实现 | `market_data_cache.py:90-105` | 注释说降级走 MCP，实际返回 None，调用方从未触发 MCP |
| P1-11 | architecture | 交易日判断不完整（仅检查周末） | `trading_day.py` | ✅ 已随 P0-01 修复 |
| P1-12 | datasource | pre_market cache miss 降级不完整 | `modules/pre_market.py:329` | 仍返回 `{}`，未定义 `FALLBACK_DATA` |
| P1-13 | datasource | BatchMCPClient 无成功/失败统计 | `mcp_client.py` | 仍无计数统计 |
| P1-14 | datasource | `has_all()` N+1 查询 | `market_data_cache.py:159-161` | 仍为 `all(self.exists(dt) for dt in data_types)`，逐条 SELECT |

---

## 四、🟢 P2 级（13 项）

| # | 来源 | 问题 | 文件 | 当前状态 |
|---|------|------|------|---------|
| P2-01 | architecture | 缺 BaseReporter/BaseFormatter 抽象基类 | — | 仍未定义 |
| P2-02 | architecture | sys.path.insert 反模式 | `report_engine.py:21` | 仍为 `sys.path.insert` |
| P2-03 | architecture | 全局单例过多 | 多文件 | 仍为全局单例 |
| P2-04 | architecture | Formatters.py 膨胀（950 行） | `formatters.py` | 仍 950+ 行 |
| P2-05 | logic | 午盘报策略信号硬编码为空 | `modules/midday.py:226-232` | 仍为 stub |
| P2-06 | logic | ETF 套利查询表不一致 | `modules/*.py` | 仍未统一表来源 |
| P2-07 | logic | MCP 工具名映射缺失 | `intraday_alert.py:40-43` | 仍未显式定义映射 |
| P2-08 | logic | formatter 消息拆分截断 Markdown | `formatters.py:split_messages()` | 仍按行拆分，未在段落边界断开 |
| P2-09 | logic | 日期类型不一致（str ↔ date） | `report_engine.py` vs `trading_day.py` | 仍未统一 |
| P2-10 | datasource | DB 连接管理（每次查 DB 都创建/关闭连接） | `market_data_cache.py` | 仍逐次 `with get_conn()` 创建/关闭 |
| P2-11 | code_quality | 邮箱凭据明文存储（.env） | `advanced-daily-report` 模块 | 非本模块 |
| P2-12 | code_quality | 子进程注入风险 | `advanced-daily-report` 模块 | 非本模块 |
| P2-13 | architecture | MCP_TOOLS/DATA_TYPE_MAP 重复定义 | `mcp_client.py` / `market_data_cache.py` | 仍重复定义 |

---

## 五、🔵 P3 级（5 项）

| # | 来源 | 问题 | 文件 | 当前状态 |
|---|------|------|------|---------|
| P3-01 | logic | MCP 降级结果结构不兼容 | `mcp_client.py:164-172` | 仍返回 `{"error": True, "data": None}` |
| P3-02 | code_quality | 导入顺序不规范 | `run_report.py` | 非本模块 |
| P3-03 | code_quality | 冗余的 re 导入 | `run_report.py` | 非本模块 |
| P3-04 | code_quality | 中文注释与英文代码混用 | 全部文件 | 仍未统一 |
| P3-05 | architecture | 无健康检查端点 | — | 仍未添加 |

---

## 六、修复进度总览

| 优先级 | 总数 | 已修复 | 未修复 | 完成率 |
|--------|------|--------|--------|--------|
| 🔴 P0 | 4 | 2 | 2 | 50% |
| 🟡 P1 | 15 | 3 (+18F) | 12 | 20% |
| 🟢 P2 | 13 | 0 | 13 | 0% |
| 🔵 P3 | 5 | 0 | 5 | 0% |
| **合计** | **37** | **5** (+18F) | **32** | **14%** |

---

## 七、核查结论（2026-06-10）

**已验证修复（代码级核查）：**
- ✅ P0-01 节假日日历（`_load_holidays()`）
- ✅ P0-02 db.py 真实实现（全部 6 方法 + DDL）
- ✅ P1-01 回溯 15 天
- ✅ P2-01 凌晨时段 `pre_market_before_open`
- ✅ Formatters F-01~F-18（18 项格式问题，2026-06-07 完成）

**未修复（代码级核查）：**
- ❌ P0-03 MCP Token 硬编码
- ❌ P1-12 pre_market 仍返回 `{}` 无 FALLBACK_DATA
- ❌ P1-14 has_all 仍逐条 `SELECT`（N+1）
- ❌ P1-10 get_or_mcp 仍返回 None 不触发 MCP
- ❌ P2-08 split_messages 仍按行截断
- ❌ P2-10 DB 逐次创建/关闭连接

---

## 八、剩余 P0/P1 修复建议

**建议优先推进顺序**：

1. **P0-03**（MCP Token 硬编码）→ 迁移到环境变量
2. **P1-12**（pre_market 降级不完整）→ 定义 `FALLBACK_DATA`
3. **P1-09**（QQ 无重试）→ 指数退避 + 文件兜底
4. **P1-03**（PreMarket 膨胀）→ 拆分 Parser/Extractor/Reporter
5. **P1-04**（loader.pg 耦合）→ DataSource 接口抽象
6. **P1-14**（has_all N+1）→ 批量查询

---

## 九、来源报告清单

| 报告 | 审计人 | 日期 |
|------|--------|------|
| `audit_architecture_report.md` | system-architect | 2026-06-09 |
| `audit_datasource_report.md` | data-architect | 2026-06-09 |
| `audit_logic_report.md` | business-analyst | 2026-06-09 |
| `audit_code_quality_report.md` | code-reviewer | 2026-06-09 |
| `audit-20260607-premarket.md` | — | 2026-06-07 |