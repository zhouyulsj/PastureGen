from typing import Callable

from app.notification.channels import NotificationChannel
from app.notification.models import notification_from_alert
from app.perception.alert_repository import Alert

TenantChannelResolver = Callable[[str], "list[NotificationChannel] | None"]


class NotificationDispatcher:
    """把告警扇出到推送通道；单通道失败被吞并，绝不影响告警入库主链路。

    路由规则：若 tenant_channel_resolver 为该租户解析出专属通道（如牧场自己的
    飞书群 webhook），则只推租户通道；否则回落到全局通道。
    """

    def __init__(
        self,
        channels: list[NotificationChannel] | None = None,
        tenant_channel_resolver: TenantChannelResolver | None = None,
    ) -> None:
        self._channels: list[NotificationChannel] = list(channels or [])
        self._resolver = tenant_channel_resolver

    def add_channel(self, channel: NotificationChannel) -> None:
        self._channels.append(channel)

    def _channels_for(self, tenant_id: str) -> list[NotificationChannel]:
        if self._resolver is not None:
            tenant_channels = self._resolver(tenant_id)
            if tenant_channels:
                return tenant_channels
        return self._channels

    def notify(self, alert: Alert) -> list[str]:
        """推送一条告警，返回成功送达的通道名列表（冷却抑制的告警不应进入此处）。"""
        try:
            notification = notification_from_alert(alert)
        except Exception:
            return []
        delivered: list[str] = []
        for channel in self._channels_for(notification.tenant_id):
            try:
                channel.send(notification)
                delivered.append(channel.name)
            except Exception:
                continue
        return delivered
