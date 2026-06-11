"""
统一报告模板格式化模块
基于 CIA 投研汇报模块模板设计（2026-06-08）定稿

板块结构（盘前报）:
  0. 【WOA工作摘要】任务表格+置信度+风险+建议
  1. 今日预判
  2. 今日市场概况（沪深300+情绪+来源标注）
  3. 今日主线预判（≤2条）
  4. 因子信号（5类标准因子：动量/价值/质量/资金流/技术面，memo优先DB fallback）
  5. ETF信号（Top5）
  6. 盘前异动（集合竞价强势股+弱转强候选）
  7. 宏观/事件面（cls_news快讯，MCP未接入时stub）
  8. 风险提示（等级+VIX+地缘）
  9. 情景假设
  10. 今日关注
  11. 今日操作参考（仅供观察，不构成建议）

板块结构（盘中追踪）:
  1. 当前大盘状态
  2. 今日主线（盘中确认）
  3. 涨停/炸板事件（实时）
  4. 策略方向实时信号
  5. ETF盘中溢价率监控
  6. 风险信号
  7. 异动提醒

板块结构（盘后复盘）:
  1. 今日市场概况
  2. 涨跌停统计
  3. 今日主线复盘
  4. 涨停梯队
  5. 断板与高标杀
  6. 策略方向复盘（五大方向）
  7. ETF套利信号复盘
  8. 风险信号复盘
  9. 今日操作参考（仅供观察，不构成建议）
  10. 今日小结
"""
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 消息长度限制
MAX_MSG_LENGTH = 4000

# ── Stub 标记 ────────────────────────────────────────────────────────────────
STUB = "🔲 数据待接入"
STUB_HINT = "（stub，暂无数据源）"


class ReportFormatter:
    """报告格式化器"""

    def __init__(self):
        self.sections = []

    def add_section(self, title: str, content: str):
        """添加板块"""
        self.sections.append({"title": title, "content": content})

    def render(self, data: Dict[str, Any]) -> str:
        """渲染报告（子类必须覆盖）"""
        raise NotImplementedError("子类需要实现 render")

    def _stub(self, hint: str = "数据待接入") -> str:
        """返回 stub 提示"""
        return f"🔲 {hint} {STUB_HINT}"

    def split_messages(self, content: str, max_len: int = MAX_MSG_LENGTH) -> List[str]:
        """拆分长消息"""
        if len(content) <= max_len:
            return [content]

        messages = []
        lines = content.split("\n")
        current = ""

        for line in lines:
            if len(current) + len(line) + 1 > max_len:
                if current:
                    messages.append(current)
                current = line
            else:
                current += "\n" + line

        if current:
            messages.append(current)

        return messages


# ─────────────────────────────────────────────────────────────────────────────
# 盘前报
# ─────────────────────────────────────────────────────────────────────────────

