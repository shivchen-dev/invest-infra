#!/usr/bin/env python3
"""
cron_industry_info.py — 申万行业信息因子采集（路径A v1）

数据流：
  cls_news(关键词) → 命中快讯 → 去重 → 密度分 → info_score(0-100)
  → 写入 industry_info_scores 表
  → 被 src/factors/etf_fundamental.py 的 _compute_industry_sentiment() 调用

触发时间：每天 15:50（盘后，申万行业数据 15:35 跑完后）
"""
import sys, os, json, time, logging, argparse
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

# ─── 路径 & env 加载（复用其他 cron 脚本的方案）──
_pipeline_dir = Path("/home/claw/invest-infra/data-pipeline")
_secrets_dir = _pipeline_dir.parent / ".secrets"

def _load_env(filepath):
    if filepath and filepath.exists():
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    os.environ.setdefault(k, v)

_load_env(_secrets_dir / "tokens.env")
_load_env(_pipeline_dir / ".env")

import psycopg2
import numpy as np
from src.config import pg

# ─── 日志 ────────────────────────────────────────────────────────────────────
LOG_DIR = Path("/home/claw/invest-infra/data-pipeline/logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "industry_info.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("industry_info")

# ─── 申万行业 → 关键词映射 ───────────────────────────────────────────────────
# 31个申万一级行业 + 扩展关键词（平衡召回与精度）
SW_INDUSTRIES = [
    ("农林牧渔",   "801010", ["农林牧渔","农业","种子","养猪","猪肉","养殖","种植","农产品","畜牧","农机"]),
    ("采掘",       "801020", ["采掘","煤炭","煤矿","原油","油气","天然气","能源开采","焦煤","动力煤"]),
    ("化工",       "801030", ["化工","新材料","化学","石化","化肥","农药","化工原料","化工行业","化工产品"]),
    ("钢铁",       "801040", ["钢铁","螺纹钢","铁矿石","钢材","钢企","冶金","特钢","板材","不锈钢"]),
    ("有色金属",   "801050", ["有色金属","有色","铜","铝","黄金","稀土","白银","锂","钴","小金属","铜矿","铝材"]),
    ("电子",       "801080", ["电子","半导体","芯片","集成电路","PCB","面板","MLCC","光刻","晶圆","HBM","GPU芯片"]),
    ("汽车",       "801110", ["汽车","新能源汽车","电动车","智能驾驶","整车","车企","锂电池车","锂电车","自动驾驶"]),
    ("家用电器",   "801120", ["家用电器","家电","空调","冰箱","洗衣机","厨电","小家电","美的","格力","海尔","家电下乡"]),
    ("食品饮料",   "801130", ["食品饮料","白酒","饮料","乳业","乳制品","调味品","零食","食品","酒","啤酒","食品加工"]),
    ("纺织服装",   "801140", ["纺织服装","纺织","服装","面料","家纺","制衣","印染","服装品牌","棉纺"]),
    ("轻工制造",   "801150", ["轻工制造","轻工","造纸","包装","印刷","家具","文娱用品","日用品","纸包装"]),
    ("医药生物",   "801170", ["医药生物","医药","中药","创新药","医疗器械","生物医药","疫苗","医疗","化药","药店","CXO","医疗设备"]),
    ("机械设备",   "801730", ["机械设备","机械","机器人","工程机械","数控机床","工业母机","自动化","农机","精密机械"]),
    ("电气设备",   "801740", ["电气设备","电气","光伏","风电","储能","锂电池","动力电池","新能源发电","电力设备","逆变器"]),
    ("公用事业",   "801710", ["公用事业","电力","燃气","水务","供热","环保","水务处理","垃圾发电","绿电","电力板块"]),
    ("交通运输",   "801720", ["交通运输","航空","机场","港口","公路","铁路","物流","快递","航运","集装箱","航空运输"]),
    ("房地产",     "801760", ["房地产","房企","楼市","物业","地产","购房","房产","万科A","保利发展","碧桂园","房地产板块"]),
    ("银行",       "801780", ["银行","存款","贷款","国有大行","股份制银行","城商行","农商行","银行股","信贷"]),
    ("非银金融",   "801790", ["非银金融","券商","保险","证券","公募基金","私募基金","信托","金融科技","租赁","投行"]),
    ("建筑装饰",   "801720", ["建筑装饰","建筑","基建","装饰","园林工程","装修","建筑设计","房地产建筑","工程建设"]),
    ("计算机",     "801750", ["计算机","软件","AI","人工智能","云计算","大数据","信息安全","操作系统","应用软件","大模型","AI应用"]),
    ("传媒",       "801760", ["传媒","游戏","影视","广告","出版","院线","短视频","流媒体","内容平台","电影","综艺"]),
    ("通信",       "801770", ["通信","5G","6G","光通信","运营商","通信设备","物联网","卫星通信","网络设备","算力网络"]),
    ("国防军工",   "801710", ["国防军工","军工","航天","航空","舰船","导弹","无人机","国防","军用","航天航空","雷达"]),
    ("商业贸易",   "801800", ["商业贸易","商贸","零售","百货","超市","电商","跨境电商","贸易","进出口","新零售"]),
    ("休闲服务",   "801210", ["休闲服务","旅游","酒店","免税","景区","乐园","出行服务","旅游景区","OTA","旅行社","餐饮","酒店旅游"]),
    ("农林牧渔2",  "801010", []),   # 备用，已合并到第一个
]

# 去重 & 合并同类项
_seen = set()
INDUSTRIES = []
for name, code, kws in SW_INDUSTRIES:
    if name.rstrip("0123456789") not in _seen or name == "农林牧渔":
        _seen.add(name.rstrip("0123456789"))
        INDUSTRIES.append((name, code, kws))

# 去除空关键词行业（保留结构完整）
INDUSTRIES = [(n, c, k) for n, c, k in INDUSTRIES if k]

# ─── MCP 调用 ────────────────────────────────────────────────────────────────
import os
import json
import time
import logging
import argparse
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

import psycopg2
import numpy as np
from src.config import pg

# ─── 从 OpenClaw config 解析 wudao_aStock API token ─────────────────────────
def _get_wudao_token() -> str:
    """从 ~/.openclaw/openclaw.json 提取 wudao_aStock 的 bearer token"""
    # 硬编码路径（venv 里 Path.home() 返回 /root）
    config_path = Path("/home/claw/.openclaw/openclaw.json")
    if not config_path.exists():
        return ""
    with open(config_path) as f:
        cfg = json.load(f)
    mcp_servers = cfg.get("mcp", {}).get("servers", {})
    server = mcp_servers.get("wudao_aStock", {})
    headers = server.get("headers", {})
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""

# ─── 日志 ────────────────────────────────────────────────────────────────────
LOG_DIR = Path("/home/claw/invest-infra/data-pipeline/logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "industry_info.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("industry_info")

# ─── MCP HTTP 调用 ───────────────────────────────────────────────────────────
BASE_URL = "https://stock.quicktiny.cn/api/mcp-stream"

def _call_cls_news(args: dict) -> tuple[int, list]:
    """
    调用 cls_news MCP 接口（通过 curl 避免 venv urllib proxy 问题）。
    返回 (news_count, parsed_rows)
    - news_count: 从 headline 解析的快讯条数
    """
    import re, subprocess, shlex
    token = _get_wudao_token()
    if not token:
        logger.warning("[industry_info] 未找到 wudao_aStock API token")
        return 0, []

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "cls_news", "arguments": args},
        "id": 1,
    }
    payload_json = json.dumps(payload)

    # curl 方式调用（绕过 venv urllib proxy 问题）
    curl_cmd = [
        "curl", "-s", "-X", "POST", BASE_URL,
        "-H", f"Authorization: Bearer {token}",
        "-H", "Content-Type: application/json",
        "-d", payload_json,
        "--max-time", "15",
    ]
    logger.debug("[industry_info] _call_cls_news args=%s", args)
    try:
        cp = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=20)
        if cp.returncode != 0:
            logger.warning("[industry_info] curl failed rc=%d: %s", cp.returncode, cp.stderr.strip()[:80])
            return 0, []
        data = json.loads(cp.stdout)
        result = data.get("result", {})
        content = result.get("content", [])
        if not content:
            logger.warning("[industry_info] cls_news 返回空 content: %s", str(data)[:200])
            return 0, []
        text = content[0].get("text", "")
        logger.debug("[industry_info] cls_news raw text: %s", text[:200])
        # headline 格式："财联社快讯 N 条（YYYY-MM-DD），B级 X 条、C级 Y 条"
        m = re.search(r"财联社快讯\s*(\d+)\s*条", text)
        count = int(m.group(1)) if m else 0
        return count, []
    except subprocess.TimeoutExpired:
        logger.warning("[industry_info] curl 超时")
    except Exception as e:
        logger.warning("[industry_info] cls_news 调用失败: %s", e)
    return 0, []

