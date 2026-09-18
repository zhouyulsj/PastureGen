from contextvars import ContextVar
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str


_current_tenant: ContextVar[TenantContext] = ContextVar(
    "current_tenant", default=TenantContext(tenant_id=settings.default_tenant_id)
)


def set_current_tenant(tenant_id: str) -> None:
    _current_tenant.set(TenantContext(tenant_id=tenant_id))


def get_current_tenant_id() -> str:
    return _current_tenant.get().tenant_id