"""API Key 哈希存储单元测试：摘要算法确定性与旧版明文库自动迁移。"""

import hashlib
import sqlite3
import uuid

from app.tenant.sqlite_store import SqliteTenantRepository
from app.tenant.tenant_registry import hash_api_key


def test_hash_api_key_is_sha256_hexdigest():
    digest = hash_api_key("some-key")
    assert digest == hashlib.sha256(b"some-key").hexdigest()
    assert hash_api_key("some-key") == digest  # 确定性检索所需
    assert hash_api_key("other-key") != digest


def test_legacy_plaintext_db_migrated(tmp_path):
    """旧版明文 Key 库：打开新仓储后自动迁移，老 Key 仍可认证且明文列被删除。"""
    legacy_path = tmp_path / "legacy_tenant.db"
    legacy_key = f"legacy-{uuid.uuid4().hex}"
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE tenants ("
        "tenant_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, "
        "breed_code TEXT NOT NULL, api_key TEXT NOT NULL, status TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO tenants VALUES ('TNT-legacy', '遗留牧场', 'holstein', ?, 'active')",
        (legacy_key,),
    )
    conn.commit()
    conn.close()

    repo = SqliteTenantRepository(str(legacy_path))
    try:
        migrated = repo.find_by_api_key(legacy_key)
        wrong = repo.find_by_api_key("wrong-key")
        assert repo.get("TNT-legacy") is not None
    finally:
        repo.close()

    assert migrated is not None and migrated.tenant_id == "TNT-legacy"
    assert migrated.api_key_hash == hash_api_key(legacy_key)
    assert wrong is None

    recheck = sqlite3.connect(legacy_path)
    after_columns = {
        row[1] for row in recheck.execute("PRAGMA table_info(tenants)")
    }
    recheck.close()
    assert "api_key" not in after_columns and "api_key_hash" in after_columns


def test_empty_api_key_never_authenticates(tmp_path):
    """空 Key 一律拒绝，防止误配导致越权。"""
    repo = SqliteTenantRepository(str(tmp_path / "tenants.db"))
    try:
        assert repo.find_by_api_key("") is None
        assert repo.find_by_api_key(None) is None
    finally:
        repo.close()
