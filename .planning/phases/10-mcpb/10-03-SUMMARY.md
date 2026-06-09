---
phase: 10-mcpb
plan: 03
subsystem: api
tags: [django, adrf, drf, serializer, viewset, owner-isolation, upsert, pat, fail-closed, remote-tool, audit]

# Dependency graph
requires:
  - phase: 10-mcpb (10-02)
    provides: tools.ToolTokenBinding 模型（三 FK CASCADE + unique(user, remote_tool)）
  - phase: 10-mcpb (10-01)
    provides: 后端 RED 锁名测试 test_tool_bindings.py / test_remote_tool_execute.py
  - phase: 07-auth
    provides: AccessTokenAuthentication（PAT→owner）+ begin_interaction_run 审计入口
provides:
  - 绑定序列化器五件套（BoundToken/ToolTokenBinding/Create/BindableTool/RemoteToolExecute）
  - 绑定 owner 隔离 ModelViewSet（list/create-upsert/delete）+ bindable 只读端点
  - RemoteTool 执行端点 RemoteToolExecuteView（PAT fail-closed + 审计 + executor 透传）
  - /api/tools/ 三路由挂载（bindings/ / bindable/ / execute/）
affects: [11-inject]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "绑定写入序列化器双 validate_* 作唯一授权关卡：access_token 归属（created_by==user）+ source/active 白名单"
    - "acreate 用 aupdate_or_create(user, remote_tool, defaults={access_token}) 收敛 upsert，不撞 unique_together 抛 500"
    - "执行端点 mirror McpToolView：handle_exception 把 NotAuthenticated/AuthenticationFailed → 401（不降级 403）"
    - "execute_tool 从模块顶层 import，使测试 monkeypatch tools.views.execute_tool 生效；签名未改（Phase 11 gap）"

key-files:
  created:
    - server/tools/serializers.py
    - server/tools/urls.py
  modified:
    - server/tools/views.py
    - server/friday/urls.py

key-decisions:
  - "[10-03] 绑定 create serializer access_token=PrimaryKeyRelatedField(queryset=all)+validate_access_token 归属断言（不限定 queryset 以走统一 ValidationError，不泄漏存在性，per Pitfall 1）"
  - "[10-03] 执行端点 authentication_classes=[AccessTokenAuthentication] 仅 PAT（不含 CookieJWT），permission=[IsAuthenticated] fail-closed；401 不降级 403（mirror McpToolView）"
  - "[10-03] 执行端点不做绑定强校验（可执行任意 active 工具，per RESEARCH Open Q2）；execute_tool 签名不变、不传 user（Phase 11 gap，RESEARCH Open Q1）"

patterns-established:
  - "owner 隔离 ModelViewSet + 写入 serializer 归属校验：跨用户引用走 ValidationError(400)，越权 list 空集 / delete 404"

requirements-completed: [MCPB-01, MCPB-02, MCPB-03, RTOOL-01]

# Metrics
duration: 12min
completed: 2026-06-10
---

# Phase 10 Plan 03: 绑定 CRUD + RemoteTool 执行端点装配 Summary

**在 tools app 落地序列化器/视图/路由并挂进 /api/tools/：owner 隔离 + 归属校验 + upsert 的绑定 ModelViewSet、mcp/skill+active 过滤的 bindable 端点、PAT fail-closed + begin_interaction_run 审计 + executor 透传的 RemoteToolExecuteView，使 10-01 后端 12 条 RED 全转 GREEN，PAT identity + mcp_tools 回归不退**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-10
- **Tasks:** 3
- **Files modified:** 4（2 新建 + 2 改）

## Accomplishments

- `serializers.py` 五件套：`BoundTokenSerializer`（仅 id/name/token_prefix/token_suffix/is_valid，零明文/hash）、`ToolTokenBindingSerializer`（嵌套令牌元数据 + 扁平工具信息，全只读）、`ToolTokenBindingCreateSerializer`（validate_access_token 归属 + validate_remote_tool source/active 白名单）、`BindableToolSerializer`、`RemoteToolExecuteSerializer`（name 必填 + arguments 缺省 {}）。
- `views.py` 三视图：`ToolTokenBindingViewSet`（get_queryset filter(user=request.user) owner 隔离 + acreate aupdate_or_create upsert）、`BindableToolsView`（source∈{mcp,skill} 且 is_active 过滤）、`RemoteToolExecuteView`（PAT-only fail-closed + handle_exception→401 + begin_interaction_run(source="tool") 审计 + execute_tool 透传）。
- `urls.py` + 挂载：DefaultRouter 注册 bindings/ + bindable/ + execute/，friday/urls.py 在 mcp/ 之后新增一行 `path("tools/", include("tools.urls"))`，最小 diff。

