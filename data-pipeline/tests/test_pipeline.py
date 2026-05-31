"""signals/alpha.py — 单元测试"""

import sys
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

from unittest.mock import MagicMock, patch
import pytest


class TestNormalizeFactor:
    """normalize_factor — 因子方向处理"""

    def test_direction_positive(self):
        from src.signals.alpha import normalize_factor
        raw = {"a": 10.0, "b": 20.0, "c": 30.0}
        result = normalize_factor(raw, direction=1)
        assert result["c"] > result["b"] > result["a"]
        assert all(0 <= v <= 100 for v in result.values())

    def test_direction_negative(self):
        from src.signals.alpha import normalize_factor
        raw = {"a": 30.0, "b": 20.0, "c": 10.0}
        result = normalize_factor(raw, direction=-1)
        # 反向：原本最大的 "a" 现在百分位最低
        assert result["a"] < result["b"] < result["c"]

    def test_all_none(self):
        from src.signals.alpha import normalize_factor
        result = normalize_factor({"a": None, "b": None}, direction=1)
        assert all(v == 50.0 for v in result.values())

    def test_empty(self):
        from src.signals.alpha import normalize_factor
        result = normalize_factor({}, direction=1)
        assert result == {}


class TestUpsertWeights:
    """upsert_weights — 权重表初始化"""

    @patch("src.signals.alpha.psycopg2")
    def test_inserts_default_weights(self, mock_pg):
        from src.signals.alpha import upsert_weights, DEFAULT_WEIGHTS

        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)

        count = upsert_weights(mock_conn, DEFAULT_WEIGHTS)
        assert count == len(DEFAULT_WEIGHTS)
        assert mock_cur.execute.call_count == len(DEFAULT_WEIGHTS)


class TestLoadWeights:
    """load_weights — 从 DB 读取权重"""

    @patch("src.signals.alpha.psycopg2")
    def test_loads_weights(self, mock_pg):
        from src.signals.alpha import load_weights

        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.return_value = [
            ("momentum_5d", "momentum", 0.07, 1),
            ("roe", "quality", 0.06, 1),
        ]

        weights = load_weights(mock_conn)
        assert len(weights) == 2
        assert weights[0]["factor_key"] == "momentum_5d"
        assert weights[0]["weight"] == 0.07
        assert weights[0]["norm_direction"] == 1