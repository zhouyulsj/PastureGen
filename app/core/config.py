from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "AI 智能牧场育种平台"
    api_prefix: str = "/api/v1"
    default_tenant_id: str = "default"
    admin_api_key: str = ""

    database_url: str = "postgresql://breeding:breeding@localhost:5432/breeding"
    timescale_url: str = "postgresql://breeding:breeding@localhost:5433/sensor"

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    sensor_db_path: str = "data/sensor.db"
    tenant_db_path: str = "data/tenant.db"
    alert_db_path: str = "data/alert.db"
    alert_cooldown_seconds: int = 3600

    alert_webhook_url: str = ""
    alert_webhook_format: str = "feishu"
    alert_push_queue_size: int = 1000
    alert_push_max_retries: int = 3
    alert_push_retry_delay_seconds: float = 1.0
    push_dead_letter_db_path: str = "data/push_dead_letter.db"

    deployment_role: str = "cloud"
    edge_mqtt_topic: str = "breeding/devices"

    enable_mock_adapters: bool = True


settings = Settings()