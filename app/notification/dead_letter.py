from abc import ABC, abstractmethod
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.notification.models import AlertNotification


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeadLetterRecord(BaseModel):
    """一条未能送达的推送消息及其失败上下文（供事后审计 / 人工补发）。"""

    notification: AlertNotification
    channel: str  # 目标通道名（如 webhook / memory）
    url: str = ""  # webhook 通道地址，便于人工核对与补发
    payload_format: str = "feishu"  # 补发时还原 webhook 载荷格式
    reason: str  # 失败原因（异常摘要 / queue_full / shutdown）
    attempts: int  # 实际尝试发送次数（队满丢弃为 0）
    failed_at: str = Field(default_factory=_utc_now_iso)
    record_id: int | None = None  # 仓储自增主键，读取时回填


class DeadLetterRepository(ABC):
    """死信仓储抽象：重试耗尽、队满丢弃、进程关停时落库，绝不阻塞推送线程。"""

    @abstractmethod
    def append(self, record: DeadLetterRecord) -> None: ...

    @abstractmethod
    def get(self, record_id: int) -> DeadLetterRecord | None: ...

    @abstractmethod
    def list(
        self,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[DeadLetterRecord]: ...

    @abstractmethod
    def delete(self, record_id: int) -> bool: ...

    @abstractmethod
    def count(self, tenant_id: str | None = None) -> int: ...

    @abstractmethod
    def close(self) -> None: ...
