"""MinIO (S3 兼容) 对象存储操作 — Bronze 层原始数据存储"""

import json
import logging
from datetime import date
from io import BytesIO

import boto3
from botocore.config import Config as BotoConfig

from src.config import minio as mc

logger = logging.getLogger(__name__)

_s3_client = None


def _get_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=f"http://{mc.endpoint}" if not mc.secure else f"https://{mc.endpoint}",
            aws_access_key_id=mc.access_key,
            aws_secret_access_key=mc.secret_key,
            region_name=mc.region,
            config=BotoConfig(signature_version="s3v4"),
        )
    return _s3_client


def ensure_buckets():
    """确保 MinIO 中所需的 bucket 已创建"""
    client = _get_client()
    buckets = [
        mc.bucket_bronze_financial,
        mc.bucket_bronze_quotes,
        mc.bucket_bronze_news,
    ]
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    for b in buckets:
        if b not in existing:
            client.create_bucket(Bucket=b)
            logger.info(f"创建 MinIO bucket: {b}")
        else:
            logger.debug(f"MinIO bucket 已存在: {b}")


def store_json(data: list[dict], bucket: str, prefix: str, trade_date: date) -> str:
    """将 JSON 数据存入 MinIO，返回对象路径

    Args:
        data:  数据记录列表
        bucket: bucket 名称
        prefix: 路径前缀，如 "quotes/daily"
        trade_date: 交易日
    Returns:
        object_key: 如 "quotes/daily/2026-05-31.json"
    """
    object_key = f"{prefix}/{trade_date.isoformat()}.json"
    body = json.dumps(data, ensure_ascii=False, default=str, indent=2).encode("utf-8")

    client = _get_client()
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=BytesIO(body),
        ContentType="application/json",
    )
    logger.info(f"Bronze 层存储: s3://{bucket}/{object_key} ({len(data)} 条)")
    return f"s3://{bucket}/{object_key}"
