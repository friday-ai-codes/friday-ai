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
    "build_write_path_assets",
]

RUNTIME_CURSOR = "cursor"
RUNTIME_CLAUDE_CODE = "claude_code"
RUNTIME_CODEX = "codex"
RUNTIMES = (RUNTIME_CURSOR, RUNTIME_CLAUDE_CODE, RUNTIME_CODEX)

# 读路径反查工具的 REST 入口（CC 注入脚本据此调用；与 mcp_tools.urls 路由一致）。
_LOOKUP_TOOL_PATH = "/api/mcp/tools/lookup_project_by_branch/"

# 写路径回写工具的 REST 入口（stop hook 脚本据此调用；与 mcp_tools.urls 路由一致）。
_REPORT_KNOWLEDGE_TOOL_PATH = "/api/mcp/tools/report_project_knowledge/"
_REPORT_STATE_TOOL_PATH = "/api/mcp/tools/report_project_state/"

# 脱敏告诫（三家资产正文通用，绝不可绕过）。
_REDACTION_NOTICE = (
    "绝不上报 / 打印任何凭证、密钥、token、个人敏感信息；"
    "上下文召回与写回均按项目成员权限校验，非成员不会得到上下文。"
)

# 写路径三道兜底告诫（accepted deviation 配套：active 直写的安全由服务端兜住）。
_SERVER_SAFEGUARDS_NOTICE = (
    "active 直写生效的防污染由 Friday 服务端三道兜底保证："
    "① 质量门槛过滤（低质 / 空 / 重复内容不写）；"
    "② 脱敏不可绕过（入库前强制 redact_secrets_in_text / redact_for_ledger）；"
    "③ 审计可回滚（每次自动写入留审计、可撤销）。客户端 stop hook 只是触发器。"
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


# ============================ 写路径（HOOK-02/03，stop hook 资产）============================


def _stop_writeback_script(project: Any, runtime: str) -> str:
    """三家通用的 stop hook 写回脚本（active 写回 MEMORY + STATE 结构化回写）。

    **默认开启 + 静默**：会话结束自动收集「本次上下文 + 改动摘要」直写项目记忆
    （``report_project_knowledge(writeback_mode="active")``）、把新增/改动 API 结构化清单
    回写 STATE（``report_project_state``）。

    fail-soft / 绝不阻断：无 PAT / 未绑项目 / 接口非 2xx / 任何异常 → 静默 ``exit 0``，
    既不弹窗也不阻断 IDE 编码。脚本不内嵌任何密钥（PAT 经环境变量传入）。
    """
    _name, project_id, _feishu_key, _space_name = _project_fields(project)
    return f"""#!/usr/bin/env bash
# Friday 写路径 stop hook（{runtime}，项目 {project_id}）。
#
# 行为（默认开启 + 静默回写）：IDE 会话结束时自动——
#   1) 收集本次「上下文 + 用户改动摘要」→ 调 Friday MCP `report_project_knowledge`
#      （writeback_mode=active）直写项目记忆 MEMORY；
#   2) 把新增 / 改动 API 的结构化清单 → 调 `report_project_state` 回写 STATE。
#
# 安全（三道兜底由 Friday 服务端保证，accepted deviation 配套）：
#   {_SERVER_SAFEGUARDS_NOTICE}
# 脱敏：{_REDACTION_NOTICE}
#       脚本只提交 git 改动摘要，绝不拼接 / 上报凭证、密钥、token、个人敏感信息。
# 静默不阻断：无 PAT / 未绑项目 / 接口非 2xx / 任何异常 → 静默 exit 0，绝不 block 编码。
#
# 所需环境变量：
#   FRIDAY_API_URL          Friday 后端基址，如 https://friday.example.com
#   FRIDAY_PAT              你的个人访问令牌（PAT）；脚本不内嵌任何密钥
#   FRIDAY_PROJECT_ID       目标项目 ID（缺省取本脚本内置值）
#   FRIDAY_STATE_APIS_FILE  可选；新增/改动 API 结构化清单 JSON 文件（数组，每项
#                           {{method, path, params?, status?}}），无文件则跳过 STATE 回写
#   FRIDAY_STOP_WRITEBACK   可选；设为 0 临时关闭本 hook（默认开启）
set -u

FRIDAY_API_URL="${{FRIDAY_API_URL:-}}"
FRIDAY_PAT="${{FRIDAY_PAT:-}}"
FRIDAY_PROJECT_ID="${{FRIDAY_PROJECT_ID:-{project_id}}}"
FRIDAY_STATE_APIS_FILE="${{FRIDAY_STATE_APIS_FILE:-}}"

# 默认开启；如需临时关闭：export FRIDAY_STOP_WRITEBACK=0
if [ "${{FRIDAY_STOP_WRITEBACK:-1}}" = "0" ]; then
  exit 0
fi

# 缺少必要配置（无 PAT / 未绑项目）→ 静默退出，不回写、不阻断编码。
if [ -z "$FRIDAY_API_URL" ] || [ -z "$FRIDAY_PAT" ] || [ -z "$FRIDAY_PROJECT_ID" ]; then
  exit 0
fi

# 收集本次改动摘要（best-effort；非 git 仓库 / 无改动均不致命）。
changes="$(git -c core.quotepath=false diff --stat HEAD 2>/dev/null | tail -n 80)"
recent="$(git log -n 5 --pretty=format:'- %s' 2>/dev/null)"

content="$(CHANGES="$changes" RECENT="$recent" python3 - <<'PY'
import os
changes = os.environ.get("CHANGES", "").strip()
recent = os.environ.get("RECENT", "").strip()
parts = ["本次会话改动摘要（Friday stop hook 自动沉淀）："]
if recent:
    parts.append("最近提交：")
    parts.append(recent)
if changes:
    parts.append("文件改动：")
    parts.append(changes)
# 仅有标题、无实际改动 → 输出空串，交给服务端质量门槛 / 此处静默跳过避免空写。
print("\\n".join(parts) if (recent or changes) else "")
PY
)" || exit 0

# 1) active 直写项目记忆（MEMORY）。安全由服务端三道兜底兜住（质量门槛 + 脱敏 + 审计回滚）。
if [ -n "$(printf '%s' "$content" | tr -d '[:space:]')" ]; then
  payload_k="$(PID="$FRIDAY_PROJECT_ID" CONTENT="$content" python3 - <<'PY'
import json, os
print(json.dumps({{
    "project_id": os.environ.get("PID", ""),
    "content": os.environ.get("CONTENT", ""),
    "writeback_mode": "active",
    "target": "memory",
}}))
PY
)" || payload_k=""
  if [ -n "$payload_k" ]; then
    curl -sS -m 20 -o /dev/null \\
      -X POST "${{FRIDAY_API_URL%/}}{_REPORT_KNOWLEDGE_TOOL_PATH}" \\
      -H "Authorization: Bearer ${{FRIDAY_PAT}}" \\
      -H "Content-Type: application/json" \\
      -d "$payload_k" >/dev/null 2>&1 || true
  fi
fi

# 2) STATE 结构化 API 清单回写（HOOK-03）。新增/改动 API 由 $FRIDAY_STATE_APIS_FILE 提供
#    （JSON 数组，每项 {{method, path, params?, status?}}）；无文件 → 跳过，绝不阻断。
if [ -n "$FRIDAY_STATE_APIS_FILE" ] && [ -f "$FRIDAY_STATE_APIS_FILE" ]; then
  payload_s="$(PID="$FRIDAY_PROJECT_ID" APIS_FILE="$FRIDAY_STATE_APIS_FILE" python3 - <<'PY'
import json, os, sys
try:
    with open(os.environ["APIS_FILE"], encoding="utf-8") as fh:
        apis = json.load(fh)
except Exception:
    sys.exit(1)
if not isinstance(apis, list) or not apis:
    sys.exit(1)
print(json.dumps({{"project_id": os.environ.get("PID", ""), "apis": apis}}))
PY
)" && [ -n "$payload_s" ] && \\
    curl -sS -m 20 -o /dev/null \\
      -X POST "${{FRIDAY_API_URL%/}}{_REPORT_STATE_TOOL_PATH}" \\
      -H "Authorization: Bearer ${{FRIDAY_PAT}}" \\
      -H "Content-Type: application/json" \\
      -d "$payload_s" >/dev/null 2>&1 || true
fi

# 无论成功与否：静默 exit 0，绝不阻断 IDE 编码。
exit 0
"""


def _cursor_stop_hooks_snippet() -> str:
    """``.cursor/hooks.json`` 的 ``stop`` 钩子注册片段。"""
    return """{
  "version": 1,
  "hooks": {
    "stop": [
      {
        "command": "bash .cursor/hooks/friday-stop-writeback.sh"
      }
    ]
  }
}
"""


def _claude_stop_settings_snippet() -> str:
    """``.claude/settings.json`` 的 ``hooks.Stop`` 注册片段。"""
    return """{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/friday-stop-writeback.sh"
          }
        ]
      }
    ]
  }
}
"""


def build_write_path_assets(project: Any, runtime: str) -> dict[str, Any]:
    """生成指定 runtime 的写路径 stop hook 资产 bundle（HOOK-02/03）。

    会话结束**默认开启 + 静默回写**：调 86-01 ``report_project_knowledge``
    （``writeback_mode=active``）直写 MEMORY/RESEARCH + 调 86-04 ``report_project_state``
    回写结构化 API 清单（STATE）。stop hook **不弹窗、不阻断编码**；无 PAT / 未绑项目 /
    接口失败 → 静默 ``exit 0``。实际写入安全由服务端三道兜底（质量门槛 / 脱敏 / 审计回滚）保证。

    Args:
        project: ``initiatives.Project`` 实例（建议已 ``select_related("space")``）。
        runtime: ``cursor`` / ``claude_code`` / ``codex`` 之一。

    Returns:
        ``{"runtime", "kind": "write", "files": [{"path", "filename", "content"}], "notes"}``，
        供前端「复制 / 下载」。

    Raises:
        ValueError: 未知 runtime。
    """
    script = _stop_writeback_script(project, runtime)

    if runtime == RUNTIME_CURSOR:
        return {
            "runtime": RUNTIME_CURSOR,
            "kind": "write",
            "files": [
                {
                    "path": ".cursor/hooks.json",
                    "filename": "hooks.json",
                    "content": _cursor_stop_hooks_snippet(),
                },
                {
                    "path": ".cursor/hooks/friday-stop-writeback.sh",
                    "filename": "friday-stop-writeback.sh",
                    "content": script,
                },
            ],
            "notes": (
                "Cursor 写路径 = `.cursor/hooks.json` 注册 `stop` 钩子 + stop 脚本，会话结束"
                "默认开启 + 静默回写（active 直写 MEMORY + STATE 回写）。脚本需配置环境变量 "
                "`FRIDAY_API_URL` / `FRIDAY_PAT`（可选 `FRIDAY_STATE_APIS_FILE` 提供结构化 API "
                "清单）；无 PAT / 未绑项目 / 接口失败均静默 exit 0，绝不弹窗或阻断编码。"
                + _SERVER_SAFEGUARDS_NOTICE
            ),
        }

    if runtime == RUNTIME_CLAUDE_CODE:
        return {
            "runtime": RUNTIME_CLAUDE_CODE,
            "kind": "write",
            "files": [
                {
                    "path": ".claude/settings.json",
                    "filename": "settings.json",
                    "content": _claude_stop_settings_snippet(),
                },
                {
                    "path": ".claude/hooks/friday-stop-writeback.sh",
                    "filename": "friday-stop-writeback.sh",
                    "content": script,
                },
            ],
            "notes": (
                "Claude Code 写路径 = `.claude/settings.json` 注册 `Stop` hook + 同款 stop "
                "脚本，会话结束默认开启 + 静默回写（active 直写 MEMORY + STATE 回写）。若已有"
                "读路径 `UserPromptSubmit` 注册，请把 `Stop` 合并进同一 `settings.json` 的 "
                "`hooks`。无 PAT / 未绑项目 / 接口失败均静默 exit 0，绝不阻断编码。"
                + _SERVER_SAFEGUARDS_NOTICE
            ),
        }

    if runtime == RUNTIME_CODEX:
        return {
            "runtime": RUNTIME_CODEX,
            "kind": "write",
            "files": [
                {
                    "path": "scripts/friday-stop-writeback.sh",
                    "filename": "friday-stop-writeback.sh",
                    "content": script,
                }
            ],
            "notes": (
                "Codex 原生 hook 注入 / 回写能力弱，按「仅 MCP + rules」对待：写路径不产自动 "
                "stop hook，仅提供**可手动执行 / CI 兜底**的回写脚本（会话结束或 CI 阶段手动 "
                "`bash scripts/friday-stop-writeback.sh` 触发 active 直写 + STATE 回写）。"
                "脚本行为与三家一致：无 PAT / 未绑项目 / 接口失败均静默 exit 0，绝不阻断编码。"
                + _SERVER_SAFEGUARDS_NOTICE
            ),
        }

    raise ValueError(
        f"未知 runtime：{runtime!r}（支持：{', '.join(RUNTIMES)}）"
    )
