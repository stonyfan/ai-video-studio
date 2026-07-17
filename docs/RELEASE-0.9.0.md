# Release v0.9.0 — 商品化版本

**发布日期**：2026-07-11
**版本号**：0.9.0（Phase 5-10 全部完成）
**定位**：首个面向付费客户的完整商品化版本，覆盖账号授权、灰度更新、运维后台、云端模型代理、错误上报、prompt 集版本管理。

---

## 下载信息

| 项目 | 值 |
|------|-----|
| 文件名 | `AI Video Studio Setup 0.9.0.exe` |
| 下载 URL | `http://<server>:8000/releases/AI Video Studio Setup 0.9.0.exe` |
| SHA256 | `EAE4B47A24D29D0045EF998160D8F4BE93C205936D024F44489A0615A3A8EE26` |
| 体积 | ~192 MB（NSIS 安装包） |
| 最低兼容版本 | 0.4.0（低于此版本必须手动升级） |
| 灰度比例 | 30%（24-48h 后视情况全量） |
| 强制升级 | 关闭（grace 期 24h） |

> 部署后请将 `download_url` 中的 `<server>` 替换为实际后端地址。

---

## 主要新功能

### 1. 灰度发布 + 强制升级 + 回滚（Phase 5）

客户端走「同源下载 + SHA256 校验 + 灰度分流」：

- **灰度算法**：`sha256(f"{device_fp}:{release_id}")[:8] % 100 < rollout_percentage`
- **回滚**：admin UI 一键 `is_active=false` + `rolled_back_at=now`，客户端下次轮询自动拿到旧版本
- **强制升级**：`force_upgrade=true` + `grace_hours` 期间弹窗提醒，过期阻断登录
- **最低兼容版本**：低于此版本必须手动升级，不走灰度

详见 `docs/updates.md`（admin UI `/releases` 页面操作）。

### 2. Web 运维后台（Phase 6）

独立 SPA，构建产物烤进 backend Docker 镜像：

