#!/usr/bin/env python3
"""
sync_etf_index.py — ETF 跟踪指数同步脚本

策略：
  1. 从 akshare index_all_cni() 拉取 1400+ 只国内指数列表（含中证/深证/国证/港股）
  2. 用 ETF 名称关键词匹配 index 简称（最长匹配优先）
  3. 写入 etfs.跟踪指数 字段

用法:
    python3 scripts/sync_etf_index.py --dry-run   # 只看映射结果
    python3 scripts/sync_etf_index.py             # 全量写入
"""

import argparse
import logging
import sys
import os

sys.path.insert(0, "/home/claw/invest-infra/data-pipeline")

# 加载 .env（确保 PG 连接信息就绪）
_dotenv = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

from src.config import pg
import akshare as ak
import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_etf_index")

# ── ETF名称 → 指数名 关键词映射（按匹配优先级排列）────────────────────────────
# 规则：最长匹配优先；值为 None 表示仅跳过（如"增强"型ETF无固定跟踪指数）
INDEX_KEYWORD_MAP = {
    # ── 宽基 ──────────────────────────────────────────────────────────
    "沪深300":      "沪深300",
    "中证500":      "中证500",
    "中证1000":     "中证1000",
    "上证50":       "上证50",
    "上证180":      "上证180",
    "上证指数":     "上证指数",
    "深证成指":     "深证成指",
    "深证100":      "深证100",
    "创业板指":      "创业板指",
    "创业板":       "创业板指",
    "科创50":       "科创50",
    "科创综指":     "科创综合",
    "科创创业":     "科创创业50",
    "北证50":       "北证50",
    "MSCI中国":     "MSCI中国",
    "MSCI A股":     "MSCI中国",
    "标普500":      "标普500",
    "纳斯达克100":  "纳斯达克100",
    "纳斯达克":     "纳斯达克100",
    "日经225":      "日经225",
    "日经":         "日经225",
    "德国DAX":      "德国DAX",
    "德国":         "德国DAX",
    "法国CAC":      "法国CAC40",
    "英国富时":     "英国富时100",
    "印度孟买":     "印度孟买30",
    "越南VN30":     "越南VN30",
    "东南亚":       "东南亚指数",
    "欧洲斯托克":   "欧洲斯托克50",

    # ── 行业/主题 ────────────────────────────────────────────────────────
    # 医药/医疗
    "中药":         "中药",
    "创新药":       "创新药",
    "生物医药":     "生物医药",
    "医药":         "中证医药",
    "医疗":         "中证医疗",
    "药ETF":        "中证医药",
    "制药":         "中证医药",
    # 消费
    "白酒":         "中证白酒",
    "酒ETF":        "中证白酒",
    "酒":           "中证白酒",
    "食品饮料":     "中证食品饮料",
    "食品":         "中证食品饮料",
    "饮料":         "中证食品饮料",
    "家电":         "中证家电",
    "消费":         "中证消费",
    "消费50":       "中证消费50",
    "零售":         "中证零售",
    "商贸":         "中证商贸",
    # 金融
    "银行":         "中证银行",
    "证券":         "中证证券",
    "保险":         "中证保险",
    "金融":         "中证金融",
    "房地产":       "中证房地产",
    "地产":         "中证房地产",
    "券商":         "中证证券",
    # 科技/高端制造
    "人工智能":     "中证人工智能",
    "AI人工智能":   "中证人工智能",
    "AI":           "中证人工智能",
    "机器人":       "机器人50",
    "机器":         "机器人50",
    "半导体":       "深港通半导体",
    "芯片":         "国证芯片",
    "集成电路":     "集成电路",
    "5G通信":       "5G通信",
    "5G":          "5G通信",
    "通信":         "中证通信",
    "光通信":       "光通信",
    "云计算":       "中证云计算",
    "大数据":       "中证大数据",
    "物联网":       "中证物联网",
    "软件":         "中证软件",
    "计算机":       "中证计算机",
    "互联网":       "中证互联网",
    "游戏":         "中证游戏",
    "传媒":         "中证传媒",
    "元宇宙":       "元宇宙",
    "量子通信":     "量子通信",
    # 新能源/电力
    "新能源":       "中证新能源",
    "光伏":         "深证光伏",
    "风电":         "中证风电",
    "电池":         "中证电池",
    "储能":         "储能",
    "电力":         "深证公用",
    "公用事业":     "深证公用",
    "公用":         "深证公用",
    "绿电":         "绿色电力",
    "核电":         "核电",
    # 工业/制造
    "汽车":         "中证汽车",
    "汽车ETF":      "中证汽车",
    "新能源汽车":   "新能源汽车",
    "机械":         "中证机械",
    "工业":         "中证工业",
    "工业母机":     "工业母机",
    "军工":         "中证军工",
    "国防":         "中证国防",
    "无人机":       "无人机",
    "基建":         "国证基建",
    "建筑":         "中证建筑",
    "钢铁":         "国证钢铁",
    "煤炭":         "绿色煤炭",
    "有色金属":     "中证有色金属",
    "有色":         "中证有色金属",
    "稀土":         "稀土",
    "石化":         "中证石化",
    "化工":         "深证绿色化工",
    "农业":         "中证农业",
    "畜牧":         "中证畜牧",
    "养殖":         "中证畜牧",
    "种子":         "种子",
    "林业":         "林业",
    # 交通运输
    "航空":         "航空出行",
    "航空出行":     "航空出行",
    "机场":         "航空出行",
    "旅游":         "航空出行",
    "酒店餐饮":     "酒店餐饮",
    "高速":         "高速公路",
    "铁路":         "铁路",
    "航运":         "航运",
    "物流":         "物流",
    # 其他行业
    "环保":         "中证环保",
    "水务":         "水务指数",
    "燃气":         "燃气指数",
    "教育":         "中证教育",
    "养老":         "中证养老",
    "体育":         "体育产业",
    "文化":         "文化产业",
    "纺织":         "纺织服装",
    "服装":         "纺织服装",
    "美容":         "美容护理",
    # 港股/海外
    "港股通":       "中证港股通",
    "港股":         "中证港股通",
    "恒生指数":     "恒生指数",
    "恒生":         "恒生指数",
    "H股":          "恒生H股",
    "国企":         "深证国企ESG",
    "央企":         "深证央企",
    # 美股
    "美国50":       "标普500",
    "美国":         "美股",
    "标普":         "标普500",

    # ── 策略/风格 ────────────────────────────────────────────────────────
    "红利":         "中证红利",
    "红利低波":     "国企红利低波",
    "低波动":       "中证低波动",
    "价值":         "中证价值",
    "质量":         "中证质量",
    "成长":         "中证成长",
    "创新":         "中证创新",
    " ESG":         "ESG",
    "社会责任":     "社会责任",
    "A100":         "中证A100",
    "800":          "中证800",
    "200":          "中证200",
    "700":          "中证700",

    # ── 商品 ─────────────────────────────────────────────────────────────
    "黄金":         "黄金现货",
    "金ETF":        "黄金现货",
    "黄金ETF":      "黄金现货",
    "白银":         "白银现货",
    "原油":         "原油价格",
    "石油":         "原油价格",
    "油气":         "石油天然气",
    "商品":         "商品指数",
    "豆粕":         "豆粕期货",
    "白糖":         "白糖期货",
    "玉米":         "玉米期货",
    "小麦":         "小麦期货",
    "天然气":       "天然气",

    # ── 其他 ─────────────────────────────────────────────────────────────
    "REITs":        "中证REITs",
    "转债":         "中证转债",
    "可转债":       "中证转债",
    "债券":         "中证债券",
    "信用债":       "信用债",
    "国债":         "国债",
    "企债":         "企业债",
    "货币":         "货币市场",
    "现金管理":     "货币市场",

    # ── 增强型/空白（不写入跟踪指数）────────────────────────────────────
    "增强":         None,   # 增强型ETF需外部数据，无固定跟踪指数
}


