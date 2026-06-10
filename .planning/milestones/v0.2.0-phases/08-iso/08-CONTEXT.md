# Phase 8: 对话/会话用户隔离 - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，推荐项已采纳；用户已授权代为决策）

<domain>
## Phase Boundary

给 `Conversation` 增加创建者维度并在所有访问路径上施加 owner 隔离：每个会话记录 `created_by`；普通用户与管理员在 AI 对话界面默认只能访问自己的会话；越权访问（含 SSE/WebSocket 流式入口与对象级操作）安全拒绝、不泄漏会话存在性。

覆盖 ISO-01..04。依赖 Phase 7 的可靠用户身份（`request.user` = 认证用户/PAT owner）。**不在本期**：管理员只读后台（Phase 9）、绑定执行（Phase 10/11）。
</domain>

<decisions>
## Implementation Decisions

### 模型与迁移（ISO-01）
- `Conversation` 新增 `created_by = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="conversations")`。
  - `null=True`：兼容历史数据与「鉴权关闭/匿名/compat」入口创建的无主会话，且用户删除时不级联删除会话。
- 数据迁移：历史无主会话 `created_by` 回填给最早的 superuser（`User.objects.filter(is_superuser=True).order_by("date_joined","id").first()`）；若无 superuser 则留空（不阻塞迁移）。回填用 schema-migration + RunPython（与里程碑决策一致）。
- 新建会话时 `created_by = request.user`（仅当 `request.user` 已认证；匿名/鉴权关闭场景保持 null）。

### owner 过滤（ISO-02 / ISO-03）
- 在 `ConversationService` / 会话查询的统一 queryset 入口按 `created_by=request.user` 过滤，覆盖全部路径：list / detail / runtime / stream(SSE) / patch / delete / fork。
- 管理员（is_staff/superuser）在 AI 对话界面**不**做特权 bypass，与普通用户一致只看自己（ISO-03）；管理员跨用户浏览能力放到 Phase 9 的独立只读后台。
- 仅对「已认证用户」施加过滤；当 `request.user` 未认证（鉴权开关关闭的开放模式 / chat-key / compat）时维持既有行为，不在本期改变开放语义（隔离语义以「有用户身份」为前提，flagged below）。

### 越权拒绝（ISO-04）
- 对象级访问他人会话一律返回 **404**（而非 403），避免泄漏会话是否存在（不可枚举）。统一在对象获取处用「owner 过滤后的 queryset + get_object_or_404 语义」实现，杜绝先取后判的存在性泄漏。
- SSE / WebSocket 流式入口（runtime/stream）在建立连接/取会话时同样走 owner 过滤；越权连接被拒（HTTP 404 / WS close），不开流。
- fork 他人会话同样按 owner 过滤拒绝（fork 自己会话在 Phase 9 才允许「管理员 fork 他人」——本期 fork 仅限自己）。

### Claude's Discretion
- queryset 过滤的具体落点（在 `ConversationService` 方法签名加 `user` 参数 vs 在 view 层统一注入）、对象级 404 的实现样式、WebSocket consumer 的 owner 校验位置，由实现按既有结构决定。
- 是否对 Message 子资源单独加 owner 校验（应通过其 Conversation 的 owner 间接保证）。
- 测试组织（新增 `test_conversation_isolation.py` vs 扩展既有 `test_chat_views.py` / `test_conversation_integration.py`）。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `server/chat/models.py`（`Conversation` 当前无 `created_by`；有 `project` FK、`status`、`is_deleted` 软删、`ordering=["-updated_at"]`）。
- `server/chat/views.py`（adrf APIView 群：list/detail/runtime/stream/patch/delete/fork；用 `ConversationService`）。
- `server/chat/conversation_service.py`（`ConversationService` —— 会话 CRUD/查询集中点，过滤最佳落点）。
- `server/chat/permissions.py`（`ChatAuthPermission` —— 可配置鉴权开关 `CHAT_AUTH_ENABLED`，默认开放）。
- `server/chat/authentication.py`（`ChatKeyAuthentication`、`OptionalJWTAuthentication`）。
- Phase 7 成果：`request.user` 现在对 PAT/JWT 均是真实 owner。

### Established Patterns
- adrf 异步 view + `sync_to_async` 桥接 ORM；软删 `is_deleted`。
- 既有迁移在 `server/chat/migrations/`（最新 0017）。

### Integration Points
- WebSocket consumer（流式）—— 确认会话流入口的鉴权与 owner 校验位置（`server/chat/streaming.py` / consumers / routing）。
- compat（OpenAI 兼容）入口是否经 Conversation —— research 需确认是否受影响。
- 既有测试：`server/tests/test_chat_views.py`、`test_conversation_integration.py`、`test_coding_session_*`。
</code_context>

<specifics>
## Specific Ideas

- 404-not-403 是 ISO-04 的关键：不可泄漏他人会话是否存在；owner 过滤后的 queryset + 404 是标准防枚举手法。
- 历史回填给最早 superuser 是里程碑锁定决策（Conversation 无 owner 字段时最稳妥归属）。
</specifics>

<deferred>
## Deferred Ideas

- 管理员只读会话管理后台 + fork 他人会话（Phase 9）。
- 鉴权关闭/匿名开放模式下的隔离语义细化（本期保持既有开放行为，隔离以「有用户身份」为前提）。
</deferred>

<open_decisions>
## 需里程碑层面知悉的取舍（已按推荐采纳，可随时纠偏）

- **开放/匿名模式**：当 `CHAT_AUTH_ENABLED` 关闭或经 chat-key/compat 无 `request.user` 身份时，本期不强加 owner 隔离（维持既有开放行为）。隔离严格生效于「有认证用户身份」的 Web AI 对话路径。若需对开放模式也强隔离，请提出——会显著改变开放部署语义。
</open_decisions>
