import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.core.config import settings
from app.tenant.context import get_current_tenant_id
from app.tenant.metadata import tenant_metadata_registry
from app.tenant.tenant_registry import DEFAULT_BREED, tenant_registry

router = APIRouter(prefix="/tenants", tags=["tenants"])


def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
    expected = settings.admin_api_key
    if not expected or x_admin_key is None or not hmac.compare_digest(
        x_admin_key, expected
    ):
        raise HTTPException(status_code=401, detail="admin authentication required")


class CreateTenantRequest(BaseModel):
    display_name: str
    breed_code: str = DEFAULT_BREED


class TraitRequest(BaseModel):
    trait_code: str
    name: str
    unit: str
    heritability: float | None = None


class AlertThresholdRequest(BaseModel):
    metric: str
    low: float
    high: float


class NotificationRequest(BaseModel):
    webhook_url: str = ""
    webhook_format: str = "feishu"


@router.post("", dependencies=[Depends(require_admin)])
def create_tenant(request: CreateTenantRequest) -> dict:
    record, api_key = tenant_registry.create_tenant(
        request.display_name, request.breed_code
    )
    tenant_metadata_registry.ensure_tenant(record.tenant_id, record.breed_code)
    return {
        "tenant_id": record.tenant_id,
        "display_name": record.display_name,
        "breed_code": record.breed_code,
        "status": record.status,
        # 明文 Key 仅此一次返回，库中只存 SHA-256 摘要
        "api_key": api_key,
    }


@router.get("", dependencies=[Depends(require_admin)])
def list_tenants() -> list[dict]:
    return [
        {
            "tenant_id": record.tenant_id,
            "display_name": record.display_name,
            "breed_code": record.breed_code,
            "status": record.status,
        }
        for record in tenant_registry.list_tenants()
    ]


@router.get("/current")
def current_tenant() -> dict:
    tenant_id = get_current_tenant_id()
    record = tenant_registry.get_tenant(tenant_id)
    if record is None:
        return {
            "tenant_id": tenant_id,
            "display_name": tenant_id,
            "breed_code": DEFAULT_BREED,
            "status": "active",
        }
    return {
        "tenant_id": record.tenant_id,
        "display_name": record.display_name,
        "breed_code": record.breed_code,
        "status": record.status,
    }


@router.post("/current/traits")
def set_current_trait(request: TraitRequest) -> dict:
    tenant_id = get_current_tenant_id()
    entry = tenant_metadata_registry.set_trait(
        tenant_id,
        request.trait_code,
        request.name,
        request.unit,
        request.heritability,
    )
    return {"tenant_id": tenant_id, "trait_code": request.trait_code, "trait": entry}


@router.post("/current/alert-thresholds")
def set_current_alert_threshold(request: AlertThresholdRequest) -> dict:
    tenant_id = get_current_tenant_id()
    bounds = tenant_metadata_registry.set_alert_threshold(
        tenant_id, request.metric, request.low, request.high
    )
    return {"tenant_id": tenant_id, "metric": request.metric, "bounds": bounds}


@router.put("/current/notification")
def set_current_notification(request: NotificationRequest) -> dict:
    if request.webhook_format not in {"feishu", "generic"}:
        raise HTTPException(status_code=400, detail="webhook_format must be feishu or generic")
    tenant_id = get_current_tenant_id()
    config = tenant_metadata_registry.set_notification(
        tenant_id, request.webhook_url.strip(), request.webhook_format
    )
    return {"tenant_id": tenant_id, **config}


@router.get("/current/metadata")
def current_metadata() -> dict:
    tenant_id = get_current_tenant_id()
    metadata = tenant_metadata_registry.get_metadata(tenant_id)
    return {"tenant_id": tenant_id, **metadata.model_dump()}
