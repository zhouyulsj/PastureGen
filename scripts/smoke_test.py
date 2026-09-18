import sqlite3
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.core.config import settings
from app.device_ingestion.event_models import SensorReadingEvent
from app.device_ingestion.ingestion_gateway import ingestion_gateway
from app.main import app
from app.notification import router as dead_letter_api
from app.notification.channels import InMemoryNotificationChannel
from app.notification.dead_letter import DeadLetterRecord
from app.notification.dispatcher import NotificationDispatcher
from app.notification.models import AlertNotification
from app.notification.queue_push import PushQueue, maybe_queued
from app.notification.routing import make_tenant_channel_resolver
from app.notification.sqlite_dead_letter import SqliteDeadLetterRepository
from app.perception.alert_service import alert_service
from app.perception.sqlite_alert_repository import SqliteAlertRepository
from app.tenant.metadata import tenant_metadata_registry
from app.tenant.sqlite_store import SqliteMetadataStore, SqliteTenantRepository
from app.tenant.tenant_registry import hash_api_key

FEISHU_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/smoke-test"


def run() -> None:
    settings.admin_api_key = "smoke-admin-key"
    admin_headers = {"X-Admin-Key": settings.admin_api_key}
    with TestClient(app) as client:
        print("healthz:", client.get("/healthz").json())
        print("adapters:", client.get("/api/v1/devices/adapters").json())

        collect = client.post(
            "/api/v1/devices/collect",
            json={"adapter_type": "mock_rfid", "animal_id": "CN-0001"},
        )
        print("collect:", collect.json())
        print("events:", client.get("/api/v1/devices/events").json())

        persisted = ingestion_gateway.query_repository(metric="rfid_presence")
        print("persisted_count:", len(persisted))

        webhook_scale = client.post(
            "/api/v1/devices/webhook/http_scale",
            json={"animal_id": "CN-0001", "weight_kg": 650.5},
        )
        print("webhook_scale:", webhook_scale.json())
        webhook_camera = client.post(
            "/api/v1/devices/webhook/http_camera",
            json={"count": 128},
        )
        print("webhook_camera:", webhook_camera.json())
        print(
            "adapter_types:",
            [a["type"] for a in client.get("/api/v1/devices/adapters").json()],
        )

        for animal in [
            {"animal_id": "S"},
            {"animal_id": "D"},
            {"animal_id": "A", "sire_id": "S", "dam_id": "D"},
        ]:
            print("animal:", client.post("/api/v1/breeding/animals", json=animal).json())
        print("inbreeding:", client.get("/api/v1/breeding/inbreeding").json())

        blup_payload = {
            "animals": [
                {"animal_id": "S"},
                {"animal_id": "D"},
                {"animal_id": "A", "sire_id": "S", "dam_id": "D"},
                {"animal_id": "B"},
                {"animal_id": "C"},
                {"animal_id": "E", "sire_id": "B", "dam_id": "C"},
            ],
            "phenotypes": [10.0, 12.0, 15.0, 8.0, 9.0, 14.0],
            "fixed_effect_levels": [0, 0, 0, 1, 1, 1],
            "heritability": 0.3,
        }
        blup_result = client.post("/api/v1/breeding/blup", json=blup_payload).json()
        print("blup_breeding_values:", blup_result["breeding_values"])
        print("blup_reliabilities:", blup_result["reliabilities"])

        print(
            "qc:",
            client.post(
                "/api/v1/genomics/quality-control",
                json={"genotypes": [[0, 1, 2], [2, 1, 0], [1, 1, 1]]},
            ).json(),
        )
        print(
            "gblup:",
            client.post(
                "/api/v1/genomics/gblup",
                json={
                    "genotypes": [[0, 2], [2, 0]],
                    "phenotypes": [1.0, 2.0],
                    "heritability": 0.3,
                },
            ).json(),
        )

        unauth = client.get("/api/v1/tenants")
        print("tenants_no_admin_status:", unauth.status_code)
        assert unauth.status_code == 401

        created = client.post(
            "/api/v1/tenants",
            headers=admin_headers,
            json={"display_name": "望京示范牧场", "breed_code": "holstein"},
        ).json()
        tenant_id = created["tenant_id"]
        api_key = created["api_key"]
        print("tenant_created:", tenant_id)
        assert tenant_id.startswith("TNT-") and api_key

        auth_headers = {"X-API-Key": api_key}
        current = client.get("/api/v1/tenants/current", headers=auth_headers).json()
        print("tenant_current:", current)
        assert current["tenant_id"] == tenant_id

        trait = client.post(
            "/api/v1/tenants/current/traits",
            headers=auth_headers,
            json={
                "trait_code": "teat_score",
                "name": "乳头评分",
                "unit": "分",
                "heritability": 0.25,
            },
        ).json()
        print("tenant_trait:", trait)
        assert trait["trait"]["name"] == "乳头评分"

        threshold = client.post(
            "/api/v1/tenants/current/alert-thresholds",
            headers=auth_headers,
            json={"metric": "activity_index", "low": 0.5, "high": 3.0},
        ).json()
        print("tenant_threshold:", threshold)
        assert threshold["bounds"] == [0.5, 3.0]

        metadata = client.get(
            "/api/v1/tenants/current/metadata", headers=auth_headers
        ).json()
        print(
            "tenant_metadata:",
            sorted(metadata["traits"]),
            sorted(metadata["alert_thresholds"]),
        )
        assert "teat_score" in metadata["traits"]
        assert "activity_index" in metadata["alert_thresholds"]
        assert "milk_yield_305d" in metadata["traits"]

        notification = client.put(
            "/api/v1/tenants/current/notification",
            headers=auth_headers,
            json={"webhook_url": FEISHU_URL, "webhook_format": "feishu"},
        ).json()
        print("tenant_notification:", notification)
        assert notification["webhook_url"] == FEISHU_URL

        bad_format = client.put(
            "/api/v1/tenants/current/notification",
            headers=auth_headers,
            json={"webhook_url": "https://example.com/hook", "webhook_format": "slack"},
        )
        print("notification_bad_format_status:", bad_format.status_code)
        assert bad_format.status_code == 400

        reload_repo = SqliteTenantRepository(settings.tenant_db_path)
        reloaded_tenant = reload_repo.get(tenant_id)
        reload_repo.close()
        print("tenant_survives_restart:", reloaded_tenant is not None)
        assert reloaded_tenant is not None
        assert reloaded_tenant.api_key_hash == hash_api_key(api_key)
        assert reloaded_tenant.display_name == "望京示范牧场"

        # 落库仅存摘要：明文列被删除，且明文 Key 不出现在 api_key_hash 字段
        verify_conn = sqlite3.connect(settings.tenant_db_path)
        columns = {
            row[1] for row in verify_conn.execute("PRAGMA table_info(tenants)")
        }
        stored_hash = verify_conn.execute(
            "SELECT api_key_hash FROM tenants WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()[0]
        verify_conn.close()
        print("api_key_storage", "columns_has_plain:", "api_key" in columns)
        assert "api_key" not in columns and "api_key_hash" in columns
        assert stored_hash == hash_api_key(api_key) and stored_hash != api_key

        reload_store = SqliteMetadataStore(settings.tenant_db_path)
        reloaded_meta = reload_store.load(tenant_id)
        reload_store.close()
        print("metadata_survives_restart:", reloaded_meta is not None)
        assert reloaded_meta is not None
        assert "teat_score" in reloaded_meta.traits
        assert "milk_yield_305d" in reloaded_meta.traits
        assert reloaded_meta.alert_thresholds.get("activity_index") == [0.5, 3.0]
        assert reloaded_meta.notification_webhook_url == FEISHU_URL
        print("notification_survives_restart:", reloaded_meta.notification_webhook_url)

        listed = client.get("/api/v1/tenants", headers=admin_headers).json()
        assert all("api_key" not in item for item in listed)
        print("tenant_listed:", [item["tenant_id"] for item in listed])

        bad = client.get("/api/v1/tenants/current", headers={"X-API-Key": "not-a-real-key"})
        print("tenant_bad_key_status:", bad.status_code)
        assert bad.status_code == 401

        # 旧版明文库迁移：打开新仓储后老 Key 仍可认证，且明文列被彻底删除
        legacy_path = Path("data/smoke_tenant_legacy.db")
        legacy_path.unlink(missing_ok=True)
        legacy_key = f"legacy-{uuid.uuid4().hex}"
        legacy_conn = sqlite3.connect(legacy_path)
        legacy_conn.execute(
            "CREATE TABLE tenants ("
            "tenant_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
            "breed_code TEXT NOT NULL, api_key TEXT NOT NULL, status TEXT NOT NULL)"
        )
        legacy_conn.execute(
            "INSERT INTO tenants VALUES ('TNT-legacy', '遗留牧场', 'holstein', ?, 'active')",
            (legacy_key,),
        )
        legacy_conn.commit()
        legacy_conn.close()
        legacy_repo = SqliteTenantRepository(str(legacy_path))
        migrated = legacy_repo.find_by_api_key(legacy_key)
        wrong = legacy_repo.find_by_api_key("wrong-key")
        legacy_repo.close()
        recheck = sqlite3.connect(legacy_path)
        after_columns = {
            row[1] for row in recheck.execute("PRAGMA table_info(tenants)")
        }
        recheck.close()
        legacy_path.unlink(missing_ok=True)
        print("legacy_key_migrated:", migrated is not None, "api_key" not in after_columns)
        assert migrated is not None and migrated.tenant_id == "TNT-legacy"
        assert migrated.api_key_hash == hash_api_key(legacy_key)
        assert wrong is None
        assert "api_key" not in after_columns

        default_events = client.get("/api/v1/devices/events").json()
        repo_events = ingestion_gateway.query_repository(tenant_id="default", limit=200)
        print("event_readthrough:", len(default_events), len(repo_events))
        assert len(default_events) == len(repo_events)
        isolated = client.post(
            "/api/v1/tenants",
            headers=admin_headers,
            json={"display_name": "隔离测试牧场"},
        ).json()
        other_events = client.get(
            "/api/v1/devices/events", headers={"X-API-Key": isolated["api_key"]}
        ).json()
        print("isolation:", len(default_events), len(other_events))
        assert len(default_events) > 0
        assert other_events == []

        def _reading(metric: str, value: float, animal: str) -> SensorReadingEvent:
            return SensorReadingEvent(
                device_id="alert-sim",
                metric=metric,
                value=value,
                unit="",
                animal_id=animal,
                tenant_id="default",
            )

        for value in [10.0, 10.0, 30.0]:
            ingestion_gateway.ingest([_reading("activity_index", value, "A-act")])
        for value in [39.0, 39.0, 38.3]:
            ingestion_gateway.ingest([_reading("body_temperature", value, "A-temp")])
        ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])

        alerts = client.get("/api/v1/alerts").json()
        kinds = {a.get("severity") or a.get("event_type") for a in alerts}
        print("alert_kinds:", sorted(kinds))
        assert "critical" in kinds
        assert "estrus" in kinds
        assert "calving" in kinds

        iso_alerts = client.get(
            "/api/v1/alerts", headers={"X-API-Key": isolated["api_key"]}
        ).json()
        print("isolated_alert_count:", len(iso_alerts))
        assert iso_alerts == []

        before_cooldown = len(alert_service.list_alerts(tenant_id="default"))
        ingestion_gateway.ingest([_reading("body_temperature", 40.5, "A-fever")])
        after_cooldown = len(alert_service.list_alerts(tenant_id="default"))
        print("cooldown_dedup:", before_cooldown, after_cooldown)
        assert after_cooldown == before_cooldown

        reload_alerts = SqliteAlertRepository(settings.alert_db_path)
        persisted_alerts = reload_alerts.list(tenant_id="default", limit=500)
        reload_alerts.close()
        persisted_kinds = {
            a.get("severity") or a.get("event_type")
            for a in (x.model_dump(mode="json") for x in persisted_alerts)
        }
        print("alert_survives_restart:", sorted(persisted_kinds))
        assert "critical" in persisted_kinds
        assert "estrus" in persisted_kinds
        assert "calving" in persisted_kinds

        class _FailingChannel:
            name = "failing"

            def send(self, notification) -> None:
                raise RuntimeError("channel down")

        memory_channel = InMemoryNotificationChannel()
        alert_service.bind_notifier(
            NotificationDispatcher([_FailingChannel(), memory_channel])
        )
        push_animal = f"A-push-{uuid.uuid4().hex[:8]}"
        ingestion_gateway.ingest([_reading("body_temperature", 41.2, push_animal)])
        print("push_delivered:", [n.message for n in memory_channel.sent])
        assert len(memory_channel.sent) == 1
        assert push_animal in memory_channel.sent[0].message
        default_alerts = alert_service.list_alerts(tenant_id="default", limit=500)
        assert any(a.animal_id == push_animal for a in default_alerts)
        ingestion_gateway.ingest([_reading("body_temperature", 41.2, push_animal)])
        assert len(memory_channel.sent) == 1
        print("cooldown_no_push:", len(memory_channel.sent))

        resolver = make_tenant_channel_resolver(tenant_metadata_registry)
        tenant_channels = resolver(tenant_id)
        print(
            "resolver_routed:",
            bool(tenant_channels) and tenant_channels[0].url,
        )
        assert tenant_channels is not None
        assert tenant_channels[0].url == FEISHU_URL
        assert tenant_channels[0].payload_format == "feishu"
        assert resolver("default") is None

        global_channel = InMemoryNotificationChannel()
        tenant_channel = InMemoryNotificationChannel()
        routing_dispatcher = NotificationDispatcher(
            [global_channel],
            tenant_channel_resolver=lambda tid: (
                [tenant_channel] if tid == "default" else None
            ),
        )
        sample_alert = alert_service.list_alerts(tenant_id="default", limit=1)[-1]
        routed = routing_dispatcher.notify(sample_alert)
        print("routing_tenant_only:", routed, len(tenant_channel.sent), len(global_channel.sent))
        assert routed == [tenant_channel.name]
        assert len(tenant_channel.sent) == 1
        assert len(global_channel.sent) == 0
        fallback_alert = sample_alert.model_copy(update={"tenant_id": "no-webhook"})
        fallback = routing_dispatcher.notify(fallback_alert)
        print("routing_global_fallback:", fallback)
        assert fallback == [global_channel.name]
        assert len(global_channel.sent) == 1

        class _SlowChannel:
            name = "slow"

            def __init__(self) -> None:
                self.sent = []

            def send(self, notification) -> None:
                time.sleep(0.3)
                self.sent.append(notification)

        class _BrokenChannel:
            name = "broken"

            def send(self, notification) -> None:
                raise RuntimeError("push endpoint down")

        push_queue = PushQueue(maxsize=10, max_retries=0, retry_delay=0.0)
        push_queue.start()
        slow_channel = _SlowChannel()
        queue_dispatcher = NotificationDispatcher(
            [maybe_queued(slow_channel, push_queue)]
        )
        started_at = time.perf_counter()
        accepted = queue_dispatcher.notify(sample_alert)
        elapsed = time.perf_counter() - started_at
        print("async_notify_elapsed:", round(elapsed, 3), "accepted:", accepted)
        assert elapsed < 0.1
        assert accepted == ["slow"]
        assert push_queue.wait_idle(timeout=5)
        assert len(slow_channel.sent) == 1

        broken_dispatcher = NotificationDispatcher(
            [maybe_queued(_BrokenChannel(), push_queue)]
        )
        broken_dispatcher.notify(sample_alert)
        assert push_queue.wait_idle(timeout=5)
        print("push_queue_stats:", push_queue.sent, push_queue.failed, push_queue.dropped)
        assert push_queue.sent >= 1
        assert push_queue.failed >= 1
        push_queue.shutdown()

        dummy = AlertNotification(
            tenant_id="default",
            animal_id="x",
            kind="health",
            severity="critical",
            message="queue overflow probe",
        )
        tiny_queue = PushQueue(maxsize=1)
        assert tiny_queue.submit(slow_channel, dummy) is True
        assert tiny_queue.submit(slow_channel, dummy) is False
        print("queue_overflow_dropped:", tiny_queue.dropped)
        assert tiny_queue.dropped == 1

        # 重试与死信：使用可删重来的临时库，保证脚本可重复运行
        dl_path = Path("data/smoke_dead_letter.db")
        dl_path.unlink(missing_ok=True)
        dl_store = SqliteDeadLetterRepository(str(dl_path))

        class _FlakyChannel:
            name = "flaky"

            def __init__(self) -> None:
                self.calls = 0

            def send(self, notification) -> None:
                self.calls += 1
                if self.calls <= 2:
                    raise RuntimeError("transient network error")

        retry_queue = PushQueue(
            maxsize=10, max_retries=3, retry_delay=0.01, dead_letter=dl_store
        )
        retry_queue.start()
        NotificationDispatcher([maybe_queued(_FlakyChannel(), retry_queue)]).notify(
            sample_alert
        )
        assert retry_queue.wait_idle(timeout=5)
        print(
            "retry_then_success:",
            retry_queue.sent, retry_queue.retried, retry_queue.failed,
        )
        assert retry_queue.sent == 1
        assert retry_queue.retried == 2
        assert retry_queue.failed == 0
        assert dl_store.count() == 0

        exhausted_queue = PushQueue(
            maxsize=10, max_retries=2, retry_delay=0.01, dead_letter=dl_store
        )
        exhausted_queue.start()
        NotificationDispatcher(
            [maybe_queued(_BrokenChannel(), exhausted_queue)]
        ).notify(sample_alert)
        assert exhausted_queue.wait_idle(timeout=5)
        exhausted_queue.shutdown()
        dead_records = dl_store.list()
        print(
            "dead_letter_after_retries:",
            exhausted_queue.failed, exhausted_queue.retried, len(dead_records),
        )
        assert exhausted_queue.failed == 1
        assert exhausted_queue.retried == 2
        assert len(dead_records) == 1
        assert dead_records[0].channel == "broken"
        assert "push endpoint down" in dead_records[0].reason
        assert dead_records[0].attempts == 3
        assert dead_records[0].notification.animal_id == sample_alert.animal_id

        dl_tiny = PushQueue(
            maxsize=1, max_retries=0, retry_delay=0.0, dead_letter=dl_store
        )
        assert dl_tiny.submit(_BrokenChannel(), dummy) is True
        assert dl_tiny.submit(_BrokenChannel(), dummy) is False
        print("dead_letter_on_overflow:", dl_tiny.dropped, dl_tiny.dead_lettered)
        assert dl_tiny.dead_lettered == 1
        overflow_record = dl_store.list()[-1]
        assert overflow_record.reason == "queue_full"
        assert overflow_record.attempts == 0

        drain_queue = PushQueue(
            maxsize=5, max_retries=0, retry_delay=0.0, dead_letter=dl_store
        )
        assert drain_queue.submit(_BrokenChannel(), dummy) is True
        drain_queue.shutdown()  # 未消费即退出：余量落死信
        print("shutdown_drain_dead_letter:", drain_queue.dead_lettered)
        assert drain_queue.dead_lettered == 1
        retry_queue.shutdown()
        dl_store.close()

        reload_dl = SqliteDeadLetterRepository(str(dl_path))
        persisted_dead = reload_dl.list(tenant_id="default")
        reload_dl.close()
        print("dead_letter_survives_restart:", len(persisted_dead))
        assert len(persisted_dead) == 3

        # 死信查询 / 补发 API（应用绑定的正式死信库）
        dl_api_store = SqliteDeadLetterRepository(settings.push_dead_letter_db_path)
        marker = uuid.uuid4().hex[:8]
        probe_note = AlertNotification(
            tenant_id="default",
            animal_id=f"A-dl-{marker}",
            kind="health",
            severity="critical",
            message=f"dead letter api probe {marker}",
        )
        dl_api_store.append(
            DeadLetterRecord(
                notification=probe_note,
                channel="webhook",
                url="http://127.0.0.1:9/unreachable",
                reason="manual probe",
                attempts=3,
            )
        )
        foreign_note = probe_note.model_copy(
            update={"tenant_id": f"TNT-foreign-{marker}"}
        )
        dl_api_store.append(
            DeadLetterRecord(
                notification=foreign_note,
                channel="webhook",
                url="http://127.0.0.1:9/unreachable",
                reason="foreign probe",
                attempts=1,
            )
        )

        dl_listing = client.get(
            "/api/v1/alerts/dead-letters", params={"limit": 500}
        ).json()
        mine = [
            r for r in dl_listing["items"] if marker in r["notification"]["message"]
        ]
        print(
            "dead_letter_api_list:",
            dl_listing["tenant_id"], len(mine), dl_listing["total"],
        )
        assert dl_listing["tenant_id"] == "default"
        assert len(mine) == 1  # 他租户死信不可见
        probe_record = mine[0]
        assert probe_record["record_id"] is not None
        assert probe_record["url"] == "http://127.0.0.1:9/unreachable"

        foreign_id = dl_api_store.list(tenant_id=f"TNT-foreign-{marker}")[0].record_id
        forbidden = client.post(f"/api/v1/alerts/dead-letters/{foreign_id}/replay")
        print("dead_letter_replay_foreign_status:", forbidden.status_code)
        assert forbidden.status_code == 404

        failed_replay = client.post(
            f"/api/v1/alerts/dead-letters/{probe_record['record_id']}/replay"
        )
        print("dead_letter_replay_fail_status:", failed_replay.status_code)
        assert failed_replay.status_code == 502
        still_there = client.get(
            "/api/v1/alerts/dead-letters", params={"limit": 500}
        ).json()
        assert any(
            marker in r["notification"]["message"] for r in still_there["items"]
        )  # 补发失败保留记录

        replay_memory = InMemoryNotificationChannel()
        original_builder = dead_letter_api._build_channel
        dead_letter_api._build_channel = lambda record: replay_memory
        try:
            ok_replay = client.post(
                f"/api/v1/alerts/dead-letters/{probe_record['record_id']}/replay"
            )
        finally:
            dead_letter_api._build_channel = original_builder
        print("dead_letter_replay_ok:", ok_replay.status_code, len(replay_memory.sent))
        assert ok_replay.status_code == 200
        assert len(replay_memory.sent) == 1
        assert replay_memory.sent[0].animal_id == f"A-dl-{marker}"

        after = client.get("/api/v1/alerts/dead-letters", params={"limit": 500}).json()
        remaining = [
            r for r in after["items"] if marker in r["notification"]["message"]
        ]
        print("dead_letter_after_replay:", len(remaining))
        assert remaining == []  # 成功补发即删除
        assert dl_api_store.get(foreign_id) is not None  # 他租户记录未被动过
        dl_api_store.delete(foreign_id)
        dl_api_store.close()

    print("ALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    run()