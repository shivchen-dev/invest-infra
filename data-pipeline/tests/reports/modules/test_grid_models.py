"""
test_grid_models.py — GridInput/GridOutput Pydantic 模型单元测试 (N-6.3)

覆盖 12 边界 case (P0/P1) + 7 档映射 + CV 修正
GridAnalyzer 业务方法需要 PG env, 留 N-9 集成测试

审计员: Arc
"""
import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# 必须在 import pandas/numpy 之前, 设好 env stubs (reports.__init__ 链路需要)
os.environ.setdefault("PG_PASSWORD", "x")
os.environ.setdefault("MINIO_SECRET_KEY", "x")
os.environ.setdefault("CIFANG_TOKEN", "x")
os.environ.setdefault("MCP_TOKEN", "x")

# 预加载 numpy, 避免 pytest-cov 收集时 pandas.__init__ 报 "numpy: cannot load module"
import numpy  # noqa: F401

import pytest
from pydantic import ValidationError

_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from reports.modules.grid_models import (  # noqa: E402
    GridInput, GridOutput, GridSignal, ConfidenceLevel,
)


# ─── B-10: 未来日期 ──────────────────────────────────────────────
def test_b10_future_date_rejected():
    """B-10: trade_date 不能是未来."""
    with pytest.raises(ValidationError) as exc:
        GridInput(etf_id=1, trade_date=date.today() + timedelta(days=1))
    assert "未来日期" in str(exc.value)


def test_b10_normal_date_accepted():
    """正常日期应接受."""
    inp = GridInput(etf_id=178, trade_date=date(2026, 6, 12))
    assert inp.etf_id == 178
    assert inp.window_days == 252  # default


# ─── B-1: 数据窗口不足 ─────────────────────────────────────────
def test_b1_window_under_252_warns():
    """B-1: window_used < 252 → warnings 包含 B-1."""
    out = GridOutput(
        etf_id=1, mean_252d=Decimal("1"), current_price=Decimal("1"),
        cv_pct=Decimal("10"), gap_pct=Decimal("5"),
        signal=GridSignal.NEUTRAL, confidence=ConfidenceLevel.HIGH,
        window_used=200, deviation_pct=Decimal("0"),
    )
    assert any("B-1" in w for w in out.warnings)


# ─── B-5: 极值偏离 → stale ──────────────────────────────────────
def test_b5_extreme_deviation_stale():
    """B-5: |deviation| > 30% → confidence = STALE."""
    out = GridOutput(
        etf_id=1, mean_252d=Decimal("1"), current_price=Decimal("1.5"),
        cv_pct=Decimal("10"), gap_pct=Decimal("5"),
        signal=GridSignal.STRONG_SELL, confidence=ConfidenceLevel.HIGH,
        window_used=252, deviation_pct=Decimal("50"),
    )
    assert out.confidence == ConfidenceLevel.STALE
    assert any("B-5" in w for w in out.warnings)


def test_b5_extreme_negative_deviation_stale():
    """B-5: deviation < -30% 也应 stale."""
    out = GridOutput(
        etf_id=1, mean_252d=Decimal("1"), current_price=Decimal("0.5"),
        cv_pct=Decimal("10"), gap_pct=Decimal("5"),
        signal=GridSignal.STRONG_BUY, confidence=ConfidenceLevel.HIGH,
        window_used=252, deviation_pct=Decimal("-50"),
    )
    assert out.confidence == ConfidenceLevel.STALE


# ─── B-6: 极值 CV → gap 锁定 ────────────────────────────────────
def test_b6_extreme_cv_locks_gap_8():
    """B-6: CV > 50% → gap_pct = 8.0 强制锁定."""
    out = GridOutput(
        etf_id=1, mean_252d=Decimal("1"), current_price=Decimal("1"),
        cv_pct=Decimal("60"), gap_pct=Decimal("5"),
        signal=GridSignal.NEUTRAL, confidence=ConfidenceLevel.MEDIUM,
        window_used=252, deviation_pct=Decimal("0"),
    )
    assert out.gap_pct == Decimal("8.0")
    assert any("B-6" in w for w in out.warnings)


# ─── Field 约束 ────────────────────────────────────────────────
def test_field_cv_pct_out_of_range():
    """Field 约束: cv_pct > 100 应 ValidationError."""
    with pytest.raises(ValidationError):
        GridOutput(
            etf_id=1, mean_252d=Decimal("1"), current_price=Decimal("1"),
            cv_pct=Decimal("150"), gap_pct=Decimal("5"),
            signal=GridSignal.NEUTRAL, confidence=ConfidenceLevel.HIGH,
            window_used=252, deviation_pct=Decimal("0"),
        )


def test_field_etf_id_must_be_positive():
    """etf_id 必须 > 0."""
    with pytest.raises(ValidationError):
        GridInput(etf_id=0, trade_date=date(2026, 6, 12))
    with pytest.raises(ValidationError):
        GridInput(etf_id=-1, trade_date=date(2026, 6, 12))


# ─── 7 档 GridSignal 枚举 ────────────────────────────────────────
def test_7_signals_complete():
    """7 档 GridSignal 枚举完整."""
    expected_signals = {
        "🟢极低估值", "🟢低估值", "🟡少量买入", "⚪观望",
        "🟡少量卖出", "🔴卖出", "🔴极高估值",
    }
    actual_signals = {s.value for s in GridSignal}
    assert actual_signals == expected_signals


# ─── model_dump v2 API ───────────────────────────────────────────
def test_model_dump_v2():
    """pydantic v2 model_dump 返回 dict 含 enum 实例."""
    out = GridOutput(
        etf_id=178, mean_252d=Decimal("1.07"), current_price=Decimal("0.798"),
        cv_pct=Decimal("33.33"), gap_pct=Decimal("8"),
        signal=GridSignal.STRONG_BUY, confidence=ConfidenceLevel.HIGH,
        window_used=252, deviation_pct=Decimal("-25.43"),
    )
    d = out.model_dump()
    assert d["signal"] == GridSignal.STRONG_BUY
    assert d["confidence"] == ConfidenceLevel.HIGH
    assert d["mean_252d"] == Decimal("1.07")  # Decimal 保留
    assert d["warnings"] == []
