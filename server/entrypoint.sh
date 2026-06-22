#!/bin/bash
set -e

# 等待数据库就绪（使用 Django 自身连接检测）
echo "等待数据库就绪..."
retries=0
max_retries=30
until python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'friday.settings')
import django; django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null; do
  retries=$((retries + 1))
  if [ "$retries" -ge "$max_retries" ]; then
    echo "错误: 数据库连接超时（${max_retries} 次重试）"
    exit 1
  fi
  echo "等待数据库就绪... (${retries}/${max_retries})"
  sleep 2
done

# 非 server 角色（worker / scheduler 等）：迁移、系统设置初始化、静态收集统一由 server
# 角色负责（compose 中 worker/scheduler 均 depends_on server healthy，启动时 DB 已迁移）。
# 这些进程只需等 DB 就绪后直接执行自己的命令（compose 经 command 传入），避免多副本
# 并发 migrate 竞争与重复 bootstrap，也不再误跑写死的 gunicorn。
ROLE="${FRIDAY_PROCESS_ROLE:-server}"
if [ "$ROLE" != "server" ] && [ "$#" -gt 0 ]; then
  echo "以角色 ${ROLE} 启动：$*"
  exec "$@"
fi

echo "数据库已就绪，执行迁移..."
python manage.py migrate --noinput

echo "初始化系统设置..."
python manage.py bootstrap_system_settings

# 注意：此处不再自动创建管理员。
# 首次部署的管理员账号改由 Web「首启初始化向导」引导用户自行设置（无 superuser 时首次访问自动进入向导）。
# 之所以移除启动期自动建号：随机密码只会打印在容器日志里，普通用户拿不到、进不去系统。
# 运维兜底（需要命令行手动建/重置管理员时）：
#   docker exec friday-server python manage.py init_superuser            # 可配 FRIDAY_ADMIN_USERNAME / FRIDAY_ADMIN_PASSWORD
#   docker exec friday-server python manage.py reset_superuser_password  # 重置已有 superuser 密码
# 已存在 superuser 的部署不受影响：首启向导门禁 is_initialized 为 true，向导不会出现，行为不回退。

echo "收集静态文件..."
python manage.py collectstatic --noinput

echo "启动 gunicorn..."
exec gunicorn friday.asgi:application \
  --workers "${GUNICORN_WORKERS:-1}" \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --timeout "${GUNICORN_TIMEOUT:-300}"