def fetch_news_for_industry(keywords: list, trade_date: date, hours: int = 24, limit: int = 20) -> tuple[int, list]:
    """按行业关键词抓取快讯，返回 (命中条数, 摘要列表)"""
    if not keywords:
        return 0, []
    today = date.today()
    # startTime 必须是 trade_date 当天的 00:00，不能用 now - 24h
    # API 的 date+startTime+endTime 组合决定查询范围
    if trade_date == today:
        start_time = "00:00"
        end_time = datetime.now().strftime("%H:%M")
    else:
        start_time = "00:00"
        end_time = "23:59"
    date_str = trade_date.strftime("%Y-%m-%d")

    args = {
        "date": date_str,
        "startTime": start_time,
        "endTime": end_time,
        "keyword": ",".join(keywords),
        "level": "all",
        "limit": limit,
    }
    return _call_cls_news(args)

# ─── 去重 ────────────────────────────────────────────────────────────────────
def dedupe_news(rows: list) -> list:
    """按 title + source 去重"""
    seen = set()
    result = []
    for r in rows:
        key = (r.get("title", "")[:50], r.get("source", ""))
        if key not in seen:
            seen.add(key)
            result.append(r)
    return result

# ─── 密度分计算 ──────────────────────────────────────────────────────────────
# 历史均值缓存（行业 → 历史日均快讯数）
_HIST_AVG: dict[str, float] = {}

