#!/usr/bin/env python3
"""同步 A 股上市公司列表到 PostgreSQL"""

import logging
import sys

sys.path.insert(0, ".")

from src.collector.companies import fetch_all_companies, sync_to_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

companies = fetch_all_companies()
result = sync_to_db(companies)
print(f"✅ 同步完成: {result}")
