"""IDE 读路径 hook 资产生成（HOOK-01，三家 always-on 规则 + Claude Code 注入）。

落地 Phase 86 读路径架构：

- **三家通用**（Cursor / Claude Code / Codex）：各产一条 **always-on 规则**，强制
  「先用当前 git 分支名经 MCP ``lookup_project_by_branch`` 反查所属 Friday 项目 + 召回
  需求/工件/记忆上下文，再编码」——读路径主链。
- **Claude Code 额外**：``UserPromptSubmit`` 注入 hook 资产（脚本 + ``settings.json``
  注册片段），自动调 ``lookup_project_by_branch`` 并把召回 ``context`` 经 **stdout** 注入
  当前对话（增强）。无 PAT / 未配置 / 接口失败 / 未命中 → **静默 exit 0**，绝不阻断编码。
- **Cursor**：``beforeSubmitPrompt`` 只能放行/拦截、**不能注入上下文** → **不产注入
  hook**，读路径只靠 always-on 规则 + MCP（资产 ``notes`` 显式声明此限制）。
- **Codex**：hook 能力弱，按「仅 MCP + rules」对待，只产规则、不产注入 hook。

读路径召回复用 Phase 85 ``lookup_project_by_branch``（已写 ``RetrievalTrace`` + 单/多/无
命中 fail-soft），本模块不另起裸召回。

纯文本生成、无 IO（项目对象由调用方传入），可单测。
"""

from __future__ import annotations

from typing import Any

from initiatives.services.cursor_rules import (
    build_project_cursor_rules,
    cursor_rules_filename,
)

__all__ = [
    "RUNTIME_CLAUDE_CODE",
    "RUNTIME_CODEX",
    "RUNTIME_CURSOR",
    "RUNTIMES",
    "build_read_path_assets",
]

RUNTIME_CURSOR = "cursor"
RUNTIME_CLAUDE_CODE = "claude_code"
RUNTIME_CODEX = "codex"
RUNTIMES = (RUNTIME_CURSOR, RUNTIME_CLAUDE_CODE, RUNTIME_CODEX)

# 读路径反查工具的 REST 入口（CC 注入脚本据此调用；与 mcp_tools.urls 路由一致）。
_LOOKUP_TOOL_PATH = "/api/mcp/tools/lookup_project_by_branch/"

# 脱敏告诫（三家资产正文通用，绝不可绕过）。
_REDACTION_NOTICE = (
    "绝不上报 / 打印任何凭证、密钥、token、个人敏感信息；"
    "上下文召回与写回均按项目成员权限校验，非成员不会得到上下文。"
)


def _project_fields(project: Any) -> tuple[str, str, str, str]:
    """提取项目展示字段（fail-soft，未预取 space 不致命）。"""
    name = getattr(project, "name", "") or "（未命名项目）"
    project_id = str(getattr(project, "id", ""))
    feishu_key = getattr(project, "feishu_project_key", "") or ""
    space_name = ""
    try:
        space_name = getattr(getattr(project, "space", None), "name", "") or ""
    except Exception:  # noqa: BLE001 — space 未预取时不致命
        space_name = ""
    return name, project_id, feishu_key, space_name


