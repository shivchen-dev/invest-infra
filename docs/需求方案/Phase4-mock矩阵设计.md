# Phase 4 — formatters 空数据 mock 矩阵设计

**主题：** Phase 4 formatters 空数据兼容性测试设计（前置 Phase 5 删 MCP 调用）
**版本：** v1
**日期：** 2026-06-11
**审计员/执行者:** Arc（方案设计）→ Claude Code（pytest 落地）→ CIA（验收）

---

## 一、目标 & 范围

### 1.1 目标

在 Phase 5 删 MCP 运行时调用前，证明 4 个 formatters 在以下场景下 **不崩溃 + 输出明确的"数据缺失"标识**：

| 场景 | 验证目标 |
|------|---------|
| 完全空 data `{}` | 不抛 KeyError/TypeError/AttributeError |
| 每个 section 字段缺失/空字典/空列表/None | 同上 |
| 类型错乱（dict 当 list） | 同上 |
| 真实数据 baseline | 不破坏现有渲染（回归）|

### 1.2 范围

| Formatter | 入口 | 覆盖 sections |
|-----------|------|--------------|
| `PreMarketFormatter` | `pre_market` | 13 个（woa/judgment/overview/main_lines/factors/etf/auction×3/macro/risks/hsgt/scenarios/attention/operation） |
| `IntradayFormatter` | `midday` & `intraday` | 7 个（market_state/main_lines/limit_events/strategy_realtime/etf_intraday/risk_signals/alerts） |
| `PostMarketFormatter` | `post_market` | 10 个（summary/limit_stats/main_review/ladder/board_break/strategy_review/etf_arbitrage/risk_review/operation_ref/day_summary） |
| `IntradayAlertFormatter` | `intraday_alert` | 3 个（limit_up/limit_down/anomaly） |

合计 **33 个 section × 5 种空数据变体 = 165 个测试用例**。

---

## 二、Mock 矩阵（核心）

### 2.1 矩阵维度

| 维度 | 取值 | 用途 |
|------|------|------|
| **D1** Section 缺失 | key 不在 data 中 | 测 `.get(..., default)` 健壮性 |
| **D2** Section = None | 显式 None | 测 NoneType 处理 |
| **D3** Section = `{}` | 空字典 | 测空 dict 迭代 |
| **D4** Section = `[]` | 空列表 | 测空 list 迭代 |
| **D5** Section = `""` | 空字符串 | 测 falsy 但非 None |
| **D6** 类型错乱 | dict 当 list 传 | 测 AttributeError/TypeError |
| **D7** 嵌套空 | `market_overview.hs300 = {}` | 测嵌套字段访问 |

### 2.2 矩阵 × Section 速查

