#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

# 确保项目根（server/）在 sys.path 最前：site-packages 里存在第三方 `workflows`
# 包（llama-index-workflows）与本项目的 `workflows` app 同名，若 server/ 不在最前会
# 被其遮蔽，导致 `workflows.schemas` 等子模块 ModuleNotFoundError。显式置顶以防御任意
# 启动方式（脚本 / 非 server 工作目录调用）下的包名冲突。
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.path and sys.path[0] != _SERVER_DIR:
    sys.path.insert(0, _SERVER_DIR)

# django-stubs monkeypatch for type checking
import django_stubs_ext

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
