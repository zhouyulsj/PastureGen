from fastapi import APIRouter
from pydantic import BaseModel

from app.device_ingestion.adapter_registry import adapter_registry
from app.device_ingestion.ingestion_gateway import ingestion_gateway
from app.tenant.context import get_current_tenant_id

router = APIRouter(prefix="/devices", tags=["devices"])


class CollectRequest(BaseModel):
    adapter_type: str
    device_id: str = ""
    animal_id: str | None = None
    count: float | None = None


@router.get("/adapters")
def list_adapters() -> list[dict]:
    return adapter_registry.list_adapters()


@router.post("/collect")
def collect_from_device(request: CollectRequest) -> dict:
    config = {"tenant_id": get_current_tenant_id()}
    if request.device_id:
        config["device_id"] = request.device_id
    if request.animal_id is not None:
        config["animal_id"] = request.animal_id
    if request.count is not None:
        config["count"] = request.count
    events = ingestion_gateway.collect_from_adapter(request.adapter_type, **config)
    return {"collected": [event.model_dump() for event in events]}


@router.post("/webhook/{adapter_type}")
def device_webhook(adapter_type: str, payload: dict) -> dict:
    adapter = adapter_registry.create(adapter_type, tenant_id=get_current_tenant_id())
    event = adapter.handle_webhook(payload)
    if not event.tenant_id:
        event.tenant_id = get_current_tenant_id()
    ingestion_gateway.ingest([event])
    return {"accepted": True, "event": event.model_dump()}


@router.get("/events")
def list_events() -> list[dict]:
    tenant_id = get_current_tenant_id()
    return [
        event.model_dump()
        for event in ingestion_gateway.list_events(tenant_id=tenant_id)
    ]