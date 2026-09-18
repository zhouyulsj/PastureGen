import json
import urllib.request
from typing import Protocol

from app.notification.models import AlertNotification


class NotificationChannel(Protocol):
    """推送通道协议：send 抛出任何异常都由调度器隔离，不影响告警主链路。"""

    name: str

    def send(self, notification: AlertNotification) -> None:
        ...


def build_feishu_payload(notification: AlertNotification) -> dict:
    """飞书自定义机器人（群 webhook）文本消息格式。"""
    return {
        "msg_type": "text",
        "content": {
            "text": f"[牧场告警][{notification.tenant_id}] {notification.message}"
        },
    }


def build_generic_payload(notification: AlertNotification) -> dict:
    """通用 webhook：直接推送结构化 JSON。"""
    return notification.model_dump(mode="json")


_PAYLOAD_BUILDERS = {
    "feishu": build_feishu_payload,
    "generic": build_generic_payload,
}


class InMemoryNotificationChannel:
    """内存通道：记录消息不发送，用于本地开发与冒烟验证。"""

    name = "memory"

    def __init__(self) -> None:
        self.sent: list[AlertNotification] = []

    def send(self, notification: AlertNotification) -> None:
        self.sent.append(notification)

    def clear(self) -> None:
        self.sent.clear()


class WebhookNotificationChannel:
    """HTTP webhook 通道（标准库实现，支持飞书/generic 载荷格式）。"""

    name = "webhook"

    def __init__(self, url: str, payload_format: str = "feishu", timeout: float = 5.0) -> None:
        self.url = url
        self.payload_format = payload_format
        self._timeout = timeout

    def send(self, notification: AlertNotification) -> None:
        builder = _PAYLOAD_BUILDERS.get(self.payload_format, build_generic_payload)
        data = json.dumps(builder(notification), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            response.read()
