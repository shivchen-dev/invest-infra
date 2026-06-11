#!/usr/bin/env python3
"""盘后报触发脚本"""
import asyncio, sys, os
sys.path.insert(0, '/home/claw/invest-infra/data-pipeline/src')
os.environ['CIFANG_TOKEN'] = 'dummy'
os.environ.setdefault('MINIO_SECRET_KEY', '')
if not os.environ.get('MINIO_SECRET_KEY'):
    raise RuntimeError('MINIO_SECRET_KEY not set; expected in .env or .secrets/minio.env')
from reports.report_engine import ReportEngine

async def main():
    engine = ReportEngine('post_market')
    success = await engine.run()
    sys.exit(0 if success else 1)

asyncio.run(main())
