# Phase 9: 管理员会话管理后台（只读） - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous，推荐项已采纳；用户已授权代为决策）

<domain>
## Phase Boundary

在 Phase 8 把普通 AI 对话界面锁成「只看自己」之后，给管理员一个**独立的只读会话管理后台**：可浏览所有用户的会话（区别于普通 AI 对话界面），后台只读不能直接在他人会话上续聊/交互；管理员如需基于他人会话交互，可 fork 一份归到自己名下后再用普通对话界面进行。

覆盖 ADMVW-01..03。依赖 Phase 8 的隔离语义与 owner 维度。**不在本期**：绑定执行/RemoteTool（Phase 10/11）。
</domain>

<decisions>
## Implementation Decisions

### 后端 API（ADMVW-01 / ADMVW-02 / ADMVW-03）
- 新增**独立的 admin 会话端点**（如 `/api/admin/conversations/`），与 Phase 8 锁定的普通 `/api/conversations/` 路径分离，互不影响：
  - list：跨用户列出所有会话（含 owner、title、project、status、updated_at、消息数等元数据），支持按 owner/关键字/分页过滤（分页与现有列表一致）。
  - detail（只读）：返回会话 + 消息用于只读查看。
  - **只读**：admin 端点不提供 patch/send-message/stream/delete 等写操作（ADMVW-02）；管理员不能在他人会话上续聊。
  - fork-to-own：新增 admin fork 端点，把任意会话**整份复制**为一份 `created_by = request.user`（发起的管理员）的新会话，返回新会话 id；之后管理员经普通对话界面以 owner 身份续聊（ADMVW-03）。该 fork 与 Phase 8 的 `fork_conversation_before_message`（继承源 owner、用于编辑消息流）**不同**：admin fork 显式归属到当前管理员。
- 权限：admin 端点用管理员权限类（沿用代码库既有 admin 约定 —— DRF `IsAdminUser`/`is_staff` 或项目自有 admin permission；planner/research 确认实际用法）。非管理员访问 403。
- 审计/隔离：admin 只读浏览不改变 Phase 8 普通路径的 owner 过滤；admin 端点是平行的、显式管理员授权的入口。

### 前端（ADMVW-01）
- 新增管理员页面 `web/src/pages/admin/conversations.vue`（路由 meta `requiresAdmin: true`，与 `admin/users.vue` 一致）。
- 用既有 `PageContainer` + `PageHeader` + `DataTable` 组件：表格列出所有会话（owner、标题、项目、状态、更新时间、消息数），支持搜索/分页。
- 只读会话查看：点开某会话以**只读**方式查看消息（无输入框/发送/编辑/删除入口）。reuse 现有消息渲染组件（只读模式）或最小只读列表。
- 每行/详情提供「fork 到我的名下」操作：调用 admin fork 端点 → 成功后跳转到普通对话界面（chat）以 owner 身份续聊。
- 入口挂到 admin 导航（与 users/providers/oidc 等并列）。

### Claude's Discretion
- admin 列表的具体过滤/分页参数、只读详情是复用 chat 的消息组件还是新建轻量只读视图、fork 后是否自动跳转/弹确认，由实现按既有 admin 页面与 chat 组件风格决定。
- admin 端点放在 chat app 还是新建 admin 模块，由 planner 决定（建议复用 chat app + 独立 admin views/urls 命名空间）。
- 测试组织（`test_admin_conversations.py` 等）。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- 后端：`server/chat/models.py`（`Conversation.created_by` 已于 Phase 8 加入）、`server/chat/conversation_service.py`（owner-scoped 取数 + fork 逻辑可参照）、`server/chat/views.py`（会话端点群）、`server/chat/serializers.py`（`ConversationListSerializer` / `ConversationDetailSerializer`）。
- 权限：`server/accounts/permissions.py`、`server/permissions/api_permissions.py`、`server/system/permissions.py`（admin 权限类来源待 research 确认）。
- 前端：`web/src/pages/admin/users.vue`（最近的 admin 列表分析样板：`definePage({ meta:{ requiresAdmin:true }})` + `DataTable` + `PageHeader` + `PageContainer` + `useErrorHandler`/`useToast`）、`web/src/pages/admin/index.vue`、`web/src/components/common/DataTable.vue`、`web/src/api/*`（api 模块约定）、chat 消息渲染组件（只读复用）。

### Established Patterns
- admin 路由 meta `requiresAdmin: true`；前端 api 模块 + TanStack Table。
- adrf 异步 view + `sync_to_async`；序列化器复用。
- Phase 8 的 owner 维度与 fork 语义。

### Integration Points
- admin 导航入口（admin 布局/菜单）。
- fork → 跳转普通 chat 页面（owner 续聊）。
- 既有测试：`server/tests/test_chat_views.py`、`test_conversation_isolation.py`（确保 admin 端点不破坏普通路径隔离）。
</code_context>

<specifics>
## Specific Ideas

- 后台「只读 + fork 到自己名下再交互」是里程碑锁定决策：避免管理员直接在他人会话写入造成归属混乱。
- 与普通对话界面**物理分离**的 admin 端点，是同时满足「管理员能看全部（ADMVW-01）」与 Phase 8「所有人默认只看自己（ISO-03）」的关键。
</specifics>

<deferred>
## Deferred Ideas

- 绑定令牌执行 / RemoteTool（Phase 10/11）。
- admin 会话的导出/批量操作、审计可视化（本期不做）。
</deferred>
