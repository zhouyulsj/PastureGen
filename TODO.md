# 待办清单（交给 trae 执行）

## 项目当前状态

`tasks.md`（`.codeartsdoer/specs/breeding/tasks.md`）中阶段一~四已全部完成，阶段五还剩 **T-14 多牧场 SaaS 化**，且该任务中断时是半成品。

## 唯一硬待办：T-14 多牧场 SaaS 化 —— 从中断处继续

### 已完成的文件（无需重写，直接沿用）

- ✅ `app/tenant/tenant_registry.py` — 租户注册 + API Key 签发/鉴权 + 仓储抽象（内存实现，`tenant_registry` 单例）
- ✅ `app/tenant/metadata.py` — 租户级元数据（性状模板/告警阈值/设备启用，含荷斯坦默认性状，`tenant_metadata_registry` 单例）

### 待办 5 步

1. **新建 `app/tenant/router.py`** — 租户管理 API（`APIRouter(prefix="/tenants", tags=["tenants"])`）：
   - `POST /tenants` 注册租户 → 返回 `tenant_id` + `api_key`（key 仅创建时返回一次）
   - `GET /tenants` 列出租户（脱敏，不含 api_key）
   - `GET /tenants/current` 返回当前上下文租户信息（读 `get_current_tenant_id()`）
   - `POST /tenants/current/traits` 配置性状模板（调 `tenant_metadata_registry.set_trait`）
   - `POST /tenants/current/alert-thresholds` 配置告警阈值
   - `GET /tenants/current/metadata` 查询当前租户元数据

2. **改造 `app/tenant/middleware.py`** — 加 API Key 鉴权：
   - 优先读 `X-API-Key` → `tenant_registry.authenticate(key)`
   - 命中 → `set_current_tenant(record.tenant_id)`；提供了 key 但无效 → 返回 `401`
   - 无 key → 回退 `X-Tenant-ID` → 默认租户（保持现有冒烟测试兼容）

3. **修改 `app/api/router.py`** — 挂载 `tenant_router`（`api_router.include_router(tenant_router)`）

4. **扩展 `scripts/smoke_test.py`** — 追加：注册租户 → 带 `X-API-Key` 访问 `/tenants/current` → 配置性状/阈值 → 查询元数据 → 验证非法 key 返回 401

5. **更新 `.codeartsdoer/specs/breeding/tasks.md`** — 勾选 T-14

### 验证命令

```bash
python scripts/smoke_test.py
```

预期输出末尾为 `ALL SMOKE TESTS PASSED`。

---

## T-14 完成后的增强方向（非硬待办）

- 真实硬件联调（T-07 适配器接真设备）
- SQLite 切换 TimescaleDB（时序持久化）
- BLUP 接入 R 求解器
- 租户数据持久化到 PostgreSQL（替换内存仓储）

## 执行建议

- 一轮只做一件，避免单轮同时读写多文件 + 跑测试导致超时。
- 写文件前先 Read（避免 staleness 报错）。