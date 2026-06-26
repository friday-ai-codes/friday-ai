# Phase 86: IDE 上下文闭环（hooks） - Context

**Gathered:** 2026-06-26
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous) — 用户逐 Wave 选定

<domain>
## Phase Boundary

打通 Cursor/Claude Code/Codex 在某分支开发时自动拉项目上下文、会话结束回写沉淀的双向闭环。读路径走 MCP 注入工具 + always-on rule（三家通）+ Claude Code UserPromptSubmit 增强；写路径 stop hook → report 写回 + STATE 结构化回写；claude code runner 派发带上下文 + session 持久化（SessionStore→Redis）支持跨容器 resume。

交付需求：HOOK-01~04。
</domain>

<decisions>
## Implementation Decisions

### 读路径（HOOK-01，锁定架构）
- 主走 MCP 工具 `lookup_project_by_branch`（Phase 85 扩多分支）+ 一条 always-on Cursor/Claude Code/Codex rule（强制"先反查项目+召回再编码"）——三家全通。
- Claude Code 额外用 `UserPromptSubmit` 自动注入做增强。
- Cursor `beforeSubmitPrompt` 不能注入上下文 → 不押注入在 Cursor hook 上。
- 新增召回（MCP 反查注入、hook 注入）写 `RetrievalTrace`。

### 写路径 stop hook 行为（用户授权的范围变更）
- **stop hook 默认开启 + 静默回写**：会话结束不弹窗、不阻断 IDE 编码。
- **⚠️ 范围变更（用户 2026-06-26 明确授权）**：用户选择"真·全自动直写生效（active）无需任何确认"，**覆盖** REQUIREMENTS HOOK-02「MEMORY/RESEARCH 落 draft 人工确认」与 Out-of-Scope「记忆全自动写入无人确认本期不做」。
  - **落地**：stop hook 组织上下文+用户改动 → `report_project_knowledge` **直接写 active**（MEMORY/RESEARCH），不经 draft 人工确认环节。
  - **防污染兜底（必须保留，绝不绕过）**：质量门槛过滤（低质/空内容不写）+ 归因（resolve_feishu_user，未映射 system）+ **脱敏不可绕过**（redact_secrets_in_text / redact_for_ledger）+ 审计可回滚（每次自动写入留审计、可撤销）。
  - hook 无 PAT / 未绑项目 → 静默跳过，绝不阻断编码。
- **note for verify**：此为 INV/Out-of-Scope 偏离，VERIFICATION 须记为"用户授权的 accepted deviation"，并确认脱敏/归因/审计回滚三道兜底齐备。

### STATE 结构化回写（HOOK-03）
- **直写 + 审计可回滚**：会话结束把新增/改动 API 以结构化清单（method/path/params/status）直接写入 `ProjectStateApi`，跨会话/跨角色（前后端）即时可读，带审计可回滚（不走 draft）。

### runner 派发 + session 持久化（HOOK-04，锁定）
- claude code runner 派发带项目上下文。
- session 持久化用 SessionStore→Redis（session JSONL 本地态跨容器不共享，必须镜像）支持冷启动/跨容器 resume；cwd 须一致。
- 复用 v0.8 callback resume + v0.12 durable。

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/mcp_tools/`：MCP 工具注入 + `report_project_knowledge` 写回入口。
- `server/initiatives/services/cursor_rules.py`：cursor_rules API（always-on rule 下发）。
- `server/initiatives/services/memory_service.py`：记忆写入收口（本期增"自动 active"分支 + 质量门槛 + 脱敏 + 审计）。
- `server/initiatives/models`（Phase 82）：`ProjectStateApi` 结构化回写目标。
- `server/resumable/`(durable) + `task/`(claude-agent-sdk runner)：runner 派发 + SessionStore。
- `server/common/logging.py`：脱敏；`server/audit` / AuditService：审计可回滚。
- `server/services/feishu.py::resolve_feishu_user`：归因。

### Established Patterns
- 容器 resume：callback 驱动 + 幂等 + fail-soft（v0.8/v0.12）。
- 写入收口 service（INV-6）；后台任务带 initiated_by_user_id。
- 审计 emit 唯一入口 + 强制脱敏 + append-only（v0.10.0）。

### Integration Points
- 读路径 MCP 依赖 Phase 85 `lookup_project_by_branch` 多分支。
- 写路径写 `ProjectStateApi`(Phase 82) + `ProjectMemory`(active 直写)。

</code_context>

<specifics>
## Specific Ideas

- 用户明确"我希望就静默回写了"+"真·全自动直写生效（active）"——这是经确认的 accepted deviation，三道兜底（质量门槛/脱敏/审计回滚）不可省。

</specifics>

<deferred>
## Deferred Ideas

- Cursor/Claude Code 专用插件主动行为采集（PROJX-04，v2）。
- Codex 原生 hook 注入上下文（能力弱，按仅 MCP+rules 对待）。

</deferred>

<canonical_refs>
## Canonical References

- `.planning/project-workspace/MILESTONE-PROPOSAL.md` — §7 IDE 闭环（三家差异 + 正确架构）、§10 调研结论（Cursor hooks/容器 resume）
- `.planning/REQUIREMENTS.md` — HOOK-01~04 + Out-of-Scope（记忆全自动写入——本 phase 经用户授权偏离）
- `.planning/ROADMAP.md` — Phase 86 Success Criteria
- `.cursor/rules/observability-logging.mdc` — 脱敏/归因/审计强制项（自动写入兜底依据）

</canonical_refs>
