# Phase 8: 对话/会话用户隔离 - Research

**Researched:** 2026-06-09
**Domain:** Django/adrf async access control — owner-scoped row isolation + non-enumerable 404 over an existing chat conversation surface
**Confidence:** HIGH (codebase grounded — every access path read directly from source)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **模型与迁移 (ISO-01)**
  - `Conversation` 新增 `created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")`。
    - `null=True`：兼容历史数据与「鉴权关闭/匿名/compat」入口创建的无主会话，用户删除时不级联删除会话。
  - 数据迁移：历史无主会话 `created_by` 回填给最早的 superuser（`User.objects.filter(is_superuser=True).order_by("date_joined","id").first()`）；若无 superuser 则留空（不阻塞迁移）。schema-migration + RunPython。
  - 新建会话时 `created_by = request.user`（仅当 `request.user` 已认证；匿名/鉴权关闭场景保持 null）。
- **owner 过滤 (ISO-02 / ISO-03)**
  - 在 `ConversationService` / 会话查询的统一 queryset 入口按 `created_by=request.user` 过滤，覆盖全部路径：list / detail / runtime / stream(SSE) / patch / delete / fork。
  - 管理员（is_staff/superuser）在 AI 对话界面**不**做特权 bypass，与普通用户一致（ISO-03）；管理员跨用户浏览放到 Phase 9。
  - 仅对「已认证用户」施加过滤；`request.user` 未认证（开放模式 / chat-key / compat）维持既有行为。
- **越权拒绝 (ISO-04)**
  - 对象级访问他人会话一律返回 **404**（非 403），避免泄漏存在性。统一在对象获取处用「owner 过滤后的 queryset + get_object_or_404 语义」实现，杜绝先取后判的存在性泄漏。
  - SSE / WebSocket 流式入口（runtime/stream）建立连接/取会话时同样走 owner 过滤；越权连接被拒（HTTP 404 / WS close），不开流。
  - fork 他人会话同样按 owner 过滤拒绝；本期 fork 仅限自己（管理员 fork 他人在 Phase 9）。

### Claude's Discretion
- queryset 过滤的具体落点（`ConversationService` 方法签名加 `user` 参数 vs view 层统一注入）、对象级 404 的实现样式、WebSocket consumer 的 owner 校验位置，由实现按既有结构决定。
- 是否对 Message 子资源单独加 owner 校验（应通过其 Conversation 的 owner 间接保证）。
- 测试组织（新增 `test_conversation_isolation.py` vs 扩展既有测试）。

### Deferred Ideas (OUT OF SCOPE)
- 管理员只读会话管理后台 + fork 他人会话（Phase 9）。
- 鉴权关闭/匿名开放模式下的隔离语义细化（本期保持既有开放行为，隔离以「有用户身份」为前提）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ISO-01 | 每个会话记录创建者 `Conversation.created_by`；迁移历史无主会话归属给最早 superuser | Model field design + RunPython backfill pattern (verified against `accounts/0005`, `workflows/0018`); create-path owner injection point identified (`ConversationListView.post` → `ConversationService.create_conversation`) |
| ISO-02 | 普通用户在 AI 对话只能查看/操作自己的会话（list/detail/runtime/stream/patch/delete/fork 等全路径） | Complete access-path enumeration below (§Conversation Access Point Inventory); centralized owner-scoped fetch落点 recommended |
| ISO-03 | 管理员在 AI 对话界面默认也只看自己的会话 | No superuser bypass in the new owner filter (distinct from existing `has_project_access` superuser-bypass checks — §Anti-Patterns) |
| ISO-04 | 越权访问他人会话（含 SSE/WS 流式入口与对象级操作）返回 403/404，不泄漏存在性 | 404-not-403 via owner-scoped queryset + `Conversation.DoesNotExist`→404; async `sync_to_async`-free ORM pattern; every leaf endpoint mapped |
</phase_requirements>

## Summary

Phase 8 adds a single nullable FK (`Conversation.created_by`) and then enforces **owner-scoped row isolation** across **every** code path that reads or writes a `Conversation` — directly or via a related model (`Message`, `CodingSession`, `CodingPlan`, `RepositoryRoutingTrace`, `ConversationIntentTrace`). The technical domain is not novel: it is Django queryset filtering + Django's `DoesNotExist`→`404` mapping, done in an **adrf async** context (so use `Conversation.objects.aget(...)` / `async for`, never `get_object_or_404` directly — there is no async variant; raise `Conversation.DoesNotExist` and map to 404). The hard part is **completeness**: ISO-04 fails if even one of ~25 endpoints leaks. This research enumerates all of them.

Two findings substantially de-risk the phase. **(1) There is NO chat WebSocket consumer.** The "stream/SSE" entry point is a plain Django REST `StreamingHttpResponse` (`ChatStreamView.post`), and `chat/streaming.py` is just SSE-formatting helpers. The only Channels consumers in the repo (`runners/`, `workflows/`) are not conversation-scoped. So the WS owner-rejection work item collapses to "guard the existence check inside `ChatStreamView.post` before the stream opens." **(2) The OpenAI-compat path never touches `Conversation`** (verified: zero `Conversation` references in `server/compat/`) — it is stateless via `aget_chat_service`, so isolation does not apply there.

