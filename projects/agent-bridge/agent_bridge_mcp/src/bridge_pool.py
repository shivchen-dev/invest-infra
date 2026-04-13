"""
Bridge Pool - Bridge 实例池管理

按 platform 缓存 Bridge 实例，避免重复启动浏览器
"""
import asyncio
import sys
from pathlib import Path
from typing import Optional

# 添加 Bridge 路径
BRIDGE_ROOT = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(BRIDGE_ROOT))

from deepseek_bridge import DeepSeekBridge
from qwen_bridge import QwenBridge


class BridgePool:
    """
    Bridge 连接池
    
    管理 DeepSeek/Qwen Bridge 实例，全局只有一个
    """
    
    _instance: Optional["BridgePool"] = None
    
    def __init__(self):
        self._bridges: dict[str, any] = {}
        self._locks: dict[str, asyncio.Lock] = {
            "deepseek": asyncio.Lock(),
            "qwen": asyncio.Lock(),
        }
    
    @classmethod
    def get_instance(cls) -> "BridgePool":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def _get_bridge_class(self, platform: str):
        """获取 platform 对应的 Bridge 类"""
        classes = {
            "deepseek": DeepSeekBridge,
            "qwen": QwenBridge,
        }
        if platform not in classes:
            raise ValueError(f"Unknown platform: {platform}")
        return classes[platform]
    
    def _get_profile_dir(self, platform: str) -> str:
        """获取 platform 对应的 profile 目录"""
        base = BRIDGE_ROOT.parent
        profiles = {
            "deepseek": f"{base}/data/browser_profile_deepseek",
            "qwen": f"{base}/data/browser_profile_qwen",
        }
        return profiles.get(platform, f"{base}/data/browser_profile_{platform}")
    
    async def get_bridge(self, platform: str):
        """
        获取 Bridge 实例（按需创建）
        
        Args:
            platform: "deepseek" | "qwen"
        
        Returns:
            Bridge 实例
        """
        if platform not in self._bridges:
            async with self._locks.get(platform, asyncio.Lock()):
                # 双重检查
                if platform not in self._bridges:
                    bridge_class = self._get_bridge_class(platform)
                    profile_dir = self._get_profile_dir(platform)
                    
                    bridge = bridge_class()
                    bridge.user_data_dir = profile_dir
                    
                    # 启动浏览器
                    if not await bridge.start():
                        raise RuntimeError(f"Failed to start {platform} bridge")
                    
                    # 确保登录
                    if not await bridge.ensure_login(timeout=120):
                        raise RuntimeError(f"{platform} login failed")
                    
                    self._bridges[platform] = bridge
        
        return self._bridges[platform]
    
    async def close_all(self):
        """关闭所有 Bridge"""
        for platform, bridge in self._bridges.items():
            try:
                await bridge.close()
            except Exception as e:
                print(f"Error closing {platform} bridge: {e}")
        self._bridges.clear()


# 全局实例
pool = BridgePool.get_instance()
