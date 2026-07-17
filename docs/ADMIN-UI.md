# Admin UI（运维后台）

Phase 6 实现的 Web 运维后台，独立 SPA，构建产物烤进 backend Docker 镜像，由 FastAPI 同源服务（`/admin/`）。

## 访问

- **URL**：`http://<server>:8000/admin/`
- **首次登录账号**：用 `.env` 里的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`

## 功能

| 页面 | 路径 | 能力 |
|------|------|------|
| Dashboard | `/` | 用户/版本/Session 总数 + 今日模型用量 + 最近 10 条审计 |
| Users | `/users` | CRUD + 改密 + 延期 + 启用/禁用 + 分配 Prompt 集 |
| Releases | `/releases` | 发布/编辑/灰度调整/回滚 |
| Prompt 集 | `/prompt-sets` | 客户独立的 prompt 集版本管理（CRUD + 复制 + 软删） |
| Provider Keys | `/providers` | C 模式：模型 API key 管理（CRUD + 测试连通性） |
| Usage | `/usage` | C 模式：模型用量统计（按 provider/用户/时间过滤） |
| Sessions | `/sessions` | 列表/过滤/吊销 |
| Audit Logs | `/audit` | 全量审计查询（actor/action/target/时间） |

## session_type 分离（Phase 7）

后端按 `(user_id, session_type)` 单会话校验：

- `session_type="desktop"` — Electron 客户端登录
- `session_type="web"` — admin UI 登录

**同一 admin 现在可以同时登 desktop + UI，互不干扰**。同 type 内仍单点（新登顶替旧 session）。

> Phase 6 的「双 admin 账号策略」已废弃，不需要再创建 admin_ui 专用账号。

## 典型操作流程

### 发布新版本（灰度）

1. 进入 `/releases` → 点击「发布新版本」
2. 填：version（如 `0.7.0`）、下载 URL、SHA256、最低兼容版本、发布说明
3. 灰度比例先设 `30`，强制升级默认关
4. 点击「确定」→ 表格出现新行
5. 观察 24-48h；调到 `100` 全量
6. 出问题 → 行内「回滚」按钮（`is_active=false` + `rolled_back_at=now`）

### 创建用户并延期

1. `/users` → 「创建账号」→ 填写信息 → 确定
2. 表格行「授权」按钮 → 选「永久」或「延长 N 天」（在当前到期日上累加）

### 排查异常 Session

1. `/sessions` → 用「用户」下拉过滤
2. 找到可疑行（陌生 IP / 异常 UA）
3. 点击「吊销」（用户下次请求 401 → 跳登录）

### 查审计

1. `/audit` → 用动作/目标/时间过滤
2. 行展开 → 看 target_snapshot JSON 摘要

### 管理 Provider Keys（C 模式）

1. `/providers` → 「添加 Key」
2. 选 provider（Qwen-VL / GLM / Doubao）+ 命名 + 明文 key + 可选 base_url
3. 保存后明文不入数据库（Fernet 加密），列表只显示 mask（如 `sk-123...wxyz`）
4. 行内「测试」按钮：发最小请求验证 key 有效性
5. 行内「启用/停用」开关：停用的 key 不会被代理端点选中
6. 切换 `JWT_SECRET` 后**所有 key 失效**，需重新录入

### 查模型用量（C 模式）

1. `/usage` → 顶部 4 卡片：今日请求数 / 总 tokens / 成本(¥) / 错误数
2. 按 provider 拆分表：每家 provider 的请求数 / tokens / 成本 / 错误
3. 主表：每条调用记录（时间 / 用户 / provider / 模型 / tokens / 成本 / 状态 / 延迟 / 错误）
4. 过滤栏：用户 / provider / 状态 / 时间范围
5. Dashboard 顶部也有「今日模型用量」卡片，点击「查看详情」跳转到这里

## 部署

Admin UI 已包含在 backend Docker 镜像（multi-stage build）：

```dockerfile
# backend/Dockerfile
FROM node:20-alpine AS ui-build
COPY admin-ui/ ./
RUN npm ci && npm run build     # → /ui/dist

FROM python:3.12-slim
COPY --from=ui-build /ui/dist /app/admin-ui
```

FastAPI 挂载：

```python
# app/main.py
app.mount("/admin", StaticFiles(directory="admin-ui", html=True), name="admin-ui")
```

`html=True` 提供 SPA fallback：`/admin/users`、`/admin/releases` 等子路径刷新都返回 `index.html`。

## Token 自动续期

- access_token 60min 过期
- 响应拦截器：401 → 用 refresh_token 调 `/auth/refresh` → 重试原请求
- refresh 失败 → 清 localStorage → 跳 `/login`
- 5xx / 网络错误 → Antd 全局 notification

## 审计写入规则

后端 middleware 自动拦截 `/api/v1/admin/*` 写操作（POST/PATCH/DELETE/PUT）→ 写 `audit_logs` 表。无需业务代码显式调日志函数。

| HTTP | 路径 | action |
|------|------|--------|
| POST | /admin/users | `user.create` |
| PATCH | /admin/users/{id} | `user.update` |
| DELETE | /admin/users/{id} | `user.delete` |
| POST | /admin/users/{id}/reset_password | `user.reset_password` |
| POST | /admin/releases | `release.create` |
| PATCH | /admin/releases/{id} | `release.update` |
| POST | /admin/releases/{id}/rollback | `release.rollback` |
| POST | /admin/sessions/{id}/revoke | `session.revoke` |
| POST | /admin/provider-keys | `provider_key.create` |
| PATCH | /admin/provider-keys/{id} | `provider_key.update` |
| DELETE | /admin/provider-keys/{id} | `provider_key.delete` |
| POST | /admin/prompt-sets | `prompt_set.create` |
| PATCH | /admin/prompt-sets/{id} | `prompt_set.update` |
| DELETE | /admin/prompt-sets/{id} | `prompt_set.delete` |
| POST | /admin/prompt-sets/{id}/duplicate | `prompt_set.duplicate` |

- `target_id` 从 URL 取（POST 类操作从 response snapshot 反填）
- `target_snapshot` 是响应 body 关键字段的 JSON（user.username / release.version / 等）
- `ip` 取 `request.client.host`
- `user_agent` 取请求头

## 开发模式

后端 + 前端分开热加载：

```bash
# Terminal 1：后端
cd backend
docker compose up

# Terminal 2：admin-ui dev server（vite）
cd backend/admin-ui
npm run dev
# 访问 http://localhost:5173/admin/，proxy 转发 /api → http://localhost:8000
```

类型检查 + 构建：

```bash
cd backend/admin-ui
npm run typecheck
npm run build    # 产物在 dist/
```

## Prompt 集版本管理（Phase 10）

详见 [`docs/PROMPT-SETS.md`](./PROMPT-SETS.md)。

### 在 admin UI 的操作

1. **`/prompt-sets` 页面**：
   - 新建集：填名称 + 在 textarea 编辑 YAML（带 js-yaml 实时校验）
   - 编辑集：改 content_yaml → version 自动 +1；改 name/is_default/is_active 不 bump
   - 复制集：新集 name 带「(副本)」，version 重置为 1
   - 软删集：默认集 / 绑定用户的集不能删
   - 设为默认：原默认集自动降级

2. **`/users` 页面 → 「Prompt」按钮**：
   - 给用户分配 prompt 集
   - 选「默认（系统）」= 解绑走默认集
   - 用户客户端下次启动（或心跳触发版本检查）时拉取新 prompt
