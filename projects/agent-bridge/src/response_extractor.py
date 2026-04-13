#!/usr/bin/env python3
"""
Response Extractor - HTML 提取方案（方案二）
从浏览器页面直接提取智能体回复文字

优势：
- 比 OCR 更准确
- 比 OCR 更快
- 无需额外依赖
"""
from typing import List, Optional, Dict, Any
from playwright.async_api import Page


class ResponseExtractor:
    """
    回复提取器
    
    针对不同平台优化选择器
    """
    
    # 平台特定的选择器配置
    PLATFORM_SELECTORS = {
        "deepseek": {
            "message_container": '[class*="ds-message"], [class*="message-list"], [class*="chat-messages"], .chat-content',
            "ai_message": '[class*="ds-message"], [class*="message"][class*="assistant"], [class*="message"][data-role="assistant"], .message.ai',
            "user_message": '[class*="message"][class*="user"], [class*="message"][data-role="user"], .message.user',
            "text_content": '.text-content, .message-content, .content, [class*="text"], [class*="ds-message"]',
        },
        "qwen": {
            "message_container": '[class*="chat-messages"], [class*="message-list"], .chat-content, [class*="conversation"]',
            "ai_message": '[class*="message"][class*="assistant"], [class*="message"][data-role="assistant"], .assistant-message, .ai-message',
            "user_message": '[class*="message"][class*="user"], [class*="message"][data-role="user"], .user-message',
            "text_content": '.message-content, .text-content, [class*="content"], .markdown-body',
        },
        "copilot": {
            "message_container": '[data-testid="chat-messages"], [class*="conversation"], [class*="message-list"]',
            "ai_message": '[class*="ac-textBlock"], [class*="message"][class*="bot"], .bot-message',
            "user_message": '[class*="message"][class*="user"], .user-message',
            "text_content": '.ac-textBlock, .text-content, .message-text',
        },
        "openai": {
            "message_container": '[class*="chat-content"], [class*="messages"], [role="log"]',
            "ai_message": '[data-testid="assistant-message"], .assistant-message, [class*="message"][class*="assistant"]',
            "user_message": '[data-testid="user-message"], .user-message, [class*="message"][class*="user"]',
            "text_content": '.markdown, .message-content, [class*="text"]',
        },
    }
    
    def __init__(self, platform: str = "deepseek"):
        """
        初始化提取器
        
        Args:
            platform: 平台名称（deepseek, copilot, openai）
        """
        self.platform = platform.lower()
        self.selectors = self.PLATFORM_SELECTORS.get(self.platform, self.PLATFORM_SELECTORS["deepseek"])
    
    async def extract_last_ai_response(self, page: Page) -> Optional[Dict[str, Any]]:
        """
        提取最后一条 AI 回复
        
        Args:
            page: Playwright Page 对象
        
        Returns:
            包含 text, html, selector 的字典，或 None
        """
        # 尝试多种选择器
        for selector in self.selectors["ai_message"].split(", "):
            try:
                elements = await page.query_selector_all(selector)
                if elements:
                    # 获取最后一条消息
                    last_element = elements[-1]
                    
                    # 提取文本
                    text = await last_element.inner_text()
                    
                    # 提取 HTML（保留格式）
                    html = await last_element.inner_html()
                    
                    if text and len(text.strip()) > 0:
                        return {
                            "text": text.strip(),
                            "html": html,
                            "selector": selector,
                            "platform": self.platform,
                        }
            except Exception:
                continue
        
        return None
    
    async def extract_all_messages(self, page: Page) -> List[Dict[str, Any]]:
        """
        提取所有消息（用户 + AI）
        
        Returns:
            消息列表，每个消息包含 role, text, html
        """
        messages = []
        
        # 尝试找到消息容器
        container_selectors = self.selectors["message_container"].split(", ")
        container = None
        
        for selector in container_selectors:
            try:
                container = await page.query_selector(selector)
                if container:
                    break
            except:
                continue
        
        if not container:
            # 回退：查找所有消息
            all_selectors = (
                self.selectors["ai_message"].split(", ") + 
                self.selectors["user_message"].split(", ")
            )
            
            for selector in set(all_selectors):
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements:
                        text = await el.inner_text()
                        if text and len(text.strip()) > 5:
                            # 判断角色
                            is_ai = any(s in selector for s in ["assistant", "bot", "ai"])
                            messages.append({
                                "role": "assistant" if is_ai else "user",
                                "text": text.strip(),
                                "html": await el.inner_html(),
                            })
                except:
                    continue
        else:
            # 从容器中提取所有子消息
            try:
                all_children = await container.query_selector_all(":scope > *")
                for child in all_children:
                    try:
                        text = await child.inner_text()
                        if not text or len(text.strip()) < 5:
                            continue
                        
                        # 判断角色
                        class_attr = await child.get_attribute("class") or ""
                        data_role = await child.get_attribute("data-role") or ""
                        
                        is_ai = any(kw in class_attr.lower() or kw in data_role.lower() 
                                   for kw in ["assistant", "bot", "ai"])
                        
                        messages.append({
                            "role": "assistant" if is_ai else "user",
                            "text": text.strip(),
                            "html": await child.inner_html(),
                        })
                    except:
                        continue
            except:
                pass
        
        return messages
    
    async def wait_for_new_response(
        self,
        page: Page,
        last_text: str = "",
        timeout: int = 180
    ) -> Optional[Dict[str, Any]]:
        """
        等待并提取新回复（稳定性检测版）

        策略：
        1. 先等 3 秒让 DeepSeek 开始打字
        2. 轮询提取内容，每隔 2 秒一次
        3. 连续 3 次内容不变且长度 > 100 字符 → 认定完成
        4. 同时检测"停止生成"按钮消失 → 辅助判断完成

        Args:
            page: Playwright Page 对象
            last_text: 上一条消息的文本（用于对比）
            timeout: 最长等待时间（秒）

        Returns:
            新回复内容，或 None（超时）
        """
        import asyncio

        STABLE_COUNT = 3       # 连续 N 次稳定则认定完成
        POLL_INTERVAL = 2      # 轮询间隔（秒）
        PRE_WAIT = 3
        baseline = last_text
        last_content = ""
        stable_unchanged = 0
        min_len = max(len(baseline) * 1.5, len(baseline) + 20, 5)

        await asyncio.sleep(PRE_WAIT)

        for elapsed in range(0, timeout, POLL_INTERVAL):
            response = await self.extract_last_ai_response(page)
            if not response:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            current_text = response["text"]
            if len(current_text) == 0:
                await asyncio.sleep(POLL_INTERVAL)
                continue

            stop_btn = await self._get_stop_button(page)

            if current_text == last_content:
                stable_unchanged += 1
                if stable_unchanged >= STABLE_COUNT:
                    return response
            else:
                stable_unchanged = 0
                last_content = current_text

            # 停止按钮消失时，等待 2 秒后再次检测
            if stop_btn is False and len(current_text) > min_len:
                await asyncio.sleep(2)
                response = await self.extract_last_ai_response(page)
                if response and len(response["text"]) > len(current_text):
                    # 有新内容，继续等待稳定性
                    last_content = response["text"]
                    stable_unchanged = 0
                else:
                    # 内容没有增加，认为完成
                    return response

            await asyncio.sleep(POLL_INTERVAL)

        return None

    async def _get_stop_button(self, page: Page) -> Optional[bool]:
        """
        检测 DeepSeek 的"停止生成"按钮状态

        Returns:
            True: 按钮存在（正在生成）
            False: 按钮不存在（已生成完成）
            None: 无法判断
        """
        try:
            selectors = [
                '[class*="stop-generating"]',
                '[class*="stopBtn"]',
                '[class*="abort"]',
                'button[class*="stop"]',
            ]
            for sel in selectors:
                btn = await page.query_selector(sel)
                if btn:
                    return True
            return False
        except Exception:
            return None
    
    def format_for_learning(self, response: Dict[str, Any], query: str = "") -> str:
        """
        格式化为学习记录格式
        
        Args:
            response: 提取的回复
            query: 用户问题
        
        Returns:
            格式化的 markdown 文本
        """
        from datetime import datetime
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        return f"""## [{timestamp}] {self.platform.upper()} - {query[:50]}

**Query**: {query}

**Response**:
{response['text']}

**Source**: {response['selector']}

---
"""


# 快捷函数
async def extract_deepseek_response(page: Page) -> Optional[str]:
    """提取 DeepSeek 最后一条回复"""
    extractor = ResponseExtractor("deepseek")
    result = await extractor.extract_last_ai_response(page)
    return result["text"] if result else None


async def extract_copilot_response(page: Page) -> Optional[str]:
    """提取 Copilot 最后一条回复"""
    extractor = ResponseExtractor("copilot")
    result = await extractor.extract_last_ai_response(page)
    return result["text"] if result else None


# 示例用法
async def demo():
    """演示用法"""
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # 访问 DeepSeek
        await page.goto("https://chat.deepseek.com/")
        
        # 提取回复
        extractor = ResponseExtractor("deepseek")
        response = await extractor.extract_last_ai_response(page)
        
        if response:
            print(f"提取到回复:\n{response['text'][:500]}")
        
        await browser.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo())
