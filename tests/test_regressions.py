"""针对体检发现的缺陷的回归测试。

每个测试对应 TODO.md 中的一条编号，用于防止修复被后续改动推翻。
"""

import pytest

from app.breeding.pedigree import Animal, PedigreeManager
from app.breeding.store import SqlitePedigreeStore, pedigree_registry
from app.core.config import settings
from app.device_ingestion.event_models import (
    AnimalHealthEvent,
    HealthSeverity,
    SensorReadingEvent,
)
from app.device_ingestion.ingestion_gateway import ingestion_gateway
from app.notification import router as dead_letter_api
from app.notification.dead_letter import DeadLetterRecord
from app.notification.models import AlertNotification
from app.notification.sqlite_dead_letter import SqliteDeadLetterRepository
from app.perception.alert_service import alert_service
from app.perception.sqlite_alert_repository import SqliteAlertRepository

PEDIGREE_IDS = ["S", "D", "A", "B", "C"]


def _reading(metric: str, value: float, animal: str) -> SensorReadingEvent:
    return SensorReadingEvent(
        device_id="regression-sim",
        metric=metric,
        value=value,
        unit="",
        animal_id=animal,
        tenant_id="default",
    )


def _full_sib_pedigree() -> list[Animal]:
    """S×D 生出全同胞 A、B，A×B 生下 C（C 的近交系数应为 0.25）。"""
    return [
        Animal(animal_id="S"),
        Animal(animal_id="D"),
        Animal(animal_id="A", sire_id="S", dam_id="D"),
        Animal(animal_id="B", sire_id="S", dam_id="D"),
        Animal(animal_id="C", sire_id="A", dam_id="B"),
    ]


def _matrix_by_id(manager: PedigreeManager) -> tuple[dict, dict]:
    matrix, ids = manager.build_additive_relationship_matrix()
    return matrix, {animal_id: i for i, animal_id in enumerate(ids)}


# --------------------------------------------------------------------------
# P0-1 租户隔离：X-Tenant-ID 不能单独作为凭据
# --------------------------------------------------------------------------


def test_tenant_header_cannot_impersonate_without_key(client, make_tenant):
    tenant_id, _, auth_headers = make_tenant("被冒充牧场")
    client.post(
        "/api/v1/devices/collect",
        headers=auth_headers,
        json={"adapter_type": "mock_rfid", "animal_id": "CN-1"},
    )

    # 只带伪造的 X-Tenant-ID、不带任何 Key -> 拒绝
    forged = client.get("/api/v1/devices/events", headers={"X-Tenant-ID": tenant_id})
    assert forged.status_code == 401

    # 带合法 Key 正常读取本租户数据
    own = client.get("/api/v1/devices/events", headers=auth_headers)
    assert own.status_code == 200
    assert len(own.json()) == 1

    # 匿名访问仍归属默认租户（保持单机演示可用）
    assert client.get("/api/v1/devices/events").status_code == 200
    assert (
        client.get(
            "/api/v1/devices/events",
            headers={"X-Tenant-ID": settings.default_tenant_id},
        ).status_code
        == 200
    )


def test_tenant_header_fallback_requires_explicit_opt_in(
    client, make_tenant, monkeypatch
):
    tenant_id, _, _ = make_tenant("联调牧场")

    monkeypatch.setattr(settings, "allow_tenant_header_fallback", True)
    assert (
        client.get(
            "/api/v1/devices/events", headers={"X-Tenant-ID": tenant_id}
        ).status_code
        == 200
    )

    monkeypatch.setattr(settings, "allow_tenant_header_fallback", False)
    assert (
        client.get(
            "/api/v1/devices/events", headers={"X-Tenant-ID": tenant_id}
        ).status_code
        == 401
    )


# --------------------------------------------------------------------------
# P0-2 列表接口必须返回“最新”而非“最旧”的 N 条
# --------------------------------------------------------------------------


