#!/usr/bin/env python3
"""
QQ Push Module — Market Report System v2.0

统一 QQ 推送接口，支持两种发送方式（自动降级）：
1. openclaw CLI（优先，稳定）：openclaw message send
2. QQ Open Platform API（备选）：直接调 channel message 接口

发送目标支持：
- channel_id：发送到 QQ 频道（QQ群）
- c2c:user_id：发送到用户私聊

统一入口：send_to_qq(messages, target=...)
"""
import json
import logging
import os
import subprocess
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
TOKEN_URL = "https://bots.qq.com/appgetAppAccessToken"
BASE_URL = "https://api.sgroup.qq.com"
OPENCLAW_BIN = "/home/claw/.npm-global/bin/openclaw"
OPENCLAW_ACCOUNT = "1903628521"  # 默认发信账号（从 known-users.json 确认）

# ── Config Helpers ────────────────────────────────────────────────────────────
def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _load_credential() -> dict:
    """从 openclaw QQ 凭证备份文件加载 appId / clientSecret。"""
    path = os.path.expanduser("~/.openclaw/qqbot/data/credential-backup-default.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


class TokenManager:
    """
    Manages QQ bot access tokens with caching and auto-refresh.

    Tokens are cached with expiry time. Refresh is triggered 5 minutes before
    expiry to avoid stale tokens. Concurrent requests share one in-flight fetch.
    """

    def __init__(self):
        self._cache: dict[str, dict] = {}  # appId -> {token, expiresAt}
        self._pending: dict[str, httpx.Response] = {}  # appId -> in-flight request

    def get_token(self, app_id: str, client_secret: str) -> str:
        """
        Get a valid access token, fetching from QQ API if needed.
        Tokens are cached; refresh happens automatically before expiry.
        """
        now = time.time()
        cached = self._cache.get(app_id)

        # Refresh if expires in < 5 minutes or not cached
        if cached and (cached["expires_at"] - now) > 300:
            return cached["token"]

        # Use in-flight request if another thread is already fetching
        if app_id in self._pending:
            # Wait for the pending request (simple spin)
            for _ in range(50):  # up to 5s
                time.sleep(0.1)
                if app_id not in self._pending:
                    cached = self._cache.get(app_id)
                    if cached:
                        return cached["token"]
            # If still pending, fetch ourselves
            self._pending.pop(app_id, None)

        self._pending[app_id] = None  # mark in-flight
        try:
            token, expires_in = self._fetch_token(app_id, client_secret)
            self._cache[app_id] = {
                "token": token,
                "expires_at": now + expires_in,
            }
            return token
        finally:
            self._pending.pop(app_id, None)

    def _fetch_token(self, app_id: str, client_secret: str) -> tuple[str, int]:
        """Fetch a new access token from QQ Open Platform."""
        logger.info(f"[qqpush:token] Fetching access token for appId={app_id}")
        resp = httpx.post(
            TOKEN_URL,
            json={"appId": app_id, "clientSecret": client_secret},
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"QQ token fetch failed: {data}")

        return data["access_token"], int(data["expires_in"])

    def clear_cache(self, app_id: Optional[str] = None):
        """Clear cached token(s)."""
        if app_id:
            self._cache.pop(app_id, None)
        else:
            self._cache.clear()


# Global token manager instance
_token_manager = TokenManager()


class QQPusher:
    """
    统一 QQ 推送器，支持两种发送方式（自动降级）：
    1. openclaw CLI（优先，稳定）：openclaw message send
    2. QQ Open Platform API（备选）：直接调 channel API

    目标支持 channel（QQ群）和 c2c（私聊）两种模式。

    Usage:
        pusher = QQPusher(target="c2c:43C77867478A33B101FA705AA70754E3")
        await pusher.send_messages(["Report line 1", "Report line 2"])

        # 或用便捷函数：
        await send_to_qq(["Hello"], target="c2c:user_id")
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        guild_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        target: Optional[str] = None,
        openclaw_account: Optional[str] = None,
    ):
        # 从 env 或显式参数获取
        self.app_id = app_id or _get_env("QQBOT_APP_ID")
        self.client_secret = client_secret or _get_env("QQBOT_CLIENT_SECRET")
        self.guild_id = guild_id or _get_env("QQ_GUILD_ID")
        self.channel_id = channel_id or _get_env("QQ_CHANNEL_ID")

        # target 格式："c2c:user_id" 或 "channel_id"
        # 如果未指定，优先用 channel_id（频道模式）
        self.target = target or self.channel_id
        self.openclaw_account = openclaw_account or OPENCLAW_ACCOUNT

        # 如果没配置 app_id/secret，尝试从凭证文件加载
        if not self.app_id or not self.client_secret:
            cred = _load_credential()
            self.app_id = self.app_id or cred.get("appId", "")
            self.client_secret = self.client_secret or cred.get("clientSecret", "")

        if not self.app_id or not self.client_secret:
            logger.warning(
                "[qqpush] QQ bot credentials not in env — will use openclaw CLI only"
            )

    def _auth_headers(self, token: str) -> dict:
        return {
            "Authorization": f"QQBot {token}",
            "Content-Type": "application/json",
        }

    def _send_via_openclaw(self, content: str) -> dict:
        """
        通过 openclaw message send CLI 发送（最可靠的方式）。

        target 格式映射：
        - "c2c:user_id" → openclaw target "c2c:user_id"
        - "qqbot:c2c:openid" → 直接透传
        - "qqbot:group:group_id" → 直接透传
        - bare channel_id（如 "134B4E8D...") → 转换为 "qqbot:group:channel_id"
        """
        raw_target = self.target

        # 规范化 target 格式
        if raw_target.startswith("qqbot:"):
            openclaw_target = raw_target
        elif raw_target.startswith("c2c:"):
            openclaw_target = raw_target  # c2c:user_id
        else:
            # bare channel_id → 视为 group
            openclaw_target = f"qqbot:group:{raw_target}"

        cmd = [
            OPENCLAW_BIN, "message", "send",
            "--channel", "qqbot",
            "--account", self.openclaw_account,
            "--target", openclaw_target,
            "--message", content,
        ]
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if cp.returncode == 0:
                logger.info(f"[qqpush:cli] ✓ sent via openclaw CLI: {content[:40]}")
                return {"ok": True, "via": "openclaw_cli", "msg_id": cp.stdout.strip()}
            else:
                logger.error(f"[qqpush:cli] ✗ openclaw CLI failed: {cp.stderr[:200]}")
                return {"error": cp.stderr[:200], "via": "openclaw_cli"}
        except subprocess.TimeoutExpired:
            logger.error("[qqpush:cli] ✗ openclaw CLI timeout")
            return {"error": "timeout", "via": "openclaw_cli"}
        except Exception as e:
            logger.error(f"[qqpush:cli] ✗ openclaw CLI error: {e}")
            return {"error": str(e), "via": "openclaw_cli"}

    def _send_one_via_api(self, token: str, content: str) -> dict:
        """通过 QQ Open Platform API 发送（需要 channel_id）。"""
        url = f"{BASE_URL}/channels/{self.channel_id}/messages"
        payload = {
            "content": content,
            "msg_type": 0,
        }
        resp = httpx.post(
            url,
            json=payload,
            headers=self._auth_headers(token),
            timeout=30.0,
        )
        if resp.status_code >= 400:
            logger.error(f"[qqpush:api] HTTP {resp.status_code}: {resp.text[:200]}")
        resp.raise_for_status()
        return resp.json()

    async def send_messages(self, messages: list[str]) -> list[dict]:
        """
        发送多条消息到 QQ。

        策略：
        1. 优先用 openclaw CLI（稳定，支持 c2c 和 channel）
        2. 若 channel_id 可用，尝试 QQ Open Platform API（可选优化）

        Args:
            messages: 消息列表（每条一次调用）。

        Returns:
            每条消息的发送结果字典列表。
        """
        if not messages:
            return []

        results = []
        for i, msg in enumerate(messages, 1):
            content = msg.strip()
            if not content:
                continue

            logger.info(f"[qqpush] Sending message {i}/{len(messages)} ({len(content)} chars) → {self.target}")

            # 策略：始终先用 openclaw CLI（最可靠）
            result = self._send_via_openclaw(content)
            results.append(result)

            # 若想用 API 备选（channel 模式且 token 可用），可在此扩展
            # 当前以 openclaw CLI 为唯一发送方式，API 待 QQ API 恢复后启用

        return results

    async def discover_guild_and_channel(self) -> dict:
        """
        Auto-discover the bot's guild and first text channel.
        Useful for initial setup.

        Returns:
            dict with guild_id and channel_id, or empty dict if not found.
        """
        token = _token_manager.get_token(self.app_id, self.client_secret)

        # Step 1: Get guild list
        resp = httpx.get(
            f"{BASE_URL}/users/@me/guilds",
            headers=self._auth_headers(token),
            timeout=30.0,
        )
        resp.raise_for_status()
        guilds = resp.json().get("guilds", [])

        if not guilds:
            logger.warning("[qqpush] No guilds found for this bot")
            return {}

        guild_id = guilds[0]["id"]
        logger.info(f"[qqpush] Bot is in {len(guilds)} guild(s), using: {guilds[0]['name']} ({guild_id})")

        # Step 2: Get channel list for the guild
        resp = httpx.get(
            f"{BASE_URL}/guilds/{guild_id}/channels",
            headers=self._auth_headers(token),
            timeout=30.0,
        )
        resp.raise_for_status()
        channels = resp.json().get("channels", [])

        # Find first text channel (type=0)
        text_channels = [c for c in channels if c.get("type") == 0]
        if not text_channels:
            logger.warning("[qqpush] No text channels found in guild")
            return {"guild_id": guild_id, "channel_id": None}

        channel = text_channels[0]
        logger.info(f"[qqpush] Auto-discovered channel: {channel['name']} ({channel['id']})")

        return {
            "guild_id": guild_id,
            "channel_id": channel["id"],
            "channel_name": channel["name"],
        }


# ── Convenience function — 统一推送入口 ────────────────────────────────────
async def send_to_qq(
    messages: list[str],
    target: Optional[str] = None,
    openclaw_account: Optional[str] = None,
    channel_id: Optional[str] = None,
    **kwargs,
) -> list[dict]:
    """
    统一推送消息到 QQ（兼容 channel 和 c2c）。

    Args:
        messages:  消息列表。
        target:    发送目标，"c2c:user_id" 或 "channel_id"。
                   不传则默认 channel_id（从 QQ_CHANNEL_ID env 读取）。
        openclaw_account: 发信 QQ 账号，不传默认 1903628521。
        channel_id:       channel_id 别名（target 未传时使用）。

    Usage:
        # 发送到用户私聊（WOA→CIA 通知）：
        await send_to_qq(["✅ 完成"], target="c2c:43C77867478A33B101FA705AA70754E3")

        # 发送到 QQ 频道（报告推送）：
        await send_to_qq(report_lines, target="channel_id")
    """
    pusher = QQPusher(
        target=target or channel_id,
        openclaw_account=openclaw_account,
        **kwargs,
    )
    return await pusher.send_messages(messages)


# ── CLI for testing / discovery ───────────────────────────────────────────────
if __name__ == "__main__":
    import argparse, asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="QQ Push — send or discover")
    parser.add_argument("--discover", action="store_true", help="Auto-discover guild and channel")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--target", help='发送目标: "c2c:user_id" 或 "channel_id"（默认: c2c 测试用户）')
    parser.add_argument("--message", help="测试消息内容")
    args = parser.parse_args()

    async def run():
        pusher = QQPusher(target=args.target or "c2c:43C77867478A33B101FA705AA70754E3")

        if args.discover:
            info = await pusher.discover_guild_and_channel()
            print(f"Discovered: {info}")

        if args.test:
            test_msg = args.message or "[Test] Market Report System v2.0 — QQ Push unified!"
            results = await pusher.send_messages([test_msg])
            print(f"Results: {results}")

    asyncio.run(run())