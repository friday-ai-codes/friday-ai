#!/bin/bash
# Friday Task 容器入口脚本
#
# 根据是否传入命令行参数决定运行模式：
# 1. 无参数 -> 容器模式（从环境变量读取配置，运行 runner.py）
# 2. "bash" 或 "sh" -> 进入交互式 shell（调试用）
# 3. 其他参数 -> CLI 模式（运行 friday-task CLI）

set -e

# === 全局环境对齐（容器与 CLI 模式都需要）===
# 1. FRIDAY_TASK_TASK_MODE -> FRIDAY_TASK_MODE 别名：Go Runner 注入的是带两层
#    TASK 前缀的变量，但 git-wrapper.sh 读单层 FRIDAY_TASK_MODE，命名不一致
#    会让 wrapper 在 coding/coding_commit 模式下完全失效。这里统一拉平。
if [ -z "${FRIDAY_TASK_MODE:-}" ] && [ -n "${FRIDAY_TASK_TASK_MODE:-}" ]; then
    export FRIDAY_TASK_MODE="$FRIDAY_TASK_TASK_MODE"
fi

# 2. GitPython 使用 real git，绕过 PATH 中的 wrapper。Runner 自己的
#    commit/push 操作必须能正常落到分支上；只有 Claude 通过 PATH 调 git
#    才会被 wrapper 拦截。
export GIT_PYTHON_GIT_EXECUTABLE=/usr/bin/git

# 3. 无 AVX 的 CPU（常见于 kvm64/qemu64 等默认 CPU 模型的虚拟机）上，
#    claude CLI（Bun 打包的独立二进制）的 JSC JIT 会生成 AVX 指令导致
#    SIGILL 崩溃。禁用 JIT 规避（性能下降但可运行）。见 oven-sh/bun#28755
if ! grep -q ' avx' /proc/cpuinfo 2>/dev/null; then
    export BUN_JSC_useJIT=0
    echo "[Friday Task] CPU lacks AVX, disabling Bun JSC JIT for claude CLI"
fi

if [ $# -eq 0 ]; then
    # 容器模式：无参数，使用环境变量配置
    echo "[Friday Task] Starting in container mode (env vars)"

    # 设置 git wrapper PATH（受限模式 git 写操作拦截，work item）
    WRAPPER_DIR="$(cd "$(dirname "$0")" && pwd)/git_ops"
    if [ -f "$WRAPPER_DIR/git-wrapper.sh" ]; then
        # 创建符号链接使 wrapper 以 "git" 名称出现在 PATH 中
        mkdir -p /tmp/friday-git-wrapper
        ln -sf "$WRAPPER_DIR/git-wrapper.sh" /tmp/friday-git-wrapper/git
        export PATH="/tmp/friday-git-wrapper:$PATH"
        echo "[Friday Task] Git wrapper installed for mode: ${FRIDAY_TASK_MODE:-default}"
    fi

    exec python -m core.runner
elif [ "$1" = "bash" ] || [ "$1" = "sh" ] || [ "$1" = "/bin/bash" ] || [ "$1" = "/bin/sh" ]; then
    # 调试模式：进入交互式 shell
    echo "[Friday Task] Starting interactive shell for debugging"
    exec /bin/bash
else
    # CLI 模式：有参数，转发给 CLI
    echo "[Friday Task] Starting in CLI mode"
    exec friday-task "$@"
fi
