# 部署指南（边缘 + 云端混合）

## 部署形态

| 角色 | 环境变量 `DEPLOYMENT_ROLE` | 职责 |
|------|---------------------------|------|
| 云端 | `cloud`（默认） | 遗传评估、跨场分析、全量存储 |
| 边缘 | `edge` | 直连传感器/摄像头/RFID，实时采集与告警 |

## 云端部署

```bash
docker compose up -d        # 启动 PostgreSQL / TimescaleDB / MinIO
uvicorn app.main:app --reload
```

## 边缘节点打包下发

构建边缘镜像（含 MQTT / Modbus 设备库）：

```bash
docker build -t ai-breeding-edge .
docker run -d --name edge-node \
  -e DEPLOYMENT_ROLE=edge \
  -e MQTT_HOST=broker.local \
  -e SENSOR_DB_PATH=/data/sensor.db \
  -v edge-data:/data \
  -p 8000:8000 \
  ai-breeding-edge
```

## 关键环境变量

| 变量 | 说明 | 默认 |
|------|------|------|
| `DEPLOYMENT_ROLE` | cloud / edge | cloud |
| `SENSOR_DB_PATH` | 传感器时序库路径 | data/sensor.db |
| `MQTT_HOST` / `MQTT_PORT` | 边缘 MQTT broker | localhost / 1883 |
| `EDGE_MQTT_TOPIC` | 边缘设备数据主题 | breeding/devices |
| `DEFAULT_TENANT_ID` | 默认租户 | default |
| `DATABASE_URL` / `TIMESCALE_URL` | 业务库 / 时序库连接串 | — |

## 设备接入方式

平台支持三种接入方式：

1. **HTTP Webhook**（零依赖，任何支持 HTTP 回调的设备）——**已接线**：
   `POST /api/v1/devices/webhook/{adapter_type}`
2. **Modbus TCP**（称重/温湿度仪表）——适配器 `modbus_scale` 已实现并通过
   `POST /api/v1/devices/collect` 可调用，需 `pip install -e ".[edge]"`
3. **MQTT 订阅**（物联网设备主流）——`MqttIngestionService` 已实现，
   但**尚未接入应用启动流程**（`app/main.py` 的 lifespan 不会自动启动它），
   需由调用方显式实例化并调用 `start()`，且需 `pip install -e ".[edge]"`。

## 生产部署检查清单

上线前请逐项确认：

- [ ] `ADMIN_API_KEY` 已设置为足够随机的值（留空会导致管理端接口不可用）
- [ ] `ALLOW_TENANT_HEADER_FALLBACK` 保持 `false`
      ——开启后任何人伪造 `X-Tenant-ID` 即可读写他人租户数据
- [ ] `ENABLE_MOCK_ADAPTERS` 关闭（当前该项尚未接线，需同时确认不暴露 mock 适配器）
- [ ] `.env` 不入库（已在 `.gitignore` 中），密钥通过环境变量或密钥管理服务注入
- [ ] `data/` 目录挂载到持久卷；SQLite 定期快照备份
- [ ] 容器以非 root 用户运行（镜像内置 `pasture` 用户）
- [ ] 在负载均衡层限制 `/api/v1/devices/webhook/*` 的来源与频率