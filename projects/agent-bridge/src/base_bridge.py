#!/usr/bin/env python3
"""
Base Bridge - Agent Bridge 公共基类
提供所有 Bridge 的通用功能
"""
import asyncio
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright, Page, BrowserContext
from config import DEFAULT_VIEWPORT, TIMEOUTS, BROWSER_ARGS


@dataclass
class BridgeResponse:
    """Bridge 统一响应结构"""
    text: str
    success: bool = True
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseBridge(ABC):
    """
    Agent Bridge 公共基类
    
    子类必须实现:
    - platform_name: 平台标识
    - login_url: 登录页面URL
    - ensure_login(): 登录状态检测
    """
    
    # 子类必须覆盖
    platform_name: str = "base"
    login_url: str = ""
    
    # 用户数据目录
    user_data_dir: str = ""
    
    def __init__(self):
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_initialized: bool = False
        self.is_logged_in: bool = False
    
    def _cleanup_environment(self):
        """
        清理环境 - 每次启动前调用
        确保没有残留的 Chromium 进程和锁文件
        """
        import subprocess
        import time
        
        # 1. 只清理锁文件，不强制杀进程
        # （杀进程可能导致挂起，让 Playwright 自己处理）
        if self.user_data_dir:
            lock_files = ['SingletonLock', 'SingletonSocket', 'SingletonCookie']
            for lock_file in lock_files:
                lock_path = os.path.join(self.user_data_dir, lock_file)
                if os.path.exists(lock_path):
                    try:
                        os.remove(lock_path)
                        print(f"[Cleanup] 已删除锁文件: {lock_file}")
                    except Exception:
                        pass
        
        # 2. 重置状态，确保下次会重新初始化
        self.is_initialized = False
        self.context = None
        self.page = None
        
        print("[Cleanup] 环境清理完成")
    
    async def start(self) -> bool:
        """
        启动浏览器
        
        Returns:
            bool: 是否启动成功
        """
        # 每次启动前清理环境，防止残留进程/锁文件导致挂起
        self._cleanup_environment()
        
        # 启动 Xvfb
        if not self._start_xvfb():
            print(f"❌ [{self.platform_name}] Xvfb 启动失败")
            return False
        
        # 确保用户数据目录存在
        if self.user_data_dir:
            os.makedirs(self.user_data_dir, exist_ok=True)
        
        p = await async_playwright().start()
        
        # 使用持久化上下文保持登录状态
        self.context = await p.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            args=BROWSER_ARGS,
            viewport=DEFAULT_VIEWPORT,
            locale='zh-CN',
        )
        
        # 获取或创建页面
        pages = self.context.pages
        self.page = pages[0] if pages else await self.context.new_page()
        
        self.is_initialized = True
        print(f"✅ [{self.platform_name}] Bridge 已启动")
        return True
    
    def _start_xvfb(self, display: str = ":99") -> bool:
        """
        启动 Xvfb 虚拟桌面
        
        Args:
            display: 显示编号
            
        Returns:
            bool: 是否成功
        """
        import subprocess
        import time
        
        try:
            result = subprocess.run(
                ['pgrep', '-f', f'Xvfb {display}'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                subprocess.Popen([
                    'Xvfb', display, '-screen', '0', '1920x1080x24',
                    '-ac', '+extension', 'RANDR', '-noreset'
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
            os.environ['DISPLAY'] = display
            return True
        except Exception as e:
            print(f"❌ Xvfb 启动失败: {e}")
            return False
    
    @abstractmethod
    async def ensure_login(self, timeout: int = 120) -> bool:
        """
        确保已登录
        
        Args:
            timeout: 等待登录超时时间（秒）
            
        Returns:
            bool: 是否已登录
        """
        pass
    
    @abstractmethod
    async def chat(self, message: str, **kwargs) -> BridgeResponse:
        """
        发送消息并获取回复
        
        Args:
            message: 消息内容
            **kwargs: 平台特定参数
            
        Returns:
            BridgeResponse: 统一响应结构
        """
        pass
    
    async def get_status(self) -> Dict[str, Any]:
        """
        获取当前状态
        
        Returns:
            状态字典
        """
        if not self.page:
            return {"initialized": False}
        
        return {
            "platform": self.platform_name,
            "initialized": self.is_initialized,
            "logged_in": self.is_logged_in,
            "url": self.page.url,
        }
    
    async def close(self):
        """关闭浏览器"""
        if self.context:
            await self.context.close()
            self.is_initialized = False
            self.is_logged_in = False
            print(f"✅ [{self.platform_name}] Bridge 已关闭")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
