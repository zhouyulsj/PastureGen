from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.tenant.context import set_current_tenant
from app.tenant.tenant_registry import tenant_registry


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        api_key = request.headers.get("X-API-Key")
        if api_key:
            record = tenant_registry.authenticate(api_key)
            if record is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid api key"},
                )
            tenant_id = record.tenant_id
        else:
            tenant_id = request.headers.get("X-Tenant-ID", settings.default_tenant_id)
        set_current_tenant(tenant_id)
        response = await call_next(request)
        response.headers["X-Tenant-ID"] = tenant_id
        return response
