#!/usr/bin/env python3
"""
DeepSeek 选择器调试工具
用于分析和修复消息提取选择器
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from playwright.async_api import async_playwright
from utils import start_xvfb


async def analyze_deepseek_selectors():
    """分析 DeepSeek 页面结构，找到正确的消息选择器"""
    
    start_xvfb()
    
    p = await async_playwright().start()
    context = await p.chromium.launch_persistent_context(
        user_data_dir='data/browser_profile_deepseek',
        headless=False,
        args=['--no-sandbox', '--window-size=1920,1080'],
        viewport={'width': 1920, 'height': 1080}
    )
    
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto('https://chat.deepseek.com/', timeout=60000)
    await asyncio.sleep(3)
    
    # 点击第一个已有话题（测试成功回复）
    print("点击话题 'Test Success Response'...")
    try:
        await page.click('text=Test Success Response', timeout=5000)
        await asyncio.sleep(2)
    except:
        print("未找到该话题")
    
    # 截图
    await page.screenshot(path='data/screenshots/selector_analysis.png')
    
    # 分析页面结构 - 查找消息元素
    print("\n=== 分析消息元素结构 ===\n")
    
    # 方法1: 通过 role 属性
    print("方法1: 通过 role 属性查找")
    for role in ['log', 'list', 'article', 'main']:
        elements = await page.query_selector_all(f'[role="{role}"]')
        if elements:
            print(f"  [role={role}]: {len(elements)} 个元素")
            for i, el in enumerate(elements[:2]):
                text = await el.inner_text()
                print(f"    [{i}] 长度: {len(text)}")
    
    # 方法2: 通过特定 class 模式（DeepSeek 使用随机类名）
    print("\n方法2: 通过特定 class 模式")
    all_divs = await page.query_selector_all('div[class]')
    print(f"  总共 {len(all_divs)} 个带 class 的 div")
    
    # 查找包含特定关键词的元素
    keywords = ['测试成功', 'How can I help', 'Message DeepSeek']
    for keyword in keywords:
        print(f"\n  查找包含 '{keyword}' 的元素:")
        try:
            # 使用 XPath 查找
            xpath = f'xpath=//div[contains(text(), "{keyword}")]'
            elements = await page.query_selector_all(xpath)
            print(f"    XPath 找到: {len(elements)} 个")
            
            for i, el in enumerate(elements[:2]):
                class_name = await el.get_attribute('class') or '无'
                parent = await el.query_selector('xpath=..')
                parent_class = await parent.get_attribute('class') if parent else '无'
                print(f"      [{i}] class: {class_name[:50]}...")
                print(f"          parent class: {parent_class[:50]}...")
        except Exception as e:
            print(f"    错误: {e}")
    
    # 方法3: 通过子元素数量筛选（消息容器通常有多个子元素）
    print("\n方法3: 查找可能的消息容器（通过子元素数量）")
    containers = await page.evaluate('''() => {
        const results = [];
        const divs = document.querySelectorAll('div');
        
        for (const div of divs) {
            const children = div.children;
            // 消息容器通常有 2-10 个直接子元素
            if (children.length >= 2 && children.length <= 20) {
                const text = div.innerText || '';
                // 包含足够文本但不是太多
                if (text.length > 50 && text.length < 2000) {
                    const classes = div.className || '';
                    // 排除常见的非消息容器
                    if (!classes.includes('sidebar') && 
                        !classes.includes('header') &&
                        !classes.includes('nav')) {
                        results.push({
                            className: classes.substring(0, 100),
                            childCount: children.length,
                            textLength: text.length,
                            textPreview: text.substring(0, 150).replace(/\\s+/g, ' ')
                        });
                    }
                }
            }
        }
        
        // 按文本长度排序，返回最长的几个
        return results.sort((a, b) => b.textLength - a.textLength).slice(0, 5);
    }''')
    
    print(f"  找到 {len(containers)} 个可能的容器:")
    for i, c in enumerate(containers):
        print(f"    [{i}] class: {c['className']}...")
        print(f"         子元素: {c['childCount']}, 文本长度: {c['textLength']}")
        print(f"         预览: {c['textPreview']}...")
    
    # 方法4: 尝试基于 DOM 层级查找
    print("\n方法4: 基于 DOM 层级结构")
    structure = await page.evaluate('''() => {
        // 获取 main 元素
        const main = document.querySelector('main');
        if (!main) return { error: 'No main element' };
        
        function analyzeStructure(el, depth = 0) {
            if (depth > 5) return null;
            
            const result = {
                tag: el.tagName,
                class: (el.className || '').substring(0, 50),
                children: []
            };
            
            for (const child of el.children) {
                const childAnalysis = analyzeStructure(child, depth + 1);
                if (childAnalysis) {
                    result.children.push(childAnalysis);
                }
            }
            
            return result;
        }
        
        return analyzeStructure(main);
    }''')
    
    print("  main 元素结构:")
    print_structure(structure, 0)
    
    await context.close()
    print("\n分析完成，截图保存: data/screenshots/selector_analysis.png")


def print_structure(node, depth):
    """打印 DOM 结构"""
    if not node or isinstance(node, dict) and 'error' in node:
        return
    
    indent = "  " * depth
    class_info = f" class={node.get('class', '无')}" if node.get('class') else ""
    print(f"{indent}<{node.get('tag', '?')}>{class_info}")
    
    for child in node.get('children', []):
        print_structure(child, depth + 1)


if __name__ == "__main__":
    asyncio.run(analyze_deepseek_selectors())
