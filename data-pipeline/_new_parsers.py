 # ── fetch_memo 辅助函数（Markdown 解析）──────────────────────────────
    # WOA body_md 格式：Markdown 表格（| 列 | 列 | 列 |）
    # 解析逻辑：按行匹配 Markdown 表格 → 提取结构化字段

    @staticmethod
    def _parse_table_rows(md_text: str) -> list:
        """解析 body_md 中的标准 Markdown 表格，返回每行字段列表"""
        if not md_text:
            return []
        rows = re.findall(r'^\|\s*(.+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$', md_text, re.MULTILINE)
        return rows

    @staticmethod
    def _parse_hs300_from_md(md_text: str) -> dict:
        result = {"point": "-", "change_pct": "-"}
        if not md_text:
            return result
        rows = PreMarketReporter._parse_table_rows(md_text)
        for row in rows:
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            key = cols[0]
            val = cols[1]
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
        rows = PreMarketReporter._parse_table_rows(md_text)
        factor_names = {"动量", "价值", "质量", "资金流", "技术面"}
        for row in rows:
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            name = cols[0]
            status = cols[1]
            if not name or name in ("因子类型", ""):
                continue
            if not any(fn in name for fn in factor_names):
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
        rows = PreMarketReporter._parse_table_rows(md_text)
        has_data = False
        for row in rows:
            cols = [c.strip() for c in row]
            if len(cols) < 2:
                continue
            key = cols[0]
            val = cols[1]
            if "北向资金" in key or "风险信号" in key:
                if val and val not in ("无数据", "-"):
                    has_data = True
        risks["risk_level"] = "中等" if has_data else "无法评估"
        return risks

    @staticmethod
    def _parse_woa_summary_from_body(body_md: str, summary: str, default_conf: str = "") -> dict:
        tasks = []
        conf_map = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
        if body_md:
            rows = PreMarketReporter._parse_table_rows(body_md)
            for row in rows:
                cols = [c.strip() for c in row]
                if len(cols) < 3:
                    continue
                task_name = cols[0]
                status = cols[1]
                conf = cols[2] if len(cols) > 2 else ""
                if not task_name or task_name in ("任务", ""):
                    continue
                emoji = "✅" if "✅" in status or "部分完成" in status else "❌"
                status_text = "部分完成" if "部分" in status else ("数据缺失" if "❌" in status else status)
                cn_conf = conf_map.get(conf.upper(), conf or "低")
                tasks.append({"task": task_name, "status": f"{emoji} {status_text}", "confidence": cn_conf})
        overall_conf = default_conf or "LOW"
        m = re.search(r'整体置信度[：:]?\s*([A-Za-z]+)', summary)
        if m:
            overall_conf = m.group(1).strip()
        risk_level = "无法评估"
        attention = "待数据更新后重新评估"
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
        scenarios = []
        if not md_text:
            return scenarios
        m = re.search(r'整体置信度[：:]?\s*([A-Za-z]+)', md_text)
        conf = m.group(1).strip().upper() if m else "LOW"
        prob_map = {
            "HIGH": {"乐观": "35%", "中性": "40%", "悲观": "25%"},
            "MEDIUM": {"乐观": "30%", "中性": "45%", "悲观": "25%"},
            "LOW": {"乐观": "25%", "中性": "40%", "悲观": "35%"},
        }
        base = prob_map.get(conf, prob_map["LOW"])
        if "无法判断" in md_text or "数据缺失" in md_text:
            scenarios = [
                {"scenario": "中性", "probability": base["中性"], "condition": "数据不完整，维持观察", "expectation": "等待市场数据更新"},
                {"scenario": "乐观", "probability": base["乐观"], "condition": "若数据全面转好，情绪修复", "expectation": "风险资产反弹"},
                {"scenario": "悲观", "probability": base["悲观"], "condition": "若数据持续缺失，谨慎情绪蔓延", "expectation": "防御性配置"},
            ]
        return scenarios

    @staticmethod
    def _parse_etf_signals_from_md(md_text: str, default_conf: str = "") -> list:
        etf_signals = []
        if not md_text:
            return etf_signals
        rows = PreMarketReporter._parse_table_rows(md_text)
        for row in rows:
            cols = [c.strip() for c in row]
            if len(cols) < 3:
                continue
            name = cols[0]
            status = cols[1]
            if not name or name in ("信号类型", ""):
                continue
            has_data = status not in ("无数据", "-", "")
            etf_signals.append({
                "name": name,
                "signal": "有效信号" if has_data else "数据缺失",
                "composite_score": "-",
                "confidence": default_conf or ("MEDIUM" if has_data else "LOW"),
            })
        return etf_signals

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

