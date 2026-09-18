"""租户通知路由集成：基于元数据的通道解析（调度器路由见 test_push_queue）。"""

from app.notification.routing import make_tenant_channel_resolver
from app.tenant.metadata import tenant_metadata_registry

FEISHU_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/routing-test"


def test_resolver_reads_tenant_webhook_metadata(client, make_tenant):
    tenant_id, _, headers = make_tenant()
    client.put(
        "/api/v1/tenants/current/notification",
        headers=headers,
        json={"webhook_url": FEISHU_URL, "webhook_format": "feishu"},
    )
    resolver = make_tenant_channel_resolver(tenant_metadata_registry)
    channels = resolver(tenant_id)
    assert channels is not None
    assert channels[0].url == FEISHU_URL
    assert channels[0].payload_format == "feishu"
    assert resolver("default") is None  # 未配置通知的租户回落全局
