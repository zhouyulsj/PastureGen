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

平台支持三种真实设备接入协议，均已实现适配器：

1. **HTTP Webhook**（零依赖，任何支持 HTTP 回调的设备）：
   `POST /api/v1/devices/webhook/{adapter_type}`
2. **MQTT 订阅**（物联网设备主流）：`MqttIngestionService`，需 `pip install .[edge]`
3. **Modbus TCP**（称重/温湿度仪表）：`modbus_scale` 适配器，需 `pip install .[edge]`