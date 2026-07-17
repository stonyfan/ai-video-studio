# Prompt 集版本管理（Phase 10 + Phase 12）

> **Phase 12 更新（2026-07-11）**：用户-prompt 集关系从 **1:1**（admin 单向分配一套）改为 **N:M**（admin 分配可选池，用户在客户端自选当前生效）。本文档保留 Phase 10 原内容，Phase 12 改动在各章节用「Phase 12 更新」子段标注。

## 概述

每个客户可以维护独立的 prompt 集，admin 在后台改了 prompt，客户下次启动客户端（或心跳时）自动拉取新版。迭代周期分钟级，**不需要重发客户端**。

### 解决的问题

之前 prompt 写在 `configs/prompts.yaml`，由 PyInstaller 打包进 worker.exe。改 prompt = 重打 worker = 重发客户端 = 用户走自动更新。B2B 售卖场景下不同客户买不同定制，每改一次 prompt 都要走完整发版流程，迭代周期是天级。

### 解决方案

- 后端 `prompt_sets` 表存 N 套 prompt 集（含完整 YAML 内容）
- **Phase 10**：每个用户绑定 0 或 1 套；不绑走默认集
- **Phase 12**：admin 给用户分配 1~N 套可选池（`user_prompt_set_options` 表）；用户在客户端 Settings 页自选当前生效集；当前集被 admin 移除时自动 fallback 到默认集
- 客户端登录后自动拉当前生效集，缓存本地
- admin 改了 prompt → 客户端心跳时检测到版本变化 → 自动同步新版
- 任务 resume 时如果 prompt 变了 → 自动重新做 AI 分析（不用旧分析结果）

## 架构

```
┌──────────┐    1. create/edit     ┌─────────────┐
│  Admin   │ ───────────────────→ │ prompt_sets │
│   UI     │                      │    table    │
│ /prompt- │    2. assign pool    └─────────────┘
│  sets    │ ─────────────┐              ↑
└──────────┘              ↓              │ 3. GET /prompts/me
                  ┌─────────────────┐    │ (login + heartbeat)
                  │ users           │    │
                  │  prompt_set_id  │ ←──┤ 当前生效集（Phase 10 字段，语义不变）
                  └─────────────────┘    │
                          ↑              │ 4. GET /prompts/me/options
                  ┌─────────────────┐    │ + POST /prompts/me/select
                  │ user_prompt_    │    │ (Phase 12 用户自选)
                  │  set_options    │    │
                  │  (多对多)        │    │
                  └─────────────────┘    │
                                         ↓
                  ┌──────────────────────────┐
                  │  Desktop Client         │
                  │  promptSetClient:       │
                  │    sync() / heartbeatTick()│
                  │    listOptions() / select()│ ← Phase 12 新增
                  │  → cache to %APPDATA%   │
                  │  → worker spawn         │
                  │    --prompts-path <id>_<v>.yaml │
                  └─────────────────────────┘
```

## 数据模型

### `prompt_sets` 表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | |
| `name` | VARCHAR(64) | 显示名（"默认" / "客户A"） |
| `description` | VARCHAR(255) | 选填 |
| `content_yaml` | TEXT | 原始 YAML 字符串（与 `configs/prompts.yaml` 同结构） |
| `version` | INT | content_yaml 变更时 +1（其他字段不变 bump） |
| `is_default` | BOOL | 同表只能有一条 is_default=True 且未软删 |
| `is_active` | BOOL | 停用后用户拉不到，走默认 |
| `deleted_at` | DATETIME | 软删时间戳（保审计链 + FK 兜底） |
| `created_at` / `updated_at` | DATETIME | |

### `users.prompt_set_id` 字段（Phase 10）

- 可空 BIGINT FK → `prompt_sets.id` (ON DELETE SET NULL)
- null = 走默认集
- 删 prompt 集时 FK SET NULL，用户自动回退默认
- **Phase 12 语义不变**：仍表示"当前生效集"；admin 不再单独设，由用户在客户端 select

### `user_prompt_set_options` 表（Phase 12 新增）

多对多关联：admin 给用户分配的「可选 prompt 集池」。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | BIGINT PK | |
| `user_id` | BIGINT FK → `users.id` (CASCADE) | |
| `prompt_set_id` | BIGINT FK → `prompt_sets.id` (CASCADE) | |
| `created_at` | DATETIME | |
| UniqueConstraint | `(user_id, prompt_set_id)` | 防重复分配 |

migration `0010_user_prompt_set_options`：建表 + 数据迁移（把现有 `users.prompt_set_id` 自动写入 options 池，老用户分配不丢）

## 后端 API

### 用户端

#### `GET /api/v1/prompts/me`
返回当前用户应使用的 prompt 集（含完整 content_yaml）。

