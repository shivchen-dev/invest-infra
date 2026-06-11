#!/usr/bin/env python3
"""盘前报触发脚本 — 修复版（2026-06-11）

职责：在开盘前通知 CIA 数据已就绪，等待 CIA 执行早盘分析。
不再依赖 reports.report_engine（该模块需要 CIFANG_TOKEN 且路径复杂），
改为直接：
  1. 检查今日是否为交易日
  2. 发送简短 QQ 通知给 CIA
  3. （可选）写入简短 pre_market 提示到 Redis
"""
import os
import sys
import subprocess
from datetime import date
from pathlib import Path

# ── .env 加载 ───────────────────────────────────────────────────────────────
_ENV_FILE = Path('/home/claw/invest-infra/data-pipeline/.env')
if _ENV_FILE.exists():
    for raw in _ENV_FILE.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# ── QQ 推送 ────────────────────────────────────────────────────────────────
QQ_BIN   = '/home/claw/.npm-global/bin/openclaw'
QQ_CHAN  = 'qqbot'
QQ_ACC   = '1903628521'
QQ_TARGET = '43C77867478A33B101FA705AA70754E3'


def _qq_send(text: str) -> bool:
    """发送 QQ 消息，返回成功/失败"""
    cmd = [QQ_BIN, 'message', 'send',
           '--channel', QQ_CHAN,
           '--account', QQ_ACC,
           '--target', QQ_TARGET,
           '--message', text]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15)
        if cp.returncode == 0:
            print(f'[QQ] OK: {text[:50]}', file=sys.stderr)
            return True
        else:
            print(f'[QQ] FAIL: {cp.stderr[:100]}', file=sys.stderr)
            return False
    except Exception as e:
        print(f'[QQ] ERROR {e}', file=sys.stderr)
        return False


# ── 交易日检查 ─────────────────────────────────────────────────────────────
def _is_trading_day(d: date) -> bool:
    """简单交易日判断：排除周末 + 已知节假日（硬编码）"""
    if d.weekday() >= 5:  # 周六、周日
        return False
    # 2026 年端午: 6月19日
    if d == date(2026, 6, 19):
        return False
    return True


# ── 主流程 ─────────────────────────────────────────────────────────────────
def main() -> int:
    today = date.today()
    print(f'[pre_market] 启动 {today}', file=sys.stderr)

    if not _is_trading_day(today):
        print(f'[pre_market] 今日 {today} 非交易日，跳过', file=sys.stderr)
        return 0

    # 发送盘前通知
    msg = f'📊 盘前报就绪 | {today} 开盘前数据已采集 | 请执行 Morning Briefing'
    ok = _qq_send(msg)

    if ok:
        print(f'[pre_market] 完成', file=sys.stderr)
        return 0
    else:
        print(f'[pre_market] QQ 发送失败', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())