def test_event_list_with_limit_returns_latest(client):
    for i in range(5):
        ingestion_gateway.ingest(
            [
                SensorReadingEvent(
                    device_id="d",
                    metric="m",
                    value=float(i),
                    unit="",
                    tenant_id="default",
                    timestamp=f"2026-01-01T00:00:0{i}+00:00",
                )
            ]
        )

    latest = ingestion_gateway.list_events(tenant_id="default", limit=2)
    assert [event.value for event in latest] == [3.0, 4.0]

    # 不带 limit 时仍按时间升序返回全部
    everything = ingestion_gateway.list_events(tenant_id="default", limit=None)
    assert [event.value for event in everything] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_alert_repository_with_limit_returns_latest(client):
    repository = SqliteAlertRepository(settings.alert_db_path)
    try:
        for i in range(5):
            repository.append(
                AnimalHealthEvent(
                    animal_id=f"A{i}",
                    metric="body_temperature",
                    value=41.0,
                    severity=HealthSeverity.critical,
                    timestamp=f"2026-01-01T00:00:0{i}+00:00",
                    tenant_id="default",
                )
            )
        latest = repository.list(tenant_id="default", limit=2)
    finally:
        repository.close()

    assert [alert.animal_id for alert in latest] == ["A3", "A4"]


# --------------------------------------------------------------------------
# P0-3 系谱：A 矩阵与登记顺序无关；环路/自引用被拒绝
# --------------------------------------------------------------------------


def test_relationship_matrix_is_registration_order_independent():
    forward = PedigreeManager()
    for animal in _full_sib_pedigree():
        forward.add_animal(animal)

    reverse = PedigreeManager()
    for animal in reversed(_full_sib_pedigree()):
        reverse.add_animal(animal)

    forward_matrix, forward_index = _matrix_by_id(forward)
    reverse_matrix, reverse_index = _matrix_by_id(reverse)

    for first in PEDIGREE_IDS:
        for second in PEDIGREE_IDS:
            assert forward_matrix[forward_index[first], forward_index[second]] == (
                pytest.approx(reverse_matrix[reverse_index[first], reverse_index[second]])
            )

    # 全同胞交配的子代近交系数必须为 0.25（修复前逆序登记会算成 0）
    assert forward.inbreeding_coefficients()["C"] == pytest.approx(0.25)
    assert reverse.inbreeding_coefficients()["C"] == pytest.approx(0.25)


def test_blup_inverse_consistent_across_registration_order():
    forward = PedigreeManager()
    for animal in _full_sib_pedigree():
        forward.add_animal(animal)
    reverse = PedigreeManager()
    for animal in reversed(_full_sib_pedigree()):
        reverse.add_animal(animal)

    forward_inverse, forward_ids = forward.build_additive_relationship_inverse()
    reverse_inverse, reverse_ids = reverse.build_additive_relationship_inverse()

    forward_index = {animal_id: i for i, animal_id in enumerate(forward_ids)}
    reverse_index = {animal_id: i for i, animal_id in enumerate(reverse_ids)}
    for first in PEDIGREE_IDS:
        for second in PEDIGREE_IDS:
            assert forward_inverse[forward_index[first], forward_index[second]] == (
                pytest.approx(
                    reverse_inverse[reverse_index[first], reverse_index[second]]
                )
            )


def test_pedigree_cycle_rejected_by_api(client):
    first = client.post(
        "/api/v1/breeding/animals", json={"animal_id": "X", "sire_id": "Y"}
    )
    assert first.status_code == 200  # 亲本尚未登记：告警但允许
    assert first.json()["parent_problems"] == ["父本 Y 不存在"]

    # Y 以 X 为父 -> 形成 X -> Y -> X 环路，必须拒绝
    second = client.post(
        "/api/v1/breeding/animals", json={"animal_id": "Y", "sire_id": "X"}
    )
    assert second.status_code == 422

    # 被拒绝的个体不得留在系谱中
    assert client.get("/api/v1/breeding/inbreeding").json() == {"X": 0.0}


def test_self_parent_rejected_by_api(client):
    response = client.post(
        "/api/v1/breeding/animals", json={"animal_id": "Z", "sire_id": "Z"}
    )
    assert response.status_code == 422
    assert client.get("/api/v1/breeding/inbreeding").json() == {}


# --------------------------------------------------------------------------
# P1-1 育种模块：租户隔离 + 持久化
# --------------------------------------------------------------------------


