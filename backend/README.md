# Backend - AI Video Studio 控制服务

## 快速开始

### 1. 准备 .env

```bash
cp .env.example .env
# 修改所有 change-me-* 为强密码
```

### 2. Docker Compose 启动

```bash
docker-compose up -d --build
```

### 3. 验证

```bash
curl http://localhost:8000/api/v1/health
# {"ok": true, "db": true}
```

首次启动会自动创建 admin 账号（用 .env 里的 ADMIN_USERNAME/ADMIN_PASSWORD）。

### 4. API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 主要端点

```
POST   /api/v1/auth/login
POST   /api/v1/auth/logout
POST   /api/v1/auth/heartbeat
POST   /api/v1/auth/refresh
GET    /api/v1/auth/me

GET    /api/v1/admin/users            (admin)
POST   /api/v1/admin/users            (admin)
PATCH  /api/v1/admin/users/:id        (admin)
DELETE /api/v1/admin/users/:id        (admin)
POST   /api/v1/admin/users/:id/reset_password  (admin)

GET    /api/v1/admin/releases         (admin)
POST   /api/v1/admin/releases         (admin)
PATCH  /api/v1/admin/releases/:id     (admin)

GET    /api/v1/updates/check?current_version=0.3.0
GET    /api/v1/updates/releases/:version
```

## 部署到 VPS

```bash
# 在 VPS 上
git clone <repo>
cd ai-video-studio/backend
cp .env.example .env  # 修改密码
docker-compose up -d --build

# 配置 nginx + Let's Encrypt 反代 80/443 → 8000
```

## 开发模式（本地 SQLite）

```bash
export DATABASE_URL=sqlite:///./dev.db
uvicorn app.main:app --reload --port 8000
```

## 测试

```bash
pytest tests/ -v
```
