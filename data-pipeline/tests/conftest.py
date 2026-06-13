"""
conftest.py — pytest 共享 fixture (N-8)

2 个 autouse fixture:
1. clear_load_secret_cache: 每个 test 前清 secrets_loader.load_secret lru_cache
2. umask_0077: 默认 0o077 防止新建文件 mode 不准

审计员: Arc
"""
import os
import sys
from pathlib import Path

import pytest

# 注入 src 路径(所有 test 文件共用)
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


@pytest.fixture(autouse=True)
def clear_load_secret_cache():
    """每个 test 前清 load_secret lru_cache, 避免测试间残留."""
    from security.secrets_loader import clear_secret_cache
    clear_secret_cache()
    yield


@pytest.fixture(autouse=True)
def umask_0077():
    """设置 umask 0o077, 新建文件默认 600, test 结束后恢复."""
    old_umask = os.umask(0o077)
    yield
    os.umask(old_umask)
