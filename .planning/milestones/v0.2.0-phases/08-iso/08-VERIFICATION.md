---
phase: 08-iso
verified: 2026-06-09T23:10:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: null
  note: "Initial goal-backward verification (08-REVIEW.md is a code review, not a prior VERIFICATION.md)."
human_verification:

  - test: "多账户浏览器流：用账号 A 登录创建若干会话，再用账号 B（含管理员账号）登录，确认对话列表只见各自会话，且直接粘贴对方会话 URL 不可访问。"
    expected: "A/B 各自只看到自己的会话；越权 URL 显示「不存在」而非「无权」，不泄漏存在性。"
    why_human: "需要两个真实登录态与前端渲染，自动化套件仅覆盖 API 层 IDOR。"

  - test: "编辑消息 → fork → 续聊 UX（CR-01 修复点）：owner 在自己会话中编辑一条历史 user message，触发前端 fork + stream 续写。"
    expected: "fork 出的新会话归 owner 所有，立即出现在列表中，编辑后的消息可正常流式发送（不被 404）。"
    why_human: "端到端前端 fork→stream 时序与可见性是 UX 行为，需浏览器实测；后端已由 TestForkInheritsOwner 覆盖。"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 8: 对话/会话用户隔离 Verification Report

**Phase Goal:** 每个会话记录创建者，普通用户与管理员在 AI 对话中默认只能访问自己的会话，越权访问安全拒绝（404，不泄漏存在性）。
**Verified:** 2026-06-09T23:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ISO requirement) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | ISO-01: `Conversation.created_by` FK 存在；新会话写 owner；0019 回填历史给最早 superuser（`created_at,id`），可逆 | ✓ VERIFIED | `models.py:50` FK(`null=True, SET_NULL, related_name="conversations"`); `0018` AddField; `0019` `forwards` `order_by("created_at","id").first()` + 无 superuser 早返回 + `backwards` 置 None; `create_conversation` 写 `created_by` (`conversation_service.py:736-741`); 3× `test_backfill_*` GREEN |
| 2 | ISO-02: 全 25 访问路径按 owner 过滤；跨用户拒绝 | ✓ VERIFIED | views.py 27 处 owner gate（`aget_for_user` ×5 + `created_by_id != user.id` ×20+）覆盖 #1-25；`test_cross_user_denied` 参数化 #3-#12/#14-#25 全 404；`test_list_only_owner`/`test_list_scoping_coding` GREEN |
| 3 | ISO-03: 管理员/superuser 在 AI 对话中无 bypass | ✓ VERIFIED | `conversation_service.py` `is_superuser` 0 处；views.py 全部 `is_superuser` 仅在 owner gate **之后**的次层 `has_project_access` 中，对跨用户行不可达；`test_admin_no_bypass` GREEN |
| 4 | ISO-04: 跨用户对象访问 404（非 403）不可枚举；SSE 流前 404；fork 继承 owner | ✓ VERIFIED | owner gate 统一抛 `DoesNotExist`→404；`ChatStreamView.post` 在 `StreamingHttpResponse` 构造前 `aget_for_user`→404 (`views.py:1212-1220`)；fork `created_by_id=source.created_by_id` (`conversation_service.py:793`)；`test_404_indistinguishable`/`test_stream_cross_user_404`/`TestForkInheritsOwner` GREEN |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/chat/models.py` | `Conversation.created_by` FK | ✓ VERIFIED | `:50` 可空 SET_NULL FK，related_name `conversations` |
| `server/chat/migrations/0018_conversation_created_by.py` | AddField | ✓ VERIFIED | AddField + swappable AUTH_USER_MODEL 依赖 |
| `server/chat/migrations/0019_backfill_conversation_created_by.py` | RunPython 可逆回填 | ✓ VERIFIED | `forwards`/`backwards`；`created_at,id` 排序；无 superuser 早返回；覆盖软删行 |
| `server/chat/conversation_service.py` | `aget_for_user` + user-aware list/create/delete + fork owner | ✓ VERIFIED | `aget_for_user:697`、`create:736`、`fork:793`、`list:1347`、`delete:1736`；0 处 `is_superuser` |
| `server/chat/views.py` | #1-25 owner gate | ✓ VERIFIED | 27 处 owner gate；越权 404/[]；`is_superuser` 仅在次层 |
| `server/tests/test_conversation_isolation.py` | 25 路径 cross-user-denied 全集 | ✓ VERIFIED | `CROSS_USER_CASES` #3-#25 + #1/#2/#10′/#13/#20 单列 + fork 双向回归 |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| `ChatStreamView.post` | `aget_for_user` | owner-scoped 存在性校验先于 `StreamingHttpResponse` | ✓ WIRED (`views.py:1212`) |
| `views.py` 关联端点 #13-25 | `session/plan/trace.conversation.created_by_id` | `select_related("conversation")` + owner 比对→404 | ✓ WIRED |
| `conversation_service.fork` | `Conversation.created_by` | `created_by_id=source.created_by_id` | ✓ WIRED (`:793`) |

### Behavioral Spot-Checks (test suite)

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| 隔离 + 集成 + facade + coding-session + chat-views 全套 | `cd server && uv run pytest tests/test_conversation_isolation.py tests/test_conversation_integration.py tests/test_conversation_facade.py tests/test_coding_session_service.py tests/test_chat_views.py -q` | **75 passed, 0 failed** | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| ISO-01 | 08-02 | created_by 落库 + 历史回填 | ✓ SATISFIED | FK + 0018/0019 + backfill 测试 |
| ISO-02 | 08-03/04 | 全路径 owner 过滤 | ✓ SATISFIED | 25 路径 owner gate + cross-user 测试 |
| ISO-03 | 08-03/04 | 管理员无 bypass | ✓ SATISFIED | owner gate 0 处 is_superuser；admin-no-bypass GREEN |
| ISO-04 | 08-03/04 | 越权 404 不泄漏存在性 | ✓ SATISFIED | 统一 404 + indistinguishable + SSE 前 404 + fork owner |

无孤儿需求：REQUIREMENTS.md 中映射到 Phase 8 的 ISO-01..04 全部被 plan 的 `requirements` 字段覆盖。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| --- | --- | --- | --- |
| — | 无 TBD/FIXME/XXX 调试标记，无占位 stub | ℹ️ Info | owner gate 全部为真实实现；`return Response(... 404)` 为正确语义而非桩 |

### Human Verification Required

后端 IDOR 隔离已被 75 个自动化用例完全覆盖且全绿。下列为前端多账户 UX，属浏览器层行为，需人工实测：

1. **多账户隔离浏览** — 账号 A 创建会话，账号 B（含管理员）登录后只见自己会话，直接粘贴对方会话 URL 显示「不存在」。
2. **编辑消息 → fork → 续聊** — owner 编辑历史消息触发 fork + stream，新 fork 归属 owner、出现在列表、续写不被 404（CR-01 修复点的端到端确认）。

### Gaps Summary

无阻断性缺口。ISO-01..04 四条可观测真值在代码中全部成立并由测试套件验证（75 passed）。08-REVIEW.md 的 CR-01（fork owner-less）与 WR-01（次层 project 403 误伤 owner）均已在代码中修复并落地回归测试（`fork:793`、owner 短路注释 `views.py:743/928/1037/2357`）。状态判定为 `human_needed` 仅因里程碑要求的多账户浏览器 UX 无法以 grep/单测验证，须人工确认——非功能缺失。

---

_Verified: 2026-06-09T23:10:00Z_
_Verifier: Claude (gsd-verifier)_
