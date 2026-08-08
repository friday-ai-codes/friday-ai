#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

# `server/` 置顶守卫（第三方 `workflows` 包遮蔽本项目 app，原因见 friday/path_guard.py）。
# 单一实现在 friday.path_guard，此处显式调用只为「最早时机」——导入 friday 包本身
# 也会触发同一守卫。
from friday.path_guard import ensure_server_dir_first

ensure_server_dir_first()

# django-stubs monkeypatch for type checking
import django_stubs_ext  # noqa: E402 — 必须在 sys.path 守卫之后

django_stubs_ext.monkeypatch()


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
