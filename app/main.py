from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.breeding.store import SqlitePedigreeStore, pedigree_registry
from app.core.config import settings
from app.device_ingestion.ingestion_gateway import ingestion_gateway
from app.device_ingestion.sqlite_timeseries_repository import SqliteTimeseriesRepository
from app.notification.channels import NotificationChannel, WebhookNotificationChannel
from app.notification.dispatcher import NotificationDispatcher
from app.notification.queue_push import PushQueue, maybe_queued
from app.notification.router import bind_dead_letter_store
from app.notification.routing import make_tenant_channel_resolver
from app.notification.sqlite_dead_letter import SqliteDeadLetterRepository
from app.perception.alert_service import alert_service
from app.perception.sqlite_alert_repository import SqliteAlertRepository
from app.tenant.metadata import tenant_metadata_registry
from app.tenant.middleware import TenantContextMiddleware
from app.tenant.sqlite_store import SqliteMetadataStore, SqliteTenantRepository
from app.tenant.tenant_registry import tenant_registry


@asynccontextmanager
async def lifespan(application: FastAPI):
    repository = SqliteTimeseriesRepository(settings.sensor_db_path)
    ingestion_gateway.set_repository(repository)
    ingestion_gateway.set_alert_service(alert_service)

    alert_repository = SqliteAlertRepository(settings.alert_db_path)
    alert_service.bind_repository(alert_repository)

    dead_letter_store = SqliteDeadLetterRepository(settings.push_dead_letter_db_path)
    bind_dead_letter_store(dead_letter_store)
    push_queue = PushQueue(
        maxsize=settings.alert_push_queue_size,
        max_retries=settings.alert_push_max_retries,
        retry_delay=settings.alert_push_retry_delay_seconds,
        dead_letter=dead_letter_store,
    )
    push_queue.start()

    channels: list[NotificationChannel] = []
    if settings.alert_webhook_url:
        channels.append(
            maybe_queued(
                WebhookNotificationChannel(
                    settings.alert_webhook_url,
                    payload_format=settings.alert_webhook_format,
                ),
                push_queue,
            )
        )
    alert_service.bind_notifier(
        NotificationDispatcher(
            channels,
            tenant_channel_resolver=make_tenant_channel_resolver(
                tenant_metadata_registry, push_queue
            ),
        )
    )

    tenant_repository = SqliteTenantRepository(settings.tenant_db_path)
    tenant_registry.bind_repository(tenant_repository)
    metadata_store = SqliteMetadataStore(settings.tenant_db_path)
    tenant_metadata_registry.bind_store(metadata_store)

    pedigree_store = SqlitePedigreeStore(settings.pedigree_db_path)
    pedigree_registry.bind_store(pedigree_store)

    yield
    push_queue.shutdown()
    # 依次解绑并关闭：先断开单例引用，再关闭连接，避免留下悬空的已关闭连接
    bind_dead_letter_store(None)
    alert_service.bind_notifier(None)
    alert_service.bind_repository(None)
    ingestion_gateway.set_alert_service(None)
    ingestion_gateway.set_repository(None)
    tenant_metadata_registry.bind_store(None)
    tenant_registry.bind_repository(None)
    pedigree_registry.bind_store(None)
    pedigree_store.close()
    dead_letter_store.close()
    metadata_store.close()
    tenant_repository.close()
    alert_repository.close()
    repository.close()


def create_app() -> FastAPI:
    application = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    application.add_middleware(TenantContextMiddleware)
    application.include_router(api_router, prefix=settings.api_prefix)
    return application


app = create_app()


@app.get("/healthz", tags=["system"])
def healthz() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}