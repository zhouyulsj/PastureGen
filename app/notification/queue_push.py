import queue
import threading
import time

from app.notification.channels import NotificationChannel
from app.notification.dead_letter import DeadLetterRecord, DeadLetterRepository
from app.notification.models import AlertNotification

# 指数退避的单次等待上限（秒），防止重试间隔无限膨胀
_MAX_RETRY_DELAY = 30.0


class PushQueue:
    """后台推送队列：入队即返回，网络发送在守护线程中串行执行。

    发送失败按指数退避重试（max_retries 次），重试耗尽 / 队满丢弃 /
    进程关停时把消息落入死信仓储，保证告警推送不静默丢失；
    死信记录本身失败也不影响推送线程（best-effort）。
    """

    def __init__(
        self,
        maxsize: int = 1000,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        dead_letter: DeadLetterRepository | None = None,
    ) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._max_retries = max(0, int(max_retries))
        self._retry_delay = max(0.0, float(retry_delay))
        self._dead_letter = dead_letter
        self.sent = 0
        self.failed = 0  # 重试耗尽后的最终失败
        self.dropped = 0
        self.retried = 0  # 累计重试尝试次数
        self.dead_lettered = 0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._worker, name="alert-push-queue", daemon=True
        )
        self._thread.start()

    def submit(self, channel: NotificationChannel, notification: AlertNotification) -> bool:
        try:
            self._queue.put_nowait((channel, notification))
            return True
        except queue.Full:
            self.dropped += 1
            self._record_dead(channel, notification, "queue_full", attempts=0)
            return False

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """等待所有已入队消息处理完毕（含正在发送的当前条）。"""
        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.02)
        return not self._queue.unfinished_tasks

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        # 队列中仍未消费的消息全部落入死信，进程退出不静默丢失
        while True:
            try:
                channel, notification = self._queue.get_nowait()
            except queue.Empty:
                break
            self.dropped += 1
            self._record_dead(channel, notification, "shutdown", attempts=0)
            self._queue.task_done()

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                channel, notification = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._deliver(channel, notification)
            self._queue.task_done()

    def _deliver(self, channel: NotificationChannel, notification: AlertNotification) -> None:
        """发送一条消息：失败按指数退避重试，耗尽后落死信。"""
        attempts = 0
        while True:
            try:
                channel.send(notification)
                self.sent += 1
                return
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                if attempts >= self._max_retries:
                    self.failed += 1
                    self._record_dead(channel, notification, reason, attempts=attempts + 1)
                    return
                delay = min(self._retry_delay * (2 ** attempts), _MAX_RETRY_DELAY)
                attempts += 1
                self.retried += 1
                if self._stop.wait(delay):
                    # 进程关停：不再重试，直接落死信，消息不静默丢失
                    self.failed += 1
                    self._record_dead(channel, notification, "shutdown", attempts=attempts)
                    return

    def _record_dead(
        self,
        channel: NotificationChannel,
        notification: AlertNotification,
        reason: str,
        attempts: int,
    ) -> None:
        """写一条死信；仓储异常被吞并，绝不让推送线程崩溃。"""
        if self._dead_letter is None:
            return
        try:
            self._dead_letter.append(
                DeadLetterRecord(
                    notification=notification,
                    channel=getattr(channel, "name", "unknown"),
                    url=getattr(channel, "url", ""),
                    payload_format=getattr(channel, "payload_format", "feishu"),
                    reason=reason[:500],
                    attempts=attempts,
                )
            )
            self.dead_lettered += 1
        except Exception:
            pass


class QueuedNotificationChannel:
    """通道装饰器：对 dispatcher 透明，send 只负责入队（纳秒级返回）。"""

    def __init__(self, inner: NotificationChannel, push_queue: PushQueue) -> None:
        self.inner = inner
        self.name = getattr(inner, "name", "queued")
        self._push = push_queue

    def send(self, notification: AlertNotification) -> None:
        self._push.submit(self.inner, notification)


def maybe_queued(
    channel: NotificationChannel, push_queue: PushQueue | None
) -> NotificationChannel:
    """有队列则异步包装，无队列保持原通道；重复包装幂等。"""
    if push_queue is None or isinstance(channel, QueuedNotificationChannel):
        return channel
    return QueuedNotificationChannel(channel, push_queue)