def test_pedigree_isolated_per_tenant(client, make_tenant):
    _, _, first_headers = make_tenant("牧场甲")
    _, _, second_headers = make_tenant("牧场乙")

    client.post(
        "/api/v1/breeding/animals",
        headers=first_headers,
        json={"animal_id": "A1", "sire_id": "S1"},
    )

    assert client.get(
        "/api/v1/breeding/inbreeding", headers=first_headers
    ).json() == {"A1": 0.0}
    # 异构租户看不到他人系谱
    assert client.get("/api/v1/breeding/inbreeding", headers=second_headers).json() == {}


def test_pedigree_persists_and_reloads(client, make_tenant):
    tenant_id, _, headers = make_tenant("持久化牧场")
    client.post(
        "/api/v1/breeding/animals", headers=headers, json={"animal_id": "P1"}
    )

    store = SqlitePedigreeStore(settings.pedigree_db_path)
    try:
        loaded = store.load(tenant_id)
    finally:
        store.close()
    assert loaded is not None
    assert [animal.animal_id for animal in loaded] == ["P1"]

    # 清空内存缓存后仍能读回（等价于进程重启）
    pedigree_registry.clear_cache()
    assert client.get("/api/v1/breeding/inbreeding", headers=headers).json() == {
        "P1": 0.0
    }


# --------------------------------------------------------------------------
# P1-2 告警趋势状态有界
# --------------------------------------------------------------------------


def test_trend_state_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "alert_trend_window", 4)
    monkeypatch.setattr(settings, "alert_trend_max_entities", 5)
    alert_service.clear()
    try:
        for i in range(200):
            alert_service.handle_events([_reading("activity_index", 10.0, f"A-{i}")])
        assert len(alert_service._history) <= 5
        assert all(
            len(bucket) <= 4 for bucket in alert_service._history.values()
        )
    finally:
        alert_service.clear()


# --------------------------------------------------------------------------
# P1-4 死信补发：瞬时失败可重试
# --------------------------------------------------------------------------


def test_dead_letter_replay_retries_transient_failure(client, monkeypatch):
    monkeypatch.setattr(settings, "dead_letter_replay_max_retries", 2)
    monkeypatch.setattr(settings, "dead_letter_replay_retry_delay_seconds", 0.0)

    store = SqliteDeadLetterRepository(settings.push_dead_letter_db_path)
    try:
        store.append(
            DeadLetterRecord(
                notification=AlertNotification(
                    tenant_id="default",
                    animal_id="A-retry",
                    kind="health",
                    severity="critical",
                    message="retry probe",
                ),
                channel="webhook",
                url="https://example.com/hook",
                reason="probe",
                attempts=3,
            )
        )
        record_id = store.list(tenant_id="default", limit=500)[-1].record_id
    finally:
        store.close()

    calls = {"count": 0}

    class _FlakyChannel:
        name = "flaky"

        def send(self, notification) -> None:
            calls["count"] += 1
            if calls["count"] < 3:
                raise RuntimeError("transient network error")

    monkeypatch.setattr(dead_letter_api, "_build_channel", lambda record: _FlakyChannel())

    response = client.post(f"/api/v1/alerts/dead-letters/{record_id}/replay")
    assert response.status_code == 200
    assert calls["count"] == 3  # 第 3 次才成功

    verify = SqliteDeadLetterRepository(settings.push_dead_letter_db_path)
    try:
        assert verify.get(record_id) is None  # 补发成功即删除
    finally:
        verify.close()


# --------------------------------------------------------------------------
# 入参长度校验：不一致时返回 422 而不是 numpy 内部异常
# --------------------------------------------------------------------------


def test_blup_rejects_length_mismatch(client):
    response = client.post(
        "/api/v1/breeding/blup",
        json={"animals": [{"animal_id": "S"}, {"animal_id": "D"}], "phenotypes": [1.0]},
    )
    assert response.status_code == 422


def test_blup_rejects_fixed_effect_length_mismatch(client):
    response = client.post(
        "/api/v1/breeding/blup",
        json={
            "animals": [{"animal_id": "S"}, {"animal_id": "D"}],
            "phenotypes": [1.0, 2.0],
            "fixed_effect_levels": [0],
        },
    )
    assert response.status_code == 422


def test_gblup_rejects_length_mismatch(client):
    response = client.post(
        "/api/v1/genomics/gblup",
        json={"genotypes": [[0, 2], [2, 0]], "phenotypes": [1.0]},
    )
    assert response.status_code == 422
