import json
from abc import ABC, abstractmethod
from datetime import datetime

from app.device_ingestion.event_models import (
    AnimalHealthEvent,
    AnimalReproductionEvent,
)

Alert = AnimalHealthEvent | AnimalReproductionEvent

HEALTH_KIND = "health"
REPRODUCTION_KIND = "reproduction"


def alert_kind(alert: Alert) -> str:
    """区分告警类型，供多态序列化使用。"""
    if isinstance(alert, AnimalHealthEvent):
        return HEALTH_KIND
    return REPRODUCTION_KIND


def alert_dedup_key(alert: Alert) -> str:
    """告警去重键：同租户+同个体+同指标（健康含等级，繁殖含事件类型）。"""
    if isinstance(alert, AnimalHealthEvent):
        return (
            f"health|{alert.tenant_id}|{alert.animal_id}"
            f"|{alert.metric}|{alert.severity.value}"
        )
    return f"repro|{alert.tenant_id}|{alert.animal_id}|{alert.event_type.value}"


def dump_alert(alert: Alert) -> tuple[str, str, str, str]:
    """返回 (tenant_id, kind, dedup_key, data_json) 便于落库。"""
    return alert.tenant_id, alert_kind(alert), alert_dedup_key(alert), alert.model_dump_json()


def load_alert(kind: str, data: str) -> Alert:
    """从库中重建告警对象。"""
    payload = json.loads(data)
    if kind == HEALTH_KIND:
        return AnimalHealthEvent(**payload)
    return AnimalReproductionEvent(**payload)


class AlertRepository(ABC):
    """告警持久化抽象（可平滑替换为 PostgreSQL / TimescaleDB）。"""

    @abstractmethod
    def append(self, alert: Alert) -> None:
        ...

    @abstractmethod
    def list(
        self,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[Alert]:
        ...

    @abstractmethod
    def last_timestamp(self, dedup_key: str) -> datetime | None:
        """返回某去重键最近一次告警时间，用于跨进程冷却判断。"""
        ...

    @abstractmethod
    def close(self) -> None:
        ...
