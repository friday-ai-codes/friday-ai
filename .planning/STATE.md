---
gsd_state_version: 1.0
milestone: v0.2.0
milestone_name: 用户身份令牌与 Agent 工具打通
status: ready_to_plan
stopped_at: Plan 06-02 complete — PAT backend增量 (note + token_suffix) GREEN; 8 backend tests pass, makemigrations --check clean
last_updated: "2026-06-09T13:23:58.472Z"
last_activity: 2026-06-09
progress:
  total_phases: 6
  completed_phases: 3
  total_plans: 6
  completed_plans: 6
  percent: 50
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-09)

**Core value:** 让每个用户用 GitHub/GitLab 风格的个人访问令牌以「用户身份 + 用户权限」安全调用 Friday，并让 skill/mcp 工具以用户身份在容器内真正执行。
**Current focus:** Phase 07 — 令牌即用户身份（认证地基）

## Current Position

Phase: 8
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-09

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 8
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 5 | 1 | - | - |
| 06 | 3 | - | - |
| 07 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 06 P03 | 35 | 3 tasks | 4 files |
| Phase 07 P01 | 12 | 3 tasks | 3 files |
| Phase 07 P02 | 8 | 2 tasks | 2 files |
| Phase 07 P03 | 6 | 1 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work (v0.2.0):

- [Milestone]: 令牌即用户身份——`authenticate()` 返回 owner，施加用户 RBAC，暂不做读写 scope 细分
- [Milestone]: 历史无主会话回填给最早的 superuser（Conversation 无 owner 字段，最稳妥归属）
- [Milestone]: 默认所有人（含管理员）在 AI 对话只看自己；另设只读「管理员会话管理」后台，交互需 fork
- [Milestone]: 用户令牌以直传 PAT 形态注入 task 容器，日志/审计脱敏
- [Milestone]: skill/mcp 以持久绑定表绑定用户令牌；吊销令牌时在途任务 graceful（跑完仅阻断新调用）
- [Roadmap]: 依赖链 6→7→8→9→10→11；Phase 7 单点认证地基全链路前置，MCP 入口同阶段收紧 fail-closed
- [Roadmap]: Conversation.created_by 历史回填是 Phase 8 首个 plan；令牌注入与脱敏必须同阶段（Phase 11）交付，杜绝先接通后补安全
- [Phase ?]: [07-02] PAT auth 返回 owner（token.created_by），request.user 即令牌所有者享其本人 RBAC
- [Phase ?]: [07-02] DEFAULT_AUTHENTICATION_CLASSES PAT 类排首位 + friday_pat_ 前缀闸门 + authenticate_header 保住站点级 401
- [Phase ?]: [07-03] MCP 入口 fail-closed：McpToolView 基类 IsAuthenticated + [AccessToken, CookieJWT]，17 个子类继承；匿名请求 401 authentication_failed

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

None yet.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| verification | Phase 01 人工验收（01-VERIFICATION.md） | human_needed | 2026-06-09 (v0.1.0 close) |
| verification | Phase 02 人工验收（02-VERIFICATION.md） | human_needed | 2026-06-09 (v0.1.0 close) |

## Session Continuity

Last session: 2026-06-09T13:23:42.706Z
Stopped at: Plan 06-02 complete — PAT backend增量 (note + token_suffix) GREEN; 8 backend tests pass, makemigrations --check clean
Resume file: None

## Operator Next Steps

- Plan the first phase with /gsd-plan-phase 6