def _load_hist_avg(conn):
    """从DB加载各行业历史日均快讯数"""
    cur = conn.cursor()
    cur.execute("""
        SELECT sw_name, AVG(news_count)::float AS avg_cnt
        FROM industry_info_scores
        WHERE trade_date >= CURRENT_DATE - INTERVAL '30 days'
          AND news_count > 0
        GROUP BY sw_name
    """)
    for name, avg in cur.fetchall():
        _HIST_AVG[name] = avg
    cur.close()
    if not _HIST_AVG:
        # 无历史数据，用经验值初始化
        for name, _, kws in INDUSTRIES:
            _HIST_AVG[name] = 3.0
        logger.info("[industry_info] 无历史数据，使用经验均值 3.0")

def calc_info_score(news_count: int, sw_name: str) -> tuple[float, float]:
    """
    计算信息分数和置信度
    density = news_count / (hist_avg + 1)
    score   = clamp(50 + (density - 1) * 25, 0, 100)
    confidence = min(1.0, news_count / 10)
    """
    hist_avg = _HIST_AVG.get(sw_name, 3.0)
    density  = news_count / (hist_avg + 1e-6)
    raw_score = 50.0 + (density - 1.0) * 25.0
    score     = float(np.clip(raw_score, 0.0, 100.0))
    confidence = float(np.clip(news_count / 10.0, 0.0, 1.0))
    return round(score, 2), round(confidence, 3)