逻辑：
1. 如果 `user.prompt_set_id` 有值且该集未软删 + is_active → 返回该集
2. 否则查 `is_default=True AND deleted_at IS NULL AND is_active=True` → 返回默认集
3. 都没有 → 404 "无可用 prompt 集"

响应头：`Cache-Control: private, max-age=30`（多 renderer 组件访问不打 DB）

#### `GET /api/v1/prompts/me/version`
轻量 polling 端点，只返回 `{id, version}`。心跳 piggyback 用。

#### `GET /api/v1/prompts/me/options`（Phase 12）

列出当前用户可切换的 prompt 集。返回值始终包含：
- `user_prompt_set_options` 表里分配的 N 套
- 用户当前 `prompt_set_id`（即使 admin 没显式分配到 options 池）
- 系统默认集（is_default=True）

按 `is_default desc, id asc` 排序。每项带 `is_current` 标记，客户端高亮当前生效用。

老用户（options 表为空）也能看到至少 1 个选项（默认集兜底）。

响应体（数组）：
```json
[
  {
    "id": 1, "name": "默认", "description": "...",
    "version": 1, "is_default": true, "is_current": true
  },
  { "id": 5, "name": "旅游版", "description": "...", "version": 2, "is_default": false, "is_current": false }
]
```

#### `POST /api/v1/prompts/me/select`（Phase 12）

用户切换当前生效集。

校验：
- target 集必须存在 + active + 未软删（否则 404）
- target 必须在用户的 allowed_ids 池（options 表 ∪ is_default 集 ∪ 当前 prompt_set_id）（否则 403）

成功 → 更新 `users.prompt_set_id`，返回新集完整内容（客户端立即 sync）。

### Admin 端（`/api/v1/admin/prompt-sets`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 列表（不含 content_yaml，含 bound_user_count）|
| GET | `/{id}` | 详情（含 content_yaml） |
| POST | `/` | 创建（YAML 校验） |
| PATCH | `/{id}` | 更新（带 expected_version 乐观锁；content_yaml 变 → version+1） |
| DELETE | `/{id}` | 软删（不能删默认集 / 不能删绑定用户的集） |
| POST | `/{id}/duplicate` | 复制为新集（name 加「(副本)」，version 重置为 1，is_default=False） |

### YAML 校验（前后端双重）

- 必须能 `yaml.safe_load` 成功
- 顶层必须是 mapping
- 必须有 `templates` 段（dict）
- 必须有 `templates.triplet_detect` 段（dict）
- `templates.triplet_detect.default` 不能为空
- `content_yaml` 大小上限 256KB

### 乐观锁

PATCH 时如果传了 `expected_version` 且与当前 version 不匹配 → 409 "版本已变，请刷新后重试"。防止两个 admin 同时改同一个集。

### `is_default` 切换

PATCH 时 `is_default: True`：
1. 单事务内把其他所有 is_default=True 的集置 false
2. 把当前集置 true

不允许 `is_default: False`（取消当前默认集的默认状态）— 必须先把其他集设为默认。

### 删除策略（软删）

- `deleted_at = now()` + `is_active = False`
- 不能删默认集 → 400
- 不能删绑定用户的集 → 400 "仍有 N 个用户绑定此集，请先解绑"
- 软删后保审计链 + FK SET NULL 兜底

## Admin UI

### 页面：`/prompt-sets`（FileTextOutlined icon）

- 表格：name / version / is_default (Tag) / is_active (Switch) / bound_user_count / updated_at
- 操作：编辑 / 复制 / 删除（软删，弹确认）
- 顶部「新建 Prompt 集」按钮
- 编辑 Modal：
  - name + description
  - 大 textarea（content_yaml，monospace 字体）
  - is_default Switch + is_active Switch
  - 显示当前 version（只读）
  - 提交前客户端 js-yaml 校验（与后端同步）
  - 隐藏 expected_version 字段

### 用户页：分配 Prompt 集（Phase 12 改造）

- Users 表格保留「当前 Prompt 集」列（显示 `users.prompt_set_id` 对应名，informational）
- **新增「可选池」列**：显示分配的 N 套（前 2 个名 / +N）
- 「Prompt」action button → Modal **改为多选**（`Select mode="multiple"`）
- 多选选项：所有 active 的 prompt 集
- 保存时 PATCH `prompt_set_option_ids: [1, 2, 3]`
- **未传** = 不改 options；**显式 `[]`** = 清空；**`[1,2,3]`** = 设为这三套（通过 `model_fields_set` 区分）
- 后端差量同步（existing - new 删，new - existing 增）
- **若用户当前 prompt_set_id 不在 new_ids** → 自动 fallback：优先 is_default，否则 new_ids[0]，否则 null

