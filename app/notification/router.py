"""死信查询与补发 API（按当前租户隔离）。"""

import time

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.notification.channels import NotificationChannel, WebhookNotificationChannel
from app.notification.dead_letter import DeadLetterRecord, DeadLetterRepository
from app.tenant.context import get_current_tenant_id

router = APIRouter(prefix="/alerts/dead-letters", tags=["alerts"])

_store: DeadLetterRepository | None = None


def bind_dead_letter_store(store: DeadLetterRepository | None) -> None:
    """lifespan 启动时注入死信仓储，关停时置回 None。"""
    global _store
    _store = store


def _require_store() -> DeadLetterRepository:
    if _store is None:
        raise HTTPException(status_code=503, detail="死信存储未配置")
    return _store


def _build_channel(record: DeadLetterRecord) -> NotificationChannel:
    """补发通道工厂（同步发送，便于向调用方即时反馈结果）。

    超时可配置——不可达的 webhook 否则会按默认值长时间占住请求线程。
    """
    return WebhookNotificationChannel(
        record.url,
        payload_format=record.payload_format,
        timeout=settings.dead_letter_replay_timeout_seconds,
    )


def _send_with_retry(channel: NotificationChannel, record: DeadLetterRecord) -> None:
    """有界重试补发：瞬时抖动不再一票判死，重试耗尽则抛出最后一次异常。

    保持同步语义（人工补发需要立刻知道成/败），重试次数与退避可配置，
    最坏耗时受 ``DEAD_LETTER_REPLAY_TIMEOUT_SECONDS × (1 + 重试次数)`` 约束。
    """
    max_retries = max(0, settings.dead_letter_replay_max_retries)
    delay = max(0.0, settings.dead_letter_replay_retry_delay_seconds)
    attempt = 0
    while True:
        try:
            channel.send(record.notification)
            return
        except Exception:
            if attempt >= max_retries:
                raise
            attempt += 1
            if delay:
                time.sleep(delay * attempt)


@router.get("")
def list_dead_letters(limit: int = 100) -> dict:
    tenant_id = get_current_tenant_id()
    store = _require_store()
    limit = max(1, min(limit, 500))
    records = store.list(tenant_id=tenant_id, limit=limit)
    return {
        "tenant_id": tenant_id,
        "total": store.count(tenant_id=tenant_id),
        "items": [record.model_dump(mode="json") for record in records],
    }


@router.post("/{record_id}/replay")
def replay_dead_letter(record_id: int) -> dict:
    """补发一条死信：送达成功即删除记录；失败保留原记录并返回 502。"""
    tenant_id = get_current_tenant_id()
    store = _require_store()
    record = store.get(record_id)
    if record is None or record.notification.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="死信记录不存在")
    if not record.url:
        raise HTTPException(status_code=400, detail="该记录没有可补发的 webhook 地址")
    try:
        _send_with_retry(_build_channel(record), record)
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"补发失败: {type(exc).__name__}: {exc}"
        )
    store.delete(record_id)
    return {
        "record_id": record_id,
        "tenant_id": tenant_id,
        "channel": record.channel,
        "replayed": True,
    }
