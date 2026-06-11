"""
formatters 空数据兼容性测试 (Phase 4)
======================================

设计依据: /home/claw/invest-infra/docs/需求方案/Phase4-mock矩阵设计.md
版本: v1 草案 (2026-06-11)

目标:
  1. 完全空 data {} → formatters 不崩
  2. 每个 section 字段缺失/空字典/空列表/None → formatters 不崩
  3. 不输出"假数据"（跌停池：0家 / 高标杀：【无】 / ST/退市异动：【无】)
  4. 真实数据 baseline 不被破坏

执行:
  cd /home/claw/invest-infra/data-pipeline
  pytest tests/test_formatters_empty_data.py -v
"""
import os
import sys

# 直接 import formatters.py,绕过 reports 包 __init__.py 触发的链式依赖
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "reports")
)
import pytest

from formatters import format_report, get_formatter


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def trade_date():
    return "2026-06-11"


def make_data(trade_date=None, **sections):
    """构造 data dict 的工厂"""
    if trade_date is None:
        trade_date = "2026-06-11"
    data = {"trade_date": trade_date}
    data.update(sections)
    return data


# 各 section 字段定义（formatters 实际访问的 key）
PRE_MARKET_SECTIONS = [
    "woa_summary", "today_judgment", "market_overview",
    "main_lines", "factors", "strategy_signals",
    "woa_etf_signals", "etf_signals",  # 二选一
    "auction_scan", "auction_wts", "auction",
    "macro_events", "risks", "hsgt",
    "scenarios", "today_attention", "operation_ref",
]

POST_MARKET_SECTIONS = [
    "summary", "limit_stats", "main_review", "ladder",
    "board_break", "strategy_review", "etf_arbitrage",
    "risk_review", "operation_ref", "day_summary",
]

INTRADAY_SECTIONS = [
    "market_state", "main_lines", "limit_events",
    "strategy_realtime", "etf_intraday", "risk_signals", "alerts",
]

INTRADAY_ALERT_SECTIONS = [
    "limit_up", "limit_down", "anomaly",
]

# "假数据"关键词（不应该在空数据时出现）
FAKE_DATA_PATTERNS = [
    "跌停池：0家",            # F-P4-01
    "高标杀：【无】",        # F-P4-01, F-P4-02
    "ST/退市异动：【无】",  # F-P4-02
]

# 降级标识（应该出现在空数据时）
FALLBACK_MARKERS = ["🔲", "数据待接入", "无", "暂无", "⚠️"]


# ─────────────────────────────────────────────────────────────────────────────
# A. Smoke Tests - 完全空 data
# ─────────────────────────────────────────────────────────────────────────────

class TestSmokeEmpty:
    """完全空 data {} 不应让 formatters 崩溃"""

    @pytest.mark.parametrize("report_type", ["pre_market", "midday", "post_market", "intraday_alert"])
    def test_completely_empty_data(self, report_type):
        result = format_report(report_type, {})
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(m, str) for m in result)
        # 至少有一个降级标识
        joined = "\n".join(result)
        assert any(marker in joined for marker in FALLBACK_MARKERS), \
            f"完全空 data 应该有降级标识，实际输出: {joined[:300]}"

    @pytest.mark.parametrize("report_type", ["pre_market", "midday", "post_market", "intraday_alert"])
    def test_only_trade_date(self, report_type, trade_date):
        """仅 trade_date，其余全部为空"""
        result = format_report(report_type, {"trade_date": trade_date})
        assert isinstance(result, list)
        assert len(result) >= 1
        joined = "\n".join(result)
        # 应该有降级标识
        assert any(marker in joined for marker in FALLBACK_MARKERS), \
            f"仅 trade_date 应该有降级标识，实际输出: {joined[:300]}"


# ─────────────────────────────────────────────────────────────────────────────
# B. PreMarketFormatter - 16 sections × 5 空数据变体
# ─────────────────────────────────────────────────────────────────────────────

