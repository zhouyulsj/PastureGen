from fastapi import APIRouter

from app.perception.alert_service import alert_service
from app.tenant.context import get_current_tenant_id

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts() -> list[dict]:
    tenant_id = get_current_tenant_id()
    return [alert.model_dump() for alert in alert_service.list_alerts(tenant_id=tenant_id)]
