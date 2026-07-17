#!/bin/sh
# DB 备份服务入口：
#   1. 安装 mariadb-client（提供 mysqldump 和 mysql）+ busybox crond
#   2. 注册 cron 任务（每天 CRON_SCHEDULE 跑 dump）
#   3. 启动时立即跑一次（验证 + 不用等到夜里才有第一份备份）
#   4. crond 前台运行（容器不退出）
set -e

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
CRON_SCHEDULE="${CRON_SCHEDULE:-17 3 * * *}"

echo "[backup] init: schedule='${CRON_SCHEDULE}' retention=${RETENTION_DAYS}d"

# 装 mariadb-client（mysqldump + mysql）
apk add --no-cache mariadb-client mariadb-connector-c > /dev/null

DUMP_CMD="mysqldump -h${MYSQL_HOST} -u${MYSQL_USER} -p${MYSQL_PASSWORD} --single-transaction --routines --triggers --events ${MYSQL_DATABASE} | gzip > /backups/studio_\$(date +%Y%m%d_%H%M%S).sql.gz && find /backups -name 'studio_*.sql.gz' -mtime +${RETENTION_DAYS} -delete && echo \"[backup] done: \$(ls -1 /backups/studio_*.sql.gz | tail -1)\""

# 写 cron 任务
mkdir -p /etc/crontabs
echo "${CRON_SCHEDULE} /bin/sh -c '${DUMP_CMD}'" > /etc/crontabs/root

# 立即跑一次（启动时验证连通性 + 立刻有备份可用）
echo "[backup] running initial backup..."
/bin/sh -c "${DUMP_CMD}" || echo "[backup] initial backup FAILED (will retry on schedule)"

# 列出现有备份
echo "[backup] current backups:"
ls -lh /backups/studio_*.sql.gz 2>/dev/null || echo "  (none)"

# 启动 crond（前台，日志到 stdout）
echo "[backup] starting cron daemon..."
crond -f -l 2