class PreMarketFormatter(ReportFormatter):
    """
    盘前报格式化器 v3.0
    移动端美化版：emoji图标 + 清晰层级 + 呼吸感布局
    """

    # emoji 映射
    _ICONS = {
        "judgment":   "🎯",
        "market":     "📊",
        "main_line":  "🔥",
        "factor":     "α",
        "etf":        "💡",
        "auction":    "⚡",
        "macro":      "📰",
        "risk":       "⚠️",
        "scenario":   "🔮",
        "attention":  "👉",
        "operation":  "🛡️",
    }

    def render(self, data: Dict[str, Any]) -> str:
        trade_date = data.get("trade_date", date.today().isoformat())
        parts = []

        def add(icon_key: str, title: str, body: str):
            if body:
                parts.append(f"**{self._ICONS.get(icon_key, '•')} {title}**\n{body}")

        # ── Section 1: WOA工作摘要 ──────────────────────────────────────────────
        parts.insert(0, self._format_woa_summary(data.get("woa_summary")))

        # 今日预判
        judgment = data.get("today_judgment", {})
        if judgment:
            direction = judgment.get("market_direction", "-")
            logic     = judgment.get("direction_logic", "-")
            sentiment = judgment.get("market_sentiment", "-")
            body = f"大盘：**{direction}**\n{logic}"
            if sentiment and sentiment != "-":
                body += f"\n情绪：{sentiment}"
            add("judgment", "今日预判", body)

        # 市场概况（沪深300 + 情绪 + 来源标注）
        overview = data.get("market_overview", {})
        if overview:
            hs300 = overview.get("hs300", {})
            point  = hs300.get("point", "-")
            change_raw = hs300.get("change_pct", "-")
            # Fix: ensure +/- sign on numeric change values (from _parse_hs300_from_md)
            if change_raw != "-":
                try:
                    v = float(change_raw)
                    # Guard against point value leaking into change_pct (-50~+100 is reasonable for %)
                    if -50 <= v <= 100:
                        change = f"{v:+.2f}"
                    else:
                        change = change_raw
                except ValueError:
                    change = change_raw
            else:
                change = change_raw
            sentiment = overview.get("sentiment", "-") or "-"
            date_str = overview.get("date", "")
            body = f"沪深300：**{point}**（{change}%）"
            if sentiment != "-":
                body += f"\n市场情绪：{sentiment}"
            # Source annotation per task_plan.md v3.0 spec
            _date = date_str if date_str else "-"
            body += f"\n【来源：investment_memos.morning_collect.hs300，数据 {_date}】"
            add("market", "今日市场概况", body)

        # 主线预判
        main_lines = data.get("main_lines", [])
        if main_lines:
            lines = []
            for i, m in enumerate(main_lines[:2], 1):
                板块 = m.get("板块", "-")
                逻辑 = m.get("逻辑", "-")
                lines.append(f"{i}. **{板块}**：{逻辑}")
            add("main_line", "今日主线", "\n".join(lines))

        # 因子信号（来自 fetch_memo factors，fallback 到 DB strategy_signals）
        parts.append(self._format_factors(data.get("factors"), data.get("strategy_signals")))

        # ETF信号
        etf_signals = data.get("woa_etf_signals") or data.get("etf_signals", [])
        if etf_signals:
            lines = []
            for s in etf_signals[:5]:
                name   = s.get("name", "-")[:16]
                signal = s.get("signal", "-")
                score  = s.get("composite_score", "-")
                conf   = self._cn_conf(s.get("confidence", ""))
                lines.append(f"• **{name}**：{signal}（评分{score}，{conf}）")
            add("etf", "ETF信号", "\n".join(lines))

        # ── Section 6: 盘前异动（集合竞价强势股 + 弱转强候选）───────────────────
        parts.append(self._format_auction(data.get("auction_scan"), data.get("auction_wts"), data.get("auction")))

        # ── Section 7: 宏观/事件面（cls_news，Medium优先级，stub）───────────────
        parts.append(self._format_macro_events(data.get("macro_events")))


        # 风险提示
        risks = data.get("risks", {})
        if risks:
            level = risks.get("risk_level", "-")
            vol   = risks.get("volatility", "-")
            vix   = risks.get("vix", "-")
            geo   = risks.get("geo_risk_star", "-")
            body = f"风险等级：**{level}**"
            if vol and vol != "-":
                body += f"\n波动率：{vol}"
            if vix and vix != "-":
                body += f"\nVIX：{vix}"
            if geo and geo not in ("-", "0"):
                stars = "⭐" * int(geo) if str(geo).isdigit() else geo
                body += f"\n地缘风险：{stars}"
            add("risk", "风险提示", body)
        # 北向资金
        hsgt = data.get("hsgt", {})
        if hsgt and hsgt.get("status") == "available":
            add("hsgt", "北向资金", self._format_hsgt(hsgt))


        # 情景假设
        scenarios = data.get("scenarios", [])
        if scenarios:
            lines = []
            for s in scenarios:
                scenario  = s.get("scenario", "-")
                prob      = s.get("probability", "-")
                cond      = s.get("condition", "-")[:24]
                expect    = s.get("expectation", "-")
                lines.append(f"• **{scenario}**（{prob}）\n  {cond} → {expect}")
            add("scenario", "情景假设", "\n".join(lines))

        # 今日关注
        attention = data.get("today_attention", [])
        if attention:
            lines = []
            for item in sorted(attention, key=lambda x: x.get("priority", 999)):
                title = item.get("title", "-")
                lines.append(f"{item.get('priority', '?')}. {title}")
            add("attention", "今日关注", "\n".join(lines))

        # 操作参考
        op_ref = data.get("operation_ref", {})
        if op_ref:
            主线 = op_ref.get("主线方向", "-")
            弱势 = op_ref.get("弱势方向", "-")
            thresh = op_ref.get("etf_threshold", "宽基>±0.3% / 行业>±0.5%")
            body = ""
            if 主线 and 主线 != "-":
                body += f"主线方向：{主线}\n"
            if 弱势 and 弱势 != "-":
                body += f"弱势方向：{弱势} 回避\n"
            body += f"ETF溢价阈值：{thresh}"
            add("operation", "操作参考", body.strip())

        # 组装
        sep = "\n" + "─" * 20 + "\n"
        header = f"📋 盘前报 {trade_date}"
        footer = "⚠️ 只输出分析结论，不提供投资建议"
        return f"**{header}**\n{sep}{sep.join(parts)}\n{sep}{footer}"

    # ── 格式化辅助方法 ───────────────────────────────────────────────────────

    def _format_woa_summary(self, woa_summary: Optional[Dict[str, Any]]) -> str:
        """渲染 WOA 工作摘要：任务表格 + 置信度 + 风险 + 建议"""
        if not woa_summary:
            return self._stub("WOA 工作摘要")

        lines = []
        tasks = woa_summary.get("tasks", [])
        conf = woa_summary.get("overall_confidence", "-")
        risk = woa_summary.get("risk_level", "-")
        attention = woa_summary.get("attention", "-")

        # 任务表格
        if tasks:
            lines.append("| 任务 | 状态 | 置信度 |")
            lines.append("|------|------|--------|")
            for t in tasks:
                name = t.get("task", "-")[:20]
                status = t.get("status", "-")
                c = t.get("confidence", "-")
                # 按重要性标注：Important（有处理意见/代码位置）必须突出
                if "⚠️" in status or "❌" in status:
                    priority = " ⚠️"
                else:
                    priority = ""
                lines.append(f"| {name}{priority} | {status} | {c} |")

            # 筛选 Important / Medium 任务，附带代码位置线索
            important = [t for t in tasks if "⚠️" in t.get("status", "")]
            medium    = [t for t in tasks if t.get("confidence", "").upper() == "MEDIUM"]
            if important or medium:
                notes = []
                for it in important:
                    notes.append(f"**Important**：{it['task']} → {it.get('status', '')}")
                for mt in medium:
                    notes.append(f"**Medium**：{mt['task']}（置信度中，需关注）")
                lines.append("")
                lines.append("\n".join(notes))
        else:
            lines.append("今日无待执行 WOA 任务")

        # 底部三要素
        summary_parts = []
        if conf and conf != "-":
            summary_parts.append(f"综合置信度：**{conf}**")
        if risk and risk != "-" and not risk.startswith("无法"):
            summary_parts.append(f"风险等级：**{risk}**")
        elif risk and risk.startswith("无法"):
            summary_parts.append("风险等级：无法评估（数据待更新）")
        if attention and attention != "-":
            summary_parts.append(f"建议关注：{attention}")

        lines.append("")
        lines.append(" | ".join(summary_parts))
        return "\n".join(lines)

    def _cn_conf(self, conf: str) -> str:
        """置信度翻译：HIGH→高 / MEDIUM→中 / LOW→低"""
        mapping = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
        return mapping.get(conf.upper(), conf or "-")

    def _format_factors(self, factors: Optional[List[Dict]], strategy_signals: Optional[Dict]) -> str:
        """渲染因子信号表格（5类因子：动量/价值/质量/资金流/技术面）"""
        # 优先使用 memo factors（fetch_memo → _parse_factor_table_from_md），fallback 到 DB strategy_signals
        if not factors and strategy_signals:
            # DB strategy_signals 格式：{phys_ai, optical, pcb, cpo, etf_broad}
            factor_map = [
                ("动量",   "phys_ai"),
                ("价值",   "optical"),
                ("质量",   "pcb"),
                ("资金流", "cpo"),
                ("技术面", "etf_broad"),
            ]
            rows = []
            for name, key in factor_map:
                s = strategy_signals.get(key, {})
                if not s:
                    continue
                signal = s.get("signal", "-")
                data_status = s.get("yesterday", "-") or "-"
                conf = self._cn_conf(s.get("confidence") or "MEDIUM")
                rows.append(f"| {name} | {signal} | {conf} | {data_status[:24]} |")
            if rows:
                lines = ["| 因子 | 信号 | 置信度 | 数据状态 |"]
                lines.append("|------|------|--------|----------|")
                lines.extend(rows)
                lines.append("")
                lines.append("【来源：etf_alpha_signals (DB etf_alpha_signals.composite_score)】")
                return "\n".join(lines)
            return self._stub("因子信号")

        if not factors:
            return self._stub("因子信号")

        # 标准 memo factors 格式：[{"name": "动量", "signal": "...", "confidence": "...", "data_status": "..."}]
        lines = ["| 因子 | 信号 | 置信度 | 数据状态 |"]
        lines.append("|------|------|--------|----------|")

        for f in factors:
            name   = f.get("name", "-")
            signal = f.get("signal", "-")
            conf   = self._cn_conf(f.get("confidence", ""))
            data_status = f.get("data_status", "-")
            lines.append(f"| {name} | {signal} | {conf} | {data_status} |")

        lines.append("")
        lines.append("【来源：investment_memos.daily_report.factors】")
        return "\n".join(lines)

    def _format_auction(self, auction_scan: Optional[List[Dict]], auction_wts: Optional[List[Dict]], legacy_auction: Optional[Dict]) -> str:
        """渲染盘前异动：集合竞价强势股 + 弱转强候选"""

        def _fmt_change(v):
            """将 change 值格式化为 ±0.00%，失败则返回'-'"""
            try:
                num = float(v)
                return f"{num:+.2f}" if -50 <= num <= 100 else "-"
            except (ValueError, TypeError):
                return "-"

        lines = []

        # ── 1. 集合竞价强势股（Top5，按 change 降序）───
        strongest = auction_scan or []
        if not strongest and legacy_auction:
            # 兼容旧版 auction.strongest 格式
            strongest = legacy_auction.get("strongest", [])

        if strongest:
            top_n = min(len(strongest), 5)
            sorted_st = sorted(strongest, key=lambda x: float(x.get("change", 0) or 0), reverse=True)[:top_n]
            lines.append("**集合竞价强势股：**")
            for i, s in enumerate(sorted_st, 1):
                code = s.get("code", "-")
                name = s.get("name", "-")[:16]
                change = _fmt_change(s.get("change"))
                amount = s.get("amount", "")
                if amount:
                    lines.append(f"  {i}. {name}({code}) {change}%（竞价额 {amount} 万）")
                else:
                    lines.append(f"  {i}. {name}({code}) {change}%")
            lines.append("")

        # ── 2. 弱转强候选（Top3）───
        wts = auction_wts or []
        if not wts and legacy_auction:
            wts = legacy_auction.get("weak_to_strong", [])

        if wts:
            top_n = min(len(wts), 3)
            sorted_wts = sorted(wts, key=lambda x: float(x.get("change", 0) or 0), reverse=True)[:top_n]
            lines.append("**弱转强候选：**")
            for i, s in enumerate(sorted_wts, 1):
                code = s.get("code", "-")
                name = s.get("name", "-")[:16]
                change = _fmt_change(s.get("change"))
                lines.append(f"  {i}. {name}({code}) {change}%")
            lines.append("")

        # Source annotation per task_plan.md v3.0 spec
        sources = []
        if auction_scan:
            sources.append("auction_scan(market_data_cache)")
        elif legacy_auction and legacy_auction.get("strongest"):
            sources.append("auction.mcp_market_data")
        if auction_wts:
            sources.append("auction_wts(market_data_cache)")
        elif legacy_auction and legacy_auction.get("weak_to_strong"):
            sources.append("auction.mcp_market_data")

        if lines:
            if sources:
                lines.append(f"【来源：{', '.join(sources)}】")
            return "\n".join(lines)
        else:
            return self._stub("盘前异动")

    def _format_macro_events(self, macro_events: Optional[List[Dict]]) -> str:
        """渲染宏观/事件面：财联社快讯（Medium优先级，cls_news MCP未接入）"""
        return self._stub("宏观/事件面")


    def _link(self, name: str, code: str, url: str = "") -> str:
        """返回 markdown 链接格式"""
        if url:
            return f"[{name}({code})]({url})"
        return f"{name}({code})"

