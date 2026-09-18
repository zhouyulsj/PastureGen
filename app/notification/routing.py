from app.notification.channels import NotificationChannel, WebhookNotificationChannel
from app.notification.dispatcher import TenantChannelResolver
from app.notification.queue_push import PushQueue, maybe_queued


def make_tenant_channel_resolver(
    registry, push_queue: PushQueue | None = None
) -> TenantChannelResolver:
    """基于租户元数据的通道解析器工厂。

    租户配置了 notification_webhook_url 则返回其专属 webhook 通道
    （有推送队列时自动异步化），否则返回 None（由调度器回落全局通道）。
    """

    def resolve(tenant_id: str) -> list[NotificationChannel] | None:
        metadata = registry.get_metadata(tenant_id)
        if metadata.notification_webhook_url:
            channel = WebhookNotificationChannel(
                metadata.notification_webhook_url,
                payload_format=metadata.notification_webhook_format,
            )
            return [maybe_queued(channel, push_queue)]
        return None

    return resolve
