# === Stage 1: 构建 admin UI（React → 静态文件） ===
FROM node:20-alpine AS ui-build
WORKDIR /ui
COPY admin-ui/package*.json ./
RUN npm ci --no-audit --no-fund
COPY admin-ui/ ./
RUN npm run build  # 输出到 /ui/dist

# === Stage 2: Python 后端 ===
FROM python:3.12-slim

WORKDIR /app

# 系统依赖（argon2/cryptography 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 拷贝 admin UI 构建产物
COPY --from=ui-build /ui/dist /app/admin-ui

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
