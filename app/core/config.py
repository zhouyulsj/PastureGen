from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "AI 智能牧场育种平台"
    api_prefix: str = "/api/v1"
    default_tenant_id: str = "default"
    admin_api_key: str = ""

    # 安全开关：是否允许在缺少 X-API-Key 时用 X-Tenant-ID 头指定租户。
    # 生产环境必须保持 False，否则任何人伪造该头即可读写他人租户数据；
    # 仅为本地单机演示/调试保留开启能力。
    allow_tenant_header_fallback: bool = False

    database_url: str = "postgresql://breeding:breeding@localhost:5432/breeding"
    timescale_url: str = "postgresql://breeding:breeding@localhost:5433/sensor"

    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    sensor_db_path: str = "data/sensor.db"
    tenant_db_path: str = "data/tenant.db"
    alert_db_path: str = "data/alert.db"
    alert_cooldown_seconds: int = 3600
    # 每 (租户, 个体, 指标) 保留的近期读数条数，用于发情/分娩趋势基线
    alert_trend_window: int = 50
    # 内存中最多跟踪多少个 (租户, 个体, 指标) 实体，超出后按插入顺序淘汰最旧的
    alert_trend_max_entities: int = 10000

    pedigree_db_path: str = "data/pedigree.db"

    alert_webhook_url: str = ""
    alert_webhook_format: str = "feishu"
    alert_push_queue_size: int = 1000
    alert_push_max_retries: int = 3
    alert_push_retry_delay_seconds: float = 1.0
    push_dead_letter_db_path: str = "data/push_dead_letter.db"

    # 死信补发：单次发送超时与有界重试，避免人工补发请求被不可达端长期占住
    dead_letter_replay_timeout_seconds: float = 5.0
    dead_letter_replay_max_retries: int = 2
    dead_letter_replay_retry_delay_seconds: float = 0.2

    deployment_role: str = "cloud"
    edge_mqtt_topic: str = "breeding/devices"

    enable_mock_adapters: bool = True


settings = Settings()