class IntradayFormatter(ReportFormatter):
    """
    盘中追踪格式化器
    模板来源: CIA 投研汇报模块模板设计 v2026-06-08
    """

    def render(self, data: Dict[str, Any]) -> str:
        alert_time = data.get("alert_time", datetime.now().strftime("%H:%M"))
        header = f"【CIA 盘中追踪】 {data.get('trade_date', date.today().isoformat())} {alert_time} 更新\n"

        # 1. 当前大盘状态
        self.add_section("当前大盘状态",
                        self._format_market_state(data.get("market_state", {})))

        # 2. 今日主线（盘中确认）
        self.add_section("今日主线（盘中确认）",
                        self._format_intraday_main_lines(data.get("main_lines", [])))

        # 3. 涨停/炸板事件（实时）
        self.add_section("涨停/炸板事件（实时）",
                        self._format_limit_events(data.get("limit_events", {})))

        # 4. 策略方向实时信号
        self.add_section("策略方向实时信号",
                        self._format_strategy_realtime(data.get("strategy_realtime", {})))

        # 5. ETF盘中溢价率监控
        self.add_section("ETF盘中溢价率监控",
                        self._format_etf_intraday(data.get("etf_intraday", {})))

        # 6. 风险信号
        self.add_section("风险信号",
                        self._format_risk_signals(data.get("risk_signals", {})))

        # 7. 异动提醒
        self.add_section("异动提醒",
                        self._format_alerts(data.get("alerts", [])))

        return header + self._build_body()

    def _format_market_state(self, market_state: Dict[str, Any]) -> str:
        if not market_state:
            return self._stub("大盘状态")
        lines = []
        indices = market_state.get("indices", {})
        if indices:
            for idx, val in indices.items():
                lines.append(f"{idx}：{val}")
        counts = market_state.get("counts", {})
        if counts:
            lines.append(f"涨跌家数：上涨{counts.get('up', '-')} / 下跌{counts.get('down', '-')} / 平盘{counts.get('flat', '-')}")
        sentiment = market_state.get("sentiment", "-")
        lines.append(f"市场情绪：【{sentiment}】")
        return "\n".join(lines) if lines else self._stub("大盘状态")

    def _format_intraday_main_lines(self, main_lines: List[Dict]) -> str:
        if not main_lines:
            return "今日盘中无明确主线，板块轮动快"
        lines = []
        for i, m in enumerate(main_lines[:2], 1):
            sector = m.get("sector", "-")
            signal_strength = m.get("signal_strength", "-")
            leader = m.get("leader", {})
            leader_name = leader.get("name", "-")
            leader_code = leader.get("code", "-")
            leader_url = leader.get("url", "")
            leader_change = leader.get("change", "-")
            link = f"[{leader_name}({leader_code})]({leader_url})" if leader_url else f"{leader_name}({leader_code})"
            扩散至 = m.get("spread_to", "-")
            lines.append(f"主线{i}：{sector} {signal_strength} ⚡")
            lines.append(f"  龙头 {link} {leader_change}")
            if 扩散至:
                lines.append(f"  扩散至：{扩散至}")
        return "\n".join(lines)

    def _format_limit_events(self, limit_events: Dict[str, Any]) -> str:
        lines = []
        limit_ups = limit_events.get("limit_ups", [])
        if limit_ups:
            lines.append("【最新涨停】（最近30分钟）")
            for e in limit_ups[:5]:
                name = e.get("name", "-")
                code = e.get("code", "-")
                url = e.get("url", "")
                time = e.get("time", "-")
                reason = e.get("reason", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  · {link} {time}涨停原因：{reason}")
        else:
            lines.append("【最新涨停】无涨停事件")

        warnings = limit_events.get("break_warnings", [])
        if warnings:
            lines.append("【炸板预警】")
            for w in warnings[:3]:
                name = w.get("name", "-")
                code = w.get("code", "-")
                url = w.get("url", "")
                open_count = w.get("open_count", "-")
                order_amount = w.get("order_amount", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  ⚠️ {link} 开板{open_count}次 封单{order_amount}万风险")
        return "\n".join(lines) if lines else self._stub("涨停炸板事件")

    def _format_strategy_realtime(self, strategy_realtime: Dict[str, Any]) -> str:
        directions = [
            ("物理AI", strategy_realtime.get("phys_ai", {})),
            ("光模块", strategy_realtime.get("optical", {})),
            ("PCB", strategy_realtime.get("pcb", {})),
            ("CPO", strategy_realtime.get("cpo", {})),
            ("宽基ETF", strategy_realtime.get("etf_broad", {})),
        ]
        lines = []
        for label, sig in directions:
            signal = sig.get("signal", "无")
            if label == "宽基ETF":
                etf_premium = sig.get("etf_premium", "-")
                lines.append(f"■ {label:<6} 盘中信号：【{signal}】 沪深300 ETF 溢价率 {etf_premium}%")
            else:
                leader = sig.get("leader", {})
                leader_name = leader.get("name", "-")
                leader_code = leader.get("code", "-")
                leader_url = leader.get("url", "")
                leader_change = leader.get("change", "-")
                link = f"[{leader_name}({leader_code})]({leader_url})" if leader_url else f"{leader_name}({leader_code})"
                lines.append(f"■ {label:<6} 盘中信号：【{signal}】 龙头 {link} {leader_change}")
        return "\n".join(lines) if lines else self._stub("策略方向实时信号")

    def _format_etf_intraday(self, etf_intraday: Dict[str, Any]) -> str:
        alerts = etf_intraday.get("alerts", [])
        if not alerts:
            return "无溢价率异动"
        lines = ["【溢价率异动告警】"]
        for a in alerts:
            name = a.get("name", "-")
            code = a.get("code", "-")
            url = a.get("url", "")
            premium_pct = a.get("premium_pct", 0)
            threshold_type = a.get("threshold_type", "")
            link = f"[{name}({code})]({url})" if url else f"{name}({code})"
            lines.append(f"  ⚠️ {link} 溢价率 {premium_pct:+.2f}% 【超过阈值：{threshold_type}】")
        return "\n".join(lines)


    def _format_hsgt(self, hsgt: Dict[str, Any]) -> str:
        """格式化北向资金数据"""
        if not hsgt or hsgt.get("status") == "unavailable":
            return "数据获取中"
        inflow = hsgt.get("inflow", "-")
        config = hsgt.get("config", "北向资金")
        return f"{config}：{inflow}"

    def _format_risk_signals(self, risk_signals: Dict[str, Any]) -> str:
        lines = []
        limit_down_count = risk_signals.get("limit_down_count", 0)
        limit_down_change = risk_signals.get("limit_down_change", "")
        if limit_down_count is not None:
            lines.append(f"跌停池：{limit_down_count}家")
            if limit_down_change:
                lines.append(f"（较盘中{limit_down_change} ⚠️）")

        high_board_broken = risk_signals.get("high_board_broken", [])
        if high_board_broken:
            lines.append("高标杀：【有】")
            for item in high_board_broken:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                streak = item.get("streak", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  ⚠️ {link} {streak}连板断板")
        else:
            lines.append("高标杀：【无】")

        break_rate = risk_signals.get("break_rate", None)
        if break_rate is not None:
            if break_rate > 20:
                lines.append(f"炸板率：{break_rate}% > 20% 情绪退潮⚠️")
            else:
                lines.append(f"炸板率：{break_rate}%")

        return "\n".join(lines) if lines else self._stub("风险信号")

    def _format_alerts(self, alerts: List[Dict[str, Any]]) -> str:
        if not alerts:
            return "无异动"
        lines = []
        for a in alerts[:5]:
            desc = a.get("description", "-")
            direction = a.get("direction", "-")
            lines.append(f"· {desc} → 观察是否形成主线{direction}")
        return "\n".join(lines)

    def _build_body(self) -> str:
        body = ""
        for section in self.sections:
            content = section["content"]
            if not content or content.startswith("🔲"):
                continue
            body += f"\n■ {section['title']}\n"
            body += f"{'━' * 30}\n"
            body += f"{content}\n"
        return body


# ─────────────────────────────────────────────────────────────────────────────
# 盘后复盘
# ─────────────────────────────────────────────────────────────────────────────

class PostMarketFormatter(ReportFormatter):
    """
    盘后复盘格式化器
    模板来源: CIA 投研汇报模块模板设计 v2026-06-08
    """

    def render(self, data: Dict[str, Any]) -> str:
        trade_date = data.get("trade_date", date.today().isoformat())
        header = f"【CIA 盘后复盘】 {trade_date} 交易日\n"

        # 1. 今日市场概况
        self.add_section("今日市场概况【共用】",
                        self._format_summary(data.get("summary", {})))

        # 2. 涨跌停统计
        self.add_section("涨跌停统计",
                        self._format_limit_stats(data.get("limit_stats", {})))

        # 3. 今日主线复盘
        self.add_section("今日主线复盘",
                        self._format_main_review(data.get("main_review", [])))

        # 4. 涨停梯队
        self.add_section("涨停梯队",
                        self._format_ladder(data.get("ladder", [])))

        # 5. 断板与高标杀
        self.add_section("断板与高标杀",
                        self._format_board_break(data.get("board_break", {})))

        # 6. 策略方向复盘（五大方向）
        self.add_section("策略方向复盘（五大方向）",
                        self._format_strategy_review(data.get("strategy_review", {})))

        # 7. ETF套利信号复盘
        self.add_section("ETF套利信号复盘",
                        self._format_etf_arbitrage(data.get("etf_arbitrage", {})))

        # 8. 风险信号复盘
        self.add_section("风险信号复盘",
                        self._format_risk_review(data.get("risk_review", {})))

        # 9. 今日操作参考（仅供观察，不构成建议）
        self.add_section("今日操作参考（仅供观察，不构成建议）",
                        self._format_operation_ref(data.get("operation_ref", {})))

        # 10. 今日小结
        self.add_section("今日小结",
                        self._format_day_summary(data.get("day_summary", "")))

        return header + self._build_body()

    def _format_summary(self, summary: Dict[str, Any]) -> str:
        if not summary:
            return self._stub("今日市场概况")
        lines = []
        indices = summary.get("indices", {})
        if indices:
            for idx, val in indices.items():
                lines.append(f"{idx}：{val}")
        amount = summary.get("amount", "-")
        amount_change = summary.get("amount_change", "")
        if amount:
            lines.append(f"成交额：{amount}亿")
            if amount_change:
                lines.append(f"（较昨日 {amount_change}）")
        counts = summary.get("counts", {})
        if counts:
            lines.append(f"涨跌家数：上涨{counts.get('up', '-')} / 下跌{counts.get('down', '-')} / 平盘{counts.get('flat', '-')}")
        sentiment = summary.get("sentiment", "-")
        tomorrow_expect = summary.get("tomorrow_expect", "-")
        lines.append(f"市场情绪：【{sentiment}】 → 明日预期：{tomorrow_expect}")
        return "\n".join(lines)

    def _format_limit_stats(self, limit_stats: Dict[str, Any]) -> str:
        if not limit_stats:
            return self._stub("涨跌停统计")
        lines = []
        limit_up = limit_stats.get("limit_up", "-")
        limit_up_yesterday = limit_stats.get("limit_up_yesterday", "-")
        seal_rate = limit_stats.get("seal_rate", "-")
        break_rate = limit_stats.get("break_rate", "-")
        limit_down = limit_stats.get("limit_down", "-")
        limit_down_yesterday = limit_stats.get("limit_down_yesterday", "-")
        broken = limit_stats.get("broken", "-")
        续板 = limit_stats.get("continued", "-")
        first_board = limit_stats.get("first_board", "-")
        second_board = limit_stats.get("second_board", "-")
        third_plus = limit_stats.get("third_plus", "-")

        lines.append(f"涨停：{limit_up}家（昨日{limit_up_yesterday}） 封板率：{seal_rate}% 炸板率：{break_rate}%")
        lines.append(f"跌停：{limit_down}家（昨日{limit_down_yesterday}） 断板：{broken}家 续板：{续板}家")
        lines.append(f"首板：{first_board}家 2连板：{second_board}家 3连板+：{third_plus}家")
        return "\n".join(lines)

    def _format_main_review(self, main_review: List[Dict]) -> str:
        if not main_review:
            return "今日市场无清晰主线，赚钱效应 中"
        lines = []
        for i, m in enumerate(main_review[:2], 1):
            sector = m.get("sector", "-")
            performance = m.get("performance", "-")
            leaders = m.get("leaders", [])
            signal_strength = m.get("signal_strength", "-")
            tomorrow = m.get("tomorrow", "观察")
            lines.append(f"主线{i}：{sector}")
            lines.append(f"  今日表现：{performance}")
            if leaders:
                leader_strs = []
                for l in leaders:
                    name = l.get("name", "-")
                    code = l.get("code", "-")
                    url = l.get("url", "")
                    result = l.get("result", "-")
                    link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                    leader_strs.append(f"{link} {result}")
                lines.append(f"  龙头：{', '.join(leader_strs)}")
            lines.append(f"  信号强度：【{signal_strength}】")
            lines.append(f"  明日预期：{tomorrow}")
        return "\n".join(lines)

    def _format_ladder(self, ladder: List[Dict]) -> str:
        if not ladder:
            return self._stub("涨停梯队")
        lines = []
        high_board = [l for l in ladder if l.get("streak", 0) >= 3]
        second_board = [l for l in ladder if l.get("streak", 0) == 2]
        first_board = [l for l in ladder if l.get("streak", 0) == 1]

        if high_board:
            lines.append("【3连板+高标】")
            for item in high_board[:3]:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                streak = item.get("streak", "-")
                reason = item.get("reason", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  {link} {streak}连板 涨停原因：{reason}")

        if second_board:
            lines.append("【2连板】")
            for item in second_board[:5]:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                reason = item.get("reason", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  {link} {reason}")

        if first_board:
            lines.append("【首板】")
            for item in first_board[:5]:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                reason = item.get("reason", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  {link} {reason} 关注：{reason}")

        return "\n".join(lines) if lines else self._stub("涨停梯队")

    def _format_board_break(self, board_break: Dict[str, Any]) -> str:
        lines = []
        broken = board_break.get("broken", [])
        if broken:
            lines.append("【断板】（昨涨停今断板）")
            for item in broken:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                open_pct = item.get("open_pct", "-")
                status = item.get("status", "")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  {link} 昨涨停今低开 {open_pct}% → {status}")
        high_board_broken = board_break.get("high_board_broken", [])
        if high_board_broken:
            lines.append("【高标杀】")
            for item in high_board_broken:
                name = item.get("name", "-")
                code = item.get("code", "-")
                url = item.get("url", "")
                streak = item.get("streak", "-")
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                lines.append(f"  ⚠️ {link} {streak}连板断板 → 注意情绪退潮信号")
        return "\n".join(lines) if lines else "无断板异常"

    def _format_strategy_review(self, strategy_review: Dict[str, Any]) -> str:
        directions = [
            ("物理AI", strategy_review.get("phys_ai", {})),
            ("光模块", strategy_review.get("optical", {})),
            ("PCB", strategy_review.get("pcb", {})),
            ("CPO", strategy_review.get("cpo", {})),
            ("宽基ETF", strategy_review.get("etf_broad", {})),
        ]
        lines = []
        for label, direction in directions:
            signal = direction.get("signal", "无")
            performance = direction.get("performance", "")
            core_data = direction.get("core_data", {})
            tomorrow = direction.get("tomorrow", "观察")
            lines.append(f"■ {label}")
            lines.append(f"  今日信号：【{signal}】")
            lines.append(f"  板块表现：{performance}")
            lines.append(f"  核心数据：")

            if label == "物理AI":
                optical = core_data.get("optical", {})
                if optical:
                    name = optical.get("name", "-")
                    code = optical.get("code", "-")
                    url = optical.get("url", "")
                    change = optical.get("change", "-")
                    premium = optical.get("premium_pct", "X")
                    link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                    lines.append(f"    - 光模块：{link} 收盘{change}，溢价率{premium}%")
                pcb = core_data.get("pcb", {})
                if pcb:
                    pcb_change = pcb.get("change", "-")
                    lines.append(f"    - PCB：板块整体{pcb_change}")
                cpo = core_data.get("cpo", {})
                if cpo:
                    name = cpo.get("name", "-")
                    code = cpo.get("code", "-")
                    url = cpo.get("url", "")
                    desc = cpo.get("desc", "")
                    link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                    lines.append(f"    - CPO：{link} {desc}")
            elif label == "光模块":
                for key in ["optical"]:
                    val = core_data.get(key, {})
                    if val:
                        name = val.get("name", "-")
                        code = val.get("code", "-")
                        url = val.get("url", "")
                        change = val.get("change", "-")
                        link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                        lines.append(f"    - {key}：{link} 收盘{change}")
            elif label == "宽基ETF":
                val = core_data.get("etf_broad", {})
                if val:
                    name = val.get("name", "-")
                    code = val.get("code", "-")
                    url = val.get("url", "")
                    premium = val.get("premium_pct", "-")
                    link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                    lines.append(f"    - 宽基ETF：{link} 溢价率{premium}%")
                else:
                    lines.append("    -")
            else:
                lines.append("    -")
            lines.append(f"  明日信号预判：{tomorrow}")

        return "\n".join(lines) if lines else self._stub("策略方向复盘")

    def _format_etf_arbitrage(self, etf_arbitrage: Dict[str, Any]) -> str:
        lines = []
        summary = etf_arbitrage.get("summary", {})
        if summary:
            lines.append("【今日溢价率异动】")
            broad = summary.get("broad", {})
            industry = summary.get("industry", {})
            qdii = summary.get("qdii", {})
            lines.append(f"  宽基 ETF：异动 {broad.get('count', 0)} 只，阈值触发 {broad.get('triggers', 0)} 次")
            lines.append(f"  行业 ETF：异动 {industry.get('count', 0)} 只，阈值触发 {industry.get('triggers', 0)} 次")
            lines.append(f"  QDII ETF：异动 {qdii.get('count', 0)} 只，阈值触发 {qdii.get('triggers', 0)} 次")

        signals = etf_arbitrage.get("signals", [])
        if signals:
            lines.append("\n【套利信号】")
            for sig in signals:
                sig_type = sig.get("type", "")
                name = sig.get("name", "-")
                code = sig.get("code", "-")
                url = sig.get("url", "")
                premium_pct = sig.get("premium_pct", 0)
                link = f"[{name}({code})]({url})" if url else f"{name}({code})"
                if sig_type == "溢价":
                    lines.append(f"  溢价卖出信号：{link} 溢价率 {premium_pct:+.2f}% ⚠️")
                elif sig_type == "折价":
                    lines.append(f"  折价买入信号：{link} 折价率 {premium_pct:+.2f}% ⚠️")

        return "\n".join(lines) if lines else self._stub("ETF套利信号")

    def _format_risk_review(self, risk_review: Dict[str, Any]) -> str:
        lines = []
        limit_down = risk_review.get("limit_down", {})
        if limit_down:
            count = limit_down.get("count", "-")
            change = limit_down.get("change", "")
            desc = limit_down.get("desc", "")
            lines.append(f"跌停池：{count}家 {change} {desc}")
        high_board_broken = risk_review.get("high_board_broken")
        if high_board_broken:
            name = high_board_broken.get("name", "-")
            code = high_board_broken.get("code", "-")
            streak = high_board_broken.get("streak", "-")
            lines.append(f"高标杀：【有】{streak}连板断板 {name}({code})")
        else:
            lines.append("高标杀：【无】")
        break_rate = risk_review.get("break_rate", None)
        if break_rate is not None:
            flag = " ⚠️" if break_rate > 20 else ""
            lines.append(f"情绪退潮：炸板率 {break_rate}%{' > 20% 情绪退潮⚠️' if break_rate > 20 else ''}")
        st = risk_review.get("st", {})
        if st and st.get("has", False):
            lines.append(f"ST/退市异动：【有】{st.get('desc', '')}")
        else:
            lines.append("ST/退市异动：【无】")
        return "\n".join(lines) if lines else self._stub("风险信号复盘")

    def _format_operation_ref(self, op_ref: Dict[str, Any]) -> str:
        if not op_ref:
            return self._stub("今日操作参考")
        lines = ["重点观察："]
        主线方向 = op_ref.get("主线方向", "-")
        切换风险 = op_ref.get("切换风险", "-")
        etf_threshold = op_ref.get("etf_threshold", "宽基 >±0.3% / 行业 >±0.5% / QDII >±1.5%")
        断板高标 = op_ref.get("断板高标", "-")
        if 主线方向:
            lines.append(f"  · 主线方向：{主线方向} 明日开盘情绪是否能延续")
        if 切换风险:
            lines.append(f"  · 切换风险：{切换风险} 明日可能轮动")
        lines.append(f"  · ETF 溢价率：{etf_threshold} 注意")
        if 断板高标:
            lines.append(f"  · 断板高标：{断板高标} 明日是否低开或直接退潮")
        return "\n".join(lines)

    def _format_day_summary(self, day_summary: str) -> str:
        if not day_summary:
            return self._stub("今日小结")
        return day_summary

    def _build_body(self) -> str:
        body = ""
        for section in self.sections:
            content = section["content"]
            if not content or content.startswith("🔲"):
                continue
            body += f"\n■ {section['title']}\n"
            body += f"{'━' * 30}\n"
            body += f"{content}\n"
        return body


# ─────────────────────────────────────────────────────────────────────────────
# 盘中异动（旧版兼容）
# ─────────────────────────────────────────────────────────────────────────────

class IntradayAlertFormatter(ReportFormatter):
    """盘中异动格式化器（兼容旧版）"""

    def render(self, data: Dict[str, Any]) -> str:
        alert_time = data.get("alert_time", datetime.now().strftime("%H:%M"))
        header = f"⚡ 盘中异动 [{alert_time}]\n"

        self.add_section("涨停监控", self._format_limit_up(data.get("limit_up", {})))
        self.add_section("跌停监控", self._format_limit_down(data.get("limit_down", {})))
        self.add_section("异常波动", self._format_anomaly(data.get("anomaly", {})))

        return header + self._build_report()

    def _format_limit_up(self, limit_up: Dict[str, Any]) -> str:
        events = limit_up.get("events", [])
        if not events:
            return "无涨停事件"
        lines = []
        for e in events[:5]:
            time = e.get("time", "-")
            name = e.get("name", "-")
            code = e.get("code", "-")
            lines.append(f"• {time} {name}({code})")
        return "\n".join(lines)

    def _format_limit_down(self, limit_down: Dict[str, Any]) -> str:
        stocks = limit_down.get("stocks", [])
        if not stocks:
            return "无跌停股"
        lines = []
        for s in stocks[:5]:
            lines.append(f"• {s.get('name', '-')}({s.get('code', '-')})")
        return "\n".join(lines)

    def _format_anomaly(self, anomaly: Dict[str, Any]) -> str:
        events = anomaly.get("events", [])
        if not events:
            return "无异常波动"
        lines = []
        for e in events[:3]:
            name = e.get("name", "-")
            code = e.get("code", "-")
            change = e.get("change", "-")
            lines.append(f"• {name}({code}): {change}")
        return "\n".join(lines)

    def _build_report(self) -> str:
        body = ""
        for section in self.sections:
            body += f"\n【{section['title']}】\n"
            body += section["content"]
        return body


# ─────────────────────────────────────────────────────────────────────────────
# 公共入口
# ─────────────────────────────────────────────────────────────────────────────

def get_formatter(report_type: str) -> ReportFormatter:
    """
    获取对应报告类型的格式化器

    Args:
        report_type: pre_market / midday / post_market / intraday_alert / intraday

    Returns:
        格式化器实例
    """
    formatters = {
        "pre_market": PreMarketFormatter,
        "midday": IntradayFormatter,   # 午盘复用盘中模板
        "post_market": PostMarketFormatter,
        "intraday_alert": IntradayAlertFormatter,
        "intraday": IntradayFormatter,  # 盘中追踪
    }

    formatter_class = formatters.get(report_type)
    if not formatter_class:
        raise ValueError(f"未知报告类型: {report_type}")

    return formatter_class()


def format_report(report_type: str, data: Dict[str, Any]) -> List[str]:
    """
    格式化报告（返回拆分后的消息列表）

    Args:
        report_type: 报告类型
        data: 报告数据

    Returns:
        消息列表
    """
    formatter = get_formatter(report_type)
    content = formatter.render(data)
    return formatter.split_messages(content)