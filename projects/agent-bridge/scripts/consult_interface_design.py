#!/usr/bin/env python3
"""
使用 DeepSeek Bridge 咨询多智能体接口设计方案
"""
import asyncio
import sys
sys.path.insert(0, '/home/chenjian/.openclaw/workspace-browser/projects/active/agent-bridge/src')

from deepseek_bridge import DeepSeekBridge

async def consult_deepseek():
    """向 DeepSeek 咨询接口设计方案"""
    
    bridge = DeepSeekBridge()
    
    try:
        print("🚀 启动 Bridge 咨询 DeepSeek...")
        await bridge.start()
        
        # 检查登录状态
        is_logged_in = await bridge.ensure_login()
        if not is_logged_in:
            print("❌ 未登录，无法咨询")
            return
        
        # 使用工作流设计模板构建问题
        # 注意：不要在问题开头加任何标签（如 [PRIORITY:xxx]），
        # DeepSeek 会自动提取开头作为话题标题
        question = """【任务背景】
我是 Browser Agent（浏览器自动化执行者），正在开发 Agent Bridge 系统，用于让 OpenClaw 本地其他 AI Agent 能够通过我访问 DeepSeek 进行咨询。

当前系统架构：
- 我已经重构了 DeepSeek Bridge，采用 BaseBridge + TopicManagerMixin 架构
- 其他智能体（如 cb-ecommerce、planner-agent）需要调用我的系统向 DeepSeek 提问
- 需要设计一个接口层，让这些智能体能够规范地提交问题并获取回复

【当前卡点】
1. 接口协议选择：HTTP REST、gRPC、还是其他方式？
2. 模板规范强制：如何让其他智能体必须使用提问模板（element_locating、error_handling 等）？
3. 提问轮数界定：
   - 简单问题可能1轮就够
   - 复杂问题可能需要多轮（confirm → execute → feedback）
   - 如何自动判断何时结束对话？

【已设计流程】
方案草稿：
1. HTTP API Server 接收请求
   - POST /api/v1/ask (单轮)
   - POST /api/v1/conversation/start (开始多轮)
   - POST /api/v1/conversation/{id}/round (继续对话)

2. 模板验证中间件
   - 检查 template 字段
   - 验证 query 是否包含模板要求的必填字段
   - 不符合则返回错误 + 示例

3. 轮数管理
   - 固定轮数：simple=1, normal=3, complex=5
   - 动态判断：检测 DeepSeek 是否给出完整方案
   - 三阶段强制：confirm → execute → feedback

【需要考虑】
- 其他智能体可能有不同的 urgency，需要优先级队列
- 需要限制并发，避免同时多个对话导致混乱
- 需要认证机制，只允许特定智能体访问
- 错误恢复：如果某轮失败，如何重试或回退

【关键问题】
1. 接口协议选择：HTTP REST vs gRPC vs 消息队列？各自的优缺点？
2. 模板规范强制：验证中间件设计是否合理？有更好的方式吗？
3. 轮数界定策略：固定轮数、动态判断、三阶段强制，哪种更适合 Agent 协作场景？
4. 人类操作模拟：我之前的咨询提问是否自然模拟了人类操作？有哪些可以改进的地方？

请从可靠性优先的角度，给出完整的接口设计方案和建议。"""

        print(f"📝 发送咨询问题 ({len(question)} 字符)...")
        
        response = await bridge.chat(
            question,
            metadata={"priority": "reliability", "topic": "多智能体接口设计"},
            wait_for_reply=True,
            save_response=True
        )
        
        if response.success:
            print("\n" + "="*60)
            print("📝 DeepSeek 回复:")
            print("="*60)
            print(response.text)
            print("="*60)
            
            if response.metadata:
                print(f"\n💾 保存位置: {response.metadata.get('saved_path')}")
        else:
            print(f"\n❌ 获取回复失败: {response.error}")
        
        await bridge.close()
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        try:
            await bridge.close()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(consult_deepseek())
