#!/usr/bin/env bash
# Phase CI 防回归脚本：禁止 server/chat/ 与 server/workflows/nodes/ai/
# 重新出现硬编码 prompt 字面量。所有新 prompt 必须走 render_prompt(slug, ...)。
#
# 本地用法：
# bash scripts/check_prompt_hardcoding.sh
#
# CI 用法（.github/workflows/ci.yaml server-ci job）：
# - name: Check prompt hardcoding
# run: bash ../scripts/check_prompt_hardcoding.sh
# working-directory: server
#
# 退出码：
# 0 — 通过
# 1 — 发现硬编码（CI 红灯）
# 2 — 脚本环境错误（rg/grep 均不可用）
set -euo pipefail
# 定位仓库根目录（支持从 repo 根或 server/ 目录运行）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVER_DIR="$REPO_ROOT/server"
if [[ ! -d "$SERVER_DIR" ]]; then
 echo "ERROR: server 目录未找到: $SERVER_DIR" >&2
 exit 2
fi
cd "$REPO_ROOT"
# 选择搜索工具（优先 rg，fallback grep -rEn）
if command -v rg >/dev/null 2>&1; then
 search {
 rg --no-heading -n "$1" "${@:2}" 2>/dev/null || true
 }
elif command -v grep >/dev/null 2>&1; then
 search {
 grep -rEn "$1" "${@:2}" 2>/dev/null || true
 }
else
 echo "ERROR: 需要 rg 或 grep 工具" >&2
 exit 2
fi
FAIL=0
# ────────────────────────────────────────────────────────────────
# 检查 1: server/chat/ + server/workflows/nodes/ai/ 下禁止出现
# "你是一位/一名/一个" 等典型中文 prompt 起始（v18.1 G3 防回归）
# ────────────────────────────────────────────────────────────────
echo "==> 检查 1: 角色 prompt 字面量（你是一位/一名/一个）"
ROLE_PATTERN='(你是一位|你是一名|你是一个)'
MATCHES_1=$(search "$ROLE_PATTERN" "server/chat/" "server/workflows/nodes/ai/")
# 白名单（Phase 双轨保留的 fallback 常量定义行 + 边界豁免）:
# 1. server/workflows/nodes/ai/prompt.py 的 config_schema.default "你是一个专业的软件开发助手"
# 2. 原 fallback 常量定义行（属于合法双轨保留，不算调用点硬编码）：
# - TITLE_PROMPT / ROLE_PROMPTS / EXTRACTION_PROMPT_TEMPLATE / REVIEW_SYSTEM_PROMPT
# - _PLAN_GENERATION_BASE_PROMPT / _STRATEGY_DEFAULT / _STRATEGY_DEEP_ANALYSIS
if [[ -n "$MATCHES_1" ]]; then
 FILTERED_1=$(echo "$MATCHES_1" \
 | grep -v 'server/workflows/nodes/ai/prompt\.py:.*你是一个专业的软件开发助手' \
 | grep -v '"你是一名资深开发工程师' \
 | grep -v '"你是一名项目经理' \
 | grep -v '"你是一名设计师' \
 | grep -v '"你是一名 QA' \
 | grep -v '"你是一名全能' \
 | grep -v '"你是一位资深代码审查' \
 | grep -v '"""你是一位资深代码审查' \
 | grep -v '"""你是一位资深技术方案架构师' \
 || true)
 if [[ -n "$FILTERED_1" ]]; then
 echo "❌ 发现未迁移的硬编码 prompt 字面量："
 echo "$FILTERED_1"
 echo ""
 echo "Phase 要求所有 prompt 走 render_prompt(slug, ..., fallback=ORIGINAL_CONST)"
 echo "如果这是合法的 fallback 常量定义行，请扩展本脚本的白名单 grep -v 链"
 FAIL=1
 fi
fi
# ────────────────────────────────────────────────────────────────
# 检查 2: 禁止 system_prompt = "..." / system_prompt = f"..." 硬编码赋值
# ────────────────────────────────────────────────────────────────
echo "==> 检查 2: system_prompt = [\"f]... 硬编码赋值"
SP_PATTERN='system_prompt\s*=\s*(["f])'
MATCHES_2=$(search "$SP_PATTERN" "server/chat/" "server/workflows/nodes/ai/" "server/agents/")
# 白名单路径 + fallback 参数 + 预渲染变量赋值
ALLOWED_PATHS='(server/tests/|server/test_claude_agent_sdk\.py|server/tasks/agent_tasks\.py)'
if [[ -n "$MATCHES_2" ]]; then
 FILTERED_2=$(echo "$MATCHES_2" \
 | grep -Ev "$ALLOWED_PATHS" \
 | grep -v 'fallback=.*PROMPT' \
 | grep -v 'system_prompt=rendered_system_prompt' \
 | grep -v 'system_prompt=enhanced_prompt' \
 | grep -v 'system_prompt=system_prompt' \
 | grep -v 'system_prompt=await _build_system_prompt' \
 | grep -v 'system_prompt=self\._precomputed' \
 || true)
 if [[ -n "$FILTERED_2" ]]; then
 echo "❌ 发现 system_prompt 硬编码赋值："
 echo "$FILTERED_2"
 echo ""
 echo "system_prompt 必须由 render_prompt(slug, ..., fallback=ORIGINAL_CONST) 返回值提供"
 FAIL=1
 fi
fi
# ────────────────────────────────────────────────────────────────
# 结果
# ────────────────────────────────────────────────────────────────
if [[ $FAIL -eq 0 ]]; then
 echo ""
 echo "✓ check_prompt_hardcoding passed — no hardcoded prompts detected"
 exit 0
else
 echo ""
 echo "❌ check_prompt_hardcoding FAILED — 上列位置需迁移到 Prompt Center（Phase）"
 exit 1
fi
