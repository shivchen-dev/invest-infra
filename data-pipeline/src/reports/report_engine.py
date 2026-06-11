#!/usr/bin/env python3
"""
综合市场汇报引擎
主入口脚本

用法:
    python report_engine.py --type pre_market
    python report_engine.py --type midday
    python report_engine.py --type post_market
    python report_engine.py --type intraday_alert
"""
import sys
import os
import asyncio
import logging
import argparse
from datetime import datetime, date
from typing import Any, Dict

# 添加 src 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from reports.trading_day import is_trading_day, get_trading_phase
from reports.db import get_db
from reports.formatters import format_report
from reports.mcp_client import get_batch_mcp_client
from reports.qq_push import send_to_qq
from reports.market_data_cache import MarketDataCache

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/claw/invest-infra/logs/report_engine.log")
    ]
)
logger = logging.getLogger(__name__)


class ReportEngine:
    """汇报引擎"""

    def __init__(self, report_type: str, trade_date: str = None):
        self.report_type = report_type
        self.trade_date_str = trade_date or date.today().strftime("%Y-%m-%d")
        self.trade_date = datetime.strptime(self.trade_date_str, "%Y-%m-%d").date() if trade_date else date.today()
        self.db = get_db()
        # 保留 _mcp 实例（暂未使用）作为未来扩展：盘中实时报告需 MCP 调用
        self._mcp = get_batch_mcp_client()
        self.data: Dict[str, Any] = {}
    
    async def run(self) -> bool:
        """
        执行报告生成
        
        Returns:
            True 成功，False 失败
        """
        logger.info(f"开始生成报告: {self.report_type}")
        
        # 检查是否为交易日
        if not is_trading_day(self.trade_date):
            logger.info(f"{self.trade_date_str} 非交易日，跳过")
            return True

        try:
            # 1. 获取数据
            self.data = await self._fetch_data()

            # 2. 格式化报告
            messages = format_report(self.report_type, self.data)

            # 3. 保存到数据库
            self.db.save_report(self.report_type, self.trade_date, self.data)
            
            # 4. 推送 QQ
            await self._send_to_qq(messages)
            
            logger.info(f"报告生成成功: {self.report_type}")
            return True
            
        except Exception as e:
            logger.error(f"报告生成失败: {e}", exc_info=True)
            return False
    
    async def _fetch_data(self) -> Dict[str, Any]:
        """获取报告数据"""
        handlers = {
            "pre_market": self._fetch_pre_market,
            "midday": self._fetch_midday,
            "post_market": self._fetch_post_market,
            "intraday_alert": self._fetch_intraday_alert,
        }
        
        handler = handlers.get(self.report_type)
        if handler:
            return await handler()
        
        return {}
    
    async def _fetch_pre_market(self) -> Dict[str, Any]:
        """获取盘前报数据"""
        logger.info("获取盘前报数据...")

        from reports.modules.pre_market import PreMarketReporter
        cache = self._get_cache(self.trade_date)
        reporter = PreMarketReporter(cache=cache)
        data = await reporter.fetch(trade_date=self.trade_date_str)

        return data

    async def _fetch_midday(self) -> Dict[str, Any]:
        """获取午盘报数据"""
        logger.info("获取午盘报数据...")

        from reports.modules.midday import MiddayReporter
        cache = self._get_cache(self.trade_date)
        reporter = MiddayReporter(cache=cache)
        data = await reporter.fetch(trade_date=self.trade_date_str)

        return data

    async def _fetch_post_market(self) -> Dict[str, Any]:
        """获取盘后报数据"""
        logger.info("获取盘后报数据...")

        from reports.modules.post_market import PostMarketReporter
        cache = self._get_cache(self.trade_date)
        reporter = PostMarketReporter(cache=cache)
        data = await reporter.fetch(trade_date=self.trade_date_str)

        return data

    def _get_cache(self, trade_date: str) -> MarketDataCache:
        """获取指定日期的市场数据缓存"""
        return MarketDataCache(trade_date)

    async def _fetch_intraday_alert(self) -> Dict[str, Any]:
        """获取盘中异动数据（实时，不走缓存）"""
        logger.info("获取盘中异动数据...")

        from reports.modules.intraday_alert import IntradayAlertReporter
        reporter = IntradayAlertReporter(self._mcp)
        data = await reporter.fetch(trade_date=self.trade_date_str)

        return data
    
    async def _send_to_qq(self, messages: list):
        """Push report messages to QQ channel via QQ Open Platform API."""
        logger.info(f"[report_engine] QQ push: {len(messages)} message(s)")

        try:
            results = await send_to_qq(messages, target="c2c:43C77867478A33B101FA705AA70754E3")
            success_count = sum(1 for r in results if "error" not in r)
            logger.info(f"[report_engine] QQ push done: {success_count}/{len(messages)} succeeded")
        except Exception as e:
            logger.error(f"[report_engine] QQ push failed: {e}")
            # Do not re-raise — QQ failure should not block report save


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="综合市场汇报引擎")
    parser.add_argument("--type", "-t", required=True,
                       choices=["pre_market", "midday", "post_market", "intraday_alert"],
                       help="报告类型")
    parser.add_argument("--date", "-d", help="指定交易日期 YYYY-MM-DD，默认今日")

    args = parser.parse_args()
    
    engine = ReportEngine(args.type, trade_date=args.date)
    success = await engine.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())