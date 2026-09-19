# PastureGen

**AI 智能牧场育种平台** —— 畜种通用（牛、水牛、羊等家畜皆可）、多租户的养殖育种一体化后端。

[![CI](https://github.com/zhouyulsj/PastureGen/actions/workflows/ci.yml/badge.svg)](https://github.com/zhouyulsj/PastureGen/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-≥3.11-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MulanPSL--2.0-green.svg)](./LICENSE)

## 项目简介

PastureGen 覆盖三大业务主线：

1. **基本管理**：传感器驱动的智能盘点、体尺体重、健康、发情、分娩监测。
2. **传统育种**：家系法、性能测定、BLUP 遗传评估与近交系数计算。
3. **新型育种**：基因芯片 SNP 质控、基因组选择（GBLUP / ssGBLUP）。

在保证育种算法可用性的同时，平台按生产级要求实现了多租户隔离、异步消息推送与完整测试基线。

## 功能特性

### 领域算法

- **系谱分析**：亲代-子代家系构建，近交系数与亲缘关系计算（拓扑排序保证结果与登记顺序无关，环路登记被拒绝）。
- **BLUP 遗传评估**：多性状育种值估计（`app/breeding/blup.py`）。
- **SNP 质控**：缺失率、最小等位基因频率过滤（`app/genomics/snp_quality_control.py`）。
- **基因组选择**：基于 GRM 的 GBLUP 育种值估计（`app/genomics/genomic_selection.py`）。
- **性能测定**：性状与测定记录领域模型已就绪（`app/breeding/performance.py`）；*API 端点尚未暴露，统计汇总亦未实现*。

### 感知与告警

- **设备接入网关**：RFID（mock）、体重秤（HTTP / Modbus）、摄像头（HTTP）多源适配，插件式 `SensorDataAdapter` 架构。
- **规则监测**：发情（活动量趋势）、分娩预警（体温下降趋势）、健康异常（体温阈值）三类算法管线。
- **告警服务**：租户内告警持久化（SQLite）、冷却去抖、趋势缓冲。

### 通知推送（生产级可靠性）

- **异步推送队列**：有界队列 + 工作协程，采集路径不阻塞（入队 < 0.1s）。
- **重试与死信**：指数退避重试（默认 3 次），耗尽后落 SQLite 死信库；关停时排空未完成任务并记录。
- **死信查询与补发 API**：按租户列出失败记录，单条重放；补发成功即删除，失败保留现场。
- **租户级通知渠道**：每租户可配置飞书 / 钉钉 / 企业微信 / Slack / 通用 Webhook，未配置时回落全局渠道。

### 多租户与安全

- **租户隔离**：`X-API-Key` 中间件鉴权，事件、告警、元数据、系谱、死信全链路按 `tenant_id` 隔离。
- **凭据边界**：`X-Tenant-ID` 属客户端可控信息，**不作为鉴权凭据**——无 Key 时指定非默认租户一律 401；仅在显式打开 `ALLOW_TENANT_HEADER_FALLBACK=true` 时用于本地联调（生产严禁开启）。
- **API Key 哈希存储**：密钥仅 SHA-256 摘要落库，明文只在创建时一次性返回；自动迁移旧明文库并物理删除明文列。
- **管理端接口**：租户创建 / 列表使用独立 `X-Admin-Key`，列表不泄露任何密钥字段。
- **可配置元数据**：性状定义、告警阈值、品种与规则按租户自定义，附默认元数据库。

### 工程质量

- **pytest 测试套件**：54 个用例覆盖领域端点、租户隔离与凭据边界、列表取数顺序、系谱顺序无关性与环路拒绝、Key 哈希迁移、告警去抖、推送重试、死信补发。
- **CI 基线**：GitHub Actions（Python 3.11 / 3.12 / 3.13 矩阵），每次 push / PR 自动跑语法门禁 + pytest + 端到端冒烟脚本。
- **容器化**：Dockerfile（非 root 运行 + HEALTHCHECK）与 docker-compose（PostgreSQL / TimescaleDB / MinIO）。

## 快速开始

### 环境要求

- Python ≥ 3.11

### 安装与运行

```bash
# 克隆仓库
git clone https://github.com/zhouyulsj/PastureGen.git
cd PastureGen

# 配置环境变量（生产环境务必设置 ADMIN_API_KEY）
cp .env.example .env

# 基础安装（开发）
pip install -e .

# 边缘采集场景（含 MQTT / Modbus 适配器依赖）
pip install -e ".[edge]"

# 启动服务
uvicorn app.main:app --reload
```

- 健康检查：<http://127.0.0.1:8000/healthz>
- 交互式接口文档（OpenAPI）：<http://127.0.0.1:8000/docs>

### 运行测试

```bash
pip install -e ".[dev]"
python -m pytest              # 单元 + 集成测试
python scripts/smoke_test.py  # 端到端冒烟
```

## API 概览

所有业务端点挂在 `/api/v1` 前缀下；租户数据接口需携带 `X-API-Key`，租户管理接口需携带 `X-Admin-Key`。

| 模块 | 端点 | 说明 |
|---|---|---|
| 系统 | `GET /healthz` | 健康检查 |
| 育种 | `POST /api/v1/breeding/animals` | 登记个体（含亲代信息） |
| 育种 | `GET /api/v1/breeding/inbreeding` | 计算子代近交系数 |
| 育种 | `POST /api/v1/breeding/blup` | BLUP 育种值评估 |
| 基因组 | `POST /api/v1/genomics/quality-control` | SNP 质控过滤 |
| 基因组 | `POST /api/v1/genomics/gblup` | GBLUP 基因组育种值 |
| 设备 | `GET /api/v1/devices/adapters` | 已注册数据适配器 |
| 设备 | `POST /api/v1/devices/collect` | 主动拉取设备数据 |
| 设备 | `POST /api/v1/devices/webhook/{adapter_type}` | 设备侧推送接入 |
| 设备 | `GET /api/v1/devices/events` | 查询本租户采集事件 |
| 告警 | `GET /api/v1/alerts` | 本租户告警列表 |
| 死信 | `GET /api/v1/alerts/dead-letters` | 推送失败死信列表 |
| 死信 | `POST /api/v1/alerts/dead-letters/{record_id}/replay` | 补发单条死信 |
| 租户 | `POST /api/v1/tenants` | 创建租户（管理员，一次性返回明文 Key） |
| 租户 | `GET /api/v1/tenants` | 租户列表（管理员） |
| 租户 | `GET /api/v1/tenants/current` | 当前租户信息 |
| 租户 | `POST /api/v1/tenants/current/traits` | 自定义本租户性状 |
| 租户 | `POST /api/v1/tenants/current/alert-thresholds` | 自定义告警阈值 |
| 租户 | `PUT /api/v1/tenants/current/notification` | 配置推送渠道（飞书/钉钉/企微/Slack/Webhook） |
| 租户 | `GET /api/v1/tenants/current/metadata` | 查看本租户生效元数据 |

## 配置

通过根目录 `.env` 或环境变量配置（pydantic-settings），主要项见 `app/core/config.py`：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ADMIN_API_KEY` | 空 | 租户管理接口的 `X-Admin-Key`（生产必填） |
| `ALLOW_TENANT_HEADER_FALLBACK` | `false` | 是否允许无 Key 时用 `X-Tenant-ID` 指定租户（**生产严禁开启**） |
| `DEFAULT_TENANT_ID` | `default` | 未带 Key 请求归属的默认租户 |
| `SENSOR_DB_PATH` | `data/sensor.db` | 时序事件 SQLite 路径 |
| `TENANT_DB_PATH` | `data/tenant.db` | 租户库路径 |
| `ALERT_DB_PATH` | `data/alert.db` | 告警库路径 |
| `PEDIGREE_DB_PATH` | `data/pedigree.db` | 系谱库路径 |
| `PUSH_DEAD_LETTER_DB_PATH` | `data/push_dead_letter.db` | 推送死信库路径 |
| `ALERT_COOLDOWN_SECONDS` | `3600` | 同类告警冷却去抖窗口 |
| `ALERT_TREND_WINDOW` | `50` | 每（租户,个体,指标）保留的趋势读数条数 |
| `ALERT_TREND_MAX_ENTITIES` | `10000` | 内存跟踪的实体上限，超出按插入顺序淘汰 |
| `ALERT_WEBHOOK_URL` | 空 | 全局推送渠道 URL（空则仅租户渠道） |
| `ALERT_WEBHOOK_FORMAT` | `feishu` | 全局渠道消息格式（`feishu` / `generic`） |
| `ALERT_PUSH_QUEUE_SIZE` | `1000` | 异步推送队列容量 |
| `ALERT_PUSH_MAX_RETRIES` | `3` | 单条消息最大重试次数 |
| `ALERT_PUSH_RETRY_DELAY_SECONDS` | `1.0` | 指数退避首档延迟 |
| `DEAD_LETTER_REPLAY_TIMEOUT_SECONDS` | `5.0` | 死信补发单次发送超时 |
| `DEAD_LETTER_REPLAY_MAX_RETRIES` | `2` | 死信补发重试次数 |
| `DEAD_LETTER_REPLAY_RETRY_DELAY_SECONDS` | `0.2` | 死信补发退避基数 |
| `DEPLOYMENT_ROLE` | `cloud` | 部署角色（`cloud` / `edge`） |
| `ENABLE_MOCK_ADAPTERS` | `true` | 是否注册 mock 适配器（演示/测试用） |
| `MQTT_HOST` / `MQTT_PORT` | `localhost` / `1883` | 边缘 MQTT 接入参数 |

完整清单与说明见 [`.env.example`](./.env.example)。

## 当前能力边界（已知未实现）

以下能力在代码中已预留接口或配置，但**尚未接线**，文档其余部分不应被理解为已具备：

| 能力 | 现状 |
|---|---|
| MQTT 订阅接入 | `MqttIngestionService` 已实现但**未在应用启动流程中实例化**，需调用方显式启动 |
| 边缘 / 云端角色切换 | `DEPLOYMENT_ROLE` 已声明，尚未据此裁剪启动的子系统 |
| mock 适配器开关 | `ENABLE_MOCK_ADAPTERS` 已声明，尚未接入注册逻辑（mock 适配器当前恒注册） |
| PostgreSQL / TimescaleDB | `DATABASE_URL` / `TIMESCALE_URL` 为预留项，仓储仍为 SQLite |
| 性能测定 API | 领域模型就绪，无端点；统计汇总未实现 |
| 钉钉 / 企业微信 / Slack 载荷 | 仅实现 `feishu` 与 `generic` 两种 webhook 格式 |
| HWE 检验、异常检测模型 | SNP 质控仅实现 call rate + MAF；健康监测仅阈值判定 |
| 参考群管理 | 未实现 |

## 部署

### Docker

```bash
docker build -t pasturegen .
docker run -p 8000:8000 --env-file .env pasturegen
```

### 依赖服务（PostgreSQL / TimescaleDB / MinIO）

```bash
docker compose up -d
```

详细部署说明见 [docs/deployment.md](docs/deployment.md)。

## 架构与扩展

- 架构文档：[docs/architecture.md](docs/architecture.md)
- 需求 / 设计 / 任务规格：`.codeartsdoer/specs/breeding/`

核心扩展点：

- **设备适配器插件**：实现 `SensorDataAdapter` 并注册到 `adapter_registry`，即可接入新厂商传感器，无需改核心代码。
- **遗传求解器**：实现 `GeneticSolver` 接口，即可插入 BLUP / ssGBLUP 等算法。
- **通知渠道**：实现 `NotificationChannel`（`send` + `supports`），加入 `dispatcher` 通道列表即可扩展推送平台。
- **多租户元数据**：性状、阈值、品种与规则按租户可配置，默认库见 `app/tenant/metadata.py`。

## 目录结构

```text
app/
├── api/            # 育种 / 基因组 REST 端点
├── breeding/       # 系谱（含租户级存储）、近交、BLUP、性能测定
├── core/           # 配置（pydantic-settings）
├── device_ingestion/   # 设备适配器、采集网关、时序存储
│   └── adapters/       # RFID / 体重秤 / 摄像头适配器
├── genomics/       # SNP 质控、基因组选择
├── notification/   # 推送渠道、异步队列、重试、死信
├── perception/     # 发情 / 分娩 / 健康监测与告警
└── tenant/         # 多租户：鉴权中间件、元数据、Key 哈希存储
tests/              # pytest 套件（54 用例，含回归测试）
scripts/            # 端到端冒烟脚本（临时库运行，不污染 data/）
docs/               # 架构与部署文档
```

## 许可证

本项目采用 [MulanPSL-2.0（木兰宽松许可证，第 2 版）](http://license.coscl.org.cn/MulanPSL2) 开源，全文见 [LICENSE](./LICENSE)。

Copyright © 2026 zhouyulsj
