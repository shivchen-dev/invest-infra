"""
test_secrets.py — secrets_loader 单元测试 (N-1.4)

3 核心 case:
1. L1 后端检测 (F-2 + F-20):fail backend 抛 InsecureKeyringError
2. L2 round-trip:save → load 验证明文
3. 统一接口 cache:同参数 2 次,第 2 次 cache 命中

审计员: Arc
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import keyring

# 注入 src 路径
_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from security.secrets_loader import (  # noqa: E402
    InsecureKeyringError, get_keyring_backend, load_keyring_secret,
    save_file_secret, load_file_secret, load_secret, clear_secret_cache,
    _SECRETS_DIR,
)

MASTER_KEY = "a" * 32


@pytest.fixture
def tmp_secrets_dir(tmp_path, monkeypatch):
    """用临时目录替换真实 _SECRETS_DIR"""
    monkeypatch.setattr("security.secrets_loader._SECRETS_DIR", tmp_path)
    yield tmp_path
    clear_secret_cache()


def test_l1_insecure_backend_raises(tmp_secrets_dir):
    """F-2 + F-20: 容器默认 fail backend 抛 InsecureKeyringError"""
    with patch.object(keyring, "get_keyring",
                      return_value=keyring.backends.fail.Keyring()):
        with pytest.raises(InsecureKeyringError) as exc:
            get_keyring_backend()
        assert "不安全" in str(exc.value)
        # 同样应在 load_keyring_secret 链路抛错
        with pytest.raises(InsecureKeyringError):
            load_keyring_secret("any_name")


def test_l2_roundtrip(tmp_secrets_dir):
    """L2 AES-256-GCM 写入+读取明文一致"""
    plaintext = "test_secret_value_12345"
    enc_path = save_file_secret("test_key", plaintext, master_key=MASTER_KEY)
    assert enc_path.exists()
    assert enc_path.stat().st_mode & 0o777 == 0o600  # 文件权限 600

    decrypted = load_file_secret("test_key", master_key=MASTER_KEY)
    assert decrypted == plaintext

    # 错 key 抛 InvalidTag
    with pytest.raises(Exception):  # cryptography.exceptions.InvalidTag
        load_file_secret("test_key", master_key="b" * 32)


def test_unified_cache_hit(tmp_secrets_dir):
    """load_secret 同参数 2 次,第 2 次 cache 命中"""
    save_file_secret("cached_pwd", "cached_value", master_key=MASTER_KEY)
    clear_secret_cache()

    v1 = load_secret("cached_pwd", master_key=MASTER_KEY)
    info1 = load_secret.cache_info()

    v2 = load_secret("cached_pwd", master_key=MASTER_KEY)
    info2 = load_secret.cache_info()

    assert v1 == v2 == "cached_value"
    assert info2.hits == info1.hits + 1