The single biggest correctness trap: the chat surface **already** has project-level access checks (`PermissionService.has_project_access`) on ~5 endpoints, and those checks **bypass for superuser and return 403**. ISO requires the opposite for the new owner gate — **no superuser bypass (ISO-03) and 404 not 403 (ISO-04)**. The new owner filter must be layered as the *primary, outermost* gate (it runs first and 404s), leaving the existing project checks as a secondary layer for null-owner/shared rows. Also note the chat conversation views override `authentication_classes` to `[OptionalJWTAuthentication, ChatKeyAuthentication]` — they do **not** include the PAT class, so on these endpoints `request.user` is a cookie/Bearer-JWT user or `AnonymousUser` (chat-key). PAT-on-chat resolves anonymous today (see Assumptions A1).

**Primary recommendation:** Add `created_by` (nullable FK) + a schema migration + a RunPython backfill. Introduce ONE owner-scoped fetch helper on `ConversationService` (e.g. `aget_for_user(conversation_id, user) -> Conversation` that filters `created_by=user` only when `user.is_authenticated`, else preserves open behavior, and raises `Conversation.DoesNotExist` otherwise). Route every view's conversation lookup through it; thread `user` into `list_conversations` and `create_conversation`. For related-model endpoints (coding-session/plan/trace/clarification), resolve the owning `Conversation` and apply the same gate. Add explicit cross-user-denied tests for every path.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Conversation ownership identity | Database (model FK) | API (set on create) | Ownership is durable row state; FK is the source of truth |
| Owner row filtering (list/detail) | API → Service queryset | — | `ConversationService` is the central query point per CONTEXT; views call it |
| Object-level 404 (non-enumerable) | API view (exception→status) | Service (owner-scoped fetch) | Django `DoesNotExist`→404 mapping is a view concern; service produces the scoped queryset |
| `request.user` resolution | API (DRF auth classes) | — | Already resolved by `OptionalJWTAuthentication`/`ChatKeyAuthentication`; Phase 7 made JWT/PAT users real owners |
| SSE stream gating | API view (`ChatStreamView.post`) | — | Existence check happens in the view before `StreamingHttpResponse` opens; no WS tier exists |
| History backfill | Database (RunPython migration) | — | One-time data migration; idempotent, reversible |

## Standard Stack

No new external packages. This phase is built entirely on the existing stack.

### Core (already present)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM | 5.1+ | `created_by` FK, queryset filtering, schema + RunPython migration | Native, async ORM (`aget`/`acreate`/`async for`) already pervasive in `chat/` |
| adrf | 0.1.12+ | async DRF `APIView`s | Every chat view is `adrf.views.APIView` |
| djangorestframework | 3.15+ | `Response`, status codes, serializers | Existing chat views |
| accounts.User | — | FK target (`settings.AUTH_USER_MODEL` is `accounts.User`) | Phase 7 made `request.user` the real owner |

### Supporting (already present)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asgiref `sync_to_async` | — | bridge sync `PermissionService` / serializer `is_valid` from async views | Only for sync calls; ORM has native async methods |
| pytest / pytest-asyncio / pytest-django | 9.x / — / 4.8 | async test suite | All chat tests are `@pytest.mark.django_db(transaction=True)` async |
| rest_framework_simplejwt `RefreshToken.for_user` | — | mint JWT for authenticated test clients | Existing `user_and_token` fixtures |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| nullable FK + RunPython backfill | non-nullable FK with default | Rejected — breaks compat with anonymous/open-mode rows and cascades on user delete; CONTEXT locks `null=True, on_delete=SET_NULL` |
| owner filter in service queryset | DRF object-level permission class | DRF `has_object_permission` runs *after* object fetch → existence leak risk + clunky in async; CONTEXT prefers owner-scoped queryset |
| `get_object_or_404` | `aget` + `except DoesNotExist → 404` | `get_object_or_404` has no async variant and would force `sync_to_async`; the codebase already uses the `aget`/`except`/404 pattern everywhere |

**Installation:** None — no dependency changes.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages (pure Django model + view + migration + test changes). No registry verification or slopcheck required.

## Conversation Access Point Inventory (ISO-02 / ISO-04 — THE CRITICAL DELIVERABLE)

Every path that reads or writes a `Conversation` (directly or via FK). **Miss none.** "Reaches Conversation via" shows the FK chain. "Gate" = where the owner filter / 404 must go. All file refs are `server/chat/views.py` unless noted.

