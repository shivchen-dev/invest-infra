# 代码审查修复记录

## 日期: 2026-04-06

## 审查结果
严重级别: 需要修改 (Request Changes)
主要问题: 并发控制竞态条件、文件 I/O 阻塞、魔法数字硬编码

## 修复内容

### 1. 并发控制修复 ✅
**问题**: `acquire_thread_lock()` 使用 check-and-set 模式，存在竞态条件
**修复**: 改用 `asyncio.Lock` + `asyncio.Lock` 保护锁字典
```python
# 修复前
if not self.processing.get(thread_id, False):
    self.processing[thread_id] = True  # 竞态条件！

# 修复后
async with self._global_lock:
    if thread_id not in self._locks:
        self._locks[thread_id] = asyncio.Lock()
    return self._locks[thread_id]
```

### 2. 文件 I/O 异步化 ✅
**问题**: `_save_records()` 同步文件操作阻塞事件循环
**修复**: 添加 `_save_records_async()` 使用线程池
```python
# 新增
import concurrent.futures
self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

async def _save_records_async(self):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(self._executor, self._save_records)
```

### 3. 配置化魔法数字 ✅
**问题**: 0.75, 0.9, 30 等阈值硬编码
**修复**: 添加 `TopicManagerConfig` 配置类
```python
@dataclass
class TopicManagerConfig:
    similarity_threshold: float = 0.75
    auto_match_threshold: float = 0.9
    expiry_minutes: int = 30
    max_alternatives: int = 3
    lock_timeout: float = 30.0
```

### 4. 修复关键词提取 ✅
**问题**: 正则 `[一-鿿]` 只匹配单字中文
**修复**: 改为 `[一-鿿]{2,}` 匹配至少2个字符
```python
# 修复前
words = re.findall(r'\b[a-zA-Z]+\b|[\u4e00-\u9fff]', message.lower())

# 修复后
words = re.findall(r'\b[a-zA-Z]+\b|[\u4e00-\u9fff]{2,}', message.lower())
```

### 5. 移动 import 到顶部 ✅
**问题**: `re` 在函数内导入
**修复**: 移到文件顶部

## 未修复问题 (技术债)
- 相似度算法权重设计仍有缺陷
- 缺少单元测试
- 异常处理不够精确
- 日志可能泄露敏感信息

## 文件变更
- `src/smart_topic_manager.py`: 重构并发控制、添加配置类、异步文件 I/O
- `src/api/deepseek_api.py`: 更新调用方式使用新的异步接口

## 验证
- ✅ 语法检查通过
- ✅ 类型检查通过
- ⏳ 待功能测试
