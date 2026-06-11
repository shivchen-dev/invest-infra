# claude-cmd 缺陷分析 & 修复方案

## 缺陷现象

发送多行 paste（如 Task 1/Task 2 的长任务描述）时，supervisor 进入 `handle_prompt` 死循环，迭代次数迅速破万次后超时终止。

## 根因分析

### 计数器设计缺陷（核心 bug）

```python
_PROMPT_COUNT = 0  # 模块级计数器

def _prompt_count() -> int:
    global _PROMPT_COUNT
    _PROMPT_COUNT += 1
    return _PROMPT_COUNT

def handle_prompt() -> bool:
    count = _prompt_count()
    if count > 2:         # ← 致命问题：只允许调用 2 次
        log(f"handle_prompt 循环 {count} 次，跳过防死锁", "WARN")
        return False
    ...
```

**问题**：一个任务会触发多个**合法的、不同的 prompt**：

```
第1个prompt: trust_prompt（"信任此目录吗？"）→ handle_prompt 第1次
第2个prompt: yes_no（"确认吗？"）→ handle_prompt 第2次
第3个prompt: yes_no（"确认吗？"）→ handle_prompt 第3次 → 计数器超限，返回 False
```

计数器在 `send()` 开始时重置为 0，但一旦超过 2 次，之后所有 prompt 都不再处理，导致：

1. 命令虽已发送，但 prompt 持续弹出（Claude Code 在等待确认）
2. supervisor 认为已处理（return False 但没有真正处理）
3. `wait_task_done()` 的 `detect_state()` 看到 "❯" → 判断 IDLE → 立即返回完成
4. 实际上命令根本未被 Claude Code 接收（被 prompt 截断）

**死循环的真正原因**：`wait_task_done()` 中的循环持续检测 prompt，但 `handle_prompt()` 返回 False 后状态仍为 PROMPT，导致循环永不退出。

### 状态机缺陷

```python
# wait_task_done() 中的循环
while time.time() < deadline:
    state = detect_state(pane)
    if state == CCState.IDLE:
        return (True, "idle")       # ← 误判：❯ 被识别为 IDLE，但实际在等 prompt
    if state == CCState.PROMPT:
        handle_prompt()             # ← count > 2 后返回 False，状态不变，循环卡住
```

`detect_state()` 把 `"❯"` 识别为 `IDLE`，但 Claude Code TUI 的 prompt 对话框也显示 `❯`，导致 **prompt 状态被误判为 IDLE**。

## 修复方案

### 方案 A：计数器改为"滑动窗口"（推荐）

```python
_PROMPT_COUNT = 0
_LAST_PROMPT_TS = 0.0  # 上次处理 prompt 的时间戳

def handle_prompt() -> bool:
    global _PROMPT_COUNT, _LAST_PROMPT_TS
    now = time.time()

    # 1. 时间窗口重置：距离上次处理 >3s 则视为新任务周期，重置计数器
    if now - _LAST_PROMPT_TS > 3.0:
        _PROMPT_COUNT = 0

    _PROMPT_COUNT += 1
    _LAST_PROMPT_TS = now

    if _PROMPT_COUNT > 5:  # 宽松限制：同一任务周期内最多处理 5 个 prompt
        log(f"handle_prompt {count} 次，跳过", "WARN")
        return False
    ...
```

### 方案 B：区分 prompt 响应 vs 新命令发送

当 `handle_prompt()` 返回 False 时，应区分：
- **已处理但超限**（应等待 CC 自己消化）
- **命令未发送成功**（应 C-c 清理，重新发）

```python
# 在 send() 中，发命令前检查 pending prompt
if state == CCState.PROMPT:
    handled = handle_prompt()
    if not handled:
        # 超限但 prompt 仍存在：发 C-c 清理，等待 CC idle
        log("prompt 处理超限，强制 C-c 清理", "WARN")
        tmux_send("C-c")
        time.sleep(0.5)
        wait_idle(timeout=30)
```

### 方案 C（最彻底）：状态机分离 prompt 与 idle

```python
def detect_state(pane: str) -> str:
    # 改写：❯ 在有 prompt 对话框内容时 = PROMPT，不是 IDLE
    lines = pane.split('\n')
    recent = '\n'.join(lines[-30:])

    # prompt 对话框特征：❯ + 数字选项 或 ❯ + 确认文本
    if re.search(r'❯\s*[\d|]', recent):  # ❯ 后跟数字/选项
        return CCState.PROMPT
    if "Ctrl-C again" in recent:
        return CCState.PROMPT
    if "Is this a project" in recent:
        return CCState.PROMPT

    if "esc to interrupt" in recent:
        return CCState.BUSY

    if re.search(r'\b(Thinking|Executing)\b', recent):
        return CCState.BUSY

    # 纯 ❯ 提示符 = IDLE
    if re.search(r'^❯\s*$', recent, re.MULTILINE):
        return CCState.IDLE

    return CCState.IDLE
```

### 方案 D（最简）：直接调高计数器上限

```python
if count > 10:  # 从 2 提高到 10，足够覆盖一个任务的合法 prompt 数
```

## 推荐组合

**方案 A + 方案 C + 方案 B 组合**：
1. 滑动时间窗口重置计数器（避免"首条任务就超限"）
2. 改进 `detect_state()` 区分纯 `❯` vs prompt 对话框
3. 超限后强制 `C-c` 清理，不静默跳过

## 验证方法

发送一个会触发 3+ 个 prompt 的任务（如多行 paste + 文件读取确认），观察：
- [ ] `handle_prompt` 迭代次数 ≤ 10（而非之前的 12000+）
- [ ] 命令被 Claude Code 正确接收并执行
- [ ] 无"假 idle"（prompt 状态被识别为 idle）
