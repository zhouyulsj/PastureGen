"""租户 API 基线：管理鉴权、CRUD、元数据、通知配置与 API Key 哈希存储。"""

import sqlite3

from app.core.config import settings
from app.tenant.sqlite_store import SqliteMetadataStore, SqliteTenantRepository
from app.tenant.tenant_registry import hash_api_key

FEISHU_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/ci-test"


def test_list_tenants_requires_admin(client):
    assert client.get("/api/v1/tenants").status_code == 401
    wrong = client.get("/api/v1/tenants", headers={"X-Admin-Key": "nope"})
    assert wrong.status_code == 401


def test_create_and_authenticate_tenant(client, make_tenant):
    tenant_id, api_key, headers = make_tenant("望京示范牧场", breed_code="holstein")
    assert tenant_id.startswith("TNT-") and api_key
    current = client.get("/api/v1/tenants/current", headers=headers).json()
    assert current["tenant_id"] == tenant_id
    assert current["display_name"] == "望京示范牧场"


def test_bad_api_key_rejected(client):
    assert client.get(
        "/api/v1/tenants/current", headers={"X-API-Key": "not-a-real-key"}
    ).status_code == 401


def test_tenant_metadata_and_thresholds(client, make_tenant):
    _, _, headers = make_tenant()
    trait = client.post(
        "/api/v1/tenants/current/traits",
        headers=headers,
        json={
            "trait_code": "teat_score",
            "name": "乳头评分",
            "unit": "分",
            "heritability": 0.25,
        },
    ).json()
    assert trait["trait"]["name"] == "乳头评分"

    threshold = client.post(
        "/api/v1/tenants/current/alert-thresholds",
        headers=headers,
        json={"metric": "activity_index", "low": 0.5, "high": 3.0},
    ).json()
    assert threshold["bounds"] == [0.5, 3.0]

    metadata = client.get("/api/v1/tenants/current/metadata", headers=headers).json()
    assert "teat_score" in metadata["traits"]
    assert "milk_yield_305d" in metadata["traits"]  # 荷斯坦默认性状库
    assert metadata["alert_thresholds"]["activity_index"] == [0.5, 3.0]


def test_notification_config(client, make_tenant):
    _, _, headers = make_tenant()
    notification = client.put(
        "/api/v1/tenants/current/notification",
        headers=headers,
        json={"webhook_url": FEISHU_URL, "webhook_format": "feishu"},
    ).json()
    assert notification["webhook_url"] == FEISHU_URL
    bad_format = client.put(
        "/api/v1/tenants/current/notification",
        headers=headers,
        json={"webhook_url": "https://example.com/hook", "webhook_format": "slack"},
    )
    assert bad_format.status_code == 400


def test_api_key_hashed_at_rest(client, make_tenant):
    """库中只存 SHA-256 摘要：明文列不存在，明文 Key 不落库。"""
    tenant_id, api_key, _ = make_tenant()
    conn = sqlite3.connect(settings.tenant_db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tenants)")}
    stored_hash = conn.execute(
        "SELECT api_key_hash FROM tenants WHERE tenant_id = ?", (tenant_id,)
    ).fetchone()[0]
    conn.close()
    assert "api_key" not in columns and "api_key_hash" in columns
    assert stored_hash == hash_api_key(api_key) and stored_hash != api_key


def test_tenants_survive_repo_reopen(client, admin_headers, make_tenant):
    """重开仓储（模拟重启）后租户与元数据完整可用，Key 摘要可继续认证。"""
    tenant_id, api_key, _ = make_tenant("重启验证牧场")
    client.put(
        "/api/v1/tenants/current/notification",
        headers={"X-API-Key": api_key},
        json={"webhook_url": FEISHU_URL, "webhook_format": "feishu"},
    )

    repo = SqliteTenantRepository(settings.tenant_db_path)
    reloaded = repo.get(tenant_id)
    repo.close()
    assert reloaded is not None
    assert reloaded.api_key_hash == hash_api_key(api_key)
    assert reloaded.display_name == "重启验证牧场"

    store = SqliteMetadataStore(settings.tenant_db_path)
    metadata = store.load(tenant_id)
    store.close()
    assert metadata is not None
    assert metadata.notification_webhook_url == FEISHU_URL


def test_list_hides_api_keys(client, admin_headers, make_tenant):
    make_tenant()
    listed = client.get("/api/v1/tenants", headers=admin_headers).json()
    assert listed and all("api_key" not in item for item in listed)
