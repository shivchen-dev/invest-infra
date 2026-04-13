# MEMORY.md - Agent Bridge 项目

## 热锚点 (Quick Links)

### 项目位置
- **项目目录**: `projects/active/agent-bridge/`
- **核心库**: `src/deepseek_bridge.py` ⭐
- **使用示例**: `examples/` ⭐
- **学习记录**: `.learnings/LEARNINGS.md`

### 快速开始
```bash
cd projects/active/agent-bridge
python3 examples/chat_simple.py
```

### 核心功能
| 功能 | 文件 | 状态 |
|------|------|------|
| 持久化登录 | `deepseek_bridge.py` | ✅ |
| 话题管理 | `list_topics/switch_topic/new_chat` | ✅ |
| 人类行为模拟 | `human_behavior_v2.py` | ✅ |

---

## SYS-20260405-001 Agent Bridge 项目命名与定位

**类型**: system-config  
**时间**: 2026-04-05  
**状态**: active  
**优先级**: P1

### 项目定位
**Agent Bridge** - 多智能体（Multi-Agent）对话桥接系统

支持平台：
- ✅ DeepSeek（生产就绪）
- ✅ Microsoft Copilot（可用）
- 📝 Claude（计划中）
- 📝 GPT（计划中）

### 演进历史
- **v1.0** - `copilot-bridge`（单一平台）
- **v2.0** - `agent-bridge`（多平台、多智能体支持）

### 项目结构
```
agent-bridge/
├── src/           # 核心库（7个模块）
├── examples/      # 生产示例（3个）⭐
├── tests/         # 核心测试（2个）
├── archive/       # 历史归档
└── data/          # 数据目录
```

**详情**: 见 `README.md` 和 `PROJECT.md`

---

## SYS-20260405-002 多标签页登录检测模式

**类型**: best-practice  
**时间**: 2026-04-05  
**状态**: active  
**优先级**: P0

### 核心模式
使用持久化上下文时，检查**所有标签页**而非单个：

```python
pages = context.pages
for page in pages:
    html = await page.content()
    if "登录" not in html:
        self.page = page  # 使用已登录的标签页
        return True
```

### 原因
- 避免 `goto()` 创建新页面破坏现有登录状态
- 正确处理 `about:blank` 默认标签页

### 应用
- `src/deepseek_bridge.py` `ensure_login()`
- 后续其他 Bridge 实现应遵循此模式

---

## SYS-20260405-003 代码组织规范

**类型**: convention  
**时间**: 2026-04-05  
**状态**: active

### 目录分工
| 目录 | 用途 | 示例 |
|------|------|------|
| `examples/` | 生产就绪示例 | `chat_simple.py` |
| `tests/` | 核心测试 | `full_auto_login.py` |
| `archive/` | 历史归档 | 旧测试脚本 |

### 原则
- 新功能先写测试，稳定后移入 `examples/`
- `examples/` 中的代码必须可运行、有文档

---

## 记忆同步记录

| 时间 | 变更 | 位置 |
|------|------|------|
| 2026-04-05 | Agent Bridge 项目初始化 | memory/2026-04-05.md |
| 2026-04-05 | 多标签页检测模式 | .learnings/LEARNINGS.md |

---

*Last updated: 2026-04-05*