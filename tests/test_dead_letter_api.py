"""死信查询 / 补发 API：租户可见性、补发失败保留、成功补发删除。"""

import uuid

from app.core.config import settings
from app.notification import router as dead_letter_api
from app.notification.channels import InMemoryNotificationChannel
from app.notification.dead_letter import DeadLetterRecord
from app.notification.models import AlertNotification
from app.notification.sqlite_dead_letter import SqliteDeadLetterRepository

UNREACHABLE = "http://127.0.0.1:9/unreachable"


def _probe_store() -> SqliteDeadLetterRepository:
    return SqliteDeadLetterRepository(settings.push_dead_letter_db_path)


def _append(
    store: SqliteDeadLetterRepository, tenant_id: str, marker: str, reason: str
) -> int:
    record = DeadLetterRecord(
        notification=AlertNotification(
            tenant_id=tenant_id,
            animal_id=f"A-dl-{marker}",
            kind="health",
            severity="critical",
            message=f"dead letter api probe {marker}",
        ),
        channel="webhook",
        url=UNREACHABLE,
        reason=reason,
        attempts=3,
    )
    store.append(record)
    return store.list(tenant_id=tenant_id, limit=500)[-1].record_id


def test_dead_letter_api_lists_only_own_tenant(client):
    marker = uuid.uuid4().hex[:8]
    store = _probe_store()
    try:
        _append(store, "default", marker, "manual probe")
        _append(store, f"TNT-foreign-{marker}", marker, "foreign probe")
        listing = client.get(
            "/api/v1/alerts/dead-letters", params={"limit": 500}
        ).json()
    finally:
        store.close()
    assert listing["tenant_id"] == "default"
    mine = [r for r in listing["items"] if marker in r["notification"]["message"]]
    assert len(mine) == 1
    assert mine[0]["url"] == UNREACHABLE
    assert mine[0]["record_id"] is not None


def test_replay_foreign_record_not_found(client):
    marker = uuid.uuid4().hex[:8]
    store = _probe_store()
    try:
        foreign_id = _append(store, f"TNT-foreign-{marker}", marker, "foreign probe")
    finally:
        store.close()
    resp = client.post(f"/api/v1/alerts/dead-letters/{foreign_id}/replay")
    assert resp.status_code == 404


def test_replay_failure_keeps_record(client):
    marker = uuid.uuid4().hex[:8]
    store = _probe_store()
    try:
        record_id = _append(store, "default", marker, "manual probe")
    finally:
        store.close()
    resp = client.post(f"/api/v1/alerts/dead-letters/{record_id}/replay")
    assert resp.status_code == 502  # 不可达地址：补发失败
    listing = client.get("/api/v1/alerts/dead-letters", params={"limit": 500}).json()
    assert any(
        r["record_id"] == record_id for r in listing["items"]
    )  # 失败保留原记录


def test_replay_success_deletes_record(client, monkeypatch):
    marker = uuid.uuid4().hex[:8]
    store = _probe_store()
    try:
        record_id = _append(store, "default", marker, "manual probe")
        foreign_id = _append(store, f"TNT-foreign-{marker}", marker, "foreign probe")
    finally:
        store.close()

    memory = InMemoryNotificationChannel()
    monkeypatch.setattr(dead_letter_api, "_build_channel", lambda record: memory)
    ok = client.post(f"/api/v1/alerts/dead-letters/{record_id}/replay")
    assert ok.status_code == 200
    assert ok.json()["replayed"] is True
    assert len(memory.sent) == 1
    assert memory.sent[0].animal_id == f"A-dl-{marker}"

    listing = client.get("/api/v1/alerts/dead-letters", params={"limit": 500}).json()
    assert not any(r["record_id"] == record_id for r in listing["items"])

    verify = _probe_store()
    try:
        assert verify.get(foreign_id) is not None  # 他租户记录未被动过
        verify.delete(foreign_id)  # 清理，避免污染后续用例
    finally:
        verify.close()


def test_replay_without_url_rejected(client):
    marker = uuid.uuid4().hex[:8]
    store = _probe_store()
    try:
        store.append(
            DeadLetterRecord(
                notification=AlertNotification(
                    tenant_id="default",
                    animal_id=f"A-dl-{marker}",
                    kind="health",
                    severity="critical",
                    message=f"no url probe {marker}",
                ),
                channel="webhook",
                url="",
                reason="no url",
                attempts=1,
            )
        )
        record_id = store.list(tenant_id="default", limit=500)[-1].record_id
    finally:
        store.close()
    resp = client.post(f"/api/v1/alerts/dead-letters/{record_id}/replay")
    assert resp.status_code == 400
