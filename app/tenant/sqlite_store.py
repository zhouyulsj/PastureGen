import json
import sqlite3
from pathlib import Path

from app.tenant.metadata import TenantMetadata
from app.tenant.tenant_registry import TenantRecord, TenantRepository, hash_api_key

_TENANTS_SCHEMA = """
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                breed_code TEXT NOT NULL,
                api_key_hash TEXT NOT NULL,
                status TEXT NOT NULL
            )
"""


class SqliteTenantRepository(TenantRepository):
    """租户注册表的 SQLite 持久实现（可平滑替换为 PostgreSQL）。

    API Key 只以 SHA-256 摘要落库；打开旧版含明文 api_key 列的库时，
    自动完成摘要回填并重建表以移除明文字段。
    """

    def __init__(self, db_path: str = "data/tenant.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(_TENANTS_SCHEMA)
        self._migrate_legacy_api_key()
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tenants_api_key_hash "
            "ON tenants(api_key_hash)"
        )
        self._connection.commit()

    def _migrate_legacy_api_key(self) -> None:
        columns = {
            row[1] for row in self._connection.execute("PRAGMA table_info(tenants)")
        }
        if "api_key" not in columns:
            return
        if "api_key_hash" not in columns:
            self._connection.execute(
                "ALTER TABLE tenants ADD COLUMN api_key_hash TEXT NOT NULL DEFAULT ''"
            )
        legacy_rows = self._connection.execute(
            "SELECT tenant_id, api_key FROM tenants WHERE api_key != ''"
        ).fetchall()
        for tenant_id, legacy_key in legacy_rows:
            self._connection.execute(
                "UPDATE tenants SET api_key_hash = ? WHERE tenant_id = ?",
                (hash_api_key(legacy_key), tenant_id),
            )
        # 重建表彻底删除明文列（兼容不支持 DROP COLUMN 的旧 SQLite）
        self._connection.execute("DROP TABLE IF EXISTS tenants_migrated")
        self._connection.execute(
            """
            CREATE TABLE tenants_migrated (
                tenant_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                breed_code TEXT NOT NULL,
                api_key_hash TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        self._connection.execute(
            "INSERT INTO tenants_migrated "
            "(tenant_id, display_name, breed_code, api_key_hash, status) "
            "SELECT tenant_id, display_name, breed_code, api_key_hash, status "
            "FROM tenants"
        )
        self._connection.execute("DROP TABLE tenants")
        self._connection.execute("ALTER TABLE tenants_migrated RENAME TO tenants")

    def save(self, record: TenantRecord) -> None:
        self._connection.execute(
            """
            INSERT OR REPLACE INTO tenants
                (tenant_id, display_name, breed_code, api_key_hash, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                record.tenant_id,
                record.display_name,
                record.breed_code,
                record.api_key_hash,
                record.status,
            ),
        )
        self._connection.commit()

    def get(self, tenant_id: str) -> TenantRecord | None:
        cursor = self._connection.execute(
            "SELECT tenant_id, display_name, breed_code, api_key_hash, status "
            "FROM tenants WHERE tenant_id = ?",
            (tenant_id,),
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def find_by_api_key(self, api_key: str) -> TenantRecord | None:
        if not api_key:
            return None
        cursor = self._connection.execute(
            "SELECT tenant_id, display_name, breed_code, api_key_hash, status "
            "FROM tenants WHERE api_key_hash = ? LIMIT 1",
            (hash_api_key(api_key),),
        )
        row = cursor.fetchone()
        return self._row_to_record(row) if row else None

    def list_all(self) -> list[TenantRecord]:
        cursor = self._connection.execute(
            "SELECT tenant_id, display_name, breed_code, api_key_hash, status "
            "FROM tenants ORDER BY tenant_id"
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def close(self) -> None:
        self._connection.close()

    @staticmethod
    def _row_to_record(row: tuple) -> TenantRecord:
        tenant_id, display_name, breed_code, api_key_hash, status = row
        return TenantRecord(
            tenant_id=tenant_id,
            display_name=display_name,
            breed_code=breed_code,
            api_key_hash=api_key_hash,
            status=status,
        )


class SqliteMetadataStore:
    """租户元数据的 SQLite 持久存储（整条记录以 JSON 落库）。"""

    def __init__(self, db_path: str = "data/tenant.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tenant_metadata (
                tenant_id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def load(self, tenant_id: str) -> TenantMetadata | None:
        cursor = self._connection.execute(
            "SELECT data FROM tenant_metadata WHERE tenant_id = ?",
            (tenant_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return TenantMetadata(**json.loads(row[0]))

    def save(self, tenant_id: str, metadata: TenantMetadata) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO tenant_metadata (tenant_id, data) VALUES (?, ?)",
            (tenant_id, metadata.model_dump_json()),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()
