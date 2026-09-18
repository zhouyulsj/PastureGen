"""告警管道基线：健康越限 / 发情 / 分娩监测、冷却去抖与持久化、推送联动。"""

import uuid

from app.core.config import settings
from app.device_ingestion.event_models import SensorReadingEvent
from app.device_ingestion.ingestion_gateway import ingestion_gateway
from app.notification.channels import InMemoryNotificationChannel
from app.notification.dispatcher import NotificationDispatcher
from app.perception.alert_service import alert_service
from app.perception.sqlite_alert_repository import SqliteAlertRepository


def _reading(metric: str, value: float, animal: str) -> SensorReadingEvent:
    return SensorReadingEvent(
        device_id="alert-sim",
        metric=metric,
        value=value,
        unit="",
        animal_id=animal,
        tenant_id="default",
    )


def _feed_pipeline_sequences() -> None:
    # 活动量突增 -> 发情；体温先高后降 -> 分娩；持续高温 -> critical 健康告警
    for value in [10.0, 10.0, 30.0]:
        ingestion_gateway.ingest([_reading("activity_index", value, "A-act")])
    for value in [39.0, 39.0, 38.3]:
        ingestion_gateway.ingest([_reading("body_temperature", value, "A-temp")])
    ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])


def test_alert_kinds(client):
    _feed_pipeline_sequences()
    alerts = client.get("/api/v1/alerts").json()
    kinds = {a.get("severity") or a.get("event_type") for a in alerts}
    assert {"critical", "estrus", "calving"} <= kinds


def test_cooldown_suppresses_duplicate_alert(client):
    ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])
    before = len(alert_service.list_alerts(tenant_id="default"))
    assert before >= 1
    ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])
    after = len(alert_service.list_alerts(tenant_id="default"))
    assert after == before  # 冷却窗口内重复告警被去抖


def test_alerts_survive_repo_reopen(client):
    _feed_pipeline_sequences()
    repo = SqliteAlertRepository(settings.alert_db_path)
    try:
        persisted = repo.list(tenant_id="default", limit=500)
    finally:
        repo.close()
    kinds = {
        a.get("severity") or a.get("event_type")
        for a in (x.model_dump(mode="json") for x in persisted)
    }
    assert {"critical", "estrus", "calving"} <= kinds


def test_alert_push_delivery_and_cooldown(client):
    """绑定内存通道后：首条告警即时推送，冷却抑制的重复告警不再推送。"""

    class _FailingChannel:
        name = "failing"

        def send(self, notification) -> None:
            raise RuntimeError("channel down")  # 单通道故障不得影响其余通道

    memory = InMemoryNotificationChannel()
    alert_service.bind_notifier(NotificationDispatcher([_FailingChannel(), memory]))

    animal = f"A-push-{uuid.uuid4().hex[:8]}"
    ingestion_gateway.ingest([_reading("body_temperature", 41.2, animal)])
    assert len(memory.sent) == 1
    assert animal in memory.sent[0].message

    ingestion_gateway.ingest([_reading("body_temperature", 41.2, animal)])
    assert len(memory.sent) == 1  # 冷却窗口内不重复推送
