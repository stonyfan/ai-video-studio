# Model Proxy（C 模式 - 云端代理）

Phase 7 实现的模型 API 代理：客户端不持有 provider key，所有调用走后端 `model_proxy` 端点，由后端转发到云厂商（Qwen-VL / GLM / Doubao）。商业部署必备。

## 为什么需要

| 维度 | A 模式（直连） | C 模式（云端代理） |
|------|---------------|-------------------|
| key 持有方 | 用户本机（config.json） | 后端 DB（Fernet 加密） |
| 计费 | 用户自付 provider 账单 | 平台统一结算，向用户计量 |
| 限速 | 无 | 每用户每分钟 N 请求 |
| 用量审计 | 无 | `model_usage` 表全量记录 |
| 切换 provider | 重发 key | admin 后台一键 |
| 适用场景 | 个人开发 / 自部署 | 商业 SaaS |

## 架构

```
[desktop client]
  ↓ HTTP（JWT 鉴权）
  POST /api/v1/vision/{provider}/chat/completions
[backend FastAPI]
  1. 验 JWT → user
  2. 检查 license_valid + is_active
  3. 限速：滑动窗口（每用户每分钟 20 次）
  4. 选 key：同 provider 多 key 随机轮换
  5. 透传：httpx.AsyncClient POST → 上游
  6. 计费：写 model_usage 表
  ↓
[qwen-vl / glm / doubao 上游]
```

## 端点

```
POST /api/v1/vision/{provider}/chat/completions
  - {provider} ∈ {qwen-vl, glm, doubao}
  - 鉴权: Bearer JWT（要求 is_active + license_valid）
  - 限速: 每用户每分钟 20 次（超出返回 429）
  - body: OpenAI ChatCompletion 格式（透传不改写）
  - response: 透传 provider 返回
```

## 数据模型

### `provider_keys` 表

```sql
CREATE TABLE provider_keys (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  provider VARCHAR(32) NOT NULL,         -- qwen-vl / glm / doubao
  name VARCHAR(64) NOT NULL,             -- admin 自命名，如 "Qwen-VL 主号"
  api_key_encrypted TEXT NOT NULL,       -- Fernet ciphertext
  base_url VARCHAR(255),                 -- null=走 provider 默认
  is_active BOOLEAN DEFAULT TRUE,
  last_used_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_provider_active (provider, is_active)
);
```

### `model_usage` 表

```sql
CREATE TABLE model_usage (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id BIGINT NOT NULL,
  provider VARCHAR(32) NOT NULL,
  model VARCHAR(64) NOT NULL,
  input_tokens INT NOT NULL DEFAULT 0,
  output_tokens INT NOT NULL DEFAULT 0,
  estimated_cost_cny FLOAT NOT NULL DEFAULT 0.0,
  status VARCHAR(16) NOT NULL,           -- success / error / rate_limited
  error_message VARCHAR(255),
  latency_ms INT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_created (user_id, created_at),
  INDEX idx_provider_created (provider, created_at),
  FOREIGN KEY (user_id) REFERENCES users(id)
);
```

## Key 加密

- **算法**：Fernet 对称加密（cryptography 库）
- **密钥派生**：`PBKDF2-HMAC-SHA256(JWT_SECRET, salt="phase7-provider-keys", rounds=100_000, dklen=32)` → urlsafe_b64encode
- **关键约束**：`JWT_SECRET` 一旦轮换，所有 `provider_keys.api_key_encrypted` 无法解密 → 需重新录入

代码：`app/services/crypto.py`

## 限速

- **算法**：进程内滑动窗口（`collections.deque[timestamp]` per user_id）
- **配置**：`VISION_RATE_LIMIT_PER_MIN`（默认 20）
- **多 worker 部署失效**：每个 worker 各自计数，N 个 worker → 用户实际可用 N×20 次/分钟
- **后续**：Phase 9 引入 Redis 后改为分布式计数

代码：`app/services/rate_limit.py`

## Key 调度

`pick_active_key(db, provider)` 随机选一个 `is_active=True` 的 key，调用后更新 `last_used_at`。

简单轮换；后续可换加权（按剩余配额 / 错误率）。

## 计费

价格表（元/千 token，公开价）：

| Provider | Model | input | output |
|----------|-------|-------|--------|
| qwen-vl | qwen-vl-plus | 0.008 | 0.008 |
| qwen-vl | qwen-vl-max | 0.020 | 0.020 |
| glm | glm-4v-plus | 0.010 | 0.050 |
| glm | glm-4v-flash | 0.0 | 0.0 |
| doubao | doubao-1.5-vision-pro | 0.003 | 0.003 |

