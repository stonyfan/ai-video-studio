# AI Video Studio — Phase 4-12 总结存档

**项目目录**：`D:\ai-video-studio`
**首次发布日期**：2026-07-11
**首个商品化版本**：v0.9.0
**最新 Phase**：Phase 12（2026-07-11 完成）

---

## 1. 项目定位

桌面端 AI 短视频生成工具，面向 B2B 售卖。**不是 SaaS** — video_worker 留在客户端本地执行（保护 prompt IP 的同时避免服务端 GPU 成本），backend 只做账号/授权/更新/prompt 分发等控制平面。

详细分析见 [`docs/项目总结与服务化分析.md`](./项目总结与服务化分析.md) 与 [`docs/产品介绍.md`](./产品介绍.md)。

## 2. 技术栈

| 层 | 技术 | 备注 |
|----|------|------|
| 桌面客户端 | Electron 33 + React 18 + Antd 5.22 + electron-vite | NSIS 安装包（~192MB） |
| 视频生成 | Python 3.11 + PyInstaller（独立 exe） | 多 provider（Qwen-VL / Doubao / GLM） |
| 后端控制面 | Python 3.12 + FastAPI + SQLAlchemy 2.x + Alembic | MySQL 8.0 |
| 运维后台 | React 18 + Antd 5.22 + Vite（独立 SPA） | 烤进 backend image，由 FastAPI 同源服务 |
| 部署 | Docker Compose | backend + mysql + backup 三容器 |

## 3. Phase 时间线

| Phase | 日期 | 一句话 | 详情 |
|-------|------|--------|------|
| **4** | 2026-07-09 | 端到端打通（client/worker/backend 三件套） | §4.1 |
| **5** | 2026-07-10 | 灰度发布 + 强制升级 + 回滚 + grace 期 | §4.2 |
| **6** | 2026-07-11 | Web 运维后台（admin UI） + 全量审计 | §4.3 |
| **7** | 2026-07-12 | C 模式：云端模型代理 + session 分离 | §4.4 |
| **8** | 2026-07-14 | 错误上报（崩溃一键上传日志） | §4.5 |
| **9** | 2026-07-14 | 后端自动化（DB 备份 + 监控） | §4.6 |
| **10** | 2026-07-15 | prompt 集版本管理（客户独立定制） | §4.7 |
| **11** | 2026-07-11 | 下载量 + 升级成功率统计 | §4.8 |
| **12** | 2026-07-11 | 用户端可选 prompt 集（多对多 + 自由切换） | §4.9 |

> 注：Phase 11 / 12 是 v0.9.0 发布后立即补做，时间戳早于 9/10 是因为 9/10 的子模块在 v0.9.0 发布前已落地。

## 4. 各 Phase 关键交付

### 4.1 Phase 4 — 端到端打通（2026-07-09）

**目标**：普通用户下载即用。

**关键交付**：
- `video_worker/` Python 流水线（50+ tests pass）：场景检测 → 镜头分析 → storyboard → 渲染
- `backend/` FastAPI 控制：auth / sessions / updates 单点控制
- `desktop/` Electron 客户端：本地视频生成 UI + worker 进程编排
- NSIS 184MB 安装包（v0.4.0）

**关键修复**：
- BrowserRouter → HashRouter（`file://` 协议下必须）
- `__dirname` 为空 → 用 `app.getAppPath()` 兜底

### 4.2 Phase 5 — 灰度发布机制（2026-07-10）

**目标**：发布新版本时能控制风险（小范围灰度 + 出问题可回滚 + 老版本能强制升级）。

**关键交付**：
- Alembic migration 框架上线（`backend/alembic/`）
- `client_releases` 加 4 字段：`rollout_percentage` / `force_upgrade` / `rolled_back_at` / `grace_hours`
- 灰度算法：`sha256(f"{device_fp}:{release_id}")[:8] % 100 < rollout_percentage`
- 客户端 `updater.ts`：30s 启动检查 + 24h 周期复查 + sha256 校验 + grace 期判断
- migration: `0001_phase5_release_fields`

