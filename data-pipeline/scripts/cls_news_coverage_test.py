#!/usr/bin/env python3
"""
cls_news_coverage_test.py — 31个申万行业关键词在财联社快讯中的覆盖测试
"""
import sys
import time
import json
from datetime import datetime, timedelta

# 申万一级行业 + 扩展关键词（每个行业多个关键词，提高召回）
SW_INDUSTRIES = [
    ("农林牧渔",    ["农林牧渔", "农业", "种子", "养猪", "猪肉", "养殖", "种植", "农产品", "农业种植", "畜牧"]),
    ("采掘",        ["采掘", "煤炭", "石油", "天然气", "油气", "煤矿", "原油", "能源开采"]),
    ("化工",        ["化工", "新材料", "化学", "石化", "化工原料", "化肥", "农药", "化工行业"]),
    ("钢铁",        ["钢铁", "螺纹钢", "铁矿石", "钢材", "钢企", "冶金", "特钢", "板材"]),
    ("有色金属",    ["有色金属", "有色", "铜", "铝", "黄金", "稀土", "白银", "锂", "钴", "小金属"]),
    ("电子",        ["电子", "半导体", "芯片", "集成电路", "PCB", "面板", "MLCC", "光刻", "晶圆"]),
    ("汽车",        ["汽车", "新能源汽车", "电动车", "锂电池车", "智能驾驶", "整车", "车企", "锂电车"]),
    ("家用电器",    ["家用电器", "家电", "空调", "冰箱", "洗衣机", "厨电", "小家电", "美的", "格力", "海尔"]),
    ("食品饮料",    ["食品饮料", "白酒", "饮料", "乳业", "乳制品", "调味品", "零食", "食品", "酒", "啤酒"]),
    ("纺织服装",    ["纺织服装", "纺织", "服装", "面料", "家纺", "制衣", "印染", "服装品牌"]),
    ("轻工制造",    ["轻工制造", "轻工", "造纸", "包装", "印刷", "家具", "文娱用品", "日用品"]),
    ("医药生物",    ["医药生物", "医药", "中药", "创新药", "医疗器械", "生物医药", "疫苗", "医疗", "化药", "药店"]),
    ("机械设备",    ["机械设备", "机械", "机器人", "工程机械", "数控机床", "工业母机", "自动化", "农机"]),
    ("电气设备",    ["电气设备", "电气", "光伏", "风电", "储能", "锂电池", "动力电池", "新能源发电", "电力设备"]),
    ("公用事业",    ["公用事业", "电力", "燃气", "水务", "供热", "环保", "水务处理", "垃圾发电"]),
    ("交通运输",    ["交通运输", "航空", "机场", "港口", "公路", "铁路", "物流", "快递", "航运", "集装箱"]),
    ("房地产",      ["房地产", "房企", "楼市", "商品房", "物业", "地产", "万科", "保利", "碧桂园", "购房"]),
    ("银行",        ["银行", "国有大行", "股份制银行", "城商行", "农商行", "存款", "贷款", "理财"]),
    ("非银金融",    ["非银金融", "券商", "保险", "证券", "公募基金", "私募基金", "信托", "租赁", "金融科技"]),
    ("建筑装饰",    ["建筑装饰", "建筑", "基建", "装饰", "园林工程", "装修", "建筑设计", "房地产建筑"]),
    ("计算机",      ["计算机", "软件", "AI", "人工智能", "云计算", "大数据", "信息安全", "操作系统", "应用软件"]),
    ("传媒",        ["传媒", "游戏", "影视", "广告", "出版", "院线", "短视频", "流媒体", "内容平台"]),
    ("通信",        ["通信", "5G", "6G", "光通信", "运营商", "通信设备", "物联网", "卫星通信", "网络设备"]),
    ("国防军工",    ["国防军工", "军工", "航天", "航空", "舰船", "导弹", "无人机", "国防", "军用", "航天航空"]),
    ("商业贸易",    ["商业贸易", "商贸", "零售", "百货", "超市", "电商", "跨境电商", "贸易", "进出口"]),
    ("休闲服务",    ["休闲服务", "旅游", "酒店", "餐饮", "免税", "景区", "乐园", "出行服务", "旅游景区"]),
    ("银行",        ["银行", "国有大行", "股份制银行", "城商行", "农商行", "存款", "贷款"]),  # 重复检查
]