def _flow_body(project: Any) -> str:
    """三家共用的「先反查 + 召回再编码」强制流程正文（无 frontmatter）。

    复用 ``cursor_rules`` 的措辞（先关联本分支项目 → 召回 → 再编码 → 完成后上报沉淀），
    供 Claude Code ``CLAUDE.md`` 规则片段与 Codex ``AGENTS.md`` 片段复用。
    """
    name, project_id, feishu_key, space_name = _project_fields(project)
    feishu_line = (
        f"- 飞书项目标识：`{feishu_key}`" if feishu_key else "- 飞书项目标识：（未关联）"
    )
    space_line = f"- 所属空间：{space_name}" if space_name else "- 所属空间：（未知）"

    return f"""# Friday 项目上下文规则：{name}

本规则确保在该项目相关分支上编码时，**先加载项目的完整交付上下文（需求 / 工件 / 记忆），
再动手写代码**。

## 项目信息

- 项目名称：{name}
- 项目 ID：`{project_id}`
{space_line}
{feishu_line}

## 强制流程（每次开始编码任务前）

1. **先关联本分支项目**：用当前 git 分支名调用 Friday MCP 工具
   `lookup_project_by_branch(branch_name=<当前分支名>)`。
   - 分支命名约定 `feat/xxxx-m{{work_item_id}}-slug`，工具据此反查所属 Friday 项目并召回
     需求 / 工件 / 记忆上下文。
   - 若 `matched=true`，**必须先阅读返回的 `context`**，把它作为本次编码的事实依据。
   - 若 `matched=false`（多 / 无命中），结合返回的 `candidates` 人工确认项目，不要在缺乏
     上下文的情况下臆测实现。
2. **再编码**：在已加载的项目上下文约束下设计与实现，遵守项目记忆中已记录的方案决策、
   约束与历史教训；不要与既有记忆 / 需求矛盾。
3. **完成后上报沉淀**：把本次产生的、对团队有价值的方案决策 / 经验教训，经 MCP 工具
   `report_project_knowledge(project_id="{project_id}", content=<提炼后的沉淀>)` 上报。

## 约束

- 上述 MCP 工具需以你的 Friday 个人访问令牌（PAT）鉴权。
- {_REDACTION_NOTICE}
- 本规则只约束「先召回、再编码、后沉淀」的流程，不替代仓库内其他工程规范。
"""


def _claude_inject_script(project: Any) -> str:
    """Claude Code ``UserPromptSubmit`` 注入脚本（读 git 分支 → lookup → stdout 注入）。

    fail-soft：无 PAT / 未配置 API / curl 失败 / 解析失败 / 未命中 → 静默 ``exit 0``，
    既不注入也不阻断编码。脚本不内嵌任何密钥（PAT 经环境变量传入）。
    """
    _name, project_id, _feishu_key, _space_name = _project_fields(project)
    return f"""#!/usr/bin/env bash
# Friday 读路径上下文注入 hook（Claude Code UserPromptSubmit，项目 {project_id}）。
#
# 行为：读取当前 git 分支名 → 调 Friday MCP `lookup_project_by_branch` →
#       把召回 context 经 stdout 注入当前对话。
# fail-soft：无 PAT / 未配置 API / 接口失败 / 解析失败 / 未命中 → 静默 exit 0，
#            既不注入也不阻断编码。
# 安全：{_REDACTION_NOTICE}
#
# 所需环境变量：
#   FRIDAY_API_URL        Friday 后端基址，如 https://friday.example.com
#   FRIDAY_PAT            你的个人访问令牌（PAT）；脚本不内嵌任何密钥
#   FRIDAY_REPOSITORY_ID  可选；跨仓同名分支时用于收窄定位
set -u

FRIDAY_API_URL="${{FRIDAY_API_URL:-}}"
FRIDAY_PAT="${{FRIDAY_PAT:-}}"
FRIDAY_REPOSITORY_ID="${{FRIDAY_REPOSITORY_ID:-}}"

# 缺少必要配置 → 静默退出，不注入、不阻断。
if [ -z "$FRIDAY_API_URL" ] || [ -z "$FRIDAY_PAT" ]; then
  exit 0
fi

branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" || exit 0
[ -z "$branch" ] && exit 0

payload="$(BRANCH="$branch" REPO="$FRIDAY_REPOSITORY_ID" python3 - <<'PY'
import json, os
data = {{"branch_name": os.environ.get("BRANCH", "")}}
repo = os.environ.get("REPO", "")
if repo:
    data["repository_id"] = repo
print(json.dumps(data))
PY
)" || exit 0

resp="$(curl -sS -m 15 \\
  -X POST "${{FRIDAY_API_URL%/}}{_LOOKUP_TOOL_PATH}" \\
  -H "Authorization: Bearer ${{FRIDAY_PAT}}" \\
  -H "Content-Type: application/json" \\
  -d "$payload" 2>/dev/null)" || exit 0
[ -z "$resp" ] && exit 0

# 解析响应：matched=true 注入 context；多/无命中给候选提示；任何异常静默退出。
RESP="$resp" python3 - <<'PY'
import json, os, sys

try:
    data = json.loads(os.environ.get("RESP", ""))
except Exception:
    sys.exit(0)
if not isinstance(data, dict):
    sys.exit(0)

context = data.get("context") or ""
if data.get("matched") and context:
    print("# Friday 项目上下文（读路径自动注入）")
    proj = data.get("project") or {{}}
    name = proj.get("name") if isinstance(proj, dict) else ""
    if name:
        print(f"当前分支关联 Friday 项目：{{name}}")
    print()
    print(context)
    sys.exit(0)

candidates = data.get("candidates") or []
names = [str(c.get("name", "")) for c in candidates if isinstance(c, dict) and c.get("name")]
if names:
    print("# Friday 读路径提示")
    print(
        "当前分支未唯一命中项目，候选：" + "、".join(names) +
        "。请先用 lookup_project_by_branch 确认项目后再编码。"
    )
sys.exit(0)
PY
exit 0
"""


