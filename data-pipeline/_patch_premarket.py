#!/usr/bin/env python3
"""Patch pre_market.py with new parsers and fetch_memo"""
import re, ast

with open('src/reports/modules/pre_market.py', 'r', encoding='utf-8') as f:
    content = f.read()

print(f"Original size: {len(content)}")

# ── Step 0 call in fetch() ────────────────────────────────────────────────
step0_call = '''
        # ── Step 0: WOA memo 数据（主数据源）─────────────────────────────
        memo_data = self.fetch_memo(trade_date_str)
        if memo_data:
            logger.info(f"盘前报：fetch_memo 成功，获取到 {len(memo_data)} 个 memo 板块")

'''

# ── fetch_memo() method ────────────────────────────────────────────────────
fetch_memo_method = '''
    def fetch_memo(self, trade_date: str) -> dict:
        """从 PG investment_memos 读取 WOA 生成的结构化数据（Markdown 解析）"""
        try:
            from loader.pg import get_conn
        except Exception as e:
            logger.warning(f"fetch_memo: 无法导入 loader.pg: {e}")
            return {}

        MEMO_TYPES = ["morning_collect", "factor_calculation", "etf_alpha_signal",
                      "risk_monitoring", "daily_report"]

        memo_map = {}
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT memo_type, summary, body_md, confidence_level, memo_date
                    FROM investment_memos
                    WHERE company_id = 5233
                      AND memo_date = %s
                      AND memo_type = ANY(%s)
                    ORDER BY memo_type
                """, (trade_date, MEMO_TYPES))
                for r in cur.fetchall():
                    memo_map[r[0]] = {
                        "summary": r[1] if r[1] else "",
                        "body_md": r[2] if r[2] else "",
                        "confidence": r[3] if r[3] else "",
                        "memo_date": r[4] if r[4] else "",
                    }
        except Exception as e:
            logger.warning(f"fetch_memo: 查询失败: {e}")
            return {}

        mc = memo_map.get("morning_collect", {})
        hs300 = self._parse_hs300_from_md(mc.get("body_md", ""))
        sentiment = self._parse_sentiment_from_md(mc.get("body_md", ""))
        market_overview = {"hs300": hs300, "sentiment": sentiment, "date": str(mc.get("memo_date", ""))}

        fc = memo_map.get("factor_calculation", {})
        factors = self._parse_factor_table_from_md(fc.get("body_md", ""), fc.get("confidence", ""))

        rm = memo_map.get("risk_monitoring", {})
        risks = self._parse_risk_from_md(rm.get("body_md", ""))

        dr = memo_map.get("daily_report", {})
        woa_summary = self._parse_woa_summary_from_body(dr.get("body_md", ""), dr.get("summary", ""), dr.get("confidence", ""))
        scenarios = self._parse_scenarios_from_md(dr.get("body_md", ""))
        etf_signals = self._parse_etf_signals_from_md(dr.get("body_md", ""), dr.get("confidence", ""))
        today_attention = self._parse_today_attention_from_md(dr.get("body_md", ""))

        return {
            "woa_summary": woa_summary,
            "market_overview": market_overview,
            "factors": factors,
            "etf_signals": etf_signals,
            "risks": risks,
            "scenarios": scenarios,
            "today_attention": today_attention,
        }

'''

