"""死信查询与补发 API（按当前租户隔离）。"""

from fastapi import APIRouter, HTTPException

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
    """补发通道工厂（同步发送，便于向调用方即时反馈结果）。"""
    return WebhookNotificationChannel(record.url, payload_format=record.payload_format)


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
        _build_channel(record).send(record.notification)
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
