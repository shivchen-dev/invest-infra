"""智能投研体系 — Phase 1 数据采集层全局配置"""

from dataclasses import dataclass, field
from typing import Optional
import os


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass
class PGConfig:
    host: str = env("PG_HOST", "localhost")
    port: int = env_int("PG_PORT", 5432)
    db: str = env("PG_DB", "investdb")
    user: str = env("PG_USER", "invest")
    password: str = env("PG_PASSWORD", "")  # 必须环境变量覆盖，无默认值

    def __post_init__(self):
        if not self.password:
            raise ValueError("PG_PASSWORD env var must be set")

    @property
    def dsn(self) -> str:
        return f"dbname={self.db} user={self.user} password={self.password} host={self.host} port={self.port}"

    @property
    def uri(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


@dataclass
class RedisConfig:
    host: str = env("REDIS_HOST", "localhost")
    port: int = env_int("REDIS_PORT", 6379)
    db: int = env_int("REDIS_DB", 0)
    password: str = env("REDIS_PASSWORD", "")


@dataclass
class MinIOConfig:
    endpoint: str = env("MINIO_ENDPOINT", "localhost:9000")
    access_key: str = env("MINIO_ACCESS_KEY", "")
    secret_key: str = env("MINIO_SECRET_KEY", "")  # 必须环境变量覆盖
    secure: bool = env("MINIO_SECURE", "false").lower() == "true"
    region: str = env("MINIO_REGION", "cn-east-1")

    def __post_init__(self):
        if not self.secret_key:
            raise ValueError("MINIO_SECRET_KEY env var must be set")

    bucket_bronze_financial: str = "bronze-financial"
    bucket_bronze_quotes: str = "bronze-quotes"
    bucket_bronze_news: str = "bronze-news"


@dataclass
class CollectorConfig:
    stock_codes: list[str] = field(default_factory=list)
    quotes_history_days: int = env_int("QUOTES_HISTORY_DAYS", 365)
    batch_size: int = env_int("COLLECTOR_BATCH_SIZE", 50)
    request_interval: float = float(env("COLLECTOR_INTERVAL", "0.5"))
    min_records_warning: int = env_int("MIN_RECORDS_WARNING", 10)


@dataclass
class RssCastConfig:
    """RssCast MCP 服务配置"""
    endpoint: str = env("RSSCAST_ENDPOINT", "https://app-cn.rsscast.io/api/mcp/v1/mcp")
    token: str = env("RSSCAST_TOKEN", "")


pg: PGConfig = PGConfig()
redis: RedisConfig = RedisConfig()
minio: MinIOConfig = MinIOConfig()
collector: CollectorConfig = CollectorConfig()
rsscast: RssCastConfig = RssCastConfig()
