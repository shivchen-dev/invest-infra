"""
Copilot Bridge 调试测试 - 查看页面结构
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from copilot_bridge import CopilotBridge


async def debug_test():
    """调试测试 - 查看页面结构"""
    print("=" * 60)
    print("Copilot Bridge 调试测试")
    print("=" * 60)
    
    os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7890'
    os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7890'
    
    bridge = CopilotBridge(headless=True, rate_limit=True, use_xvfb=False)
    
    try:
        print("\n[1] 启动浏览器...")
        await bridge.start()
        print("✅ 浏览器启动成功")
        
        # 保存页面截图
        await bridge.page.screenshot(path="copilot_initial.png")
        print("📸 初始页面截图已保存: copilot_initial.png")
        
        # 获取页面 HTML 结构
        html = await bridge.page.content()
        with open("copilot_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("📄 页面 HTML 已保存: copilot_page.html")
        
        # 获取页面标题
        title = await bridge.page.title()
        print(f"📋 页面标题: {title}")
        
        # 尝试查找输入框
        print("\n[2] 查找输入框...")
        for selector in bridge.selectors["input_box"]:
            try:
                element = await bridge.page.query_selector(selector)
                if element:
                    print(f"  ✅ 找到输入框: {selector}")
                    break
            except:
                continue
        
        # 发送一条消息
        print("\n[3] 发送测试消息...")
        response = await bridge.ask("你好", timeout=60)
        
        # 保存回复后的截图
        await bridge.page.screenshot(path="copilot_after_response.png")
        print("📸 回复后截图已保存: copilot_after_response.png")
        
        print(f"\n🤖 回复内容:\n{response.text[:200]}...")
        
        print("\n" + "=" * 60)
        print("调试完成! 请查看截图和 HTML 文件")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        # 尝试保存错误截图
        try:
            await bridge.page.screenshot(path="copilot_error.png")
            print("📸 错误截图已保存: copilot_error.png")
        except:
            pass
    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(debug_test())