### 4.3 Phase 6 — Admin UI（2026-07-11）

**目标**：admin 后台管理账号/版本/审计，不再直连 DB。

**关键交付**：
- 独立 React SPA，multi-stage build 烤进 backend image
- 同源服务 `/admin/`（FastAPI 挂载）
- 页面：Dashboard / Users / Releases / Sessions / Audit
- `AuditMiddleware` 自动拦截 `/admin/*` 写操作入 `audit_logs` 表
- session_type 分离：`desktop` vs `web`，同 admin 可双端在线
- migration: `0002_phase6_audit_logs` + `0003_phase7_session_type`

详见 [`docs/ADMIN-UI.md`](./ADMIN-UI.md)。

### 4.4 Phase 7 — C 模式（云端代理）

**目标**：商业部署时模型 key 在后端，不暴露给客户端。

**关键交付**：
- `provider_keys` 表（Fernet 加密入库，切换 `JWT_SECRET` 后失效）
- `model_usage` 表（每次调用记 tokens / 成本 / 延迟 / 错误）
- `/api/v1/vision/*` 代理端点（透传到 Qwen-VL / Doubao / GLM）
- `model_mode: 'A' | 'C'`（A=直连，C=代理）
- migration: `0004_phase7_provider_keys_model_usage`

详见 [`docs/MODEL-PROXY.md`](./MODEL-PROXY.md)。

### 4.5 Phase 8 — 错误上报

**目标**：客户端崩溃时能拿到日志和环境快照，定位 bug 不再靠用户口述。

**关键交付**：
- `error_reports` 表
- 客户端 `errorReport.ts`：未捕获异常 → 弹「是否上报」对话框 → 打包日志上传
- `POST /api/v1/error-reports`（无鉴权，device_fp 兜底）
- admin UI `/error-reports` 页面（列表 + 下载日志包）
- migration: `0006_phase8_error_reports` / `0007_phase8_error_reports`

### 4.6 Phase 9 — 后端自动化

**目标**：服务端能自己照顾自己（备份 + 监控）。

**关键交付**：
- `backup` 容器（alpine + cron）：每天 03:17 dump → `/backups/studio_YYYYMMDD.sql.gz`，保留 7 天
- `/api/v1/admin/stats/health`：DB / 磁盘 / 容器状态
- Admin UI Dashboard 顶部加监控卡片
- `docker-compose.yml` 加 backup 服务

### 4.7 Phase 10 — Prompt 集版本管理（2026-07-15）

**目标**：B2B 售卖，每个客户独立的 prompt 集，admin 后台改完客户分钟级拿到新版，不再重打客户端。

**关键交付**：
- `prompt_sets` 表（content_yaml Text + version Integer + is_default + 软删）
- `users.prompt_set_id` FK（null 走默认）
- 客户端启动 + 心跳 piggyback 版本检查 → sync `%APPDATA%/ai-video-studio/prompts/<id>_<version>.yaml`
- worker spawn 注入 `--prompts-path` + `WORKER_PROMPTS_SIG` env
- `job_config.json` 加 `prompts_signature`：resume 时 prompt 变 → 废 `analyzed.json` 重分析
- 乐观锁 `expected_version` → 409
- migration: `0008_prompt_sets`

详见 [`docs/PROMPT-SETS.md`](./PROMPT-SETS.md)。

### 4.8 Phase 11 — 下载量 / 升级成功率（2026-07-11）

**目标**：admin 能看到运营数据，灰度发布后不再盲跑。

**关键交付**：
- `client_releases` 加 `download_count` + `upgrade_success_count`
- `main.py` 把 `/releases/{filename}` 从 StaticFiles 改为自定义路由（path traversal 防护 + 命中 `Setup X.Y.Z.exe` 时 +1）
- `POST /updates/report-upgrade`（无鉴权，按 to_version 反查 release +1）
- 客户端 `install()` 前写 `pending_upgrade_report`；新版本首次启动 fire-and-forget 上报
- Admin UI `/releases` 表格加「下载」+「升级成功」2 列（带百分比）
- migration: `0009_release_metrics`

