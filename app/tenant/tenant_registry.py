import hashlib
import secrets
import uuid
from abc import ABC, abstractmethod

from pydantic import BaseModel

DEFAULT_BREED = "holstein"


def hash_api_key(api_key: str) -> str:
    """计算 API Key 的存储摘要（SHA-256 十六进制）。

    Key 由 secrets 生成、含 192 位随机熵，拿到摘要也无法反推或暴力还原，
    因此用确定性快速摘要即可（与 GitHub/AWS 的令牌存储同模式），
    并允许直接按摘要列建索引精确检索。
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class TenantRecord(BaseModel):
    tenant_id: str
    display_name: str
    breed_code: str = DEFAULT_BREED
    api_key_hash: str
    status: str = "active"


class TenantRepository(ABC):
    @abstractmethod
    def save(self, record: TenantRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, tenant_id: str) -> TenantRecord | None:
        raise NotImplementedError

    @abstractmethod
    def find_by_api_key(self, api_key: str) -> TenantRecord | None:
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> list[TenantRecord]:
        raise NotImplementedError


class InMemoryTenantRepository(TenantRepository):
    def __init__(self) -> None:
        self._records: dict[str, TenantRecord] = {}

    def save(self, record: TenantRecord) -> None:
        self._records[record.tenant_id] = record

    def get(self, tenant_id: str) -> TenantRecord | None:
        return self._records.get(tenant_id)

    def find_by_api_key(self, api_key: str) -> TenantRecord | None:
        if not api_key:
            return None
        digest = hash_api_key(api_key)
        for record in self._records.values():
            if record.api_key_hash == digest:
                return record
        return None

    def list_all(self) -> list[TenantRecord]:
        return list(self._records.values())


class TenantRegistry:
    def __init__(self, repository: TenantRepository | None = None) -> None:
        self.repository: TenantRepository = repository or InMemoryTenantRepository()

    def bind_repository(self, repository: TenantRepository) -> None:
        self.repository = repository

    def create_tenant(
        self, display_name: str, breed_code: str = DEFAULT_BREED
    ) -> tuple[TenantRecord, str]:
        """创建租户并返回 (记录, 明文 API Key)。

        明文只在创建时返回一次，仓储中仅保存其 SHA-256 摘要。
        """
        api_key = secrets.token_urlsafe(24)
        record = TenantRecord(
            tenant_id=f"TNT-{uuid.uuid4().hex[:12]}",
            display_name=display_name,
            breed_code=breed_code,
            api_key_hash=hash_api_key(api_key),
        )
        self.repository.save(record)
        return record, api_key

    def authenticate(self, api_key: str) -> TenantRecord | None:
        """按明文 Key 认证：摘要化后交由仓储精确匹配。"""
        return self.repository.find_by_api_key(api_key)

    def get_tenant(self, tenant_id: str) -> TenantRecord | None:
        return self.repository.get(tenant_id)

    def list_tenants(self) -> list[TenantRecord]:
        return self.repository.list_all()


tenant_registry = TenantRegistry()