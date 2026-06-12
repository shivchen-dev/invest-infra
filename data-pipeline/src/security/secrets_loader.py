"""
secrets_loader.py — 统一敏感数据加载接口 (v1.0)

Layer 1: OS keyring (keyring lib) — 当前实现 (N-1.1)
Layer 2: AES-256-GCM encrypted file (主密钥从 L1 读) — N-1.2 待实现

设计要点:
- keyring 后端检测 (F-2 + F-20 修复):同时检查 module + class name
  - PlaintextKeyring (明文存盘) ❌
  - keyring.backends.fail.Keyring (无后端) ❌ — F-20 真跑发现
  - 容器内默认 fail 后端,必须拒启动或警告
- L1 服务名固定 "invest-infra",secret name 由调用方传
- 后续 N-1.2 会在文件里加 L2 实现,N-1.3 加统一 load_secret() 接口

审计员: Arc
"""
from __future__ import annotations

import base64
import keyring
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class InsecureKeyringError(RuntimeError):
    """keyring 后端不安全(PlaintextKeyring / fail / 未识别)"""


def get_keyring_backend() -> str:
    """检测 keyring 后端,不可信时抛 InsecureKeyringError.

    Returns:
        后端完整标识 "{module}.{name}" (例: 'keyring.backends.SecretServiceKeyring')

    Raises:
        InsecureKeyringError: 检测到不安全后端
    """
    backend = keyring.get_keyring()
    cls_name = type(backend).__name__
    module = type(backend).__module__
    full = f"{module}.{cls_name}"

    # F-20 修复:同时检查 module + class name,避免漏判 fail 后端
    is_unsafe = (
        "PlaintextKeyring" in cls_name
        or "PlaintextKeyring" in module
        or ".fail." in module
        or "Fail" in cls_name
        or "fail" in module.lower()
    )
    if is_unsafe:
        raise InsecureKeyringError(
            f"不安全 keyring 后端: {full}. "
            "请安装 GNOME Keyring/KWallet/libsecret 后端包"
        )
    return full


def load_keyring_secret(name: str) -> str:
    """从 OS keyring 加载 L1 secret.

    Args:
        name: secret 名称(例: 'pg_password', 'minimax_key')

    Returns:
        secret 字符串值

    Raises:
        InsecureKeyringError: keyring 后端不安全
        KeyError: secret 不存在
        NoKeyringError: keyring 后端抛底层错误(虽然检测通过但运行时挂)
    """
    get_keyring_backend()  # 先检测后端
    secret = keyring.get_password("invest-infra", name)
    if secret is None:
        raise KeyError(f"keyring 中未找到 secret: {name}")
    return secret


# ════════════════════════════════════════════════════════════════════════
# L2 (Layer 2) — AES-256-GCM encrypted file loader
# ════════════════════════════════════════════════════════════════════════
# 存储: secrets/{name}.enc 文件(700 权限目录)
# 加密: AES-256-GCM (cryptography.hazmat.primitives.ciphers.aead.AESGCM)
# 密钥: master_key (32 bytes,从 L1 keyring 读,或测试注入)
#
# 文件格式: base64(nonce(12) + ciphertext + tag(16))
# nonce 每次随机 (os.urandom(12))
# ════════════════════════════════════════════════════════════════════════

# secrets 目录(项目根)
_SECRETS_DIR = Path(__file__).resolve().parents[2] / "secrets"


def _get_master_key(master_key: Optional[str] = None) -> bytes:
    """获取 32 字节 master_key.

    优先用注入的(测试),否则从 L1 读
    """
    if master_key is not None:
        key = master_key.encode("utf-8")
    else:
        key = load_keyring_secret("master_key").encode("utf-8")
    if len(key) != 32:
        raise ValueError(f"master_key 必须是 32 字节,实际 {len(key)}")
    return key


def save_file_secret(name: str, plaintext: str, master_key: Optional[str] = None) -> Path:
    """加密并保存 secret 到 secrets/{name}.enc.

    Returns: 加密文件路径
    """
    _SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_SECRETS_DIR, 0o700)
    key = _get_master_key(master_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), name.encode("utf-8"))
    enc_path = _SECRETS_DIR / f"{name}.enc"
    enc_path.write_bytes(base64.b64encode(nonce + ct))
    os.chmod(enc_path, 0o600)
    return enc_path


def load_file_secret(name: str, master_key: Optional[str] = None) -> str:
    """从 secrets/{name}.enc 解密加载 secret.

    master_key 不传时从 L1 读;测试可注入
    """
    enc_path = _SECRETS_DIR / f"{name}.enc"
    if not enc_path.exists():
        raise FileNotFoundError(f"加密文件不存在: {enc_path}")
    key = _get_master_key(master_key)
    aesgcm = AESGCM(key)
    blob = base64.b64decode(enc_path.read_bytes())
    nonce, ct = blob[:12], blob[12:]
    return aesgcm.decrypt(nonce, ct, name.encode("utf-8")).decode("utf-8")


# ════════════════════════════════════════════════════════════════════════
# L3 (Layer 3) — 统一接口 + LRU 缓存
# ════════════════════════════════════════════════════════════════════════
# load_secret(name, layer='auto') 是外部调用入口
# - 'auto': L2 优先(本地快),L1 fallback
# - 'L1': 强制 keyring
# - 'L2': 强制加密文件
# - 缓存: 进程内 lru_cache(maxsize=128)
# ════════════════════════════════════════════════════════════════════════


def _l2_exists(name: str) -> bool:
    """L2 加密文件路径"""
    return (_SECRETS_DIR / f"{name}.enc").exists()


@lru_cache(maxsize=128)
def load_secret(name: str, layer: str = "auto", master_key: Optional[str] = None) -> str:
    """统一敏感数据加载接口(进程内 lru_cache).

    layer: 'auto' (L2 → L1) / 'L1' / 'L2'
    master_key: L2 模式注入用(测试);生产不传(从 L1 读)
    """
    layer_norm = layer.upper()
    if layer_norm == "L1":
        return load_keyring_secret(name)
    if layer_norm == "L2":
        return load_file_secret(name, master_key=master_key)
    if layer_norm != "AUTO":
        raise ValueError(f"不支持的 layer: {layer} (期望 'auto' / 'L1' / 'L2')")
    # auto: L2 优先,L1 fallback
    if _l2_exists(name):
        return load_file_secret(name, master_key=master_key)
    return load_keyring_secret(name)


def clear_secret_cache() -> None:
    """清空 load_secret 缓存(N-1.4 测试用)."""
    load_secret.cache_clear()
