# Session: 2026-04-07 - Agent Bridge 开发知识库

## 任务
根据 DeepSeek Bridge 开发经验，创建技术知识库，为第三方智能体接入提供技术沉淀。

## 成果

### 创建文件
- `docs/BRIDGE_DEVELOPMENT_KB.md` - Agent Bridge 开发知识库 (12KB)

### 知识库内容
1. **架构概述** - 整体架构图和核心组件说明
2. **Bridge 开发规范** - 目录结构、类模板、选择器策略
3. **持久化登录实现** - 核心机制、状态保持、多标签页处理
4. **人类行为模拟** - 模拟器组件、核心方法、打字模拟
5. **API 服务开发** - 服务架构、端点规范、请求响应格式
6. **systemd 服务配置** - 服务文件模板、安装命令
7. **开发检查清单** - Bridge实现、API服务、部署检查
8. **常见问题** - 登录、元素定位、回复提取、风控处理

### 技术要点提炼

#### 持久化登录关键
```python
context = await p.chromium.launch_persistent_context(
    user_data_dir=self.user_data_dir,  # 关键！
    headless=False,
)
```

#### 多标签页登录检测
```python
for page in self.context.pages:
    html = await page.content()
    if "登录" not in html:
        self.page = page
        self.is_logged_in = True
        return True
```

#### 人类行为模拟参数
- 打字延迟: 50-200ms/字符
- 点击前停顿: 0.1-0.5s
- 思考停顿: 3-12s
- 回复等待: 20-30s

### 经验总结
1. 元素选择器优先使用 placeholder 属性
2. 登录状态检测结合多个特征（登录按钮不存在 + 页面内容长度）
3. 多标签页检查可避免重复登录
4. 虚拟桌面环境（Xvfb）确保浏览器正常渲染

### 后续复用
- 千问 Bridge 开发
- Claude Bridge 开发
- GPT Bridge 开发
- 其他平台 Bridge 开发

---

**记录时间**: 2026-04-07 10:08  
**知识库位置**: `projects/active/agent-bridge/docs/BRIDGE_DEVELOPMENT_KB.md`
