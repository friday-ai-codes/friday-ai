---
gsd_state_version: 1.0
milestone: v0.2.0
milestone_name: 用户身份令牌与 Agent 工具打通
status: executing
stopped_at: Plan 10-01 complete — Wave 0 RED 脚手架：conftest make_remote_tool/make_tool_binding + test_tool_bindings.py(7) + test_remote_tool_execute.py(5) + 前端 ToolBindingSettings.spec.ts(5)，预期 RED；test_pat_identity 8 passed 不回退
last_updated: "2026-06-10T00:50:00.000Z"
last_activity: 2026-06-10 -- Phase 10 Plan 01 complete (Wave 0 RED)
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 17
  completed_plans: 14
  percent: 82
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-09)

**Core value:** 让每个用户用 GitHub/GitLab 风格的个人访问令牌以「用户身份 + 用户权限」安全调用 Friday，并让 skill/mcp 工具以用户身份在容器内真正执行。
**Current focus:** Phase 10 — MCP 绑定用户令牌 + RemoteTool 执行端点

## Current Position

Phase: 10 (MCP 绑定用户令牌 + RemoteTool 执行端点) — EXECUTING
Plan: 2 of 4
Status: Ready to execute
Last activity: 2026-06-10 -- Phase 10 Plan 01 complete (Wave 0 RED)

Progress: [████████░░] 82%

## Performance Metrics

**Velocity:**

- Total plans completed: 16
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 5 | 1 | - | - |
| 06 | 3 | - | - |
| 07 | 3 | - | - |
| 08 | 4 | - | - |
| 09 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 06 P03 | 35 | 3 tasks | 4 files |
| Phase 07 P01 | 12 | 3 tasks | 3 files |
| Phase 07 P02 | 8 | 2 tasks | 2 files |
| Phase 07 P03 | 6 | 1 tasks | 1 files |
| Phase 08 P01 | 15 | 3 tasks | 2 files |
| Phase 08 P02 | 12 | 3 tasks | 4 files |
| Phase 08 P03 | 18 | 3 tasks | 1 files |
| Phase 08 P04 | 22 | 3 tasks | 1 files |
| Phase 09 P01 | 12 | 2 tasks | 2 files |
| Phase 09-admvw P02 | 10min | 3 tasks | 5 files |
| Phase 09 P03 | 8 | 3 tasks | 4 files |
| Phase 10 P01 | 10min | 3 tasks | 4 files |

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
- [Phase 08]: [08-01] 隔离回填排序字段用 created_at（accounts.User 实有；accounts/0005 同款），解决 RESEARCH A2（非 date_joined）
- [Phase 08]: [08-01] accounts/0006 partial unique index 限制最多一个 superuser → 回填「最早 superuser」即「唯一 superuser」
- [Phase 08]: [08-01] 越权对象级一律 404 / list 一律 []（禁 403，ISO-04 不泄漏存在性）；owner-allowed 断言 != 404 捕捉过度收紧
- [Phase 08]: [08-02] 两步迁移分离——0018 AddField + 0019 可逆 RunPython 回填（最早 superuser，无 superuser 早返回留 null 不阻塞部署）
- [Phase 08]: [08-02] owner gate 收口到 ConversationService.aget_for_user 单一真源；service 方法加 user=None 关键字默认参数向后兼容，端点接线留待 08-03/08-04
- [Phase 08]: [08-02] owner 过滤仅对已认证用户生效（getattr user is_authenticated），无 superuser bypass（源码 0 处 is_superuser，grep 守卫通过）
- [Phase 08]: [08-03] 直接会话端点 #1-12 接线 owner gate；owner gate 作主/外层先于既有 has_project_access，越权 404、无 superuser bypass，既有 403 分支保留为 null-owner/共享行次层
- [Phase 08]: [08-03] SSE stream 在 StreamingHttpResponse 构造前 aget_for_user → 干净 HTTP 404（非流内 error，Pitfall 5）；interrupt 在 runner.interrupt()/barrier 取消前加 owner-scoped 校验（T-08-11）
- [Phase 08]: [08-03] 两种 owner gate 风格：aget_for_user（detail/runtime/patch/stream/interrupt）+ created_by_id 比对（preflight/messages-delete/fork/export，已 select_related），统一 owner-miss → 404
- [Phase 08]: [08-04] 关联模型端点 #13-25 经 .conversation FK 接线 owner gate（select_related("conversation") + created_by_id 比对 → 404；list 型 #13/#20 走 aget_for_user → []），全 25 路径隔离套件全绿
- [Phase 08]: [08-04] #24/#25 去除 owner 判定的 superuser bypass（ISO-03，管理员越权 → 404）；#22 owner gate 前置覆盖旧 403→404；既有 has_project_access 降为 null-owner/共享行次层不 bypass owner gate
- [Phase 09]: [09-01] admin gate 语义用 403（非管理员明确 403），区别于 Phase 8 普通路径越权的 404（不泄漏存在性）——admin 端点管理员有权看全部，非管理员应明确拒绝
- [Phase 09]: [09-01] 「不可续聊」双重钉死：admin detail POST → 405（方法层）+ stream 子路径 → 404（路由层）；test_admin_no_stream_route 在 Wave 0 即 PASS 且 GREEN 后仍成立
- [Phase ?]: admin fork: created_by=admin + status=DRAFT + copy all messages (avoid owner inherit/pin freeze)
- [Phase ?]: admin endpoints physically separated (new admin_views/admin_urls, zero change to chat/views.py); IsSuperUser + default auth rejects anonymous
- [Phase 09]: 前端 admin 会话后台只读查看器与普通 chat 渲染同源但不耦合 chatStore；fork→/chat?conversation= 续聊
- [Phase 10]: [10-01] 跨用户 owner 隔离用例经 ORM 工厂 make_tool_binding(second_user) 播种他人绑定（make_access_token 仅主用户铸令牌，create 序列化器拒跨用户令牌引用，二号用户无法经 API 绑定）
- [Phase 10]: [10-01] 前端绑定 client 不引用 /tools/execute/（PAT-only 容器回调）；浏览器仅 list/bindable/upsert/unbind 走 /tools/bindings/ + /tools/bindable/
- [Phase 10]: [10-01] Wave 0 RED 脚手架：硬编码 URL 不 import 未落地 views → 端点 404 即 RED 而非 collection error；make_tool_binding 用 importorskip+getattr 守卫，ToolTokenBinding 缺失时优雅 skip

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

Last session: 2026-06-10T00:50:00.000Z
Stopped at: Plan 10-01 complete — Wave 0 RED 脚手架：conftest make_remote_tool/make_tool_binding + test_tool_bindings.py(7) + test_remote_tool_execute.py(5) + 前端 ToolBindingSettings.spec.ts(5)，预期 RED；test_pat_identity 8 passed 不回退
Resume file: None

## Operator Next Steps

- Plan the first phase with /gsd-plan-phase 6
