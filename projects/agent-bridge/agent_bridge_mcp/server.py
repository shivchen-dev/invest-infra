"""
Agent Bridge MCP Server

提供 ask() 工具，通过 MCP 协议调用 DeepSeek/Qwen
"""
import asyncio
import sys
from pathlib import Path

# 添加 MCP Server 路径
sys.path.insert(0, str(Path(__file__).parent))

from mcp.server import Server
from mcp.types import TextContent

from agent_bridge_mcp.src.bridge_pool import pool
from agent_bridge_mcp.src.tools.ask import ASK_TOOL, call_ask


# ============== MCP Server ==============

app = Server(name="agent-bridge")


@app.list_tools()
async def list_tools():
    """列出所有可用工具"""
    return [ASK_TOOL]


@app.call_tool()
async def handle_tool_call(name: str, arguments: dict):
    """处理工具调用"""
    if name == "ask":
        result = await call_ask(arguments)
        
        if result["success"]:
            return [TextContent(type="text", text=result["response"])]
        else:
            # 返回错误信息作为文本
            return [TextContent(type="text", text=f"Error: {result['error']}")]
    
    raise ValueError(f"Unknown tool: {name}")


# ============== 运行 ==============

async def main():
    """启动 MCP Server"""
    from mcp.server.stdio import stdio_server
    
    # 创建初始化选项
    options = app.create_initialization_options()
    
    # 使用 stdio 模式运行
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, options)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # 关闭所有 Bridge
        asyncio.run(pool.close_all())
