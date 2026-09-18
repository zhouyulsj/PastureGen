"""异步推送队列与死信单元测试：异步化、指数重试、队满/关停死信、租户路由。"""

import time

import pytest

from app.device_ingestion.event_models import AnimalHealthEvent, HealthSeverity
from app.notification.channels import InMemoryNotificationChannel
from app.notification.dead_letter import DeadLetterRecord
from app.notification.dispatcher import NotificationDispatcher
from app.notification.models import AlertNotification
from app.notification.queue_push import PushQueue, maybe_queued
from app.notification.sqlite_dead_letter import SqliteDeadLetterRepository


def _health_alert(tenant_id: str = "default") -> AnimalHealthEvent:
    return AnimalHealthEvent(
        animal_id="A-1",
        metric="body_temperature",
        value=41.0,
        severity=HealthSeverity.critical,
        tenant_id=tenant_id,
    )


@pytest.fixture
def dl_store(tmp_path):
    store = SqliteDeadLetterRepository(str(tmp_path / "dead_letter.db"))
    yield store
    store.close()


class _BrokenChannel:
    name = "broken"

    def send(self, notification) -> None:
        raise RuntimeError("push endpoint down")


class _FlakyChannel:
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    def send(self, notification) -> None:
        self.calls += 1
        if self.calls <= 2:  # 前两次瞬时失败，第三次成功
            raise RuntimeError("transient network error")


class _SlowChannel:
    name = "slow"

    def __init__(self) -> None:
        self.sent = []

    def send(self, notification) -> None:
        time.sleep(0.3)
        self.sent.append(notification)


def test_notify_via_queue_is_async():
    """入队即返回，不阻塞告警主链路；后台线程完成慢发送。"""
    queue = PushQueue(maxsize=10, max_retries=0, retry_delay=0.0)
    queue.start()
    try:
        slow = _SlowChannel()
        dispatcher = NotificationDispatcher([maybe_queued(slow, queue)])
        started = time.perf_counter()
        accepted = dispatcher.notify(_health_alert())
        elapsed = time.perf_counter() - started
        assert elapsed < 0.1
        assert accepted == ["slow"]
        assert queue.wait_idle(timeout=5)
        assert len(slow.sent) == 1
    finally:
        queue.shutdown()


def test_retry_then_success_no_dead_letter(dl_store):
    queue = PushQueue(maxsize=10, max_retries=3, retry_delay=0.01, dead_letter=dl_store)
    queue.start()
    try:
        NotificationDispatcher([maybe_queued(_FlakyChannel(), queue)]).notify(
            _health_alert()
        )
        assert queue.wait_idle(timeout=5)
        assert queue.sent == 1
        assert queue.retried == 2
        assert queue.failed == 0
        assert dl_store.count() == 0
    finally:
        queue.shutdown()


def test_retries_exhausted_land_in_dead_letter(dl_store):
    queue = PushQueue(maxsize=10, max_retries=2, retry_delay=0.01, dead_letter=dl_store)
    queue.start()
    try:
        NotificationDispatcher([maybe_queued(_BrokenChannel(), queue)]).notify(
            _health_alert()
        )
        assert queue.wait_idle(timeout=5)
    finally:
        queue.shutdown()
    assert queue.failed == 1
    assert queue.retried == 2
    records = dl_store.list()
    assert len(records) == 1
    assert records[0].channel == "broken"
    assert "push endpoint down" in records[0].reason
    assert records[0].attempts == 3  # 首次 + 2 次重试
    assert records[0].notification.animal_id == "A-1"


def test_queue_full_dropped_lands_in_dead_letter(dl_store):
    dummy = AlertNotification(
        tenant_id="default",
        animal_id="x",
        kind="health",
        severity="critical",
        message="queue overflow probe",
    )
    queue = PushQueue(maxsize=1, max_retries=0, retry_delay=0.0, dead_letter=dl_store)
    assert queue.submit(_BrokenChannel(), dummy) is True
    assert queue.submit(_BrokenChannel(), dummy) is False  # 队满拒绝
    assert queue.dropped == 1
    assert queue.dead_lettered == 1
    overflow = dl_store.list()[-1]
    assert overflow.reason == "queue_full"
    assert overflow.attempts == 0


def test_shutdown_drains_pending_to_dead_letter(dl_store):
    dummy = AlertNotification(
        tenant_id="default",
        animal_id="x",
        kind="health",
        severity="critical",
        message="shutdown drain probe",
    )
    queue = PushQueue(maxsize=5, max_retries=0, retry_delay=0.0, dead_letter=dl_store)
    assert queue.submit(_BrokenChannel(), dummy) is True
    queue.shutdown()  # 未消费即关停：余量落死信而非丢失
    assert queue.dead_lettered == 1
    reasons = [r.reason for r in dl_store.list()]
    assert any("shutdown" in r for r in reasons)


def test_dead_letter_records_survive_reopen(tmp_path):
    path = str(tmp_path / "dead_letter.db")
    store = SqliteDeadLetterRepository(path)
    store.append(
        DeadLetterRecord(
            notification=AlertNotification(
                tenant_id="default",
                animal_id="x",
                kind="health",
                severity="critical",
                message="persist probe",
            ),
            channel="webhook",
            url="http://127.0.0.1:9/unreachable",
            reason="manual probe",
            attempts=3,
        )
    )
    store.close()
    reopened = SqliteDeadLetterRepository(path)
    try:
        records = reopened.list(tenant_id="default")
        assert len(records) == 1
        assert records[0].notification.message == "persist probe"
    finally:
        reopened.close()


def test_dispatcher_tenant_channel_only_or_global_fallback():
    """租户有专属通道则不回落全局；无专属通道才推全局。"""
    global_channel = InMemoryNotificationChannel()
    tenant_channel = InMemoryNotificationChannel()
    dispatcher = NotificationDispatcher(
        [global_channel],
        tenant_channel_resolver=lambda tid: (
            [tenant_channel] if tid == "default" else None
        ),
    )
    routed = dispatcher.notify(_health_alert(tenant_id="default"))
    assert routed == [tenant_channel.name]
    assert len(tenant_channel.sent) == 1
    assert len(global_channel.sent) == 0

    fallback_alert = _health_alert(tenant_id="no-webhook")
    fallback = dispatcher.notify(fallback_alert)
    assert fallback == [global_channel.name]
    assert len(global_channel.sent) == 1


def test_dispatcher_swallows_single_channel_failure():
    ok = InMemoryNotificationChannel()
    dispatcher = NotificationDispatcher([_BrokenChannel(), ok])
    assert dispatcher.notify(_health_alert()) == [ok.name]
    assert len(ok.sent) == 1