def load_cni_indices() -> dict[str, str]:
    """从 akshare index_all_cni() 加载指数代码→简称映射"""
    logger.info("加载 CNI 指数列表...")
    df = ak.index_all_cni()
    result = {}
    for _, r in df.iterrows():
        code = str(r["指数代码"]).strip()
        name = str(r["指数简称"]).strip()
        if code and name:
            result[code] = name
    logger.info(f"CNI 指数: {len(result)} 只")
    return result


def build_name_to_index_map(cni_indices: dict[str, str]) -> dict[str, str]:
    """
    构建关键词→指数名 映射。
    包含三层来源（优先级递增）：
      1. 从 CNI 指数列表自动生成简称映射
      2. INDEX_KEYWORD_MAP 人工关键词
    """
    name_map = {}

    # 层1: CNI 指数自动生成
    for _code, name in cni_indices.items():
        name_map[name] = name
        if name.endswith("指数"):
            short = name[:-2]
            name_map[short] = name
        for suffix in ["等权", "等权重", "R"]:
            if suffix in name:
                base = name.replace(suffix, "")
                name_map[base] = name

    # 层2: 人工关键词（覆盖自动映射）
    for kw, idx_name in INDEX_KEYWORD_MAP.items():
        name_map[kw] = idx_name  # idx_name 为 None 时显式设为 None

    return name_map