# ── Parser methods ────────────────────────────────────────────────────────
parser_methods = '''
    # ── fetch_memo 辅助函数（Markdown 解析）──────────────────────────────

    @staticmethod
    def _parse_table_rows(md_text: str) -> list:
        if not md_text:
            return []
        return re.findall(r'^\|\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$', md_text, re.MULTILINE)

    @staticmethod
    def _parse_hs300_from_md(md_text: str) -> dict:
        result = {"point": "-", "change_pct": "-"}
        if not md_text:
            return result
        for row in PreMarketReporter._parse_table_rows(md_text):
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            key, val = cols[0], cols[1]
            if "收盘点位" in key or "点位" in key:
                m = re.search(r'([\d.]+)', val)
                if m:
                    result["point"] = m.group(1)
            elif "涨跌幅" in key or "涨跌" in key:
                if val and val not in ("无数据", "-", ""):
                    m = re.search(r'([-+]?[\d.]+)', val)
                    if m:
                        result["change_pct"] = m.group(1)
        return result

    @staticmethod
    def _parse_sentiment_from_md(md_text: str) -> str:
        if not md_text:
            return "-"
        m = re.search(r'情绪[：:]?\s*([^\n，,。]+)', md_text)
        return m.group(1).strip() if m else "-"

    @staticmethod
    def _parse_factor_table_from_md(md_text: str, default_conf: str = "") -> list:
        factors = []
        if not md_text:
            return factors
        factor_names = {"动量", "价值", "质量", "资金流", "技术面"}
        for row in PreMarketReporter._parse_table_rows(md_text):
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            name, status = cols[0], cols[1]
            if not name or name in ("因子类型", "") or not any(fn in name for fn in factor_names):
                continue
            has_data = status not in ("无数据", "-", "")
            factors.append({
                "name": name,
                "signal": "有效信号" if has_data else "数据缺失",
                "confidence": default_conf or ("MEDIUM" if has_data else "LOW"),
                "data_status": status,
            })
        return factors

    @staticmethod
    def _parse_risk_from_md(md_text: str) -> dict:
        risks = {"risk_level": "无法评估", "volatility": "-", "vix": "-", "geo_risk_star": "-"}
        if not md_text:
            return risks
        for row in PreMarketReporter._parse_table_rows(md_text):
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            key, val = cols[0], cols[1]
            if "北向资金" in key or "风险信号" in key:
                if val and val not in ("无数据", "-"):
                    risks["risk_level"] = "中等"
        return risks

    @staticmethod
    def _parse_woa_summary_from_body(body_md: str, summary: str, default_conf: str = "") -> dict:
        tasks = []
        conf_map = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
        if body_md:
            for row in PreMarketReporter._parse_table_rows(body_md):
                cols = [c.strip() for c in row]
                if len(cols) < 3:
                    continue
                task_name, status, conf = cols[0], cols[1], cols[2]
                if not task_name or task_name in ("任务", ""):
                    continue
                emoji = "✅" if "✅" in status or "部分完成" in status else "❌"
                status_text = "部分完成" if "部分" in status else ("数据缺失" if "❌" in status else status)
                tasks.append({"task": task_name, "status": f"{emoji} {status_text}", "confidence": conf_map.get(conf.upper(), conf or "低")})
        overall_conf = default_conf or "LOW"
        m = re.search(r'整体置信度[：:]?\s*([A-Za-z]+)', summary)
        if m:
            overall_conf = m.group(1).strip()
        risk_level, attention = "无法评估", "待数据更新后重新评估"
        m = re.search(r'风险等级[：:]?\s*([^\n,。]+)', summary)
        if m:
            risk_level = m.group(1).strip()
        m = re.search(r'建议关注[：:]?\s*([^\n,。]+)', summary)
        if m:
            attention = m.group(1).strip()
        return {
            "tasks": tasks,
            "overall_confidence": conf_map.get(overall_conf.upper(), overall_conf),
            "risk_level": risk_level,
            "attention": attention,
        }

    @staticmethod
    def _parse_scenarios_from_md(md_text: str) -> list:
        if not md_text:
            return []
        m = re.search(r'整体置信度[：:]?\s*([A-Za-z]+)', md_text)
        conf = m.group(1).strip().upper() if m else "LOW"
        prob_map = {
            "HIGH": {"乐观": "35%", "中性": "40%", "悲观": "25%"},
            "MEDIUM": {"乐观": "30%", "中性": "45%", "悲观": "25%"},
            "LOW": {"乐观": "25%", "中性": "40%", "悲观": "35%"},
        }
        base = prob_map.get(conf, prob_map["LOW"])
        if "无法判断" in md_text or "数据缺失" in md_text:
            return [
                {"scenario": "中性", "probability": base["中性"], "condition": "数据不完整，维持观察", "expectation": "等待市场数据更新"},
                {"scenario": "乐观", "probability": base["乐观"], "condition": "若数据全面转好，情绪修复", "expectation": "风险资产反弹"},
                {"scenario": "悲观", "probability": base["悲观"], "condition": "若数据持续缺失，谨慎情绪蔓延", "expectation": "防御性配置"},
            ]
        return []

    @staticmethod
    def _parse_etf_signals_from_md(md_text: str, default_conf: str = "") -> list:
        signals = []
        if not md_text:
            return signals
        for row in PreMarketReporter._parse_table_rows(md_text):
            cols = [c.strip() for c in row]
            if len(cols) < 3:
                continue
            name, status = cols[0], cols[1]
            if not name or name in ("信号类型", ""):
                continue
            has_data = status not in ("无数据", "-", "")
            signals.append({
                "name": name,
                "signal": "有效信号" if has_data else "数据缺失",
                "composite_score": "-",
                "confidence": default_conf or ("MEDIUM" if has_data else "LOW"),
            })
        return signals

    @staticmethod
    def _parse_today_attention_from_md(md_text: str) -> list:
        attention = []
        if not md_text:
            return attention
        m = re.search(r'### 今日关注\s*\n(.*?)(?=^### |\Z)', md_text, re.DOTALL | re.MULTILINE)
        section = m.group(1) if m else md_text
        for i, n in enumerate(re.finditer(r'\d+\.\s*([^\n]+)', section), 1):
            title = n.group(1).strip()
            if title and len(title) > 3:
                attention.append({"priority": i, "title": title, "source": "daily_report"})
        return attention

'''

# Find insertion points
marker_cache = '        cache = self.cache or MarketDataCache(trade_date_str)'
marker_old_woa = '    # ── 旧版 WOA 数据直接查询 ────────────────────────────────────────────────'
marker_parse_news = '    def _parse_news_time(self, raw: str) -> str:'

pos_cache = content.find(marker_cache)
pos_old_woa = content.find(marker_old_woa)
pos_parse_news = content.find(marker_parse_news)

print(f"pos_cache={pos_cache}, pos_old_woa={pos_old_woa}, pos_parse_news={pos_parse_news}")

# Insert Step 0
new_content = content[:pos_cache + len(marker_cache)] + step0_call + content[pos_cache + len(marker_cache):]

# Recalculate positions after first insertion
shift1 = len(step0_call)
pos_old_woa_s1 = pos_old_woa + shift1
pos_parse_news_s1 = pos_parse_news + shift1

# Insert fetch_memo
new_content = new_content[:pos_old_woa_s1] + fetch_memo_method + new_content[pos_old_woa_s1:]

# Recalculate after second insertion
shift2 = len(fetch_memo_method)
pos_parse_news_s2 = pos_parse_news_s1 + shift2

# Insert parsers
new_content = new_content[:pos_parse_news_s2] + parser_methods + new_content[pos_parse_news_s2:]

# Verify syntax
with open('src/reports/modules/pre_market.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

with open('src/reports/modules/pre_market.py', 'r', encoding='utf-8') as f:
    ast.parse(f.read())
print("✅ Syntax OK")
print(f"New size: {len(new_content)}")
