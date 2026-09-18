import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 保证从仓库根目录直接运行 pytest 时（即使未 pip install -e）可以导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.perception.alert_service import alert_service  # noqa: E402
from app.tenant.metadata import tenant_metadata_registry  # noqa: E402

ADMIN_KEY = "ci-admin-key"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """为每个测试提供完全隔离的 TestClient。

    把所有 SQLite 持久化路径重定向到独立临时目录，并在进入前清理
    模块级单例的跨测试残留（租户元数据缓存、告警趋势/冷却内存状态）；
    TestClient 上下文触发 lifespan，完成仓储/注册表绑定与关停解绑。
    """
    monkeypatch.setattr(settings, "sensor_db_path", str(tmp_path / "sensor.db"))
    monkeypatch.setattr(settings, "tenant_db_path", str(tmp_path / "tenant.db"))
    monkeypatch.setattr(settings, "alert_db_path", str(tmp_path / "alert.db"))
    monkeypatch.setattr(
        settings, "push_dead_letter_db_path", str(tmp_path / "push_dead_letter.db")
    )
    monkeypatch.setattr(settings, "alert_webhook_url", "")  # 关闭全局 webhook 通道
    monkeypatch.setattr(settings, "admin_api_key", ADMIN_KEY)
    tenant_metadata_registry._cache.clear()
    alert_service.clear()
    with TestClient(app) as test_client:
        yield test_client
    tenant_metadata_registry._cache.clear()


@pytest.fixture
def admin_headers() -> dict:
    """管理端点鉴权头。"""
    return {"X-Admin-Key": ADMIN_KEY}


@pytest.fixture
def make_tenant(client, admin_headers):
    """租户创建辅助工厂：返回 (tenant_id, 明文 api_key, 认证头)。"""

    def _make(display_name: str = "测试牧场", **extra):
        payload = {"display_name": display_name, **extra}
        created = client.post(
            "/api/v1/tenants", headers=admin_headers, json=payload
        ).json()
        api_key = created["api_key"]
        return created["tenant_id"], api_key, {"X-API-Key": api_key}

    return _make