`compute_cost(provider, model, in_tok, out_tok)` → 元。

代码：`app/services/provider_router.py`

## Admin 管理

后台 `/admin/providers` 页面：

- 新建 key（provider + name + 明文 key + base_url 选填）
- 编辑（name / base_url / is_active，**不能改明文 key**）
- 删除
- 测试连通性（用该 key 发最小请求，根据响应状态判断 ok/fail）

> 明文 key **永远不返回给前端**，列表只显示 mask（前 6 + 后 4，中间星号）。

后台 `/admin/usage` 页面：

- 4 个汇总卡片：今日请求数 / 总 tokens / 成本(¥) / 错误数
- 按 provider 拆分表
- 主表：时间 / 用户 / provider / 模型 / tokens / 成本 / 状态 / 延迟 / 错误
- 过滤：用户 / provider / 状态 / 时间范围

## Desktop 客户端切换

设置页 →「模型调用模式」：

- **A 模式 - 直连**：本机填 key，调 provider
- **C 模式 - 云端代理**：用 JWT 调后端 `/api/v1/vision/{provider}/chat/completions`

切换后立即生效，下次跑任务用新 mode。

代码路径：
- `desktop/electron/worker.ts`：spawn 时根据 `cfg.model_mode` 注入不同 env
- `video_worker/__main__.py`：读 `WORKER_MODE` env，传给 `process_job(mode=...)`
- `video_worker/providers/{qwen_vl,glm,doubao}.py`：mode=proxy 时用 `auth_token` 当 key、`proxy_base_url` 当 base_url

## C 模式调用链示例

```
[desktop] AppConfig { model_mode: 'C', session_token: '<JWT>', backend_url: 'http://srv:8000/api/v1' }
  ↓ spawn worker.exe with env:
    WORKER_MODE=proxy
    WORKER_AUTH_TOKEN=<JWT>
    WORKER_PROXY_BASE_URL=http://srv:8000/api/v1/vision/qwen-vl
[video_worker]
  ↓ get_provider('qwen-vl', mode='proxy', auth_token=JWT, proxy_base_url=.../vision/qwen-vl)
  ↓ OpenAI(api_key=JWT, base_url=.../vision/qwen-vl)
  ↓ client.chat.completions.create(...)
  → POST http://srv:8000/api/v1/vision/qwen-vl/chat/completions
[backend]
  ↓ 验 JWT → user
  ↓ 限速 + 选 key + httpx POST → qwen 上游
  ↓ 写 model_usage
  → 透传响应
[video_worker] ← 拿到响应继续分析
```

## 配置项

后端 `.env`：

```bash
JWT_SECRET=<必须固定，不能轮换；轮换则所有 provider_keys 失效>
VISION_PROXY_ENABLED=true          # 默认 true；false 时端点返回 404
VISION_RATE_LIMIT_PER_MIN=20       # 每用户每分钟限速
VISION_UPSTREAM_TIMEOUT_SEC=60     # 上游调用超时
```

## 风险与限制

| 风险 | 说明 |
|------|------|
| 限速进程内 | 多 worker 部署时实际限额 = N × 配置值；Phase 9 换 Redis |
| JWT_SECRET 轮换 | 所有加密 key 解密失败 → admin 重新录入 |
| 上游超时 | 单请求最多 60s 占用；高并发下 worker 池可能耗尽 |
| Provider 不兼容 | 三家都声明 OpenAI 兼容，但 response_format 支持度不同；透传不改写 body |
| Fernet 依赖 | cryptography 库（已是 transitive dep，显式加 requirements） |

## 测试

后端 pytest 已覆盖：

- `test_session_type_isolation` - desktop/web session 共存
- `test_vision_proxy_rejects_unknown_provider` - 404
- `test_vision_proxy_no_active_key` - 503
- `test_vision_proxy_records_usage_and_forwards` - 透传 + 写 usage
- `test_vision_proxy_rate_limited` - 429 + 写 rate_limited usage
- `test_provider_key_crud_and_mask` - CRUD + mask
- `test_model_usage_summary` - summary 聚合

## 后续阶段

- **Phase 9**：Redis 引入 → 限速 + 任务队列复用
- **Phase 10**：模型 prompt/skill 版本管理（动态下发，不重启客户端）