# ─── 写入 DB ─────────────────────────────────────────────────────────────────
def write_to_db(conn, rows: list, trade_date: date, window_h: int = 24):
    """UPSERT 写入 industry_info_scores"""
    cur = conn.cursor()
    written = 0
    for sw_name, sw_code, news_count, info_score, confidence, sources in rows:
        sources_json = json.dumps(sources, ensure_ascii=False)
        cur.execute("""
            INSERT INTO industry_info_scores
              (trade_date, sw_name, sw_code, news_count, density, info_score,
               window_h, sources, confidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (trade_date, sw_name, window_h) DO UPDATE SET
              news_count = EXCLUDED.news_count,
              density    = EXCLUDED.density,
              info_score = EXCLUDED.info_score,
              sources    = EXCLUDED.sources,
              confidence = EXCLUDED.confidence
        """, (trade_date, sw_name, sw_code, news_count,
              round(news_count / (_HIST_AVG.get(sw_name, 3.0) + 1e-6), 4),
              info_score, window_h, sources_json, confidence))
        written += 1
    conn.commit()
    cur.close()
    return written

# ─── 建表 ────────────────────────────────────────────────────────────────────
def init_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS industry_info_scores (
            id          SERIAL PRIMARY KEY,
            trade_date  DATE NOT NULL,
            sw_name     TEXT NOT NULL,
            sw_code     TEXT,
            news_count  INTEGER DEFAULT 0,
            density     FLOAT DEFAULT 0.0,
            info_score  FLOAT DEFAULT 50.0,
            window_h    INTEGER DEFAULT 24,
            sources     TEXT,
            confidence  FLOAT DEFAULT 0.0,
            created_at  TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(trade_date, sw_name, window_h)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_industry_info_trade ON industry_info_scores(trade_date)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_industry_info_name  ON industry_info_scores(sw_name)")
    conn.commit()
    cur.close()
    logger.info("[industry_info] 表结构就绪")

# ─── 主流程 ──────────────────────────────────────────────────────────────────
def run(trade_date: date, window_h: int = 24, dry_run: bool = False):
    logger.info("[industry_info] 开始采集 %s 申万行业信息因子 (窗口=%dh)", trade_date, window_h)
    conn = psycopg2.connect(pg.uri)
    init_table(conn)
    _load_hist_avg(conn)

    results = []
    delay = 3.0  # 避免 MCP 接口限流

    for i, (sw_name, sw_code, keywords) in enumerate(INDUSTRIES):
        # dry_run 时跳过 API 调用（避免消耗每日50次限额）
        if dry_run:
            rows = (0, [])
        else:
            rows = fetch_news_for_industry(keywords, trade_date, hours=window_h)
        news_count, raw_rows = rows if isinstance(rows, tuple) else (0, [])
        info_score, confidence = calc_info_score(news_count, sw_name)
        # 保留摘要（headline 模式只有 count，没有 title）
        source_titles = []
        results.append((sw_name, sw_code, news_count, info_score, confidence, source_titles))
        logger.info("  %-12s %2d条  score=%.2f  conf=%.3f",
                    sw_name, news_count, info_score, confidence)
        time.sleep(delay)

    if not dry_run:
        written = write_to_db(conn, results, trade_date, window_h)
        logger.info("[industry_info] 写入 %d/%d 条", written, len(results))
    else:
        logger.info("[industry_info] dry_run=%s，共 %d 个行业", dry_run, len(results))

    conn.close()
    return results

# ─── CLI ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="申万行业信息因子采集")
    parser.add_argument("--date", help="交易日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--window", type=int, default=24, help="快讯窗口小时数（默认24h）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    args = parser.parse_args()
    target = date.fromisoformat(args.date) if args.date else date.today()
    run(target, window_h=args.window, dry_run=args.dry_run)