| Section (Type) | D1 缺失 | D2 None | D3 `{}` | D4 `[]` | D5 `""` | D6 类型错乱 | D7 嵌套空 |
|-----------------|---------|---------|---------|---------|---------|------------|----------|
| **PreMarketFormatter** ||||||||
| woa_summary (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(tasks=[]) |
| today_judgment (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(空子字段) |
| market_overview (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(hs300={}) |
| main_lines (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅(dict 当 list) | n/a |
| factors (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| strategy_signals (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(子 key 缺失) |
| etf_signals (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| auction_scan (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| auction_wts (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| auction (Dict,legacy) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| macro_events (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| risks (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(vix/vix/geo 异常) |
| hsgt (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| scenarios (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| today_attention (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| operation_ref (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| **PostMarketFormatter** ||||||||
| summary (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(indices={}) |
| limit_stats (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| main_review (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| ladder (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| board_break (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(broken=[]) |
| strategy_review (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(5 方向任一缺失) |
| etf_arbitrage (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| risk_review (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| operation_ref (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| day_summary (str) | ✅ | ✅ | n/a | n/a | ✅ | ✅(int) | n/a |
| **IntradayFormatter** ||||||||
| market_state (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(indices={}) |
| main_lines (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| limit_events (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(limit_ups=[]) |
| strategy_realtime (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(5 方向任一缺失) |
| etf_intraday (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(alerts=[]) |
| risk_signals (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | n/a |
| alerts (List) | ✅ | ✅ | n/a | ✅ | n/a | ✅ | n/a |
| **IntradayAlertFormatter** ||||||||
| limit_up (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(events=[]) |
| limit_down (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(stocks=[]) |
| anomaly (Dict) | ✅ | ✅ | ✅ | n/a | n/a | ✅ | ✅(events=[]) |

---

## 三、Phase 4 读代码发现（v1 审计）

> **关键**：这些是 mock 矩阵的"已知必崩点"，**Phase 4 必须修才能进 Phase 5**。
> **执行结果**：起草稿 + 跑 1次 pytest 后，**96 失败 + 1 错误 = 共 4 个根因 bug**。

### 测试运行结果（2026-06-11 18:50，v1 测试套件）

```
114 failed, 113 passed in 0.14s
```

**按测试类分类**：

| 测试类 | 通过 | 失败 | 状态 |
|--------|------|------|------|
| TestSmokeEmpty | 8/8 | 0 | ✅ |
| TestPreMarketFormatterEmpty | 88/88 | 0 | ✅ PreMarket 已健壮 |
| TestPostMarketFormatterEmpty | 2/52 | 50 | ❌ F-P4-02 risk_review |
| TestIntradayFormatterEmpty | 2/38 | 36 | ❌ F-P4-01 risk_signals |
| TestIntradayAlertFormatterEmpty | 6/33 | 27 | ❌ F-P4-04 类型校验 |
| TestRealDataRegression | 2/2 | 0 | ✅ 现有渲染未破坏 |
| TestBoundaries | 5/5 | 0 | ✅ |

> **结论**：3 个 formatters 存在空数据健壮性 bug。**PreMarket 已 100% 健壮**（修复优先级低于其他3个），其他 3 个需修后才能进 Phase 5。

### 🐛 F-P4-01（**高优先级**）IntradayFormatter._format_risk_signals 空 dict 输出假数据

**位置**：`src/reports/formatters.py` line 624-645

**当前行为**：
```python
def _format_risk_signals(self, risk_signals: Dict[str, Any]) -> str:
    lines = []
    limit_down_count = risk_signals.get("limit_down_count", 0)  # ⚠️ 默认 0
    if limit_down_count is not None:
        lines.append(f"跌停池：{limit_down_count}家")  # ⚠️ 总 append
    high_board_broken = risk_signals.get("high_board_broken", [])
    if high_board_broken:
        lines.append("高标杀：【有】")
    else:
        lines.append("高标杀：【无】")  # ⚠️ 总 append
    ...
    return "\n".join(lines) if lines else self._stub("风险信号")
```

**问题**：`risk_signals = {}` 时：
- `limit_down_count` 默认 0，**append "跌停池：0家"**（不是 stub！）
- `high_board_broken` 默认 []，**append "高标杀：【无】"**（不是 stub！）
- 返回 `"跌停池：0家\n高标杀：【无】"`
- `_build_body` 不会过滤（非 🔲 开头），**会在盘中报输出"假"风险信号**

**实测**：
```
=== F-P4-01: IntradayFormatter empty risk_signals ===
contains 跌停池：0家: True      # 假数据
contains 高标杀：【无】: True   # 假数据
```

**修复方向**：仅当 key 显式存在且非默认值时才 append，或全空时返回 stub。

### 🐛 F-P4-02（**中优先级**）PostMarketFormatter._format_risk_review 同类问题

**位置**：`src/reports/formatters.py` line 906-932

**当前行为**：
```python
def _format_risk_review(self, risk_review: Dict[str, Any]) -> str:
    lines = []
    limit_down = risk_review.get("limit_down", {})
    if limit_down:  # OK，empty 不进
        ...
    high_board_broken = risk_review.get("high_board_broken")
    if high_board_broken:
        ...
    else:
        lines.append("高标杀：【无】")  # ⚠️ 总是 append
    break_rate = risk_review.get("break_rate", None)
    if break_rate is not None:  # OK
        ...
    st = risk_review.get("st", {})
    if st and st.get("has", False):
        ...
    else:
        lines.append("ST/退市异动：【无】")  # ⚠️ 总是 append
    return "\n".join(lines) if lines else self._stub("风险信号复盘")
```

**问题**：`risk_review = {}` 时输出 `"高标杀：【无】\nST/退市异动：【无】"`，**不是 stub，会出现在报告里**。

**实测**：
```
=== F-P4-02: PostMarketFormatter empty risk_review ===
contains 高标杀：【无】: True      # 假数据
contains ST/退市异动：【无】: True  # 假数据
```

### 🐛 F-P4-03（**低优先级**）IntradayFormatter._format_strategy_realtime 空 dict 不返 stub

**位置**：`src/reports/formatters.py` line 596-615

**问题**：`strategy_realtime = {}` 时，5 个方向都 fall 到 `signal = "无"`，输出 5 行"无信号"——不是 stub。**不算崩，但是浪费版面**。

**处理**：可作为后续清理，Phase 4 仅记录不阻塞。

### 🐛 F-P4-04（**中优先级**）IntradayAlertFormatter 类型校验不全 → AttributeError

**位置**：`src/reports/formatters.py` line 1031-1050（_format_limit_up/_format_limit_down/_format_anomaly）

**当前行为**：
```python
def _format_limit_up(self, limit_up: Dict[str, Any]) -> str:
    events = limit_up.get("events", [])  # ⚠️ 假设 limit_up 是 dict
    ...
```

**问题**：`limit_up` 传 None / `""` / `[]` / `0` 时崩溃：
```
val=None: FAIL AttributeError: 'NoneType' object has no attribute 'get'
val='':   FAIL AttributeError: 'str' object has no attribute 'get'
val=[]:   FAIL AttributeError: 'list' object has no attribute 'get'
val=0:    FAIL AttributeError: 'int' object has no attribute 'get'
```

**影响范围**：IntradayAlertFormatter 3 个 helpers × 3 种非法类型 = 9 个 fail 用例

**修复方向**：入口加类型校验，非 dict → 走 stub 或空 dict fallback：
```python
if not isinstance(limit_up, dict):
    return self._stub("涨停监控")
```

---

### 📊 失败用例归类（v1 测试套件最终 = 114 fail）

| Bug ID | 失败用例数 | 测试类 | 触发条件 |
|--------|------------|--------|----------|
| F-P4-01 | 36 | TestIntradayFormatterEmpty | Intraday 7 sections × 5 variants + 1 直接测试（risk_signals bug 跨 section 传染）|
| F-P4-02 | 51 | TestPostMarketFormatterEmpty | PostMarket 10 sections × 5 variants + 1 直接测试（risk_review bug 跨 section 传染）|
| F-P4-04 | 27 | TestIntradayAlertFormatterEmpty | IntradayAlert 3 sections × 6 bad_types + 3 sections × 3 variants |
| F-P4-03 | 0 | — | 未被直接捕获（不返 fake data 模式，仅浪费版面） |
| **合计** | **114** | 3 个 bug 根因 |

> 修这 3 个 bug 后，预期 100% 通过（227/227 pass）。

---

## 四、测试用例结构

### 4.1 测试文件

**新文件**：`data-pipeline/tests/test_formatters_empty_data.py`

### 4.2 测试类组织

```python
class TestPreMarketFormatterEmpty:        # 16 sections × 5 变体
class TestPostMarketFormatterEmpty:       # 10 sections × 5 变体
class TestIntradayFormatterEmpty:         # 7 sections × 5 变体
class TestIntradayAlertFormatterEmpty:    # 3 sections × 5 变体
class TestSmokeEmpty:                     # 完全空 data {} × 4 formatters
class TestRealDataRegression:             # 真实数据 baseline，4 formatters
```

### 4.3 关键 fixture

```python
@pytest.fixture
def empty_section_variants():
    """5 种空数据变体工厂"""
    return {
        "missing": lambda: {},                        # 完全不传 key
        "none":    lambda key: {key: None},           # 显式 None
        "empty_dict": lambda key: {key: {}},          # 空字典
        "empty_list": lambda key: {key: []},          # 空列表
        "empty_str": lambda key: {key: ""},           # 空字符串
    }

@pytest.fixture
def minimal_data():
    """最小可用 data"""
    return {"trade_date": "2026-06-11"}

@pytest.fixture
def real_pre_market_data():
    """真实盘前报 data fixture"""
    # 从一次成功运行的 data 快照来
    ...
```

### 4.4 断言模式

每个空数据用例断言：
1. **不抛异常**：`format_report(...)` 成功返回 `List[str]`
2. **有合理降级**：
   - 包含 stub 标识 `🔲` 或降级提示词
   - **OR** 包含"无"/"暂无"/"数据待接入"/"⚠️"中的至少一个
3. **不输出"假数据"**（**核心**）：
   - 不含 `"跌停池：0家"`（除非 `limit_down_count=0` 显式传入）
   - 不含 `"高标杀：【无】"`（除非显式 `high_board_broken=[]`）
   - 不含 `"ST/退市异动：【无】"`（除非显式 `st.has=False`）
   - 不含 `"-"` 单独成行
4. **长度合理**：单条消息不超过 4000 字符（QQ 限制）

### 4.5 关键测试用例示例

```python
def test_pre_market_completely_empty_does_not_crash():
    """硬兜底：完全空 data"""
    result = format_report("pre_market", {})
    assert isinstance(result, list)
    assert all(isinstance(m, str) for m in result)
    # 至少有一个降级标识
    joined = "\n".join(result)
    assert "🔲" in joined or "数据待接入" in joined

@pytest.mark.parametrize("section_key", [
    "woa_summary", "today_judgment", "market_overview",
    "main_lines", "factors", "etf_signals", "auction_scan",
    "auction_wts", "auction", "macro_events", "risks",
    "hsgt", "scenarios", "today_attention", "operation_ref",
])
@pytest.mark.parametrize("variant", ["missing", "none", "empty_dict", "empty_list", "empty_str"])
def test_pre_market_section_empty(section_key, variant):
    """每个 section × 5 种空变体"""
    data = {"trade_date": "2026-06-11"}
    if variant == "missing":
        pass
    elif variant == "none":
        data[section_key] = None
    elif variant == "empty_dict":
        data[section_key] = {}
    elif variant == "empty_list":
        data[section_key] = []
    elif variant == "empty_str":
        data[section_key] = ""
    result = format_report("pre_market", data)
    assert isinstance(result, list)
    # 验证不输出"假数据"（核心断言）
    joined = "\n".join(result)
    assert "跌停池：0家" not in joined  # F-P4-01 保护

def test_intraday_risk_signals_empty_does_not_show_fake_data():
    """F-P4-01 回归测试：空 risk_signals 不能输出假数据"""
    data = {"trade_date": "2026-06-11", "risk_signals": {}}
    result = format_report("midday", data)
    joined = "\n".join(result)
    # 修复前会 fail，修复后 pass
    assert "跌停池：0家" not in joined
    assert "高标杀：【无】" not in joined

def test_post_market_risk_review_empty_does_not_show_fake_data():
    """F-P4-02 回归测试"""
    data = {"trade_date": "2026-06-11", "risk_review": {}}
    result = format_report("post_market", data)
    joined = "\n".join(result)
    assert "高标杀：【无】" not in joined
    assert "ST/退市异动：【无】" not in joined

@pytest.mark.parametrize("bad_value", [None, "", [], 0, "string"])
def test_intraday_alert_handles_non_dict_sections(bad_value):
    """F-P4-04 回归测试：IntradayAlert 不应因非 dict section 崩溃"""
    for report_type in ["intraday_alert"]:
        data = {
            "limit_up": bad_value,
            "limit_down": bad_value,
            "anomaly": bad_value,
        }
        # 不应抛异常
        result = format_report(report_type, data)
        assert isinstance(result, list)
```

---

## 五、执行计划

### 5.1 步骤

| 步骤 | 任务 | 责任 | 估时 | 验收 |
|------|------|------|------|------|
| 1 | 写 pytest 草稿（test_formatters_empty_data.py） | ✅ **已完成** (Arc) | 20min | 草稿文件存在 |
| 2 | **先跑一次，预期 fail**（F-P4-01/02/04 必 fail） | ✅ **已完成** (Arc) | 5min | 114 fail, 113 pass |
| 3 | 修复 F-P4-01（Intraday._format_risk_signals） | ✅ **已完成** (CC) | 10min | 36 测试 pass |
| 4 | 修复 F-P4-02（PostMarket._format_risk_review） | ✅ **已完成** (CC) | 10min | 51 测试 pass |
| 5 | 修复 F-P4-04（IntradayAlert 3 个 helper 类型校验） | ✅ **已完成** (CC) | 10min | 27 测试 pass |
| 6 | **补充发现**：F-P4-04 模式扩展到 6 个额外 helper（Intraday/PostMarket 各 3 个） | ✅ **已完成** (CC) | 5min | 18 测试 pass |
| 7 | 重跑全部测试 | ✅ **已完成** (CC) | 5min | **227/227 pass** |
| 8 | py_compile 验证 | ✅ **已完成** (CC) | — | exit 0 |
| 9 | commit + 更新 v3 文档 §4.0 状态 | ⏳ CIA | 5min | git log |

**完成总估时**：~25min（实际耗时）vs v3 方案 §6.2 估算 1h

**实际修复 scope**（超出原 3 个 bug 计划）：

- F-P4-01 1 个 helper
- F-P4-02 1 个 helper
- F-P4-04 3 个 helper (原计划)
- **额外 6 个 helper** （同 F-P4-04 模式， Claude Code 在 round-2 prompt 后一并修了）
- **合计：11 个 helper / 22 行插入 / 6 行删除**

> **说明**：F-P4-04 实际是 formatters 的系统性问题（原设计只识别了 IntradayAlert 3 个，测试揭露 Intraday/PostMarket 也有 6 个同类问题）。已一并修复以达成 100% pass。

### 5.2 回归保证

- 修复 F-P4-01/02 **不能破坏现有真实数据渲染**
- 通过 `TestRealDataRegression` 套件保证
- baseline data：可用最近一次成功运行的 pre_market/midday/post_market data 快照

---

## 六、风险与决策

### 6.1 已识别风险

| 风险 | 缓解 |
|------|------|
| F-P4-01/02 修复引入新 bug | 真实数据 regression 测试保护 |
| 真实数据 baseline 难构造 | 用最近一次成功运行的 data 快照（已存在 daily_market_snapshot） |
| pytest 没装 / 路径错 | 已确认 data-pipeline/pyproject.toml 包含 pytest 依赖 |

### 6.2 决策点（需 CIA 拍板）

| # | 决策 | 默认建议 |
|---|------|---------|
| 1 | F-P4-03（strategy_realtime 不返 stub）Phase 4 是否一并修 | **不修**，记入 backlog（不算崩） |
| 2 | "降级标识"统一文案（v3 提"⚠️ 数据采集失败"vs 现 stub 标识"🔲"） | **保留 🔲 stub + 新增 ⚠️ 降级** 两套；stub 表示"暂无数据源"，⚠️ 表示"采集失败可降级" |
| 3 | 真实数据 baseline 来源 | **从最近一次成功运行的 daily_market_snapshot 取** |

---

## 七、验收标准

1. **pytest 全部 227 用例 pass** ✅ 达成
2. **formatters.py 覆盖率 ≥ 90%** ⏳ 待补充 pytest-cov 报告
3. **真实数据 regression pass**（不破坏现有渲染） ✅ TestRealDataRegression 2/2 pass
4. **CI 集成**（可选）：`pytest tests/test_formatters_empty_data.py` 可在 CI 跑 ⏳

**最终结果（2026-06-11 19:15）**：

```
227 passed in 0.08s
```

- formatters.py 改动：+22 -6 = 28 行（单文件，≤40 行 scope）
- py_compile: 0 错误
- 修改但未 commit（待 CIA 决定）

---

## 八、关联文档

- 上游：[MCP采集-报告DB化改造方案.md](MCP采集-报告DB化改造方案.md) v3
- 测试文件：`data-pipeline/tests/test_formatters_empty_data.py`（待生成）
- 修复 commit：待生成（修复 F-P4-01/02）

---

*设计: Arc 2026-06-11*
*待执行: Claude Code (Claude Code + tmux 自动化)*
