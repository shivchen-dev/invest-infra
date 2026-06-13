"""
test_alert_dispatcher.py — monitoring.alert_dispatcher 单元测试 (N-10)

4 层阈值 + deque 滑窗 + stats() + 未知 level 容忍
审计员: Arc
"""
import sys
import time
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from monitoring.alert_dispatcher import AlertDispatcher, SLA_THRESHOLDS  # noqa: E402


# ─── SLA 阈值 ───────────────────────────────────────────────────
def test_sla_thresholds_defaults():
    """默认 SLA 阈值 (规范 §③ 3.5)."""
    assert SLA_THRESHOLDS["FATAL"]["threshold"] == 3
    assert SLA_THRESHOLDS["FATAL"]["window_sec"] == 300
    assert SLA_THRESHOLDS["ERROR"]["threshold"] == 5
    assert SLA_THRESHOLDS["WARN"]["threshold"] == 10
    assert SLA_THRESHOLDS["INFO"]["threshold"] == 0  # 不告警


# ─── AlertDispatcher 短窗口测试 ──────────────────────────────────
@pytest.fixture
def short_alert():
    """短 SLA (2s 窗口) 用于快速测试."""
    return AlertDispatcher(thresholds={
        "FATAL": {"window_sec": 2, "threshold": 2},
        "ERROR": {"window_sec": 2, "threshold": 3},
        "WARN":  {"window_sec": 2, "threshold": 5},
        "INFO":  {"window_sec": 0, "threshold": 0},
    })


def test_fatal_threshold_triggers(short_alert):
    """FATAL 阈值触发."""
    short_alert.reset()
    short_alert.record("FATAL", "PG-E010", "1st")
    assert not short_alert.should_alert("FATAL")
    short_alert.record("FATAL", "PG-E010", "2nd")
    assert short_alert.should_alert("FATAL")


def test_info_never_alerts(short_alert):
    """INFO 100 次也不告警."""
    short_alert.reset()
    for i in range(100):
        short_alert.record("INFO", "X-R201", f"info {i}")
    assert not short_alert.should_alert("INFO")


def test_sliding_window_expiry(short_alert):
    """滑窗外不应告警."""
    short_alert.reset()
    short_alert.record("FATAL", "PG-E010", "1st")
    short_alert.record("FATAL", "PG-E010", "2nd")
    assert short_alert.should_alert("FATAL")
    time.sleep(2.5)
    assert not short_alert.should_alert("FATAL")


def test_stats_and_unknown_level(short_alert):
    """stats() 接口 + 未知 level 容忍."""
    short_alert.reset()
    short_alert.record("WARN", "GRID-W101", "w1")
    short_alert.record("WARN", "GRID-W101", "w2")
    s = short_alert.stats()
    assert s["WARN"] == 2
    # 未知 level 不抛错
    short_alert.record("BOGUS", "X-E001", "test")  # 应容忍