**统计精度**：Counter 计数（无去重）；**升级信号**：新版本首次启动时上报（确认"真的装好且能跑"）；**上报失败**：静默丢弃不重试。

### 4.9 Phase 12 — 用户端可选 prompt 集（2026-07-11）

**目标**：同一客户公司员工处理不同项目时，需要在多套 prompt 间切换（旅游 / 美食 / 通用）。admin 分配一个"可选池"，用户在客户端设置页全局选一套当前生效，**不依赖 platform/style**（实测 Phase 4 的 platform/style UI 选项不影响 prompt 选择 — `vision_analyze.py` 始终用 `vertical="default"`）。

**关键决策**：

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | 数据模型 | 新表 `user_prompt_set_options`（多对多）+ 保留 `users.prompt_set_id`（当前生效） | 标准多对多，便于查询"哪些用户能用这套" |
| 2 | `users.prompt_set_id` 语义 | 不变（"当前生效集"） | 兼容 Phase 10 的 `_resolve_prompt_set()` 和客户端缓存逻辑 |
| 3 | options 池为空 | GET /me/options 自动包含 is_default + 当前 prompt_set_id | 老用户即使没分配也能看到至少 1 个选项 |
| 4 | admin 移除当前生效集 | 自动 fallback 到 is_default | 防止"用户当前选的不可用" |
| 5 | 选择粒度 | **全局设置一次**（不是每次任务选） | 低频操作 + 减少 UI 心智负担 |
| 6 | 用户可见性 | 名称 + 描述（不含 YAML 内容） | 保护 prompt IP |
| 7 | 数据迁移 | migration 0010 把现有 `prompt_set_id` 自动写入 options 池 | 老用户分配过的集不丢 |

**关键交付**：

后端：
- 新表 `user_prompt_set_options`（`user_id` + `prompt_set_id` + UniqueConstraint + 双 FK CASCADE）
- migration `0010_user_prompt_set_options`（含数据迁移：把现有 `users.prompt_set_id` 复制到 options 池）
- 用户端 2 个新端点：
  - `GET /api/v1/prompts/me/options` — 返回可选池（is_default 集 + 当前 prompt_set_id + options 表 ∪），按 is_default desc + id asc 排序，标记 is_current
  - `POST /api/v1/prompts/me/select` — 校验 target 存在 / active + 在 allowed_ids 池 → 更新 `users.prompt_set_id`
- `users_admin.py` PATCH 加 `prompt_set_option_ids` 处理（差量同步 + 移除当前集时 fallback）；UserOut 加该字段返回
- 5 个新 pytest（49/49 全过）

客户端：
- `types.ts` 加 `PromptSetOption` + 2 IPCChannel
- `promptSet.ts` 加 `listOptions()` + `select()`（select 后立即 sync 拉新 yaml）
- `ipc.ts` + `preload.ts` 加 `prompt-set:listOptions` / `prompt-set:select`
- `src/pages/Settings.tsx` 加「Prompt 集」Card：下拉 + 当前高亮 + 切换 toast
- **顺带修了 Phase 10 的 URL 拼接 bug**：所有 fetch 误拼 `${backend_url}/api/v1/...` 导致 `/api/v1/api/v1/...` → 404（已修为 `${backend_url}/prompts/...`）

Admin UI：
- `api/users.ts` UserListResponse + UserUpdatePayload 加 `prompt_set_option_ids`
- `pages/Users.tsx` Prompt Modal 从单选改多选；表格新增「可选池」列；「Prompt 集」列改名为「当前 Prompt 集」（informational）

E2E 验证（9 个 curl 场景全过）：新用户默认集 / admin 分配多套 / 用户看到 3 套 / select 切换 / 404 不存在 / 403 未授权 / admin 移除当前 → 自动 fallback