def extract_index_from_etf_name(etf_name: str, name_map: dict[str, str]) -> str | None:
    """
    从 ETF 名称提取跟踪指数名称（最长匹配原则）。
    返回指数全称，或 None。
    """
    # 清理：去掉常见后缀
    clean = etf_name
    for suffix in ["ETF", "etf", "LOF", "lof"]:
        clean = clean.replace(suffix, "")

    candidates = []
    for keyword, index_name in name_map.items():
        if keyword in clean and index_name is not None:
            candidates.append((len(keyword), keyword, index_name))

    if not candidates:
        return None

    # 最长匹配优先
    candidates.sort(key=lambda x: -x[0])
    return candidates[0][2]


def fetch_etf_rows_from_db(conn) -> list[tuple]:
    """读取所有活跃 ETF (id, code, name)"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, code, name FROM etfs WHERE is_active = true ORDER BY id"
        )
        return cur.fetchall()


def sync_etf_index(dry_run: bool = False) -> dict:
    """主同步流程。返回统计字典。"""
    cni_indices = load_cni_indices()
    name_map = build_name_to_index_map(cni_indices)
    logger.info(f"关键词映射表: {len(name_map)} 条")

    conn = psycopg2.connect(pg.uri)
    try:
        etf_rows = fetch_etf_rows_from_db(conn)

        matched, no_match = [], []
        for etf_id, code, name in etf_rows:
            index_name = extract_index_from_etf_name(name, name_map)
            if index_name:
                matched.append((etf_id, index_name))
            else:
                no_match.append((etf_id, code, name))

        logger.info(f"匹配: {len(matched)}/{len(etf_rows)}  无法匹配: {len(no_match)}")

        if not dry_run and matched:
            with conn.cursor() as cur:
                for etf_id, index_name in matched:
                    cur.execute(
                        "UPDATE etfs SET 跟踪指数 = %s, updated_at = now() "
                        "WHERE id = %s",
                        (index_name, etf_id),
                    )
            conn.commit()
            logger.info(f"写入 {len(matched)} 条跟踪指数")
        else:
            logger.info(f"Dry-run: 拟写入 {len(matched)} 条（未实际执行）")

        # 样例
        logger.info("匹配样例（前 15）:")
        # matched 是 (etf_id, index_name)，需要查 name
        for etf_id, idx_name in matched[:15]:
            with conn.cursor() as cur:
                cur.execute("SELECT code, name FROM etfs WHERE id = %s", (etf_id,))
                r = cur.fetchone()
            logger.info(f"  [{etf_id}] {r[0]} {r[1]} → {idx_name}")

        logger.info("无法匹配 ETF（前 20）:")
        for _, code, name in no_match[:20]:
            logger.info(f"  {code} {name}")

        return {
            "total": len(etf_rows),
            "matched": len(matched),
            "unmatched": len(no_match),
        }
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="同步 ETF 跟踪指数")
    parser.add_argument("--dry-run", action="store_true", help="只查看不写入")
    args = parser.parse_args()

    result = sync_etf_index(dry_run=args.dry_run)
    print(
        f"\n结果: matched={result['matched']}/{result['total']}, "
        f"unmatched={result['unmatched']}"
    )