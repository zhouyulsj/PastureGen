from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.tenant.context import set_current_tenant
from app.tenant.tenant_registry import tenant_registry


class TenantContextMiddleware(BaseHTTPMiddleware):
    """租户上下文解析与鉴权。

    解析优先级：

    1. 带 ``X-API-Key``：必须命中注册表，否则 401；
    2. 不带任何凭据：归属默认租户（``DEFAULT_TENANT_ID``）；
    3. 不带 Key 却用 ``X-Tenant-ID`` 指定**非默认**租户：直接 401 拒绝。

    第 3 条是安全边界——``X-Tenant-ID`` 是纯客户端可控字符串，若无条件采信，
    任何人伪造该头即可读写他人牧场数据。本地多租户联调需显式打开
    ``ALLOW_TENANT_HEADER_FALLBACK=true``（生产环境严禁开启）。
    """

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
            header_tenant = request.headers.get("X-Tenant-ID")
            if not header_tenant or header_tenant == settings.default_tenant_id:
                tenant_id = settings.default_tenant_id
            elif settings.allow_tenant_header_fallback:
                tenant_id = header_tenant
            else:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": (
                            "X-Tenant-ID 不能单独作为租户凭据，请提供 X-API-Key"
                        )
                    },
                )
        set_current_tenant(tenant_id)
        response = await call_next(request)
        response.headers["X-Tenant-ID"] = tenant_id
        return response
