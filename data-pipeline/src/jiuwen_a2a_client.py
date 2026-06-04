"""
JiuwenSwarm A2A Client — CIA → JiuwenSwarm 通信客户端

关键发现：
- JiuwenSwarm A2A Server 仅支持 non-streaming JSON-RPC
- 正确 endpoint: POST http://127.0.0.1:19100/a2a
- role 用整数 1 (ROLE_USER)，不是字符串 "user"
- 返回结果在 result.task.history[0].parts[0].text

用法:
    from src.jiuwen_a2a_client import get_client, quick_send

    client = await get_client()
    result = await client.send("分析 512480 最新 alpha 信号")
"""

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ─── 全局 client 实例 ─────────────────────────────────────────────

_client: "A2AClientWrapper | None" = None

# JiuwenSwarm A2A endpoint
A2A_ENDPOINT = "http://127.0.0.1:19100/a2a"

# Role enum (integer, not string)
ROLE_USER = 1


class A2AClientWrapper:
    """
    A2A 客户端封装 — 使用 non-streaming JSON-RPC

    每次 send() 发一个请求，等待完成，返回文本。
    不使用 SSE streaming。
    """

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=60)

    async def close(self):
        await self._client.aclose()

    async def send(self, query: str) -> str:
        """
        发送消息，返回 agent 回复的纯文本。
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": ROLE_USER,
                    "parts": [{"text": query}],
                }
            },
        }

        resp = await self._client.post(A2A_ENDPOINT, json=payload)
        resp.raise_for_status()
        data = resp.json()

        # 从 result.task.history[0].parts[0].text 提取回复
        return _extract_agent_text(data)

    async def send_structured(self, query: str) -> dict[str, Any]:
        """发送并尝试解析 JSON 结果；失败返回原始文本"""
        text = await self.send(query)
        parsed = _extract_json(text)
        if parsed:
            return {"ok": True, "data": parsed, "raw": text}
        return {"ok": False, "data": text, "raw": text}

    async def stream(self, query: str):
        """保留接口签名，但不产出（server 不支持 streaming）"""
        text = await self.send(query)
        yield text


def _extract_agent_text(data: dict) -> str:
    """从 A2A JSON-RPC 响应中提取 agent 回复文本"""
    try:
        history = data["result"]["task"]["history"]
        if history:
            parts = history[0].get("parts", [])
            if parts:
                return parts[0].get("text", "")
        return ""
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"提取 agent 文本失败: {e}, data={str(data)[:200]}")
        return ""


def _extract_json(text: str) -> dict | None:
    """从文本中提取 JSON（处理 ```json 包裹）"""
    import re
    # 去掉 ```json ... ``` 包裹
    m = re.search(r"```json\s*(\{[^}]*(?:\{[^}]*\}[^}]*)*\})\s*```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 兜底：找第一个 { 到最后一个 }
    j_start = text.find("{")
    j_end = text.rfind("}")
    if j_start >= 0 and j_end > j_start:
        try:
            return json.loads(text[j_start:j_end + 1])
        except json.JSONDecodeError:
            pass
    return None


async def get_client() -> A2AClientWrapper:
    """获取或创建全局 A2A 客户端实例"""
    global _client
    if _client is None:
        _client = A2AClientWrapper()
        logger.info("[A2A] Client initialized (non-streaming)")
    return _client


# ─── 快捷函数 ────────────────────────────────────────────────────

async def quick_send(query: str) -> str:
    """一行发送任务（自动建 client）"""
    client = await get_client()
    return await client.send(query)


if __name__ == "__main__":
    async def demo():
        print("=== A2A Client Demo ===")
        client = await get_client()
        print("✓ Client 就绪")

        result = await client.send("用三个字回答：1+1等于几")
        print(f"文本结果: {result[:200]}")

        r = await client.send_structured(
            "回答以下JSON问题，直接输出JSON："
            "512480 ETF 最新价0.89元，跌-2.1%。"
            "输出：{\"code\":\"512480\",\"summary\":\"一句话摘要\"}"
        )
        print(f"\n结构化结果 ok={r['ok']}")
        if r["ok"]:
            print(f"Parsed: {r['data']}")
        else:
            print(f"Raw: {r['raw'][:200]}")

        await client.close()

    asyncio.run(demo())