from collections import deque
from datetime import datetime, timedelta
from statistics import mean

from app.core.config import settings
from app.device_ingestion.event_models import (
    AnimalHealthEvent,
    AnimalReproductionEvent,
    HealthSeverity,
    SensorReadingEvent,
)
from app.notification.dispatcher import NotificationDispatcher
from app.perception.alert_repository import (
    Alert,
    AlertRepository,
    alert_dedup_key,
)
from app.perception.health_monitor import HealthMonitor
from app.perception.reproduction_monitor import ReproductionMonitor
from app.tenant.metadata import tenant_metadata_registry

ALERT_BUFFER_SIZE = 1000
DEFAULT_ALERT_LIMIT = 200


class AlertService:
    """入库事件驱动的告警管道：阈值越限告警 + 发情/分娩趋势监测。

    写入优先落库（若绑定仓储），未绑定时退化为有界内存缓冲；读取走仓储穿透，
    并按去抖/冷却窗口抑制同实体短时间内的重复告警。
    """

    def __init__(self) -> None:
        self._alerts: deque[Alert] = deque(maxlen=ALERT_BUFFER_SIZE)
        self._history: dict[tuple[str, str, str], list[float]] = {}
        self._repro_monitor = ReproductionMonitor()
        self._repository: AlertRepository | None = None
        self._notifier: NotificationDispatcher | None = None
        self._last_fired: dict[str, datetime] = {}

    def bind_repository(self, repository: AlertRepository) -> None:
        self._repository = repository

    def bind_notifier(self, notifier: NotificationDispatcher) -> None:
        self._notifier = notifier

    def _tenant_thresholds(self, tenant_id: str) -> dict[str, tuple[float, float]]:
        bounds = tenant_metadata_registry.get_metadata(tenant_id).alert_thresholds
        thresholds: dict[str, tuple[float, float]] = {}
        for metric, pair in bounds.items():
            if len(pair) >= 2:
                thresholds[metric] = (pair[0], pair[1])
        return thresholds

    def handle_events(self, events: list[SensorReadingEvent]) -> None:
        for event in events:
            self._evaluate_health(event)
            self._evaluate_reproduction(event)

    def _evaluate_health(self, event: SensorReadingEvent) -> None:
        alert = HealthMonitor(self._tenant_thresholds(event.tenant_id)).evaluate_event(event)
        if alert.severity != HealthSeverity.normal:
            self._record(alert)

    def _evaluate_reproduction(self, event: SensorReadingEvent) -> None:
        animal_id = event.animal_id
        if not animal_id:
            return
        key = (event.tenant_id, animal_id, event.metric)
        history = self._history.get(key, [])
        if history:
            baseline = mean(history)
            alert: AnimalReproductionEvent | None = None
            if event.metric == "activity_index":
                alert = self._repro_monitor.detect_estrus([event], baseline)
            elif event.metric == "body_temperature":
                alert = self._repro_monitor.detect_calving([event], baseline)
            if alert is not None:
                self._record(alert)
        self._history.setdefault(key, []).append(event.value)

    def _within_cooldown(self, dedup_key: str, fired_at: datetime) -> bool:
        cooldown = settings.alert_cooldown_seconds
        if cooldown <= 0:
            return False
        if self._repository is not None:
            last = self._repository.last_timestamp(dedup_key)
        else:
            last = self._last_fired.get(dedup_key)
        if last is None:
            return False
        return fired_at - last < timedelta(seconds=cooldown)

    def _record(self, alert: Alert) -> None:
        dedup_key = alert_dedup_key(alert)
        if self._within_cooldown(dedup_key, alert.timestamp):
            return
        self._last_fired[dedup_key] = alert.timestamp
        if self._repository is not None:
            self._repository.append(alert)
        else:
            self._alerts.append(alert)
        if self._notifier is not None:
            self._notifier.notify(alert)

    def list_alerts(
        self,
        tenant_id: str | None = None,
        limit: int | None = DEFAULT_ALERT_LIMIT,
    ) -> list[Alert]:
        if self._repository is not None:
            return self._repository.list(tenant_id=tenant_id, limit=limit)
        buffered = list(self._alerts)
        if tenant_id is not None:
            buffered = [alert for alert in buffered if alert.tenant_id == tenant_id]
        if limit is not None:
            buffered = buffered[-limit:]
        return buffered

    def clear(self) -> None:
        self._alerts.clear()
        self._history.clear()
        self._last_fired.clear()


alert_service = AlertService()