**约束**：

| 约束 | 说明 |
|------|------|
| 老用户 prompt_set_id 自动迁移 | migration 0010 把现有绑定写入 options 池 |
| options 为空也至少有 1 个选项 | GET /me/options 自动兜底包含 is_default + 当前 prompt_set_id |
| admin 移除当前生效集 → 自动 fallback | 优先 is_default，否则 new_ids 第一个，否则 null |
| 用户 select 失败 UI 不变 | API 失败 → toast 错误，前端状态不变（后端没改不算） |
| 心跳 piggyback 兼容 | 用户切换 prompt_set_id → 触发不同集 → version 必变 → 心跳 sync |

## 5. 跨 Phase 关键架构决策

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| 1 | video_worker 位置 | **客户端本地** | 保护 prompt IP 同时避免服务端 GPU 成本 |
| 2 | DB | MySQL 8.0（不用 Postgres） | 团队熟悉 + 阿里云 RDS 成本低 |
| 3 | 灰度算法 | sha256(device_fp:release_id) % 100 | 同设备结果稳定，灰度变化时不重新分配已命中设备 |
| 4 | 升级检测 | 新版本首次启动时主动上报 | 确认"真的装好且能跑"，比"下载完成"更准 |
| 5 | Prompt IP 保护 | DB 存 + 客户端缓存 + worker `--prompts-path` 注入 | A/C 模式都从后端拉，admin 改完分钟级生效 |
| 6 | 客户独立定制 | 完全独立的 N 套 prompt 集（不共享不 override） | B2B 售卖场景，客户不愿共享 prompt |
| 7 | 模型 key 管理 | Fernet 加密入库，绑 `JWT_SECRET` | 切 `JWT_SECRET` 自动失效所有 key（防泄露） |
| 8 | 软删策略 | `deleted_at` 时间戳 | 保审计链 + 防 FK SET NULL 中途解绑 |
| 9 | 后端 session 单点 | 同 user_id + session_type 单点 | 防 token 泄露后被多端滥用 |
| 10 | 升级回滚 | `is_active=False` + `rolled_back_at` | 止损（阻止新升级），不能让已升级用户降级 |
| 11 | 用户 vs prompt 集关系 | N:M（admin 分配可选池，用户自选当前） | 同客户多场景需要切换；admin 不必为每次切换介入 |
| 12 | platform/style UI | 与 prompt 解耦（实际不生效） | Phase 12 用户切换 prompt 走 `/prompts/me/select`，platform/style 是死代码 |

## 6. 累计交付的能力清单

### 客户端
- 单机视频生成（输入素材 → 镜头分析 → storyboard → 渲染输出）
- 多 provider 支持（Qwen-VL / Doubao / GLM，A 模式直连 / C 模式代理）
- 自动更新（灰度 + sha256 校验 + grace 期 + 回滚感知）
- Prompt 集版本管理（启动 sync + 心跳 piggyback + 本地缓存）
- **Prompt 集切换（Phase 12）**：Settings 页下拉选当前生效集
- 错误上报（崩溃一键上传日志）
- 单实例锁（防重复启动）

### Backend 控制面
- 账号 / 授权（用户 CRUD + license 过期 + 启用/禁用 + session 管理）
- 版本管理（发布 + 灰度 + 强制升级 + 回滚 + 下载量 + 升级成功率）
- prompt 集管理（CRUD + 复制 + 软删 + 默认集 + 用户绑定）
- **prompt 集分配（Phase 12）**：admin 给用户分配 N 套可选池；用户自选当前生效
- Provider key 管理（加密入库 + 测试连通性 + 启用/停用）
- 模型用量统计（按 provider / 用户 / 时间过滤）
- 审计日志（全量写操作 + IP / UA / snapshot）
- 错误报告（接收 + 日志包管理）
- 系统监控（DB / 磁盘 / 容器状态）
- 自动备份（每日 dump + 7 天保留）

