#!/bin/bash
# setup_cron_timers.sh — ⚠️ DEPRECATED ⚠️
# 请改用 setup_systemd_timers.py（统一入口）
# 此脚本使用 transient systemd-run timers，重启后丢失，且可能与 static timers 重复触发。
# 用法: bash setup_cron_timers.sh

set -e

set -e
SCRIPT="/home/claw/invest-infra/data-pipeline/.venv/bin/python /home/claw/invest-infra/data-pipeline/scripts/cron_dispatcher.py"
LOG="/home/claw/invest-infra/logs/cron_cia.log"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"

# 注册单个 timer 的函数
reg_timer() {
    local name="$1"
    local calendar="$2"
    local service_file="$UNIT_DIR/cia_timer_${name}.service"

    # 创建 service（oneshot，调用 cron_dispatcher.py）
    cat > "$service_file" << EOF
[Unit]
Description=CIA ${name} — via cron_dispatcher
PartOf=cia_cron.target

[Service]
Type=oneshot
ExecStart=${SCRIPT} ${name}
StandardOutput=append:${LOG}
StandardError=append:${LOG}
EOF

    # 用 systemd-run 创建 timer（transient unit）
    systemd-run \
        --user \
        --no-block \
        --on-calendar="${calendar}" \
        --unit="cia_timer_${name}" \
        /bin/bash -c "${SCRIPT} ${name}" >> ${LOG} 2>&1

    echo "✓ Registered: ${name} (${calendar})"
}

echo "=== 注册 CIA cron_dispatcher timers ==="

# ── 早盘 ──────────────────────────────────────────────────
reg_timer "morning_briefing" "*-*-* 05:50:00"
reg_timer "woa_audit"        "*-*-* 07:30:00"
# briefing_dispatch removed 2026-06-12: 已合并到 morning_briefing(06:30 派发)
reg_timer "etf_spot_morning" "*-*-* 09:25:00"
reg_timer "etf_spot_intraday" "*-*-* 09:35:00"

# ── 午盘/盘后 ─────────────────────────────────────────────
reg_timer "financial_p1"     "*-*-* 14:00:00"
reg_timer "sw_industry"      "*-*-* 15:35:00"
reg_timer "etf_kline"        "*-*-* 15:40:00"
reg_timer "industry_info"    "*-*-* 15:50:00"
reg_timer "index_eod"        "*-*-* 16:00:00"
reg_timer "etf_factor"       "*-*-* 17:05:00"
reg_timer "etf_alpha"        "*-*-* 17:15:00"
reg_timer "etf_health"       "*-*-* 17:25:00"
reg_timer "etf_arbitrage"    "*-*-* 17:35:00"

# ── 夜盘 ──────────────────────────────────────────────────
reg_timer "financial_p2"     "*-*-* 18:30:00"
reg_timer "financial_p3"     "*-*-* 19:30:00"
reg_timer "financial_p4"     "*-*-* 20:30:00"

# ── 收盘批量采集（周一至周五 16:00）──────────────────
reg_timer "market_data_collector" "Mon,Tue,Wed,Thu,Fri *-*-* 16:00:00"

# ── ETF日内刷新（10:00-15:00 每15分钟）───────────────────
for h in 10 11 12 13 14 15; do
    for m in 00 15 30 45; do
        reg_timer "etf_spot_intraday" "*-*-* ${h}:${m}:00"
    done
done

echo ""
echo "=== 列出已注册的 CIA timers ==="
systemctl --user list-timers --all | grep cia_timer | head -30

echo ""
echo "=== 下次触发时间 ==="
systemctl --user list-timers cia_timer_morning_briefing 2>&1 || true
