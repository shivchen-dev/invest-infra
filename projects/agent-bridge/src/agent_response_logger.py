#!/usr/bin/env python3
"""
Agent Response Logger
自动存储智能体回复（文字+截图+元信息）

目录结构：
data/agent_responses/{agent_name}/{timestamp}/
    - response.txt     # 完整回复文字
    - screenshot.png   # 截图
    - metadata.json    # 元信息
"""
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


class AgentResponseLogger:
    """
    智能体回复日志记录器
    
    使用示例：
    ```python
    logger = AgentResponseLogger("deepseek")
    logger.save_response(
        text="DeepSeek 回复内容...",
        screenshot_path="/path/to/screenshot.png",
        query="用户问题",
        metadata={"model": "deepseek-chat"}
    )
    ```
    """
    
    def __init__(self, agent_name: str, base_dir: str = "data/agent_responses"):
        """
        初始化日志记录器
        
        Args:
            agent_name: 智能体名称（如 deepseek, copilot, openai）
            base_dir: 基础存储目录
        """
        self.agent_name = agent_name
        self.base_dir = Path(base_dir)
        self.agent_dir = self.base_dir / agent_name
        
        # 创建目录
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        
    def _generate_timestamp(self) -> str:
        """生成时间戳（格式：2026-04-05_090830）"""
        return datetime.now().strftime("%Y-%m-%d_%H%M%S")
    
    def _create_session_dir(self, timestamp: str) -> Path:
        """创建会话目录"""
        session_dir = self.agent_dir / timestamp
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
    
    def save_response(
        self,
        text: str,
        screenshot_path: Optional[str] = None,
        query: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        保存智能体回复
        
        Args:
            text: 回复文字内容
            screenshot_path: 截图文件路径（可选）
            query: 用户问题/查询
            metadata: 额外元信息（可选）
        
        Returns:
            保存的文件路径字典
        """
        timestamp = self._generate_timestamp()
        session_dir = self._create_session_dir(timestamp)
        
        result = {
            "timestamp": timestamp,
            "session_dir": str(session_dir),
        }
        
        # 1. 保存回复文字
        response_file = session_dir / "response.txt"
        with open(response_file, 'w', encoding='utf-8') as f:
            f.write(f"Query: {query}\n")
            f.write(f"Agent: {self.agent_name}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write("=" * 70 + "\n\n")
            f.write(text)
        result["response_file"] = str(response_file)
        
        # 2. 复制截图（如果提供）
        if screenshot_path and os.path.exists(screenshot_path):
            import shutil
            screenshot_target = session_dir / "screenshot.png"
            shutil.copy2(screenshot_path, screenshot_target)
            result["screenshot_file"] = str(screenshot_target)
        
        # 3. 保存元信息
        meta = {
            "agent": self.agent_name,
            "timestamp": timestamp,
            "query": query,
            "response_length": len(text),
            "has_screenshot": screenshot_path is not None,
        }
        if metadata:
            meta.update(metadata)
        
        metadata_file = session_dir / "metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        result["metadata_file"] = str(metadata_file)
        
        # 4. 更新索引文件
        self._update_index(timestamp, query, text[:100])
        
        print(f"✅ 回复已保存: {session_dir}")
        return result
    
    def _update_index(self, timestamp: str, query: str, preview: str):
        """更新索引文件"""
        index_file = self.agent_dir / "index.md"
        
        # 读取现有内容
        existing_content = ""
        if index_file.exists():
            with open(index_file, 'r', encoding='utf-8') as f:
                existing_content = f.read()
        
        # 创建新条目
        new_entry = f"""
## {timestamp}

- **Query**: {query[:80]}...
- **Preview**: {preview[:100]}...
- **Directory**: [{timestamp}](./{timestamp}/)
- **Files**: [response.txt](./{timestamp}/response.txt) | [screenshot.png](./{timestamp}/screenshot.png)

---
"""
        
        # 写入（新条目在前）
        header = f"# {self.agent_name.upper()} Agent Responses Index\n\n"
        header += f"Auto-generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(header + new_entry + "\n" + existing_content.replace(header, ""))
    
    def list_sessions(self) -> list:
        """列出所有会话目录"""
        sessions = []
        for item in sorted(self.agent_dir.iterdir()):
            if item.is_dir() and item.name != "__pycache__":
                sessions.append({
                    "timestamp": item.name,
                    "path": str(item),
                })
        return sessions
    
    def get_session(self, timestamp: str) -> Optional[Dict[str, Any]]:
        """获取指定会话的内容"""
        session_dir = self.agent_dir / timestamp
        if not session_dir.exists():
            return None
        
        result = {
            "timestamp": timestamp,
            "path": str(session_dir),
        }
        
        # 读取 response.txt
        response_file = session_dir / "response.txt"
        if response_file.exists():
            with open(response_file, 'r', encoding='utf-8') as f:
                result["response"] = f.read()
        
        # 读取 metadata.json
        metadata_file = session_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file, 'r', encoding='utf-8') as f:
                result["metadata"] = json.load(f)
        
        # 检查截图
        screenshot_file = session_dir / "screenshot.png"
        if screenshot_file.exists():
            result["has_screenshot"] = True
            result["screenshot_path"] = str(screenshot_file)
        
        return result


# 快捷函数
def log_deepseek_response(text: str, screenshot_path: Optional[str] = None, query: str = ""):
    """记录 DeepSeek 回复"""
    logger = AgentResponseLogger("deepseek")
    return logger.save_response(text, screenshot_path, query)


def log_copilot_response(text: str, screenshot_path: Optional[str] = None, query: str = ""):
    """记录 Copilot 回复"""
    logger = AgentResponseLogger("copilot")
    return logger.save_response(text, screenshot_path, query)


# 示例用法
if __name__ == "__main__":
    # 测试
    logger = AgentResponseLogger("test")
    result = logger.save_response(
        text="这是一个测试回复。\n\n## 要点\n1. 第一点\n2. 第二点",
        query="测试问题",
        metadata={"test": True}
    )
    print(f"保存结果: {result}")
