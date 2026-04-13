"""
API 测试模拟器 - 无需登录测试接口逻辑
"""
import sys
sys.path.insert(0, 'src')

from api.validators import TemplateValidator
from api.responses import success_response, error_response
from api.bridge_factory import BridgeFactory

print("=" * 50)
print("Agent Bridge API 完整流程测试")
print("=" * 50)

# 模拟 Bridge 状态
class MockBridge:
    is_initialized = True
    is_logged_in = True
    
    def get_current_topic(self):
        return "test_topic_123"
    
    async def chat(self, message):
        return f"[模拟回复] 收到消息: {message}"

# 注入模拟 Bridge
BridgeFactory._instances["deepseek"] = MockBridge()

print("\n[1] 平台列表查询")
print("-" * 30)
platforms = BridgeFactory.list_platforms()
print(f"平台: {platforms}")

print("\n[2] 健康检查")
print("-" * 30)
bridge = BridgeFactory.get_bridge("deepseek")
print(f"初始化: {bridge.is_initialized}")
print(f"登录: {bridge.is_logged_in}")

print("\n[3] 模板验证测试")
print("-" * 30)

# 3.1 无效请求
print("\n3.1 无效请求 (缺少 template):")
is_valid, result = TemplateValidator.validate({"message": "测试"})
print(f"  通过: {is_valid}")
print(f"  错误: {result['error']['code']}")

# 3.2 有效请求
print("\n3.2 有效请求:")
is_valid, result = TemplateValidator.validate({
    "template": "general_query",
    "message": "你好，请介绍一下自己"
})
print(f"  通过: {is_valid}")
print(f"  模板: {result['template']}")

print("\n[4] 模拟对话流程")
print("-" * 30)
import asyncio

async def mock_chat():
    # 模拟 /ask 端点处理
    request_data = {
        "template": "general_query",
        "message": "API 测试消息"
    }
    
    # 验证
    is_valid, result = TemplateValidator.validate(request_data)
    if not is_valid:
        return error_response("VALIDATION_FAILED", "验证失败")
    
    # 获取 Bridge
    bridge = BridgeFactory.get_bridge("deepseek")
    if not bridge:
        return error_response("BRIDGE_NOT_FOUND", "Bridge 不存在")
    
    # 检查登录
    if not bridge.is_logged_in:
        return error_response("NOT_LOGGED_IN", "未登录 (实际环境需要登录)")
    
    # 发送消息
    response_text = await bridge.chat(request_data["message"])
    
    return success_response({
        "response": response_text,
        "topic_id": bridge.get_current_topic(),
        "template": request_data["template"],
        "rounds_used": 1
    })

result = asyncio.run(mock_chat())
print(f"  成功: {result['success']}")
print(f"  回复: {result['data']['response']}")
print(f"  话题: {result['data']['topic_id']}")

print("\n" + "=" * 50)
print("✅ 完整流程测试通过 (模拟模式)")
print("=" * 50)
print("\n注意: 实际环境需要 DeepSeek 登录状态")
print("当前测试使用 Mock Bridge 验证接口逻辑")