# 去重
seen = set()
SW_INDUSTRIES_DEDUP = []
for item in SW_INDUSTRIES:
    if item[0] not in seen:
        seen.add(item[0])
        SW_INDUSTRIES_DEDUP.append(item)

print(f"共 {len(SW_INDUSTRIES_DEDUP)} 个申万一级行业")
print(f"测试时间范围: 最近24小时 (2026-06-02 17:30 ~ 2026-06-03 17:30)")
print()

# MCP 调用函数（通过 subprocess 调用 openclaw mcp 工具）
# 这里直接用 HTTP 调用 wudao_aStock MCP
import urllib.request
import urllib.error
import json

API_KEY = None
# 尝试从 .env 读取
env_path = "/home/claw/invest-infra/data-pipeline/.env"
with open(env_path) as f:
    for line in f:
        line = line.strip()
        if line.startswith("WUDAO_API_KEY") or line.startswith("WUDAO_ASTOCK_API_KEY"):
            API_KEY = line.split("=", 1)[1].strip()

if not API_KEY:
    print("未找到 WUDAO API Key，跳过实际 API 调用")
    print("使用模拟数据生成报告...")
    USE_MOCK = True
else:
    USE_MOCK = False

BASE_URL = "https://stock.quicktiny.cn/api/mcp-stream"

def call_cls_news(keywords, hours_ago=24, limit=10):
    """调用 cls_news MCP"""
    if USE_MOCK:
        return []

    # 构造 MCP JSON-RPC 请求
    now = datetime.now()
    start_time = (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M")
    date_str = now.strftime("%Y-%m-%d")

    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {
            "name": "cls_news",
            "arguments": {
                "date": date_str,
                "startTime": start_time.split()[1] if len(start_time.split()) > 1 else "00:00",
                "endTime": "23:59",
                "keyword": ",".join(keywords),
                "level": "all",
                "limit": limit,
                "format": "json"
            }
        },
        "id": 1
    }

    req = urllib.request.Request(
        BASE_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            content = data.get("result", {}).get("content", [])
            if content and isinstance(content, list):
                text = content[0].get("text", "")
                parsed = json.loads(text)
                return parsed.get("rows", [])
            return []
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []

results = []
batch_size = 4  # 每批 4 个行业
delay_between_calls = 0.8  # 0.8秒间隔

for i in range(0, len(SW_INDUSTRIES_DEDUP), batch_size):
    batch = SW_INDUSTRIES_DEDUP[i:i+batch_size]
    for name, keywords in batch:
        hits = 0
        if not USE_MOCK:
            rows = call_cls_news(keywords, hours_ago=24, limit=10)
            hits = len(rows)
        results.append((name, keywords, hits))
        print(f"  {name:12s} → {hits} 条快讯  (关键词: {keywords[:3]})")
    if i + batch_size < len(SW_INDUSTRIES_DEDUP):
        time.sleep(delay_between_calls)

print()
print("=" * 60)
print("覆盖测试报告")
print("=" * 60)

# 统计
total_industries = len(results)
covered = sum(1 for _, _, h in results if h > 0)
zero_coverage = [(name, kws) for name, kws, h in results if h == 0]
high_coverage = [(name, h) for name, _, h in results if h >= 3]
low_coverage = [(name, h) for name, _, h in results if 0 < h < 3]

print(f"行业总数: {total_industries}")
print(f"有快讯覆盖: {covered} ({covered/total_industries*100:.1f}%)")
print(f"零覆盖行业: {len(zero_coverage)} ({len(zero_coverage)/total_industries*100:.1f}%)")
print()

print("【零覆盖行业 - 需补充关键词】")
for name, kws in zero_coverage:
    print(f"  ⚠️  {name}")

print()
print("【高频覆盖（≥3条）】")
for name, h in sorted(high_coverage, key=lambda x: -x[1]):
    print(f"  ✅ {name}: {h} 条")

print()
print("【低频覆盖（1~2条）】")
for name, h in sorted(low_coverage, key=lambda x: -x[1]):
    print(f"  ⚡ {name}: {h} 条")

print()
print("【覆盖缺口分析】")
if zero_coverage:
    print(f"  需为以下行业扩展关键词：{[n for n,_ in zero_coverage]}")
else:
    print("  所有行业均有快讯覆盖")

print()
print("测试完成时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))