class TestPreMarketFormatterEmpty:
    """PreMarketFormatter 各 section 空数据兼容性"""

    @pytest.mark.parametrize("section_key", PRE_MARKET_SECTIONS)
    @pytest.mark.parametrize("variant", ["missing", "none", "empty_dict", "empty_list", "empty_str"])
    def test_pre_market_section_empty(self, section_key, variant, trade_date):
        """每个 section × 5 种空变体"""
        data = {"trade_date": trade_date}
        if variant == "missing":
            pass  # key 不在 data 中
        elif variant == "none":
            data[section_key] = None
        elif variant == "empty_dict":
            data[section_key] = {}
        elif variant == "empty_list":
            data[section_key] = []
        elif variant == "empty_str":
            data[section_key] = ""
        # 不应崩
        result = format_report("pre_market", data)
        assert isinstance(result, list)
        assert len(result) >= 1
        # 验证不输出"假数据"
        joined = "\n".join(result)
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined, \
                f"section={section_key}, variant={variant} 不应输出假数据 '{pattern}', 实际: {joined[:500]}"

    def test_woa_summary_tasks_empty_list(self, trade_date):
        """F-P4-01 周边: woa_summary.tasks = [] 边界"""
        data = make_data(trade_date, woa_summary={"tasks": [], "overall_confidence": "-"})
        result = format_report("pre_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # tasks 空时，应该走"今日无待执行 WOA 任务"分支，不应崩
        # 不会输出假数据
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined

    def test_risks_partial_fields(self, trade_date):
        """risks 字段部分存在（vix=空字符串，geo_risk_star="abc"非数字）"""
        data = make_data(trade_date, risks={
            "risk_level": "中等",
            "volatility": "15%",
            "vix": "",
            "geo_risk_star": "abc",  # 非数字
        })
        result = format_report("pre_market", data)
        assert isinstance(result, list)
        # vix 空 → 不应 append
        # geo "abc" → isdigit False → else 分支，输出 "abc"（实际代码会输出"abc"作为星号替代）
        # 不应崩

    def test_market_overview_hs300_empty(self, trade_date):
        """market_overview.hs300 = {} 嵌套空"""
        data = make_data(trade_date, market_overview={"hs300": {}, "sentiment": "中性"})
        result = format_report("pre_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # hs300 空 → point="-", change_raw="-" → 应输出 "沪深300：**-**（-%）" 或类似
        # 不应崩
        assert "沪深300" in joined


# ─────────────────────────────────────────────────────────────────────────────
# C. PostMarketFormatter - 10 sections × 5 空数据变体
# ─────────────────────────────────────────────────────────────────────────────

class TestPostMarketFormatterEmpty:
    """PostMarketFormatter 各 section 空数据兼容性"""

    @pytest.mark.parametrize("section_key", POST_MARKET_SECTIONS)
    @pytest.mark.parametrize("variant", ["missing", "none", "empty_dict", "empty_list", "empty_str"])
    def test_post_market_section_empty(self, section_key, variant, trade_date):
        data = {"trade_date": trade_date}
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
        result = format_report("post_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined, \
                f"section={section_key}, variant={variant} 不应输出假数据 '{pattern}'"

    def test_risk_review_empty_no_fake_data(self, trade_date):
        """F-P4-02 回归测试：空 risk_review 不能输出'高标杀：【无】'"""
        data = make_data(trade_date, risk_review={})
        result = format_report("post_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # 修复前会 fail，修复后 pass
        assert "高标杀：【无】" not in joined, \
            f"空 risk_review 不应输出 '高标杀：【无】'，实际: {joined[:500]}"
        assert "ST/退市异动：【无】" not in joined, \
            f"空 risk_review 不应输出 'ST/退市异动：【无】'，实际: {joined[:500]}"

    def test_risk_review_explicit_empty(self, trade_date):
        """显式 high_board_broken=None 时,应仍输出'高标杀：【无】'（合理）"""
        # 注意: 这个测试是用来确认 explicit 行为正常,不是 bug
        data = make_data(trade_date, risk_review={"high_board_broken": None, "st": {"has": False}})
        result = format_report("post_market", data)
        assert isinstance(result, list)
        # 这种情况代码会输出 【无】，是合理行为（用户传了 None 显式表示"无"）
        # 不强制 assert

    def test_strategy_review_empty(self, trade_date):
        """strategy_review={} 时不应崩"""
        data = make_data(trade_date, strategy_review={})
        result = format_report("post_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # 应输出 stub 或 5 行"无信号"
        # 不应崩


# ─────────────────────────────────────────────────────────────────────────────
# D. IntradayFormatter - 7 sections × 5 空数据变体
# ─────────────────────────────────────────────────────────────────────────────

class TestIntradayFormatterEmpty:
    """IntradayFormatter (midday/intraday 复用) 各 section 空数据兼容性"""

    @pytest.mark.parametrize("section_key", INTRADAY_SECTIONS)
    @pytest.mark.parametrize("variant", ["missing", "none", "empty_dict", "empty_list", "empty_str"])
    def test_intraday_section_empty(self, section_key, variant, trade_date):
        data = {"trade_date": trade_date}
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
        result = format_report("midday", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined, \
                f"section={section_key}, variant={variant} 不应输出假数据 '{pattern}'"

    def test_risk_signals_empty_no_fake_data(self, trade_date):
        """F-P4-01 回归测试：空 risk_signals 不能输出'跌停池：0家'"""
        data = make_data(trade_date, risk_signals={})
        result = format_report("midday", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # 修复前会 fail，修复后 pass
        assert "跌停池：0家" not in joined, \
            f"空 risk_signals 不应输出 '跌停池：0家'，实际: {joined[:500]}"
        assert "高标杀：【无】" not in joined, \
            f"空 risk_signals 不应输出 '高标杀：【无】'，实际: {joined[:500]}"

    def test_risk_signals_explicit_zero(self, trade_date):
        """显式 limit_down_count=0 时,应输出'跌停池：0家'（合理）"""
        data = make_data(trade_date, risk_signals={"limit_down_count": 0})
        result = format_report("midday", data)
        assert isinstance(result, list)
        # 这种情况是合理输出，不算 bug
        # 不强制 assert

    def test_strategy_realtime_empty_5_directions(self, trade_date):
        """strategy_realtime={} 不应崩,可能输出 5 行 '无'"""
        data = make_data(trade_date, strategy_realtime={})
        result = format_report("midday", data)
        assert isinstance(result, list)
        # 当前实现会输出 5 行"无信号"，不算崩但是浪费版面
        # F-P4-03 是后续优化项


# ─────────────────────────────────────────────────────────────────────────────
# E. IntradayAlertFormatter - 3 sections × 5 空数据变体
# ─────────────────────────────────────────────────────────────────────────────

class TestIntradayAlertFormatterEmpty:
    """IntradayAlertFormatter 各 section 空数据兼容性"""

    @pytest.mark.parametrize("section_key", INTRADAY_ALERT_SECTIONS)
    @pytest.mark.parametrize("variant", ["missing", "none", "empty_dict", "empty_list", "empty_str"])
    def test_intraday_alert_section_empty(self, section_key, variant, trade_date):
        data = {"trade_date": trade_date}
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
        result = format_report("intraday_alert", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined

    @pytest.mark.parametrize("bad_value", [None, "", [], 0, "string", 3.14])
    @pytest.mark.parametrize("section_key", INTRADAY_ALERT_SECTIONS)
    def test_intraday_alert_handles_non_dict_sections(self, section_key, bad_value):
        """F-P4-04 回归测试：IntradayAlert 不应因非 dict section 崩溃"""
        data = {"trade_date": "2026-06-11", section_key: bad_value}
        # 不应抛异常
        result = format_report("intraday_alert", data)
        assert isinstance(result, list)
        assert len(result) >= 1
        joined = "\n".join(result)
        # 不应输出假数据
        for pattern in FAKE_DATA_PATTERNS:
            assert pattern not in joined



# ─────────────────────────────────────────────────────────────────────────────
# F. 真实数据 Regression - 防止 Phase 4 修复破坏现有渲染
# ─────────────────────────────────────────────────────────────────────────────

class TestRealDataRegression:
    """真实数据 baseline 测试 - 验证 Phase 4 修复不破坏现有渲染"""

    @pytest.fixture
    def real_pre_market_data(self, trade_date):
        """真实盘前报 data fixture (从一次成功运行的快照构造)"""
        return make_data(
            trade_date=trade_date,
            woa_summary={
                "tasks": [
                    {"task": "数据采集", "status": "✅", "confidence": "HIGH"},
                    {"task": "报告生成", "status": "⏳", "confidence": "MEDIUM"},
                ],
                "overall_confidence": "高",
                "risk_level": "中等",
            },
            today_judgment={
                "market_direction": "震荡偏多",
                "direction_logic": "成交量温和放大",
                "market_sentiment": "谨慎乐观",
            },
            market_overview={
                "hs300": {"point": "3850.5", "change_pct": "0.45"},
                "sentiment": "中性偏多",
                "date": trade_date,
            },
            main_lines=[
                {"板块": "AI算力", "逻辑": "海外需求强劲"},
                {"板块": "新能源", "逻辑": "政策催化"},
            ],
            factors=[
                {"name": "动量", "signal": "偏多", "confidence": "HIGH", "data_status": "OK"},
            ],
            etf_signals=[
                {"name": "沪深300ETF", "signal": "持有", "composite_score": 75, "confidence": "HIGH"},
            ],
            auction_scan=[
                {"code": "300750", "name": "宁德时代", "change": 5.2, "amount": 15000},
            ],
            risks={"risk_level": "中等", "volatility": "15%", "vix": "18", "geo_risk_star": "2"},
        )

    @pytest.fixture
    def real_post_market_data(self, trade_date):
        """真实盘后报 data fixture"""
        return make_data(
            trade_date=trade_date,
            summary={
                "indices": {"上证指数": "3200", "深证成指": "10500"},
                "amount": 8500,
                "amount_change": "+5%",
                "counts": {"up": 3500, "down": 1500, "flat": 100},
                "sentiment": "偏多",
                "tomorrow_expect": "震荡",
            },
            limit_stats={
                "limit_up": 65, "limit_up_yesterday": 55,
                "seal_rate": 75, "break_rate": 25,
                "limit_down": 8, "limit_down_yesterday": 12,
                "broken": 5, "continued": 12,
                "first_board": 48, "second_board": 13, "third_plus": 4,
            },
            ladder=[
                {"name": "龙头A", "code": "600000", "streak": 5, "reason": "AI概念"},
                {"name": "龙头B", "code": "600001", "streak": 2, "reason": "新能源"},
            ],
            main_review=[
                {"sector": "AI", "performance": "强势", "leaders": [], "signal_strength": "强", "tomorrow": "持续"},
            ],
        )

    def test_pre_market_real_data_renders(self, real_pre_market_data):
        """真实盘前报数据能正常渲染"""
        result = format_report("pre_market", real_pre_market_data)
        assert isinstance(result, list)
        assert len(result) >= 1
        joined = "\n".join(result)
        # 关键内容应出现
        assert "盘前报" in joined
        assert "沪深300" in joined
        assert "AI算力" in joined
        assert "宁德时代" in joined or "300750" in joined

    def test_post_market_real_data_renders(self, real_post_market_data):
        """真实盘后报数据能正常渲染"""
        result = format_report("post_market", real_post_market_data)
        assert isinstance(result, list)
        assert len(result) >= 1
        joined = "\n".join(result)
        assert "盘后复盘" in joined
        assert "涨停" in joined
        assert "龙头A" in joined


# ─────────────────────────────────────────────────────────────────────────────
# G. 长度 & 边界
# ─────────────────────────────────────────────────────────────────────────────

class TestBoundaries:
    """边界条件"""

    @pytest.mark.parametrize("report_type", ["pre_market", "midday", "post_market", "intraday_alert"])
    def test_message_length_within_qq_limit(self, report_type, trade_date):
        """单条消息不超过 4000 字符 (QQ 限制)"""
        result = format_report(report_type, {"trade_date": trade_date})
        for msg in result:
            assert len(msg) <= 4000, f"{report_type} 单条消息超 4000 字符: {len(msg)}"

    def test_pre_market_factors_empty_strategy_signals_present(self, trade_date):
        """factors=[], strategy_signals 有数据时,应走 DB fallback 分支"""
        data = make_data(
            trade_date,
            factors=[],
            strategy_signals={
                "phys_ai": {"signal": "偏多", "yesterday": "OK", "confidence": "HIGH"},
            }
        )
        result = format_report("pre_market", data)
        assert isinstance(result, list)
        joined = "\n".join(result)
        # 应输出 factor 表格,包含"动量"行
        assert "动量" in joined or "phys_ai" in joined or "🔲" in joined


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
