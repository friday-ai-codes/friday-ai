"""Module entry point for friday_task.

支持两种入口方式：
1. python -m friday_task        - CLI 模式（推荐）
2. python -m core.runner        - 容器模式（环境变量配置）
"""

from cli import main

if __name__ == "__main__":
    main()