## Task Commits

1. **Task 1: serializers.py（五序列化器，白名单杜绝明文/hash）** — `fab1f417` (feat)
2. **Task 2: views.py（绑定 ViewSet owner 隔离+upsert / bindable / execute fail-closed）** — `0ee6a2aa` (feat)
3. **Task 3: urls.py + 挂载 /api/tools/** — `e9b7c67e` (feat)

## Files Created/Modified

- `server/tools/serializers.py` — 新建，五序列化器；字段白名单严禁 token_hash/明文。
- `server/tools/views.py` — 覆写（原为空模板），三视图类。
- `server/tools/urls.py` — 新建，router + bindable/ + execute/ 路由。
- `server/friday/urls.py` — api_patterns 内 mcp/ 之后新增 tools/ 一行（仅一行改动）。

## Verification Results

- `uv run pytest tests/test_tool_bindings.py tests/test_remote_tool_execute.py -q` → **12 passed**（10-01 后端 RED 全转 GREEN）。
- `uv run pytest tests/test_tool_bindings.py tests/test_remote_tool_execute.py tests/test_pat_identity.py tests/mcp_tools -q` → **57 passed**（PAT identity + mcp_tools 回归不退）。
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（无 schema 漂移）。
- `rg "token_hash" tools/serializers.py` → 仅命中 docstring/注释（无任何 serializer 字段引用 token_hash，白名单契约成立）。

## Deviations from Plan

None - plan executed exactly as written.

## Threat Mitigations Applied

- **T-10-01**（IDOR 引用他人令牌）→ `validate_access_token` 断言 `created_by_id == request.user.id`，越权引用 ValidationError(400)，`test_bind_others_token_rejected` GREEN 且未落库。
- **T-10-02**（list/delete 他人绑定）→ `get_queryset(user=request.user)`；越权 list 空集、delete aget_object → 404，`test_list_owner_isolation` / `test_unbind_and_cross_user_404` GREEN。
- **T-10-03**（匿名/无效 PAT 调执行端点）→ `authentication_classes=[AccessTokenAuthentication]` + `IsAuthenticated` + `handle_exception → 401`，`test_anonymous_401` / `test_revoked_pat_401` GREEN（精确 401，非 403）。
- **T-10-04**（重复绑定撞 unique 抛 500）→ `aupdate_or_create` 收敛 upsert，`test_upsert_rebind_updates_token` GREEN。
- **T-10-05**（响应/日志泄漏明文/hash）→ serializer 字段白名单 + begin_interaction_run 指纹=token_hash，`test_serializer_no_plaintext_no_hash` / `test_execute_records_run` GREEN。
- **T-10-06**（绑 builtin/失活工具）→ `validate_remote_tool` 校验 source∈{mcp,skill} 且 is_active，`test_bind_builtin_rejected` / `test_bindable_filters_mcp_skill_active` GREEN。

## Known Stubs

无。本 plan 生产代码全部接线落地；执行端点不向 execute_tool 传 user 是 Phase 11 的已知 gap（RESEARCH Open Q1 记录），非 stub。

## Issues Encountered

None.

## Next Phase Readiness

- Phase 11 容器接通可经 `/api/tools/execute/` 以用户 PAT 回调执行；(user, remote_tool)→access_token 映射经 `ToolTokenBinding` 可查。
- execute_tool 仍无 user 上下文（Phase 11 gap）：被绑定工具「以 owner 身份执行」目前由审计指纹（token_hash）体现，真正容器内身份注入留待 Phase 11。
- 无阻塞项。

## Self-Check: PASSED

- Files: server/tools/serializers.py / server/tools/urls.py / server/tools/views.py / server/friday/urls.py — all FOUND.
- Commits: fab1f417 / 0ee6a2aa / e9b7c67e — to be verified post-commit.

---
*Phase: 10-mcpb*
*Completed: 2026-06-10*