> Phase 10 的单选「Prompt 集」列保留为「当前 Prompt 集」（用户在客户端切换后会反映在这里），admin 不再直接改这个字段。

## Desktop 客户端

### `desktop/electron/promptSet.ts`

`PromptSetClient` 类：

- `sync()` — 完整拉取：GET /prompts/me → 写盘 → 持久化到 config.json
- `heartbeatTick()` — 每 5 次心跳查 /prompts/me/version，不同则触发 sync
- `getCachedPath()` — 读 config.json 拿缓存路径
- `resolveForWorker()` — 返回 `{promptsPath, signature}` 给 worker spawn
- `listOptions()`（Phase 12）— GET /prompts/me/options，返回可选池数组
- `select(id)`（Phase 12）— POST /prompts/me/select，成功后立即 sync 拉新 yaml

> Phase 12 顺带修了 Phase 10 的 URL 拼接 bug：所有 fetch 误拼 `${backend_url}/api/v1/...` 导致 `/api/v1/api/v1/...` → 404。已统一改为 `${backend_url}/prompts/...`（v0.9.2+ 含此修复）。

### 缓存位置

`%APPDATA%/ai-video-studio/prompts/<id>_<version>.yaml`

- 用版本号防冲突
- sync 后清同 id 的旧版本文件
- 写盘用 tmp + rename 原子操作

### sync 时机

1. `auth.ts login()` 成功后 → 后台 sync（不阻塞登录返回）
2. `auth.ts resumeIfHasSession()` 后 → 后台 sync（应用启动时）
3. 心跳 piggyback：每 5 次心跳（约 5 分钟）查 /prompts/me/version，版本变化 → sync
4. **Phase 12**：用户在 Settings 页切换 prompt 集 → `select()` 内部立即 sync（不等待心跳）

### Settings 页「Prompt 集」Card（Phase 12）

进入 Settings 页时调 `listOptions()`，渲染下拉框：
- 选项 = 用户可选池（默认集 + options 池 + 当前生效集）
- 当前生效的有绿色「当前」Tag
- 默认集有蓝色「默认」Tag
- 选中后立即调 `select(id)`，成功 toast「已切换到 X（下次任务生效）」+ 重新拉 options（更新 is_current）
- 失败 → toast 错误，UI 不变（后端没改不算）

> 客户端只看到 prompt 集的 name + description，看不到 YAML 内容（IP 保护）。

### 失败兜底

- 网络错误 → 用上次缓存（config.json 里的 path 还在）
- 首次启动 + 后端不可达 → `bundledPromptsPath()` 返回打包的 configs/prompts.yaml
- worker spawn 时永远传 `--prompts-path`，不会因为缺路径而崩

### `AppConfig.prompt_set_cache`

```typescript
prompt_set_cache?: {
  id: number
  version: number
  path: string  // %APPDATA%/.../prompts/<id>_<version>.yaml
} | null
```

## video_worker 改动

### `__main__.py`

新增 `--prompts-path <Path>` 参数，传给 `process_job(cfg, prompts_path=...)`。

### `job.py`

- `process_job()` 加 `prompts_path: Optional[Path] = None`
- 从 env `WORKER_PROMPTS_SIG` 读 signature（"id:version" 或 "bundled"）
- 写 `job_config.json` 时追加 `prompts_signature` 字段
- resume 时读旧 `job_config.json`，若 `prompts_signature` 不一致 → 删 `work/analyzed.json` 强制重分析
- 调 `vision_analyze.analyze(..., prompts_path=effective_prompts_path)`

### `vision_analyze.py`

- `analyze_scene()` 加 `prompts_path` 参数
- `analyze()` 加 `prompts_path` 参数，透传给 `analyze_one` → `analyze_scene`
- 都默认 `PROMPTS_DEFAULT_PATH`（bundled configs/prompts.yaml）

## resume 兼容性

**问题**：用户跑了一半的任务被中断，admin 改了 prompt，用户 resume 时如果用旧分析结果 + 新 prompt → 编排可能不一致。

**解决**：
- `job_config.json` 里记录 `prompts_signature`（set_id:version）
- resume 时读旧 signature，与当前 `WORKER_PROMPTS_SIG` 比对
- 不一致 → 删 `analyzed.json` → 强制重做 AI 分析

**代价**：用户得为重分析多花一些 API 调用钱。但比"用旧分析+新 prompt 拼出诡异视频"安全。

## 关键约束

