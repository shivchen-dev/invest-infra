"""
ask() 工具 - 向 DeepSeek/Qwen 提问

MCP 工具定义 + 实现
"""
from typing import Any
from mcp.types import Tool

from agent_bridge_mcp.src.bridge_pool import pool


# ============== MCP 工具定义 ==============

ASK_TOOL = Tool(
    name="ask",
    description="向 DeepSeek 或 Qwen 发送消息并获取回复。多轮对话时网站自动维护上下文，无需手动管理 session_id。",
    inputSchema={
        "type": "object",
        "properties": {
            "platform": {
                "type": "string",
                "enum": ["deepseek", "qwen"],
                "description": "平台类型"
            },
            "message": {
                "type": "string",
                "description": "消息内容"
            }
        },
        "required": ["platform", "message"]
    }
)


# ============== 工具实现 ==============

async def call_ask(arguments: dict) -> dict[str, Any]:
    """
    调用 ask 工具
    
    Args:
        arguments: {
            "platform": "deepseek" | "qwen",
            "message": "问题内容"
        }
    
    Returns:
        {
            "success": bool,
            "response": str,  # AI 回复
            "error": str | None
        }
    """
    platform = arguments.get("platform")
    message = arguments.get("message")
    
    if not platform or not message:
        return {
            "success": False,
            "response": "",
            "error": "platform and message are required"
        }
    
    try:
        bridge = await pool.get_bridge(platform)
        result = await bridge.chat(message)
        
        if result.success:
            return {
                "success": True,
                "response": result.text,
                "error": None
            }
        else:
            return {
                "success": False,
                "response": "",
                "error": result.error or "Unknown error"
            }
    
    except Exception as e:
        return {
            "success": False,
            "response": "",
            "error": str(e)
        }
