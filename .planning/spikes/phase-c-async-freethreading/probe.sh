#!/usr/bin/env bash
# Phase C spike 复现脚本（只读探测，临时 venv 在 /tmp，不污染主 lock）。
# 用法：bash probe.sh
set -uo pipefail

echo "=== Spike 1: django-async-backend 与生产栈兼容性 ==="
rm -rf /tmp/dab-spike
uv venv /tmp/dab-spike --python 3.14.2 >/dev/null 2>&1
uv pip install --python /tmp/dab-spike \
  "django==6.0.1" "psycopg[binary]>=3,<4" django-async-backend
/tmp/dab-spike/bin/python - <<'PY'
import importlib
for m in ("django_async_backend.db",
          "django_async_backend.db.backends.postgresql",
          "django_async_backend.db.transaction",
          "django_async_backend.middleware"):
    importlib.import_module(m); print("OK", m)
from django_async_backend.db.transaction import async_atomic
from django_async_backend.db import async_connections
print("async_atomic:", callable(async_atomic),
      "| async_connections:", type(async_connections).__name__)
PY

echo
echo "=== Spike 2: free-threading 依赖 wheel 矩阵（cp314t） ==="
rm -rf /tmp/ft-spike
uv venv /tmp/ft-spike --python 3.14.2+freethreaded >/dev/null 2>&1
/tmp/ft-spike/bin/python -c "import sys; print('freethreaded:', not sys._is_gil_enabled())"
for pkg in "psycopg[binary]" tree-sitter tree-sitter-python grpcio onnxruntime \
           numpy "pydantic>=2.6" cryptography bcrypt tokenizers mysqlclient; do
  if uv pip install --python /tmp/ft-spike --only-binary=:all: "$pkg" >/dev/null 2>&1; then
    printf "  OK  %-22s cp314t wheel\n" "$pkg"
  else
    printf "  --  %-22s no cp314t wheel\n" "$pkg"
  fi
done
