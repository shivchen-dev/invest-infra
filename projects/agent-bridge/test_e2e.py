"""
API 端到端测试 - 简化版
直接调用 Bridge，不通过 HTTP 服务
"""
import sys
sys.path.insert(0, 'src')

import asyncio
from deepseek_bridge import DeepSeekBridge
from api.validators import TemplateValidator
from api.responses import success_response, error_response

print("=" * 60)
print("Agent Bridge API 端到端测试 (直接调用)")
print("=" * 60)

async def test_api_flow():
    """模拟完整的 API 调用流程"""
    
    # 模拟请求
    request_data = {
        "template": "general_query",
        "message": "你好 DeepSeek，我是 Agent Bridge，请多关照！"
    }
    
    print(f"\n[1] 收到请求: {request_data}")
    
    # 1. 模板验证
    print("\n[2] 模板验证...")
    is_valid, result = TemplateValidator.validate(request_data)
    if not is_valid:
        print(f"❌ 验证失败: {result['error']['code']}")
        return
    print(f"✅ 验证通过: {result['template']}")
    
    # 2. 获取 Bridge
    print("\n[3] 启动 DeepSeek Bridge...")
    bridge = DeepSeekBridge()
    started = await bridge.start()
    if not started:
        print("❌ Bridge 启动失败")
        return
    print("✅ Bridge 启动成功")
    
    # 3. 检查登录
    print("\n[4] 检查登录状态...")
    is_logged_in = await bridge.ensure_login()
    if not is_logged_in:
        print("❌ 未登录")
        await bridge.close()
        return
    print("✅ 已登录")
    
    # 4. 发送消息
    print(f"\n[5] 发送消息: {request_data['message']}")
    print("-" * 40)
    response = await bridge.chat(request_data['message'])
    
    if not response.success:
        print(f"❌ 对话失败: {response.error}")
        await bridge.close()
        return
    
    print("✅ 收到回复")
    print("-" * 40)
    
    # 5. 构建响应
    print("\n[6] 构建 API 响应...")
    data = {
        "response": response.text,
        "topic_id": bridge.get_current_topic(),
        "template": request_data.get("template"),
        "rounds_used": 1,
        "success": response.success
    }
    
    # 安全地添加元数据
    if response.metadata:
        safe_metadata = {}
        from pathlib import Path
        for key, value in response.metadata.items():
            if isinstance(value, (str, int, float, bool, list, dict)) or value is None:
                safe_metadata[key] = value
            elif isinstance(value, Path):
                safe_metadata[key] = str(value)
        if safe_metadata:
            data["metadata"] = safe_metadata
    
    api_response = success_response(data)
    
    # 输出结果
    print("\n" + "=" * 60)
    print("API 响应:")
    print("=" * 60)
    import json
    print(json.dumps(api_response, ensure_ascii=False, indent=2))
    
    await bridge.close()
    
    print("\n" + "=" * 60)
    print("✅ 端到端测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_api_flow())
