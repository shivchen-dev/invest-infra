# Agent Bridge 模板详解

> 以下模板通过 `bridge.chat(message, template=)` 调用，模板只是给 AI 的提示词增强。

## general_query

**用途**：通用查询，适合大多数问题

```python
result = await bridge.chat("解释一下什么是 MVC 架构", template="general_query")
```

---

## code_review

**用途**：代码审查，AI 会分析代码质量、性能、安全性

```python
result = await bridge.chat(
    "审查这段代码的性能问题：\ndef fib(n): return n if n < 2 else fib(n-1) + fib(n-2)",
    template="code_review"
)
```

**AI 会关注**：
- 代码结构和可读性
- 性能问题（时间/空间复杂度）
- 安全漏洞（SQL注入、XSS等）
- 边界情况处理
- 错误处理

---

## error_analysis

**用途**：错误分析，AI 会诊断错误原因并提供解决方案

```python
result = await bridge.chat(
    "程序启动失败，请分析原因：Connection refused: localhost:8787",
    template="error_analysis"
)
```

**AI 会关注**：
- 错误类型识别
- 错误堆栈分析
- 根本原因定位
- 解决方案建议
- 预防措施

---

## architecture_design

**用途**：架构设计，AI 会提供系统设计方案

```python
result = await bridge.chat(
    "设计一个日处理千万请求的爬虫系统",
    template="architecture_design"
)
```

**AI 会关注**：
- 系统架构图
- 核心组件设计
- 技术选型理由
- 扩展性考虑
- 容灾方案

---

## element_locating

**用途**：元素定位（用于浏览器操作场景）

```python
result = await bridge.chat(
    "点击登录按钮",
    template="element_locating"
)
```