| 约束 | 说明 |
|------|------|
| `JWT_SECRET` 不能轮换 | 与 Phase 7 一致（影响 provider_keys 加密） |
| 默认集不能删 | 必须先把其他集设为默认再删原默认 |
| 绑定用户的集不能删 | 先解绑（PATCH user.prompt_set_id=null，或清空 options 池） |
| content_yaml ≤ 256KB | 前后端双重校验 |
| 客户端缓存 5min polling | 心跳 piggyback 每 5 次查版本 |
| 软删不真删 | deleted_at + is_active=False，保审计链 |
| `configs/prompts.yaml` 仅 dev 用 | 生产以 DB 为准；bundled 兜底用 |
| 老用户 prompt_set_id 自动迁移 | migration 0010 把现有绑定写入 options 池（Phase 12） |
| options 为空也至少有 1 个选项 | GET /me/options 自动兜底包含 is_default + 当前 prompt_set_id（Phase 12） |
| admin 移除当前生效集 → 自动 fallback | 优先 is_default，否则 new_ids[0]，否则 null（Phase 12） |
| 用户 select 失败 UI 不变 | API 失败 → toast 错误，前端状态不变（Phase 12） |
| platform/style UI 与 prompt 解耦 | Phase 4 的 platform/style 选项实际不生效，vision_analyze 始终用 vertical="default" |

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 默认集种子与 video_worker configs 不同步 | 中 | 新装用户 prompt 不一致 | 文档说明：以 DB 为准；bundled 仅兜底 |
| 心跳 piggyback 增加心跳响应体积 | 低 | 网络略增 | 仅加 id+version（16 字节级） |
| 客户端首次启动无缓存 + 后端不可达 | 低 | worker 用 bundled prompts | 总是传 `--prompts-path`，fallback 到 bundled |
| admin 误改 prompt 导致 worker 解析失败 | 中 | 用户任务失败 | YAML 校验在前后端双重；可软删回滚（is_active=False 后用户走默认） |
| resume 时 prompt 变更未触发重分析 | 高 | 新旧分析结果混用 | `prompts_signature` 写入 job_config.json，不一致时废 analyzed.json |
| 软删后用户仍引用 | 低 | 用户拉不到 prompt | 删除前检查 bound users；FK ON DELETE SET NULL 兜底（走默认） |
| content_yaml 过大 | 低 | DB / 写盘压力 | PATCH 校验 max 256KB |

## 操作流程示例

### 给客户 A 配独立 prompt（Phase 10 经典场景）

1. admin 登录后台 → `/prompt-sets` 页面
2. 点「新建 Prompt 集」→ 名字「客户A」→ 在 textarea 里编辑 YAML → 保存
3. 去 `/users` 页面 → 找到客户 A 的账号 → 点「Prompt」按钮 → 多选勾上「客户A」→ 保存
4. 客户 A 下次启动客户端 → Settings 页能看到「客户A」+ 默认集 → 切换到「客户A」→ 下次任务生效

### 给同一客户分配多套 prompt（Phase 12 新场景）

1. admin 在 `/prompt-sets` 建 N 套集（如「旅游版」/「美食版」/「通用版」）
2. 去 `/users` → 选目标用户 → 点「Prompt」→ 多选勾上 3 套 → 保存
3. 用户客户端启动 → Settings → 「Prompt 集」Card 显示下拉（3 套 + 默认）
4. 用户根据今天的项目类型自己切换 → 立即生效（下次任务）

### 改 prompt 后即时生效

1. admin 在 `/prompt-sets` 编辑「客户A」→ 改 textarea → 保存（version 自动 +1）
2. 客户 A 的客户端在 5 分钟内（下次心跳 piggyback）检测到版本变化 → 自动 sync
3. 客户 A 下次跑任务 → 用新 prompt
4. 如果客户 A 有 resume 中的任务 → 自动重做 AI 分析（因为 signature 变了）

### admin 移除用户当前生效集 → 自动 fallback

1. 用户当前 `prompt_set_id=5`（「旅游版」）
2. admin 在 `/users` 把用户的 options 改成 `[6]`（只剩「美食版」）
3. 后端检测到 `5 ∉ [6]` → 自动把 `prompt_set_id` 改为 is_default 集 id
4. 用户客户端心跳触发 sync（version 变了）→ 自动回到默认集

### 回滚

1. admin 把「客户A」集的 `is_active` 设为 false → 客户 A 立即回退到默认集
2. 或软删「客户A」集（先清空所有用户的 options 引用）→ 客户 A 走默认集

## 后续阶段

- **Phase 13（可选）**：客户端缓存多套 options（切换瞬时生效，不重新 sync）
- **Phase 14（可选）**：每次任务选 prompt（粒度更细，与全局设置解耦）
- **Phase 15（可选）**：prompt 集预览（让用户看到 YAML 内容，需要 IP 风险评估）
- **Phase 16（可选）**：prompt A/B 测试（同一用户绑多个集，按比例分流）
- **Phase 17（可选）**：prompt 历史版本保留 + 一键回滚（当前 MVP 不做，每次改覆盖）