- **URL**：`http://<server>:8000/admin/`
- **登录**：用 `.env` 里的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`
- **页面**：Dashboard / Users / Releases / Prompt 集 / Provider Keys / Usage / Sessions / Audit

详见 `docs/ADMIN-UI.md`。

### 3. C 模式：云端模型代理（Phase 7）

backend 加 `/api/v1/vision/*` 代理端点，desktop 可走云端：

- **session 分离**：`session_type="desktop"` vs `"web"`，同一 admin 可同时登 desktop + UI
- **provider keys**：Qwen-VL / GLM / Doubao，Fernet 加密入库，列表只显示 mask
- **用量统计**：每次调用记 tokens / 成本 / 延迟 / 错误
- **C 模式开关**：`settings.DESKTOP_USE_PROXY`（B 模式 = 客户自带 key 走原生；C 模式 = 走 backend 代理）

详见 `docs/MODEL-PROXY.md`。

### 4. 错误上报（Phase 8）

客户端崩溃时一键上传日志 + 环境快照：

- **触发**：renderer/main/worker 任何未捕获异常 → 弹「发生错误，是否上报？」对话框
- **端点**：`POST /api/v1/error-reports`（无鉴权，但带 device_fp 防滥用）
- **admin 查看**：`/error-reports` 页面（如有，否则直查 DB `error_reports` 表）
- **隐私**：上报前显示清单让用户确认，不含视频内容、API key

### 5. Prompt 集版本管理（Phase 10）

每个客户独立的 prompt 集，admin 后台维护：

- **数据模型**：`prompt_sets` 表 + `users.prompt_set_id` FK
- **编辑**：textarea + js-yaml 实时校验（前后端双重）
- **版本号**：`content_yaml` 变更自动 +1，名/状态变更不 bump
- **乐观锁**：PATCH 带 `expected_version`，不匹配返回 409
- **客户端拉取**：启动 + 心跳 piggyback（每 5 次心跳查一次版本）
- **缓存**：`%APPDATA%/ai-video-studio/prompts/<id>_<version>.yaml`，sync 后清旧版本
- **resume 兼容**：`job_config.json` 写 `prompts_signature`，不一致时废 `analyzed.json` 重分析
- **默认集**：未绑定的用户走 `is_default=true` 的集
- **软删**：`deleted_at` 时间戳，保审计链；删除前检查 bound users

详见 `docs/PROMPT-SETS.md`。

### 6. 后端自动化（Phase 9）

- **DB 每日备份**：alpine 容器 + cron，每天 03:17 自动 dump → `/backups/studio_YYYYMMDD.sql.gz`，保留 7 天
- **系统监控**：`/api/v1/admin/stats/health` 暴露 DB / 磁盘 / 容器状态
- **全量审计**：所有 `/api/v1/admin/*` 写操作自动入 `audit_logs` 表，含 actor / action / target / IP / UA / snapshot

---

## 升级指引

### 从 v0.4.x 升级（用户侧）

1. 客户端自动检测到 v0.9.0（在 30% 灰度内）
2. 弹「发现新版本」提示 → 点「立即下载」
3. 下载完成后自动校验 SHA256 → 提示重启安装
4. 旧版配置/授权自动迁移（`%APPDATA%/ai-video-studio/config.json`）

> 若不在 30% 灰度内：等全量（24-48h 后）或联系 admin 手动调灰度比例。

### 服务端升级（admin 侧）

1. 拉最新代码：`git pull`
2. 构建镜像：`docker compose build`
3. 起新服务：`docker compose up -d`
4. Alembic 自动跑 migration（0001-0008）
5. 用 `.env` 的 admin 账号登 `/admin/`，进 `/releases` 确认 v0.9.0 已发布

### Alembic migrations 清单

```
0001_initial
0002_phase5_release_management
0003_phase6_audit_logs
0004_phase7_provider_keys_model_usage
0005_phase7_sessions_session_type
0006_phase8_error_reports
0007_phase8_error_reports   # 实际编号按实际为准
0008_prompt_sets
```

---

## 已知问题与限制

| # | 问题 | 影响 | 缓解 |
|---|------|------|------|
| 1 | prompt 集编辑 textarea 无语法高亮 | admin 体验略差 | Phase 11+ 接 CodeMirror |
| 2 | Provider Key 切换 `JWT_SECRET` 后全部失效 | 需重新录入 | 文档提示 + Fernet 加密绑 JWT_SECRET |
| 3 | 心跳 piggyback 仅查版本号，不拉内容 | 版本更新后需 1 次额外 sync | 已优化为最小 payload |
| 4 | admin UI 双因素认证未做 | 弱密码风险 | 部署时配强密码 + IP 白名单 |
| 5 | 错误上报无去重 | 同一 crash 多次上报 | Phase 11+ 加 client-side 指纹去重 |
| 6 | 客户端 fallback bundled prompts | 装机首次启动后端不可达时走老 prompt | 文档提示：默认集以 DB 为准 |

---

## 技术栈版本

| 组件 | 版本 |
|------|------|
| backend | Python 3.12 + FastAPI + SQLAlchemy 2.x + Alembic |
| admin-ui | React 18.3 + Antd 5.22 + Vite 5 |
| desktop | Electron 33 + electron-vite + electron-builder (NSIS) |
| video_worker | Python 3.11 + PyInstaller（独立 exe） |
| DB | MySQL 8.0 |
| 部署 | Docker Compose（backend + mysql + backup 三容器） |

---

## 验收清单（打包前已确认）

- [x] backend pytest 全过（47 个测试）
- [x] admin-ui typecheck + build 通过
- [x] desktop typecheck + build 通过
- [x] video_worker 单独跑通自定义 prompt
- [x] 端到端：admin 改 prompt → desktop 心跳检测 → sync → worker 用新版
- [x] SHA256 校验匹配
- [x] 安装包在干净 Win11 上跑通
- [x] 升级路径：0.4.x → 0.9.0 配置迁移

---

## 后续阶段

- **Phase 11（可选）**：prompt A/B 测试（同用户绑多集按比例分流）+ 历史版本保留/回滚
- **Phase 12（可选）**：多语言 UI（i18n）+ macOS 支持
- **Phase 13（可选）**：online dashboard（运维数据可视化大屏）

---

## 联系方式

- **问题反馈**：admin UI `/error-reports` 页面，或客户提工单
- **紧急回滚**：admin UI `/releases` → 找到 v0.9.0 → 点「回滚」（is_active=false，用户下次轮询回到旧版本）
- **文档入口**：`docs/` 目录下分专题文档

---

**v0.9.0 — 第一个可以收钱的版本。**
