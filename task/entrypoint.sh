#!/bin/bash
# Friday Task 容器入口脚本
#
# 根据是否传入命令行参数决定运行模式：
# 1. 无参数 -> 容器模式（从环境变量读取配置，运行 runner.py）
# 2. "bash" 或 "sh" -> 进入交互式 shell（调试用）
# 3. 其他参数 -> CLI 模式（运行 friday-task CLI）
set -e
if [ $# -eq 0 ]; then
 # 容器模式：无参数，使用环境变量配置
 echo "[Friday Task] Starting in container mode (env vars)"
 exec python -m friday_task.runner
elif [ "$1" = "bash" ] || [ "$1" = "sh" ] || [ "$1" = "/bin/bash" ] || [ "$1" = "/bin/sh" ]; then
 # 调试模式：进入交互式 shell
 echo "[Friday Task] Starting interactive shell for debugging"
 exec /bin/bash
else
 # CLI 模式：有参数，转发给 CLI
 echo "[Friday Task] Starting in CLI mode"
 exec friday-task "$@"
fi
