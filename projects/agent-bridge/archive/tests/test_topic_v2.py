#!/usr/bin/env python3
"""
测试话题选取功能 - 改进版
等待页面完全加载后再提取
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from human_behavior_v2 import HumanBehaviorSimulator
from utils import start_xvfb
import os

USER_DATA_DIR = "data/browser_profile_deepseek"

async def test_topics():
    print("="*70)
    print("话题选取功能测试 - 改进版")
    print("="*70)
    
    if not start_xvfb():
        print("❌ Xvfb 启动失败")
        return
    
    os.makedirs(USER_DATA_DIR, exist_ok=True)
    
    print("\n[1] 启动浏览器...")
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
    
    page = await context.new_page()
    simulator = HumanBehaviorSimulator(page)
    
    print("[2] 访问 DeepSeek...")
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    
    print("[3] 等待页面完全加载...")
    await asyncio.sleep(5)  # 等待 JavaScript 渲染
    
    # 等待网络空闲
    try:
        await page.wait_for_load_state('networkidle', timeout=10000)
        print("✅ 网络空闲")
    except:
        print("⚠️ 网络未完全空闲，继续执行")
    
    # 截图看页面
    await page.screenshot(path='data/screenshots/topic_test_v2.png')
    print("✅ 截图: topic_test_v2.png")
    
    # 获取HTML分析话题列表
    html = await page.content()
    
    # 尝试多种选择器找话题 - 基于截图分析
    print("\n[4] 尝试提取话题列表...")
    
    # 从截图看，左侧边栏包含话题列表
    selectors = [
        # 基于常见模式的尝试
        '[class*="chat-list"] [class*="item"]',
        '[class*="conversation-list"]',
        '[class*="history"] > div',
        '[class*="sidebar"] [class*="list"] > div',
        '[class*="menu"] > div',
        
        # 基于文本内容
        'div:has-text("今天") + div > div',
        'div:has-text("昨天") + div > div',
        
        # 通用尝试
        'aside div[role="button"]',
        'nav div',
        
        # 基于层级结构
        'body > div > div > div > div > div',
    ]
    
    found_topics = []
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
            valid_elements = []
            
            for el in elements:
                try:
                    text = await el.inner_text()
                    # 过滤有效话题（有文字、不太长、不是按钮文字）
                    if text and 5 < len(text) < 100 and \
                       text not in ['开启新对话', '深度思考', '智能搜索']:
                        valid_elements.append(text.strip()[:50])
                except:
                    pass
            
            if valid_elements:
                print(f"\n  {selector}: 找到 {len(valid_elements)} 个可能的话题")
                for v in valid_elements[:3]:
                    print(f"    - {v}")
                found_topics.extend(valid_elements)
                    
        except Exception as e:
            pass
    
    # 尝试通过 XPath 定位
    print("\n[5] 尝试 XPath 定位...")
    try:
        # 找包含特定文字的元素
        elements = await page.query_selector_all('xpath=//div[contains(text(), "持久化") or contains(text(), "测试") or contains(text(), "Agent")]')
        print(f"  找到 {len(elements)} 个匹配元素")
        for el in elements[:5]:
            text = await el.inner_text()
            print(f"    - {text[:50]}")
    except Exception as e:
        print(f"  XPath 失败: {e}")
    
    print(f"\n[6] 共找到 {len(found_topics)} 个可能的话题")
    
    # 测试点击"开启新对话"
    print("\n[7] 测试点击'开启新对话'...")
    try:
        new_chat_btn = await page.wait_for_selector('text="开启新对话"', timeout=5000)
        if new_chat_btn:
            await new_chat_btn.click()
            await asyncio.sleep(3)
            print("✅ 已点击'开启新对话'")
            await page.screenshot(path='data/screenshots/topic_test_new_chat.png')
    except Exception as e:
        print(f"❌ 点击失败: {e}")
    
    print("\n" + "="*70)
    print("测试完成")
    print("="*70)
    
    print("\n浏览器保持运行30秒...")
    await asyncio.sleep(30)
    
    await context.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(test_topics())
