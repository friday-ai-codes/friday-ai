#!/bin/bash
set -e
# 等待数据库就绪（使用 Django 自身连接检测）
echo "等待数据库就绪..."
retries=0
max_retries=30
until python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'friday.settings')
import django; django.setup
from django.db import connection
connection.ensure_connection
" 2>/dev/null; do
 retries=$((retries + 1))
 if [ "$retries" -ge "$max_retries" ]; then
 echo "错误: 数据库连接超时（${max_retries} 次重试）"
 exit 1
 fi
 echo "等待数据库就绪... (${retries}/${max_retries})"
 sleep 2
done
echo "数据库已就绪，执行迁移..."
python manage.py migrate --noinput
echo "初始化管理员..."
python manage.py init_superuser
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
