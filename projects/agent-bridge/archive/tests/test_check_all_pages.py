#!/usr/bin/env python3
"""
检查所有标签页的登录状态
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def check_all_pages():
    print("="*70)
    print("检查所有标签页的登录状态")
    print("="*70)
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    
    p = await async_playwright().start()
    
    context = await p.chromium.launch_persistent_context(
        user_data_dir=USER_DATA_DIR,
        headless=False,
        args=[
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--window-size=1920,1080',
        ],
        viewport={'width': 1920, 'height': 1080},
        locale='zh-CN',
    )
    
    # 获取所有标签页
    pages = context.pages
    print(f"\n[1] 发现 {len(pages)} 个标签页")
    
    logged_in_page = None
    
    for i, page in enumerate(pages):
        print(f"\n  标签页 {i+1}: {page.url}")
        
        # 检查登录状态
        html = await page.content()
        
        if "登录" in html:
            print(f"    ❌ 未登录")
        else:
            print(f"    ✅ 已登录")
            logged_in_page = page
            
        # 检查是否包含话题
        if "持久化" in html or "测试" in html or "开启新对话" in html:
            print(f"    📋 包含话题列表")
    
    # 如果没有找到已登录的页面，创建新页面并访问
    if not logged_in_page:
        print("\n[2] 未找到已登录标签页，创建新页面...")
        page = await context.new_page()
        await page.goto('https://chat.deepseek.com/', timeout=60000)
        await asyncio.sleep(5)
        
        html = await page.content()
        if "登录" in html:
            print("    ❌ 新页面也未登录")
        else:
            print("    ✅ 新页面已登录")
            logged_in_page = page
    else:
        print(f"\n[2] 找到已登录标签页，切换到该页面")
        # 切换到已登录的页面
        await logged_in_page.bring_to_front()
        await asyncio.sleep(2)
    
    # 如果找到已登录页面，尝试提取话题
    if logged_in_page:
        print("\n[3] 提取话题列表...")
        html = await logged_in_page.content()
        
        # 使用 JavaScript 提取所有文本
        texts = await logged_in_page.evaluate('''() => {
            const divs = document.querySelectorAll('div');
            return Array.from(divs).map(d => d.innerText?.trim()).filter(t => t && t.length > 5 && t.length < 100);
        }''')
        
        # 过滤可能的话题
        topics = []
        for text in texts:
            if text not in ['开启新对话', '深度思考', '智能搜索', '今天', '昨天', '7天内']:
                if any(keyword in text for keyword in ['持久化', '测试', 'Agent', 'qmd', 'Docker', 'OpenClaw']):
                    topics.append(text)
        
        # 去重
        seen = set()
        unique_topics = []
        for t in topics:
            if t not in seen:
                seen.add(t)
                unique_topics.append(t)
        
        print(f"    找到 {len(unique_topics)} 个话题:")
        for t in unique_topics[:10]:
            print(f"      - {t[:50]}")
    
    print("\n" + "="*70)
    print("检查完成")
    print("="*70)
    
    await asyncio.sleep(30)
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(check_all_pages())