### A. Direct conversation endpoints (`/api/chat/conversations/…`)
| # | Endpoint | View / method | Reaches Conversation via | Current ownership check | Required Phase-8 gate |
|---|----------|---------------|--------------------------|-------------------------|------------------------|
| 1 | `GET conversations/` (list) | `ConversationListView.get` → `ConversationService.list_conversations()` | direct queryset | **none** | owner filter on queryset (`created_by=user` when authed) |
| 2 | `POST conversations/` (create) | `ConversationListView.post` → `ConversationService.create_conversation()` | new row | validates `project` only | set `created_by=user` (when authed) |
| 3 | `GET conversations/{id}/` (detail) | `ConversationDetailView.get` → `get_conversation_with_messages()` + a 2nd `Conversation.objects…aget` | direct `aget` | none | owner-scoped fetch → 404 |
| 4 | `DELETE conversations/{id}/` | `ConversationDetailView.delete` → `delete_conversation()` (filter `is_deleted=False`.aupdate) | direct `aupdate` | none | owner-scoped filter → 404 when 0 rows |
| 5 | `PATCH conversations/{id}/` (pin) | `ConversationDetailView.patch` | direct `aget` | none | owner-scoped fetch → 404 |
| 6 | `GET conversations/{id}/preflight/` | `ConversationPreflightView.get` | direct `aget` (select_related) | **`has_project_access("viewer")` + superuser bypass → 403** | owner gate FIRST → 404 (precede provider payload to avoid info-disclosure) |
| 7 | `GET conversations/{id}/runtime/` | `ConversationRuntimeView.get` → `get_conversation_runtime()` | direct `aget` then service re-queries | none | owner-scoped fetch → 404 (gate before runtime payload) |
| 8 | `DELETE conversations/{id}/messages/?before_id=` | `ConversationMessagesDeleteView.delete` | direct `aget` (select_related project) | **`has_project_access("member")` + superuser bypass → 403** | owner gate FIRST → 404 |
| 9 | `POST conversations/{id}/messages/{mid}/fork/` | `ConversationMessageForkView.post` → `fork_conversation_before_message()` | direct `aget` + service `aget` | **`has_project_access("member")` + superuser bypass → 403** | owner gate FIRST → 404 (fork only-own per CONTEXT) |
| 10 | `POST conversations/{id}/stream/` (SSE send-message) | `ChatStreamView.post` → `send_message_stream()` | direct `aget` (existence check) then service `aget` | none | owner-scoped fetch → 404 **before** `StreamingHttpResponse` opens |
| 11 | `POST conversations/{id}/interrupt/` | `ChatInterruptView.post` | `OrchestrationRun`/`Conversation` filter by id; `aupdate` | none | owner-scoped existence check → 404 (else any user can interrupt another's run) |
| 12 | `POST conversations/{id}/export-to-feishu/` | `ExportToFeishuView.post` | direct `aget` (select_related project) | none (filters messages by conv_id) | owner-scoped fetch → 404 |

### B. SSE / streaming entry (no WebSocket consumer exists)
| # | Path | Reality | Gate |
|---|------|---------|------|
| 10′ | SSE stream | `ChatStreamView` returns `StreamingHttpResponse` (REST). `chat/streaming.py` = `format_sse`/`format_keepalive` helpers only. **No Channels consumer for chat.** `asgi.py` routes only `runners` + `workflows` WS patterns. | Same as #10 — the existence `aget` in `ChatStreamView.post` is the single chokepoint; make it owner-scoped → 404 before stream opens. No WS close-code work needed. |

### C. Related-model endpoints that reach a Conversation via FK (CodingSession / CodingPlan)
These currently use **`IsAuthenticated` only** (most have **no** conversation/owner check at all → today any authenticated user can read/act on another user's coding session by id). They must resolve the owning conversation and apply the owner gate → 404.
| # | Endpoint | View | Reaches Conversation via | Current check | Required gate |
|---|----------|------|--------------------------|---------------|---------------|
| 13 | `GET coding-sessions/?conversation_id=` | `CodingSessionListView.get` | `Conversation.aget(id=conversation_id)` then sessions filter | existence only (returns `[]` if missing) | owner-scoped conv fetch → `[]`/404 (don't list others') |
| 14 | `GET coding-sessions/{id}/` | `CodingSessionDetailView.get` | `CodingSession.conversation` | none | resolve `session.conversation`, owner gate → 404 |
| 15 | `POST coding-sessions/{id}/confirm/` | `CodingSessionConfirmView.post` | `CodingSession.conversation__project` (select_related) | none | owner gate via `session.conversation` → 404 |
| 16 | `GET/POST coding-sessions/{id}/commit-confirm/` | `CommitConfirmView` | `CodingSession.conversation` | none | owner gate → 404 |
| 17 | `GET/POST coding-sessions/{id}/pr-confirm/` | `PRConfirmView` | `CodingSession.conversation` | none | owner gate → 404 |
| 18 | `GET coding-sessions/{id}/conflict-check/` | `ConflictCheckView` | `CodingSession.conversation` | none | owner gate → 404 |
| 19 | `GET coding-sessions/{id}/diff-summary/` | `DiffSummaryView` | `CodingSession.conversation` | none | owner gate → 404 |
| 20 | `GET coding-plans/?conversation_id=` | `CodingPlanListView.get` | `Conversation.aget` then plans filter | existence only | owner-scoped conv fetch → `[]` |
| 21 | `GET coding-plans/{id}/` | `CodingPlanDetailView.get` | `CodingPlan.conversation` | none | owner gate via `plan.conversation` → 404 |
| 22 | `POST coding-plans/{id}/sessions/` (batch create) | `CodingPlanSessionsBatchCreateView.post` | `CodingPlan.conversation__project` | **`has_project_access(MEMBER)` + superuser bypass → 403** | owner gate FIRST → 404 |
| 23 | `POST coding-plans/{id}/export-to-feishu/` | `ExportCodingPlanToFeishuView.post` | `CodingPlan.conversation__project` | none | owner gate via `plan.conversation` → 404 |

### D. Trace / clarification endpoints that reach a Conversation via FK
| # | Endpoint | View | Reaches Conversation via | Current check | Required gate |
|---|----------|------|--------------------------|---------------|---------------|
| 24 | `POST routing-traces/{id}/override/` | `RoutingTraceManualOverrideView.post` | `RepositoryRoutingTrace.conversation__project` | **`has_project_access("member")` + superuser bypass → 404** (already 404!) | add owner gate (`trace.conversation.created_by`) → 404, no superuser bypass |
| 25 | `POST clarifications/{cid}/answer/` | `ClarificationAnswerView.post` | `ConversationIntentTrace.conversation__project` | **`has_project_access("member")` + superuser bypass → 404** (already 404!) | add owner gate (`trace.conversation.created_by`) → 404, no superuser bypass |

### E. NOT in scope (verified — do not add owner filtering)
| Surface | Why excluded |
|---------|--------------|
| `POST /api/chat/completions/` (`ChatCompletionsView`) | OpenAI-compat; stateless via `aget_chat_service`; **never touches `Conversation`** (grep-verified) |
| `GET /api/chat/models/` (`ModelsView`) | provider model listing; no conversation |
| `POST /api/chat/images/` + `GET images/{name}/` | image storage; not conversation-scoped (storage-ref keyed) |
| `push/*` (`WebPush*`) | per-user push subscriptions, already keyed by `request.user.id` |
| `server/compat/**` (OpenAI compat app) | **zero `Conversation` references** (grep-verified) — stateless |
| `runners/` + `workflows/` Channels consumers | not conversation-scoped (runner status / workflow execution) |

**Total: 25 conversation-touching endpoints require the owner gate.**

## Architecture Patterns

### Data Flow (owner gate)
```
request (DRF auth: OptionalJWTAuthentication | ChatKeyAuthentication)
   │  request.user = JWT user  (authenticated)  ── strict isolation applies
   │  request.user = AnonymousUser (chat-key / open mode) ── open behavior preserved
   ▼
View.<method>(request, conversation_id)
   ▼
ConversationService.aget_for_user(conversation_id, request.user)
   │   queryset = Conversation.objects.filter(id=conversation_id, is_deleted=False)
   │   if user.is_authenticated:  queryset = queryset.filter(created_by=user)
   │   conv = await queryset.aget()      # raises Conversation.DoesNotExist if not owned
   ▼ (DoesNotExist)
View maps → Response(status=404)   # non-enumerable: same 404 for "missing" and "not yours"
```

### Pattern 1: Centralized owner-scoped fetch (RECOMMENDED落点)
**What:** One async helper on `ConversationService`; all views call it. Single source of truth for the isolation rule keeps 25 endpoints consistent (CONTEXT gives discretion; centralization minimizes miss-risk).
**When to use:** Every direct conversation lookup (#1,3,4,5,6,7,8,9,10,11,12) and as a sub-step after resolving a related model's `.conversation` (#13–25).
**Example (new code — illustrative):**
```python
# chat/conversation_service.py
@staticmethod
async def aget_for_user(conversation_id: str, user) -> Conversation:
    """按 owner 过滤获取会话；越权/不存在统一抛 DoesNotExist（view 映射 404）。

    隔离仅对已认证用户生效；匿名（chat-key / 开放模式）维持既有开放行为。
    管理员不做特权 bypass（ISO-03）。
    """
    qs = Conversation.objects.filter(id=conversation_id, is_deleted=False)
    if getattr(user, "is_authenticated", False):
        qs = qs.filter(created_by=user)
    return await qs.aget()  # Conversation.DoesNotExist → view returns 404
```
**View usage (replaces the existing `aget` existence checks):**
```python
try:
    conversation = await ConversationService.aget_for_user(str(conversation_id), request.user)
except Conversation.DoesNotExist:
    return Response({"error": "对话不存在"}, status=status.HTTP_404_NOT_FOUND)
```

### Pattern 2: List filtering (#1)
```python
@staticmethod
async def list_conversations(user) -> list[Conversation]:
    qs = Conversation.objects.filter(is_deleted=False)
    if getattr(user, "is_authenticated", False):
        qs = qs.filter(created_by=user)
    return [c async for c in qs.order_by("-updated_at")]
```

### Pattern 3: Create owner injection (#2)
`create_conversation(space_id, title, model, user=None)` → pass `created_by=user if user.is_authenticated else None` to `acreate`. View passes `request.user`.

### Pattern 4: Related-model gate (#14–25)
Resolve the related row with `select_related("conversation")` (or `conversation__project` where already used), then apply the owner check on `obj.conversation`:
```python
session = await CodingSession.objects.select_related("conversation").aget(id=session_id)
conv = session.conversation
if getattr(user, "is_authenticated", False) and conv.created_by_id != user.id:
    return Response({"detail": "..."}, status=status.HTTP_404_NOT_FOUND)
```
(Equivalent to re-fetching via `aget_for_user(conv.id, user)`; pick one style and apply uniformly.)

### Pattern 5: SSE gate before stream opens (#10)
The owner check must happen in `ChatStreamView.post` **before** constructing `StreamingHttpResponse` (it already does an existence `aget` there — swap it for `aget_for_user`). Do NOT rely on the inner `send_message_stream` `aget`: by then headers are sent and you can only emit an SSE `error` event, not a clean 404.

### Recommended Project Structure
No new files required. Touch points:
```
server/chat/
├── models.py                 # + created_by FK
├── migrations/
│   ├── 0018_conversation_created_by.py        # AddField (schema)
│   └── 0019_backfill_conversation_created_by.py # RunPython (data)
├── conversation_service.py   # + aget_for_user / list+create user param
└── views.py                  # route 25 endpoints through the gate
server/tests/
└── test_conversation_isolation.py  # NEW — cross-user-denied per path (recommended)
```

### Anti-Patterns to Avoid
- **Reusing `has_project_access` for the new owner gate.** It bypasses for superuser (breaks ISO-03) and returns 403 (breaks ISO-04). The owner gate is *stricter and orthogonal*; layer it as the primary/outer gate. Leave existing project checks intact for null-owner/shared rows.
- **403 for "not yours."** ISO-04 mandates 404 to avoid existence enumeration. A 403 tells the attacker the id exists.
- **Fetch-then-check (`aget` then `if conv.created_by != user`).** Works but risks accidental info leakage if any field is read/serialized before the check (cf. the preflight info-disclosure note already in code). Prefer owner-scoped queryset so the row never materializes for non-owners. Where fetch-then-check is unavoidable (related models), do the check immediately and return 404 before touching any other field.
- **Gating only inside `send_message_stream`.** Too late for a clean HTTP 404 (stream already open). Gate in the view.
- **Filtering `created_by=user` and silently hiding null-owner rows from their backfilled superuser owner.** After backfill, legacy rows belong to the earliest superuser; that superuser (when acting as a normal authed user) correctly sees them via `created_by=user`. New anonymous rows stay null and are invisible to authed users by design (open-mode artifacts) — document this is intended.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Non-enumerable object lookup | custom "exists? then 403/404" branching | owner-scoped queryset + `aget` → `DoesNotExist`→404 | Django idiom; avoids existence leak; already the repo pattern |
| User identity in request | parse JWT/headers manually | `request.user` (DRF auth classes, Phase 7) | Auth already resolves owner |
| History backfill | ad-hoc SQL / shell | `migrations.RunPython(forwards, backwards)` with `apps.get_model` | Matches `accounts/0005`, `workflows/0018`; app-registry-safe + reversible |
| Async object-or-404 | `sync_to_async(get_object_or_404)` | native `await qs.aget()` + try/except | No async `get_object_or_404`; native async ORM is already used |

**Key insight:** The entire phase is a *consistency* problem, not an *invention* problem. The risk is missing an endpoint, not picking the wrong tool.

## Runtime State Inventory

This is a schema + access-control change (not a string rename), but the data-state checklist matters for the backfill.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `conversations` table rows with no owner today (`created_by` does not exist yet). Related rows (`messages`, `coding_sessions`, `coding_plans`, `repository_routing_traces`, `conversation_intent_traces`) inherit ownership transitively via `conversation` FK — **no separate owner column needed** (CONTEXT discretion: Message owner enforced via its Conversation). | Data migration: backfill `created_by` to earliest superuser for all existing rows |
| Live service config | None — ownership is a DB column, no external service holds it | None |
| OS-registered state | None | None |
| Secrets/env vars | None — no new secret/env keys | None |
| Build artifacts | None — no package/binary rename | None |

**Backfill specifics (ISO-01, verified pattern):**
- Earliest superuser selection: `User.objects.filter(is_superuser=True).order_by("date_joined", "id").first()`. (Note: `accounts.User` orders by `created_at` in the existing backfill; **verify the actual field name** — CONTEXT specifies `date_joined`. `accounts/0005` used `order_by("created_at")`. The planner/executor must confirm which timestamp field exists on `accounts.User` and use it; see Assumptions A2.)
- No-superuser case: leave `created_by=NULL` (do **not** abort the migration).
- Use `apps.get_model("chat", "Conversation")` and `apps.get_model("accounts", "User")` inside `forwards` (app-registry safety, per `accounts/0005`).
- Reversibility: `backwards` sets `created_by=None` for all rows (cf. `workflows/0018` `reverse_backfill`).
- Backfill should set owner for **all** rows including soft-deleted (`is_deleted=True`) — they still belong to the superuser for any future admin view.
- Two-migration split (AddField then RunPython) matches the milestone decision ("schema-migration + RunPython") and `workflows/0017`+`0018` precedent. Single migration with both ops also works; split is cleaner for `makemigrations --check`.

## Common Pitfalls

### Pitfall 1: Missing an endpoint (ISO-04 total-coverage failure)
**What goes wrong:** Owner filter added to list/detail/stream but a coding-session or trace endpoint left open → cross-user leak.
**Why it happens:** 25 endpoints across 4 groups; coding-session endpoints have *no* existing ownership check, so they're easy to overlook.
**How to avoid:** Use the §Access Point Inventory as a checklist; one cross-user-denied test per row.
**Warning signs:** A `CodingSession`/`CodingPlan`/trace endpoint that does `aget(id=...)` without resolving `.conversation` and checking owner.

### Pitfall 2: Admin bypass via copied project-check code
**What goes wrong:** Developer copies the existing `if not user.is_superuser: has_project_access(...)` block → superuser sees everyone's conversations → ISO-03 violated.
**Why it happens:** 5 endpoints already contain that exact pattern; tempting to reuse.
**How to avoid:** The owner gate has **no** `is_superuser` branch. Keep the new gate separate from the legacy project check.
**Warning signs:** `is_superuser` appears anywhere in the new owner-filter code.

### Pitfall 3: 403 instead of 404 (existence leak)
**What goes wrong:** Returning 403 for "not your conversation" reveals the id exists.
**How to avoid:** Map owner miss → 404 with the same body as "not found." The two legacy 403 endpoints (#6,8,9,22) must return 404 from the *new* owner gate even though their *legacy* project check returns 403.
**Warning signs:** New code path returning `HTTP_403_FORBIDDEN`.

### Pitfall 4: SynchronousOnlyOperation in async views
**What goes wrong:** Touching a FK (`conv.created_by`, `conv.project`) lazily in async context raises `SynchronousOnlyOperation`.
**How to avoid:** Filter by `created_by` in the queryset (no attribute access needed), or compare `conv.created_by_id` (the `_id` column, no DB hit) instead of `conv.created_by`. For related models, `select_related("conversation")` before reading `conversation.created_by_id`.
**Warning signs:** Reading `.created_by` (not `.created_by_id`) after a non-`select_related` fetch.

### Pitfall 5: SSE 404 too late
**What goes wrong:** Owner check only in `send_message_stream` → stream already streaming → can't send HTTP 404.
**How to avoid:** Gate in `ChatStreamView.post` before `StreamingHttpResponse`.
**Warning signs:** No owner check between serializer validation and `StreamingHttpResponse(...)`.

### Pitfall 6: Test fixtures create owner-less conversations
**What goes wrong:** After adding strict filtering, existing tests that create a `Conversation` with no `created_by` and then GET it as an authenticated user start returning 404.
**Why it happens:** `frozen_conversation_factory` and `_create_conversation` helpers don't set `created_by`; `test_conversation_integration.py` creates via authed POST (will auto-set owner) but other tests create rows directly.
**How to avoid:** Update factories to accept/set `created_by`; for tests asserting an authed user can access, set `created_by=that_user`. See §Validation Architecture / Regression Surface.
**Warning signs:** Pre-existing chat tests flipping to 404 after the filter lands.

## Code Examples

### Owner-scoped delete returning 404 (replaces #4)
```python
# conversation_service.py
@staticmethod
async def delete_conversation(conversation_id: str, user) -> None:
    qs = Conversation.objects.filter(id=conversation_id, is_deleted=False)
    if getattr(user, "is_authenticated", False):
        qs = qs.filter(created_by=user)
    updated = await qs.aupdate(is_deleted=True)
    if updated == 0:
        raise Conversation.DoesNotExist(f"对话不存在或无权访问: {conversation_id}")
```

### RunPython backfill (model new code — mirrors accounts/0005 & workflows/0018)
```python
# 0019_backfill_conversation_created_by.py
from django.db import migrations

def forwards(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    User = apps.get_model("accounts", "User")
    # CONFIRM the timestamp field name on accounts.User (date_joined vs created_at) — see A2
    earliest = User.objects.filter(is_superuser=True).order_by("date_joined", "id").first()
    if earliest is None:
        return  # no superuser → leave NULL, do not block
    Conversation.objects.filter(created_by__isnull=True).update(created_by=earliest)

def backwards(apps, schema_editor):
    Conversation = apps.get_model("chat", "Conversation")
    Conversation.objects.update(created_by=None)

class Migration(migrations.Migration):
    dependencies = [("chat", "0018_conversation_created_by")]
    operations = [migrations.RunPython(forwards, backwards)]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Project-level access via `has_project_access` (superuser bypass, 403) | + Owner-level isolation (`created_by`, no bypass, 404) | Phase 8 | Two complementary layers; owner gate is primary for authed users |
| `request.user` unreliable for tokens | `request.user` = real owner (PAT/JWT) | Phase 7 | Owner identity is now trustworthy on JWT-bearing chat requests |

**Deprecated/outdated:** Nothing removed. The phase is additive.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | On chat conversation endpoints, PAT (`friday_pat_`) tokens resolve to `AnonymousUser` because chat views override `authentication_classes=[OptionalJWTAuthentication, ChatKeyAuthentication]` (no `AccessTokenAuthentication`). So owner isolation only binds JWT (web) users; PAT-on-chat keeps open behavior. | Summary, Access Inventory | If the milestone expects PAT callers to also get per-owner chat isolation, chat views must additionally include `AccessTokenAuthentication` — a scope addition. Flag to user before planning. |
| A2 | `accounts.User` has a `date_joined` field for "earliest superuser" ordering. CONTEXT specifies `date_joined`, but the existing `accounts/0005` backfill used `order_by("created_at")`. | Runtime State Inventory, Code Examples | If the field is `created_at` not `date_joined`, the migration errors. Executor must confirm the actual field name on `accounts.User`. Low risk (either works as ordering; just pick the existing one). |
| A3 | No chat WebSocket consumer exists; SSE is the only streaming entry. (Verified: `asgi.py` routes only `runners`+`workflows`; `chat/streaming.py` has no consumer.) | Summary, Access Inventory B | If a chat WS consumer is added later, it needs the same owner gate via Channels `scope["user"]`. Not in this phase. |
| A4 | OpenAI-compat (`server/compat/`) never persists/reads `Conversation` (grep: zero matches). | Access Inventory E | If compat later creates conversations, isolation must extend there. Currently N/A. |

**If this table is empty:** N/A — confirm A1 and A2 with the user/executor before locking the plan.

## Open Questions

1. **PAT access to chat conversation endpoints (A1).**
   - What we know: chat views accept JWT + chat-key only; PAT class is not in their `authentication_classes`.
   - What's unclear: whether v0.2.0 wants PAT-authenticated callers to access *their own* conversations via the chat API (would require adding `AccessTokenAuthentication` to chat views).
   - Recommendation: Keep scope as-is (web/JWT isolation) per CONTEXT ("Web AI 对话路径"); explicitly note PAT-on-chat = anonymous/open. Raise to user if PAT chat access is desired.

2. **`accounts.User` ordering field for earliest-superuser (A2).**
   - Recommendation: Executor greps `accounts/models.py` and uses the real timestamp field; both `date_joined` and `created_at` are valid orderings.

3. **Null-owner conversations after backfill.**
   - What we know: post-backfill, only future anonymous/open-mode rows stay null.
   - Recommendation: Authed users do not see null-owner rows (filter excludes them) — confirm this is the intended open-mode artifact behavior (it matches CONTEXT). No action needed.

## Environment Availability

SKIPPED — pure code/config/migration change with no new external tools, services, or runtimes.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio + pytest-django 4.8 |
| Config | `server/pyproject.toml` ([tool.pytest]); `server/tests/conftest.py` (fixtures: `db`, `project`, `frozen_conversation_factory`, `user_and_token`, `auth_headers`) |
| Test style | `@pytest.mark.django_db(transaction=True)` async classes; `django.test.AsyncClient`; JWT via `RefreshToken.for_user(user)` → `headers={"authorization": f"Bearer {token}"}` |
| Quick run | `cd server && uv run pytest tests/test_conversation_isolation.py -x` |
| Full chat suite | `cd server && uv run pytest tests/test_chat_views.py tests/test_conversation_integration.py tests/test_conversation_facade.py tests/test_coding_session*.py -q` |
| Migration check | `cd server && uv run python manage.py makemigrations --check --dry-run` |

### Phase Requirements → Test Map
An isolation phase MUST have an **explicit cross-user-denied test for every access path** (ISO-04 is all-or-nothing).
| Req | Behavior | Test Type | Automated Command | Exists? |
|-----|----------|-----------|-------------------|---------|
| ISO-01 | `created_by` set on authed create | integration | `pytest tests/test_conversation_isolation.py::test_create_sets_owner -x` | ❌ Wave 0 |
| ISO-01 | backfill assigns earliest superuser; no-superuser→NULL; reversible | migration | `pytest tests/test_conversation_isolation.py::test_backfill_*` (use `django_test_migrations` style or direct `forwards`/`backwards` call) | ❌ Wave 0 |
| ISO-02 | owner sees only own in list (#1) | integration | `::test_list_only_owner` | ❌ Wave 0 |
| ISO-02 | owner can detail/runtime/patch/delete/stream/fork own (#3,5,7,4,10,9) | integration | `::test_owner_can_access_*` | ❌ Wave 0 |
| ISO-03 | superuser (as authed user) does NOT see others' (no bypass) | integration | `::test_admin_no_bypass` | ❌ Wave 0 |
| ISO-04 | cross-user → 404 for EVERY endpoint #3–25 (parametrized) | integration | `::test_cross_user_denied[endpoint]` | ❌ Wave 0 |
| ISO-04 | 404 body identical to "not found" (non-enumerable) | integration | `::test_404_indistinguishable` | ❌ Wave 0 |
| ISO-04 | SSE stream rejected before stream opens (HTTP 404, not SSE error event) | integration | `::test_stream_cross_user_404` | ❌ Wave 0 |
| compat | open-mode/anonymous unchanged (auth off → still works) | regression | `::test_open_mode_unaffected` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_conversation_isolation.py -x`
- **Per wave merge:** full chat suite (above) + `makemigrations --check`
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_conversation_isolation.py` — NEW; parametrized cross-user-denied across all 25 endpoints + owner-allowed + admin-no-bypass + open-mode + backfill. Covers ISO-01..04.
- [ ] Fixture updates: extend `frozen_conversation_factory` (conftest L811) and `_create_conversation` helpers to accept/set `created_by`. Add a `second_user` + second-user-JWT fixture for cross-user tests.
- [ ] No framework install needed (pytest stack present).

### Regression Surface (existing tests that will break / need updating)
| File | Why it breaks | Fix |
|------|---------------|-----|
| `tests/test_conversation_integration.py` | Creates conversations via authed POST → will now auto-set `created_by`; GET-by-same-user OK, but any direct-ORM `Conversation.create` then authed GET → 404 | Ensure created rows owned by the requesting user |
| `tests/test_conversation_facade.py` | `_create_conversation(project)` builds owner-less rows; facade `send_message_stream` tests call service directly (no `request.user`) — fine if service `aget` stays unscoped internally, but if owner gate added to service, set `created_by` | Set `created_by` in helper or keep service `send_message_stream` owner-agnostic (gate in view) |
| `tests/test_coding_session*.py` (`test_coding_session.py`, `test_coding_session_service.py`, `test_coding_session_graph*.py`, `test_coding_session_graph_e2e.py`) | Create `Conversation`/`CodingSession` without owner; new owner gate on coding-session endpoints (#13–23) → 404 for unauthed/cross-user | Set `created_by` on the conversation used; assert cross-user denial separately |
| `conftest.py::frozen_conversation_factory` (L811), `frozen_conversation_factory` callers | Owner-less rows | Add `created_by` passthrough (forward-compatible **overrides style already used**) |
| `tests/test_chat_views.py` | Only tests `completions/` + `models/` (no Conversation) | No change expected (group E) — verify still green |
| `tests/test_conversation_resolved_provider_chain.py` | Creates conversations for provider-chain assertions | Set `created_by` if it hits owner-gated detail endpoint |

## Security Domain

### Applicable ASVS Categories (Level 1, `security_enforcement: true`)
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (relies on) | Phase 7 `request.user` = owner; this phase consumes it, doesn't change auth |
| V3 Session Management | no | unchanged |
| V4 Access Control | **yes (core)** | Owner-scoped queryset filtering; deny-by-default for authed users; no horizontal privilege escalation (IDOR) |
| V5 Input Validation | partial | conversation_id is path UUID (Django `<uuid:>` converter validates) |
| V6 Cryptography | no | none |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR — read/act on another user's conversation by guessing/knowing UUID (#3–25) | Elevation of Privilege / Information Disclosure | Owner-scoped queryset → object never materializes for non-owner |
| Existence enumeration via 403-vs-404 distinction | Information Disclosure | Uniform 404 for missing AND not-owned (ISO-04) |
| Admin over-reach in normal chat UI | Elevation of Privilege | No superuser bypass in owner gate (ISO-03); cross-user admin browsing deferred to Phase 9 |
| SSE info leak after stream opens | Information Disclosure | Gate in view before `StreamingHttpResponse` |
| Coding-session/plan/trace lateral access (currently `IsAuthenticated`-only) | Elevation of Privilege | Resolve `.conversation` → owner gate → 404 (#13–25) |

## Sources

### Primary (HIGH confidence) — codebase, read directly
- `server/chat/models.py` — `Conversation` (no `created_by`; `project` FK, `status`, `is_deleted`, `ordering=-updated_at`), related models (`Message`, `CodingSession`, `CodingPlan`, `RepositoryRoutingTrace`, `ConversationIntentTrace`)
- `server/chat/views.py` — all 25 endpoints + existing `has_project_access`/`IsAuthenticated` patterns
- `server/chat/conversation_service.py` — `list_conversations`, `create_conversation`, `get_conversation_with_messages`, `get_conversation_runtime`, `delete_conversation`, `fork_conversation_before_message`, `send_message_stream`
- `server/chat/urls.py` — route map; `server/chat/streaming.py` — SSE helpers (no consumer)
- `server/chat/permissions.py` (`ChatAuthPermission`), `server/chat/authentication.py` (`OptionalJWTAuthentication`, `ChatKeyAuthentication`)
- `server/friday/asgi.py` — WS routing (runners+workflows only; no chat consumer)
- `server/friday/settings.py` L273-278 — `DEFAULT_AUTHENTICATION_CLASSES` (PAT-first); `server/access_tokens/authentication.py` (PAT prefix gate)
- `server/accounts/migrations/0005_backfill_user_source.py`, `server/workflows/migrations/0018_backfill_execution_project.py` — RunPython backfill patterns
- `server/chat/migrations/` (latest `0017_message_parts.py`) — next migration is 0018
- `server/tests/conftest.py` (fixtures), `test_chat_views.py`, `test_conversation_integration.py`, `test_conversation_facade.py` — test patterns + regression surface
- `.planning/phases/07-ident/07-02-SUMMARY.md` — Phase 7 `request.user` = owner

### Secondary (MEDIUM) — grep verification
- `server/compat/**` — zero `Conversation` references (compat is conversation-free)
- repo-wide consumer search — only `runners/` + `workflows/` Channels consumers

### Tertiary (LOW)
- None — all claims grounded in source.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; all primitives already used in `chat/`
- Architecture / access-path inventory: HIGH — every endpoint read from `views.py`/`urls.py`
- Migration/backfill: HIGH — two in-repo precedents; one field-name confirmation needed (A2)
- Pitfalls: HIGH — derived from existing code (project-check bypass, async FK access, SSE timing)
- Auth nuance (A1): MEDIUM — inferred from `authentication_classes` override; recommend user confirmation

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable internal codebase; revalidate if chat auth classes or compat change)