def _claude_settings_snippet() -> str:
    """``.claude/settings.json`` 的 ``hooks.UserPromptSubmit`` 注册片段。"""
    return """{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/friday-context-inject.sh"
          }
        ]
      }
    ]
  }
}
"""


def build_read_path_assets(project: Any, runtime: str) -> dict[str, Any]:
    """生成指定 runtime 的读路径资产 bundle（HOOK-01）。

    Args:
        project: ``initiatives.Project`` 实例（建议已 ``select_related("space")``）。
        runtime: ``cursor`` / ``claude_code`` / ``codex`` 之一。

    Returns:
        ``{"runtime", "files": [{"path", "filename", "content"}], "notes"}``，
        供前端「复制 / 下载」。

    Raises:
        ValueError: 未知 runtime。
    """
    project_id = str(getattr(project, "id", ""))

    if runtime == RUNTIME_CURSOR:
        filename = cursor_rules_filename(project)
        return {
            "runtime": RUNTIME_CURSOR,
            "files": [
                {
                    "path": f".cursor/rules/{filename}",
                    "filename": filename,
                    "content": build_project_cursor_rules(project),
                }
            ],
            "notes": (
                "Cursor `beforeSubmitPrompt` 只能放行 / 拦截、不能注入上下文，"
                "因此 Cursor 读路径不产注入 hook，只靠本 always-on 规则（alwaysApply）+ "
                "MCP `lookup_project_by_branch` 反查 + 召回。"
            ),
        }

    if runtime == RUNTIME_CLAUDE_CODE:
        rule_filename = f"friday-project-{project_id}.md"
        return {
            "runtime": RUNTIME_CLAUDE_CODE,
            "files": [
                {
                    "path": f".claude/rules/{rule_filename}",
                    "filename": rule_filename,
                    "content": _flow_body(project),
                },
                {
                    "path": ".claude/hooks/friday-context-inject.sh",
                    "filename": "friday-context-inject.sh",
                    "content": _claude_inject_script(project),
                },
                {
                    "path": ".claude/settings.json",
                    "filename": "settings.json",
                    "content": _claude_settings_snippet(),
                },
            ],
            "notes": (
                "Claude Code 读路径 = always-on 规则（`.claude/rules/`）+ MCP "
                "`lookup_project_by_branch`，并额外用 `UserPromptSubmit` hook 自动把召回 "
                "context 经 stdout 注入对话。注入脚本需配置环境变量 `FRIDAY_API_URL` / "
                "`FRIDAY_PAT`；无 PAT / 未配置 / 接口失败 / 未命中均静默跳过，绝不阻断编码。"
            ),
        }

    if runtime == RUNTIME_CODEX:
        rule_filename = f"friday-project-{project_id}.AGENTS.md"
        return {
            "runtime": RUNTIME_CODEX,
            "files": [
                {
                    "path": "AGENTS.md",
                    "filename": rule_filename,
                    "content": _flow_body(project),
                }
            ],
            "notes": (
                "Codex hook 能力弱，按「仅 MCP + rules」对待：只产 always-on 规则"
                "（合并进 `AGENTS.md`）+ MCP `lookup_project_by_branch`，不产注入 hook。"
            ),
        }

    raise ValueError(
        f"未知 runtime：{runtime!r}（支持：{', '.join(RUNTIMES)}）"
    )
