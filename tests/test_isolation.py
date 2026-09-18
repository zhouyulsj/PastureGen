"""多租户数据隔离：事件流与告警列表按租户严格隔离。"""

from app.device_ingestion.event_models import SensorReadingEvent
from app.device_ingestion.ingestion_gateway import ingestion_gateway


def _reading(metric: str, value: float, animal: str) -> SensorReadingEvent:
    return SensorReadingEvent(
        device_id="iso-sim",
        metric=metric,
        value=value,
        unit="",
        animal_id=animal,
        tenant_id="default",
    )


def test_events_readthrough_and_tenant_isolation(client, make_tenant):
    client.post(
        "/api/v1/devices/collect",
        json={"adapter_type": "mock_rfid", "animal_id": "CN-0001"},
    )
    default_events = client.get("/api/v1/devices/events").json()
    repo_events = ingestion_gateway.query_repository(tenant_id="default", limit=200)
    assert len(default_events) > 0
    assert len(default_events) == len(repo_events)  # 读取穿透到同一持久层

    _, _, other_headers = make_tenant("隔离测试牧场")
    other_events = client.get("/api/v1/devices/events", headers=other_headers).json()
    assert other_events == []


def test_alerts_tenant_isolation(client, make_tenant):
    # 默认租户越限体温 -> 产生 critical 告警
    ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])
    default_alerts = client.get("/api/v1/alerts").json()
    assert any(
        a.get("severity") == "critical" for a in default_alerts
    )
    _, _, other_headers = make_tenant("告警隔离牧场")
    assert client.get("/api/v1/alerts", headers=other_headers).json() == []
