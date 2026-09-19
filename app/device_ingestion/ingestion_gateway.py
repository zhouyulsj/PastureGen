from collections import deque
from typing import TYPE_CHECKING

from app.device_ingestion.adapter_base import SensorDataAdapter
from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.event_models import SensorReadingEvent
from app.device_ingestion.timeseries_repository import TimeseriesRepository

if TYPE_CHECKING:
    from app.perception.alert_service import AlertService

EVENT_BUFFER_SIZE = 1000
DEFAULT_EVENT_LIMIT = 200


class IngestionGateway:
    def __init__(self) -> None:
        self._events: deque[SensorReadingEvent] = deque(maxlen=EVENT_BUFFER_SIZE)
        self._instances: dict[str, SensorDataAdapter] = {}
        self._repository: TimeseriesRepository | None = None
        self._alert_service: "AlertService | None" = None

    def set_repository(self, repository: TimeseriesRepository | None) -> None:
        """绑定/解绑时序仓储。关停时应传 None，避免持有已关闭的连接。"""
        self._repository = repository

    def set_alert_service(self, alert_service: "AlertService | None") -> None:
        """绑定/解绑告警服务。关停时应传 None。"""
        self._alert_service = alert_service

    def ingest(self, events: list[SensorReadingEvent]) -> None:
        if self._repository is not None:
            self._repository.append(events)
        else:
            self._events.extend(events)
        if self._alert_service is not None:
            self._alert_service.handle_events(events)

    def collect_from_adapter(self, adapter_type: str, **config) -> list[SensorReadingEvent]:
        adapter = adapter_registry.create(adapter_type, **config)
        adapter.connect()
        events = adapter.collect()
        for event in events:
            if not event.tenant_id:
                event.tenant_id = adapter.config.get("tenant_id", "")
        self.ingest(events)
        adapter.close()
        return events

    def list_events(
        self, tenant_id: str | None = None, limit: int = DEFAULT_EVENT_LIMIT
    ) -> list[SensorReadingEvent]:
        if self._repository is not None:
            return self._repository.query(tenant_id=tenant_id, limit=limit)
        if tenant_id is None:
            return list(self._events)[-limit:]
        return [event for event in self._events if event.tenant_id == tenant_id][-limit:]

    def query_repository(
        self,
        device_id: str | None = None,
        metric: str | None = None,
        animal_id: str | None = None,
        tenant_id: str | None = None,
        limit: int | None = None,
    ) -> list[SensorReadingEvent]:
        if self._repository is None:
            return []
        return self._repository.query(
            device_id=device_id,
            metric=metric,
            animal_id=animal_id,
            tenant_id=tenant_id,
            limit=limit,
        )

    def clear_events(self) -> None:
        self._events.clear()


ingestion_gateway = IngestionGateway()
