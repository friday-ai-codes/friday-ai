# 86-03 SUMMARY — IDE 读路径闭环（HOOK-01）

**Plan:** 86-03（Phase 86 IDE 上下文闭环，里程碑 v0.16.0）
**Requirement:** HOOK-01（读路径架构）
**Status:** ✅ Done — 测试全绿，ruff 干净

## 目标回顾

落地 HOOK-01 读路径：三家（Cursor / Claude Code / Codex）各产一条 **always-on 规则**，
强制「先用分支名经 MCP `lookup_project_by_branch` 反查项目 + 召回，再编码」；Claude Code
**额外**用 `UserPromptSubmit` hook 自动把召回 `context` 经 stdout 注入对话（增强）。
Cursor `beforeSubmitPrompt` 不能注入 → 不产注入 hook，只靠规则 + MCP。读路径召回复用
Phase 85 `lookup_project_by_branch`（已写 `RetrievalTrace`），不另起裸召回。

## 交付物

### 新增模块 / 服务

- `server/initiatives/services/ide_hook_assets.py`
  - `build_read_path_assets(project, runtime) -> {"runtime", "files":[{path,filename,content}], "notes"}`
  - `RUNTIME_CURSOR` / `RUNTIME_CLAUDE_CODE` / `RUNTIME_CODEX` 常量 + `RUNTIMES`
  - 内部 helper `_flow_body(project)`：三家共用「先反查 + 召回再编码」正文（复用 cursor_rules 措辞）
  - `_claude_inject_script(project)`：UserPromptSubmit 注入 bash 脚本（读 git 分支 → POST
    `lookup_project_by_branch` → matched 注入 context / 多无命中给候选提示 / 失败静默 `exit 0`）
  - `_claude_settings_snippet()`：`.claude/settings.json` 的 `hooks.UserPromptSubmit` 注册片段
  - **复用** `cursor_rules.build_project_cursor_rules` / `cursor_rules_filename`（Cursor 规则正文，不重造）

### 各 runtime 产出资产

| runtime | files | notes 要点 |
|---------|-------|-----------|
| `cursor` | `.cursor/rules/friday-project-<id>.mdc`（alwaysApply） | beforeSubmitPrompt 不能注入，靠规则 + MCP |
| `claude_code` | `.claude/rules/friday-project-<id>.md` + `.claude/hooks/friday-context-inject.sh` + `.claude/settings.json` | UserPromptSubmit 注入；无 PAT/失败静默跳过 |
| `codex` | `AGENTS.md` 片段 | hook 能力弱，仅 MCP + rules，不产注入 hook |

三家资产正文均含**脱敏告诫**（绝不上报凭证/密钥/token/个人敏感信息）。未知 runtime →
`ValueError`。

### 新增端点 / 路由 / 序列化器

- `server/initiatives/views.py`：`ProjectIdeHookAssetsView(APIView)`
  - `GET /api/projects/<uuid:project_id>/ide-hook-assets/?runtime=cursor|claude_code|codex&kind=read`
  - 读权限对齐项目读口径（`_aget_project_for_read` fail-closed）；无效 runtime → 400
- `server/initiatives/urls.py`：路由 `project-ide-hook-assets`
- `server/initiatives/serializers.py`：`IdeHookAssetsQuerySerializer`（runtime 必填校验，kind 默认 `read`；write 由 86-05 扩展）

### 新增测试

- `server/tests/initiatives/test_ide_hook_assets.py`（14 用例）
  - 服务层：三家资产内容（alwaysApply / lookup / 再编码 / 注入脚本 exit 0 / settings.json 注册 / 脱敏告诫 / 未知 runtime 抛错）
  - 端点：三家 runtime 200、CC 含注入资产、无效 runtime 400、非成员 403、路由 reverse

## 可观测性

- 读路径召回经既有 `lookup_project_by_branch` 写 `RetrievalTrace`（Phase 85，本 plan 复用不另起）。
- 本 plan 无新增 LLM 调用 / call_source；资产下发端点为只读 GET。
- 注入脚本 fail-soft：无 PAT/未配置/接口失败/未命中 → 静默 `exit 0`，绝不阻断编码。

## 测试结果

- `uv run pytest tests/initiatives/test_ide_hook_assets.py -q` → **14 passed**
- `uv run pytest tests/initiatives -q` → **262 passed**（无回归）
- `uv run ruff check`（5 个改动文件）→ **All checks passed**

## LOCKED 决策遵守

- ✅ 读路径 = MCP `lookup_project_by_branch` + always-on 规则（三家通用）
- ✅ CC `UserPromptSubmit` 注入；Cursor 不注入（规则 + MCP），Codex 仅 MCP + rules
- ✅ RetrievalTrace 复用 lookup 工具；复用 cursor_rules，不重造
- ✅ fail-soft（注入脚本静默退出）

## Deferred / 后续

- 写路径 stop hook 资产（`kind=write`）→ 86-05；`IdeHookAssetsQuerySerializer.kind` 已预留。
- Cursor / CC 专用插件主动采集（PROJX-04，v2）。