### Admin UI
- 8 个页面：Dashboard / Users / Releases / Prompt Sets / Providers / Usage / Sessions / Audit
- 双 Factor：username/password + session_type 分离
- 自动 token 续期（access 60min + refresh）

## 7. 已知风险与未完成事项

| 风险 | 当前状态 | 缓解 |
|------|---------|------|
| Provider Key 切换 `JWT_SECRET` 后全部失效 | 已知约束 | 文档提示 + 部署 checklist |
| prompt 集编辑 textarea 无语法高亮 | 已知 | 后续接 CodeMirror |
| admin UI 无双因素认证 | 已知 | 部署配强密码 + IP 白名单 |
| 错误上报无去重 | 已知 | 后续加客户端指纹 |
| v0.9.0 客户端无 Phase 11/12 逻辑 | 已知 | 需发 v0.9.1+ 才有完整数据；v0.9.2 已含 Phase 12 |
| Counter 计数虚高（同设备重复） | 用户已接受 | 后续可改事件表 + 去重 |
| updater.ts grace 期误判（用户装好后仍弹"可安装"） | **已修代码，待发版** | 当前装的是 v0.9.2 仍带此 bug；下一版修复 |
| Phase 10 客户端 URL 拼接 bug（`/api/v1/api/v1/...`） | **已修代码，v0.9.2 已含** | 老版本 v0.9.0/0.9.1 用户需升级才能用 prompt 切换 |

## 8. 后续阶段候选

- **Phase 13**：客户端缓存多套 options（切换瞬时生效，不重新 sync）
- **Phase 14**：每次任务选 prompt（粒度更细，与全局设置解耦）
- **Phase 15**：prompt 集预览（让用户看到 YAML 内容，需要 IP 风险评估）
- **Phase 16**：多语言 UI（i18n）+ macOS 支持
- **Phase 17**：online dashboard（运维数据可视化大屏）

## 9. 关键运维信息

### 部署

```bash
cd backend
cp .env.example .env  # 改 ADMIN_PASSWORD / JWT_SECRET / DB_PASSWORD
docker compose up -d
# 容器：ai-video-backend / ai-video-mysql / ai-video-backup
```

### 访问

- 客户端下载：`http://<server>:8000/releases/AI Video Studio Setup X.Y.Z.exe`
- Admin UI：`http://<server>:8000/admin/`
- API 文档：`http://<server>:8000/docs`

### 关键文件

| 路径 | 用途 |
|------|------|
| `backend/app/main.py` | FastAPI 入口 + 路由注册 + `/releases/` 自定义服务 |
| `backend/alembic/versions/` | 10 个 migration（baseline + phase5-12） |
| `backend/admin-ui/` | Admin UI 源码（multi-stage build 进 backend image） |
| `desktop/electron/` | Electron 主进程（auth / updater / worker / promptSet / errorReport） |
| `video_worker/` | Python 流水线（PyInstaller 打包成独立 exe） |
| `desktop/release/` | 历史客户端安装包（docker-compose mount 到 `/releases`） |
| `docs/` | 项目文档（按主题分文件） |

### 数据库表（截至 Phase 12）

```
users                       # 用户 + role + license + prompt_set_id（当前生效）
sessions                    # 登录会话（session_type 分离）
client_releases             # 客户端版本（含 download_count / upgrade_success_count）
provider_keys               # 模型 API key（Fernet 加密）
model_usage                 # 每次模型调用记录
prompt_sets                 # prompt 集版本（含软删）
user_prompt_set_options     # 用户可选 prompt 集池（多对多，Phase 12）
audit_logs                  # 全量审计
error_reports               # 客户端崩溃上报
```

---

**Phase 4-12 全部 ship，商品化版本完整可售。**

> 本文档作为 v0.9.0 发布时的存档快照。后续 Phase 进展请参考 [`memory/ai-video-studio-phase4-status.md`](../../C:\Users\86150\.claude\projects\C--Users-86150\memory\ai-video-studio-phase4-status.md) 中的逐 Phase 记录。
