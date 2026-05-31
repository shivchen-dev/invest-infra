"""pg.py批量写入 —单元测试（mock DB）"""

import sys
sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

from unittest.mock import MagicMock, patch
import pytest


class TestNanToNone:
    """_nan_to_none 工具函数"""

    def test_none_passthrough(self):
        from src.loader.pg import _nan_to_none
        assert _nan_to_none(None) is None

    def test_float_nan(self):
        import math
        from src.loader.pg import _nan_to_none
        assert _nan_to_none(float("nan")) is None

    def test_float_inf(self):
        import math
        from src.loader.pg import _nan_to_none
        assert _nan_to_none(float("inf")) is None
        assert _nan_to_none(float("-inf")) is None

    def test_valid_float(self):
        from src.loader.pg import _nan_to_none
        assert _nan_to_none(1.23) == 1.23
        assert _nan_to_none(0.0) == 0.0

    def test_int_passthrough(self):
        from src.loader.pg import _nan_to_none
        assert _nan_to_none(42) == 42


class TestNormalizeDate:
    """_normalize_date 工具函数"""

    def test_none(self):
        from src.loader.pg import _normalize_date
        assert _normalize_date(None) is None

    def test_iso_format(self):
        from src.loader.pg import _normalize_date
        assert _normalize_date("2026-05-31T00:00:00") == "2026-05-31"
        assert _normalize_date("2026-05-31T15:30:00.123") == "2026-05-31"

    def test_plain_date(self):
        from src.loader.pg import _normalize_date
        assert _normalize_date("2026-05-31") == "2026-05-31"


class TestBatchUpsertQuotes:
    """batch_upsert_quotes — 批量 upsert"""

    @patch("src.loader.pg.psycopg2")
    def test_empty_records(self, mock_pg):
        from src.loader.pg import batch_upsert_quotes
        result = batch_upsert_quotes([])
        assert result["written"] == 0

    @patch("src.loader.pg.psycopg2")
    def test_all_skipped_unknown_code(self, mock_pg):
        from src.loader.pg import batch_upsert_quotes

        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        # company_id_map returns empty → all skipped
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.execute.return_value = None
        mock_cur.fetchall.return_value = []

        result = batch_upsert_quotes([
            {"stock_code": "000001.SZ", "trade_date": "2026-05-31", "close_price": 10.0},
        ])
        assert result["written"] == 0
        assert result["skipped"] == 1

    @patch("src.loader.pg.psycopg2")
    @patch("src.loader.pg.execute_batch")
    def test_valid_record(self, mock_exec_batch, mock_pg):
        from src.loader.pg import batch_upsert_quotes

        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.side_effect = [
            [("000001.SZ", 1)],   # get_company_id_map
        ]
        mock_exec_batch.return_value = None

        result = batch_upsert_quotes([
            {"stock_code": "000001.SZ", "trade_date": "2026-05-31",
             "open_price": 9.5, "high_price": 10.0, "low_price": 9.4,
             "close_price": 9.8, "pre_close": 9.7, "volume": 1000000,
             "amount": 9700000.0, "turnover_rate": 0.5, "amplitude": 1.2,
             "change_pct": 1.03, "source": "akshare"},
        ])
        assert result["written"] == 1
        assert result["skipped"] == 0
        mock_exec_batch.assert_called_once()
        # execute_batch(cursor, sql, rows) → rows 在 call_args[0][2]
        call_args = mock_exec_batch.call_args
        submitted_rows = call_args[0][2]
        assert len(submitted_rows) == 1  # 1 row


class TestBatchUpsertEtfQuotes:
    """batch_upsert_etf_quotes — ETF 批量 upsert"""

    @patch("src.loader.pg.psycopg2")
    @patch("src.loader.pg.execute_batch")
    def test_nan_cleaned(self, mock_exec_batch, mock_pg):
        import math
        from src.loader.pg import batch_upsert_etf_quotes

        mock_conn = MagicMock()
        mock_pg.connect.return_value = mock_conn
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.__enter__ = MagicMock(return_value=mock_cur)
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchall.side_effect = [
            [("510300", 1)],  # get_etf_id_map
        ]
        mock_exec_batch.return_value = None

        result = batch_upsert_etf_quotes([
            {"etf_code": "510300", "trade_date": "2026-05-31",
             "close_price": float("nan"), "volume": float("inf"),
             "iopv": 3.5, "premium_rate": 0.01, "source": "akshare-spot"},
        ])
        assert result["written"] == 1
        # execute_batch(cursor, sql, rows) → rows 在 call_args[0][2]
        call_args = mock_exec_batch.call_args
        submitted_rows = call_args[0][2]
        assert len(submitted_rows) == 1
        submitted_row = submitted_rows[0]
        # close_price (index 5) and volume (index 11) should be None
        assert submitted_row[5] is None   # close_price
        assert submitted_row[11] is None  # volume
        # iopv and premium_rate should be preserved
        assert submitted_row[7] == 3.5   # iopv
        assert submitted_row[8] == 0.01  # premium_rate