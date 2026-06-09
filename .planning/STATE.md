---
gsd_state_version: 1.0
milestone: v0.2.0
milestone_name: 用户身份令牌与 Agent 工具打通
status: executing
stopped_at: Plan 11-02 complete — task 容器侧机制：core/remote_tools.py（schema→SdkMcpTool 动态注册 + PAT 回调 handler + 401/403/非200/传输错误 graceful）+ TaskConfig 三字段（FRIDAY_TASK_ 自动 JSON 解码）+ executor 条件挂载 mcp_servers/allowed_tools；11-01 task RED 全转 GREEN（35 passed/3 skipped），PAT 仅进 header 不入日志，零新增依赖；Phase 11 进度 2/4
last_updated: "2026-06-10T02:20:00.000Z"
last_activity: 2026-06-10 -- Plan 11-02 complete（task 容器侧 RemoteTool 机制）
progress:
  total_phases: 6
  completed_phases: 5
  total_plans: 21
  completed_plans: 19
  percent: 90
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-09)

**Core value:** 让每个用户用 GitHub/GitLab 风格的个人访问令牌以「用户身份 + 用户权限」安全调用 Friday，并让 skill/mcp 工具以用户身份在容器内真正执行。
**Current focus:** Phase 11 — task 容器接通（RemoteTool 链路闭环）

## Current Position

Phase: 11 (task 容器接通（RemoteTool 链路闭环）) — EXECUTING
Plan: 3 of 4
Status: Executing Phase 11
Last activity: 2026-06-10 -- Plan 11-02 complete（task 容器侧 RemoteTool 机制）

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 21
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
| 10 | 4 | - | - |

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
| Phase 10 P02 | 6min | 2 tasks | 2 files |
| Phase 10 P04 | 6min | 3 tasks | 7 files |
| Phase 10 P03 | 12min | 3 tasks | 4 files |
| Phase 11 P01 | 14min | 3 tasks | 4 files |
| Phase 11 P02 | 9min | 3 tasks | 4 files |

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
- [Phase ?]: 10-02 ToolTokenBinding 三 FK 全 CASCADE + unique(user, remote_tool); related_name tool_token_bindings/tool_bindings/token_bindings 对齐 conftest
- [Phase ?]: 10-02 0003 迁移仅 CreateModel 无 RunPython (RESEARCH 零历史回填); migrate OK + makemigrations --check 干净, make_tool_binding 停止 skip
- [Phase 10]: [10-04] 前端绑定 UI 镜像 accessTokens 范式：types↔serializer 一一对应 + setup-store 元数据-only + Settings/Table/Dialog 三件套；下拉仅列 is_valid 令牌（computed filter，Pitfall 5）
- [Phase 10]: [10-04] upsertBinding 就地按 remote_tool 替换（unique(user,remote_tool) 语义）；浏览器 client grep 零 /tools/execute 引用（T-10 边界）；10-01 前端 spec 5/5 GREEN
- [Phase 10]: [10-03] 绑定 create serializer access_token=PrimaryKeyRelatedField(queryset=all)+validate_access_token 归属断言 created_by==user（不限定 queryset，统一走 ValidationError 不泄漏存在性）；validate_remote_tool 校验 source∈{mcp,skill}+is_active
- [Phase 10]: [10-03] 绑定 ViewSet owner 隔离 get_queryset(user=request.user) + acreate aupdate_or_create 收敛 upsert；执行端点 auth=[AccessTokenAuthentication] 仅 PAT + IsAuthenticated + handle_exception→401（不降级 403，mirror McpToolView）
- [Phase 10]: [10-03] 执行端点不做绑定强校验（可执行任意 active 工具）；execute_tool 签名不变、不传 user（Phase 11 gap，RESEARCH Open Q1）；后端 12 RED 全 GREEN，57 passed 回归不退，Phase 10 完成 4/4
- [Phase 11]: [11-01] Wave 0 RED 三组件契约字段名三侧一致（FRIDAY_TASK_USER_TOKEN/REMOTE_TOOLS/TOOLS_ENDPOINT）；task importorskip("core.remote_tools") 守卫零 collection error，handler 直测（monkeypatch httpx，无 live Claude）
- [Phase 11]: [11-01] WR-3 钉定：机会性 PAT 经 _run_repo_coding 可选 user_pat 形参（mirror anthropic_api_key），_execute_with_branch 经 AICodingNode._resolve_user_pat 解析实时明文；server 测试 monkeypatch 该解析器钉死 11-04 实现形态
- [Phase 11]: [11-01] omit-PAT/never-reads-AccessToken 为安全负向不变量（Wave 0 即 GREEN 须保持）；tools_endpoint 由 FRIDAY_BASE_URL 推导非 callback_url（Pitfall 1）；FRIDAY_TASK_REMOTE_TOOLS 前缀修复待 11-03（Pitfall 2）
- [Phase 11]: [11-02] handler 不 raise_for_status，显式 status_code 分支（401/403→令牌失效 / !=200→HTTP{code} / 传输错误→catch httpx.HTTPError）全 return is_error 不抛（RTOOL-04 graceful）
- [Phase 11]: [11-02] TaskConfig.remote_tools 走 pydantic v2 复杂类型 env 自动 JSON 解码（A2 首选，实测通过，无需 model_validator+json.loads 兜底）
- [Phase 11]: [11-02] executor 装配 options_kwargs dict 条件加 mcp_servers/allowed_tools（仅 build_remote_tools_mcp_server 非 None 时），log 加 has_user_token bool + remote_tool_count，绝不记 PAT 明文

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

Last session: 2026-06-10T02:20:00.000Z
Stopped at: Plan 11-02 complete — task 容器侧 RemoteTool 机制（remote_tools.py SDK MCP server + PAT 回调 + graceful + TaskConfig 三字段 + executor 条件挂载），task RED 全 GREEN，PAT 不入日志，回归不退；Phase 11 进度 2/4
Resume file: None

## Operator Next Steps

- Plan the first phase with /gsd-plan-phase 6
