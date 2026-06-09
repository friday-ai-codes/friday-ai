# Phase 9: 管理员会话管理后台（只读） - Research

**Researched:** 2026-06-09
**Domain:** Django adrf 异步 REST + DRF 权限（is_superuser）+ Vue 3 admin 页面（reka-ui / DataTable）+ 会话深拷贝服务
**Confidence:** HIGH（全部结论基于本仓库源码逐行核对，无外部依赖）

## Summary

Phase 9 在 Phase 8（会话 owner 隔离，普通 `/api/chat/conversations/` 全路径 owner-gate）之上，新增一个**物理分离的管理员只读后台**：一组用 `IsSuperUser` 守门的 admin 端点（跨用户列会话 / 只读看消息 / fork 到自己名下），加一个前端 `web/src/pages/admin/conversations.vue` 页面。关键设计是**不碰 Phase 8 锁定的普通端点与 owner-gate 服务方法**——admin 路径走全新的 view/service 方法，显式跳过 owner 过滤，由 `IsSuperUser` 权限类（而非 owner gate）授权。

核心事实已核实：本仓库"管理员"= `is_superuser`。前端路由 meta `requiresAdmin: true` 在 `web/src/main.ts:117` 映射到 `authStore.isAdmin`，后者在 `web/src/stores/auth.ts:30` 定义为 `user.is_superuser`。后端 admin 端点的标准约定是 `permission_classes = [IsSuperUser]`（`server/permissions/api_permissions.py:21`），被 `system/runners/repositories` 等多处采用；非管理员被该类拒绝返回 **403**（注意：与 Phase 8 越权 **404** 的"不泄漏存在性"语义不同——admin 入口是显式管理员授权入口，403 是正确语义）。

Admin fork-to-own 必须是一个**新的** `ConversationService` 方法，区别于 `fork_conversation_before_message`（后者继承源 owner、只拷贝目标消息之前的历史，用于编辑消息流）。Admin fork 整份拷贝会话 + 全部消息，并把 `created_by` 设为发起的管理员，status 重置为 `draft`，之后管理员经普通 `/chat` 界面以 owner 身份续聊。

**Primary recommendation:** 新建 `server/chat/admin_views.py` + `server/chat/admin_urls.py`，挂到 `/api/admin/conversations/`（`server/friday/urls.py` 加一行 `path("admin/", include("chat.admin_urls"))`）；三个 adrf APIView 全部 `permission_classes = [IsSuperUser]`、走默认认证（PAT + CookieJWT）。新增 `ConversationService.admin_list_conversations()` / `admin_fork_to_own()` 两个**显式无 owner 过滤**的 staticmethod，绝不复用/修改 Phase 8 的 `aget_for_user` / `list_conversations`。前端复用 `users.vue` 的 `PageContainer + PageHeader + DataTable` 样板 + 新建 `web/src/api/adminConversations.ts`，只读详情用轻量自建 viewer（不复用 store 耦合的 `ChatMessageArea`），fork 成功后跳 `/chat?conversation=<newId>`。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 新增**独立的 admin 会话端点**（如 `/api/admin/conversations/`），与 Phase 8 锁定的普通 `/api/conversations/` 路径分离，互不影响：
  - list：跨用户列出所有会话（含 owner、title、project、status、updated_at、消息数等元数据），支持按 owner/关键字/分页过滤（分页与现有列表一致）。
  - detail（只读）：返回会话 + 消息用于只读查看。
  - **只读**：admin 端点不提供 patch/send-message/stream/delete 等写操作（ADMVW-02）；管理员不能在他人会话上续聊。
  - fork-to-own：新增 admin fork 端点，把任意会话**整份复制**为一份 `created_by = request.user`（发起的管理员）的新会话，返回新会话 id；之后管理员经普通对话界面以 owner 身份续聊（ADMVW-03）。该 fork 与 Phase 8 的 `fork_conversation_before_message`（继承源 owner、用于编辑消息流）**不同**：admin fork 显式归属到当前管理员。
- 权限：admin 端点用管理员权限类（沿用代码库既有 admin 约定 —— DRF `IsAdminUser`/`is_staff` 或项目自有 admin permission；planner/research 确认实际用法）。非管理员访问 403。
- 审计/隔离：admin 只读浏览不改变 Phase 8 普通路径的 owner 过滤；admin 端点是平行的、显式管理员授权的入口。
- 前端：新增管理员页面 `web/src/pages/admin/conversations.vue`（路由 meta `requiresAdmin: true`，与 `admin/users.vue` 一致）。用既有 `PageContainer` + `PageHeader` + `DataTable`；只读会话查看（无输入框/发送/编辑/删除入口）；每行/详情提供「fork 到我的名下」→ 调 admin fork 端点 → 成功后跳转普通对话界面（chat）以 owner 身份续聊；入口挂到 admin 导航。

### Claude's Discretion
- admin 列表的具体过滤/分页参数、只读详情是复用 chat 的消息组件还是新建轻量只读视图、fork 后是否自动跳转/弹确认，由实现按既有 admin 页面与 chat 组件风格决定。
- admin 端点放在 chat app 还是新建 admin 模块，由 planner 决定（建议复用 chat app + 独立 admin views/urls 命名空间）。
- 测试组织（`test_admin_conversations.py` 等）。

### Deferred Ideas (OUT OF SCOPE)
- 绑定令牌执行 / RemoteTool（Phase 10/11）。
- admin 会话的导出/批量操作、审计可视化（本期不做）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADMVW-01 | 管理员有专门的「会话管理」后台视图，可浏览所有用户的会话（区别于普通 AI 对话界面） | 新增 `AdminConversationListView`（`IsSuperUser`，跨用户 list，无 owner 过滤）+ `web/src/pages/admin/conversations.vue`（DataTable，列 owner/title/project/status/updated_at/消息数） |
| ADMVW-02 | 该后台视图只读，管理员不能直接在他人会话上续聊/交互 | admin 端点仅暴露 GET（list/detail）+ 一个 POST fork；不提供 patch/stream/delete/send-message。前端只读 viewer 无输入框 |
| ADMVW-03 | 管理员如需基于他人会话交互，可 fork 一份归属到自己名下后再进行 | 新增 `AdminConversationForkView` + `ConversationService.admin_fork_to_own()`（深拷贝会话+消息，`created_by=request.user`，status=draft）→ 返回新 id → 前端跳 `/chat?conversation=<id>` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 跨用户会话列举（含 owner 元数据 + 消息数） | API / Backend | Database | 必须在后端用 `is_superuser` 授权 + 显式无 owner 过滤的 queryset；前端无权决定可见性（否则等于绕过 Phase 8 隔离） |
| 只读会话详情（会话 + 消息） | API / Backend | — | 取数走后端；前端仅渲染，无写入口 |
| Admin 权限判定 | API / Backend | — | `IsSuperUser` 权限类在 DRF 层判定；前端 `requiresAdmin` 守卫只是 UX 兜底，非安全边界 |
| Admin fork-to-own（深拷贝 + 改 owner） | API / Backend (Service) | Database | 写操作必须服务端完成；`created_by=request.user` 由服务端从认证态取，前端不可传 |
| 只读消息渲染 | Browser / Client | — | 纯展示；自建轻量 viewer，避免复用 store 耦合的 chat 组件 |
| Admin 导航入口 | Browser / Client | — | `AppSidebar.vue` `adminNavItems` 数组追加一项，`v-if="isSystemAdmin"` 已有 |
| fork 后跳转续聊 | Browser / Client | — | `router.push('/chat?conversation=<id>')`；普通 chat 路径以 owner 身份接管 |

## Standard Stack

本期**不引入任何新依赖**。全部复用既有栈。

### Core（全部 [VERIFIED: codebase]）
| 能力 | 既有资产 | 位置 | 用途 |
|------|---------|------|------|
| 管理员权限类 | `IsSuperUser` | `server/permissions/api_permissions.py:21` | admin 端点 `permission_classes`，非管理员 → 403 |
| 异步 view 基类 | `adrf.views.APIView` | `server/chat/views.py:8` | admin 端点继承，`async def get/post` |
| owner 服务（**仅参照，勿改**） | `ConversationService` | `server/chat/conversation_service.py:693` | 新增 admin 方法，不动 `aget_for_user`/`list_conversations` |
| fork 参照实现 | `fork_conversation_before_message` | `server/chat/conversation_service.py:751` | admin fork 的拷贝逻辑范本（deepcopy 消息字段） |
| 会话 / 消息模型 | `Conversation` / `Message` | `server/chat/models.py:21` | `created_by`（`:50` SET_NULL）、status（`:24`） |
| 消息序列化 | `ConversationMessageSerializer` | `server/chat/serializers.py:202` | admin 只读详情的 messages 直接复用 |
| 前端 admin 列表样板 | `users.vue` | `web/src/pages/admin/users.vue` | `definePage requiresAdmin` + DataTable + PageHeader + PageContainer |
| 通用表格 | `DataTable.vue` | `web/src/components/common/DataTable.vue` | TanStack Table 封装 |
| 前端 api 模块约定 | `users.ts` / `chat.ts` | `web/src/api/` | `get/post` from `./client`，默认导出对象 |
| admin 导航 | `adminNavItems` | `web/src/components/layout/AppSidebar.vue:54` | 追加 `/admin/conversations` 入口 |
| 路由守卫 | `to.meta.requiresAdmin && !authStore.isAdmin → /403` | `web/src/main.ts:117` | `isAdmin = user.is_superuser`（`web/src/stores/auth.ts:30`） |

### Supporting
| 资产 | 位置 | 何时用 |
|------|------|--------|
| `usePermission().isSystemAdmin` | `web/src/composables/usePermission.ts:12` | sidebar `v-if`（已有）/页面内角色判定 |
| `useErrorHandler` / `useToast` | `web/src/composables/` | 列表加载失败 / fork 成功提示（users.vue 同款） |
| `chatStore.selectConversation` + URL `?conversation=` | `web/src/stores/chat.ts:244` / `:1958` | fork 后 `/chat?conversation=<id>` 续聊 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `IsSuperUser` 权限类 | accounts 风格内联 `if not request.user.is_superuser: 403`（`server/accounts/views.py:305`） | 内联更随意；`IsSuperUser` 是 system/runners/repositories 的统一约定，更一致、可测，**推荐** |
| 新建 `chat/admin_views.py`+`admin_urls.py` 挂 `/api/admin/` | 直接在 `chat/urls.py` 加 `admin/conversations/` 路径 | 后者污染普通 chat urlconf；前者物理分离更清晰，符合 CONTEXT「独立 admin views/urls 命名空间」，**推荐** |
| 自建轻量只读 viewer | 复用 `ChatMessageArea.vue`/`ChatMessageBubble.vue` | chat 组件深度耦合 `useChatStore()`（`ChatMessageArea.vue:26`）、含发送/编辑/cleanup 入口，read-only 复用代价高且易引入写路径，**推荐自建** |

**Installation:** 无。`npm install` / `uv add` 均不需要。

## Package Legitimacy Audit

不适用——本期不安装任何外部包（纯复用既有栈）。Step 1-4 包合法性门禁跳过。

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────── Browser (admin) ───────────────────────┐
                    │  /admin/conversations  (requiresAdmin meta → isAdmin guard)    │
                    │   PageContainer+PageHeader+DataTable                           │
                    │      │ list                  │ open row(只读)     │ fork按钮     │
                    └──────┼──────────────────────┼───────────────────┼────────────┘
                           │ GET                   │ GET               │ POST
                           ▼                       ▼                   ▼
        ┌──────────────────────────── /api/admin/conversations/ ──────────────────────────┐
        │ AdminConversationListView    AdminConversationDetailView   AdminConversationForkView│
        │ permission_classes = [IsSuperUser]  (非admin → 403)  默认认证(PAT+CookieJWT)        │
        └──────┬───────────────────────────┬──────────────────────────────┬────────────────┘
               │                            │                              │
               ▼                            ▼                              ▼
   ConversationService.admin_list_*   Conversation.objects.aget    ConversationService.admin_fork_to_own
   (NO owner filter,                  (NO owner filter, by id)      (deepcopy conv+messages,
    annotate message_count,                                          created_by=admin, status=draft)
    select_related created_by,project) ──► Message.objects.filter   ──► 返回 new conversation id
               │                            (order_by created_at)              │
               ▼                                                               ▼
   AdminConversationListSerializer    ConversationMessageSerializer    {id: <new>} → 前端 router.push
   (owner_id/owner_username/title/                                     /chat?conversation=<new>
    project/status/updated_at/msg_count)                                      │
                                                                              ▼
                                              ┌──────── 普通 /api/chat/conversations/* ────────┐
                                              │ Phase 8 owner-gate（aget_for_user）保持不变      │
                                              │ admin 现在是该 fork 的 created_by → 以 owner 续聊 │
                                              └────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
server/chat/
├── admin_views.py       # 新增：AdminConversationListView / DetailView / ForkView (IsSuperUser)
├── admin_urls.py        # 新增：conversations/ , conversations/<id>/ , conversations/<id>/fork/
├── conversation_service.py  # 改：新增 admin_list_conversations() / admin_fork_to_own()（勿动 Phase 8 方法）
├── serializers.py       # 改：新增 AdminConversationListSerializer（+owner+message_count）
server/friday/urls.py    # 改：api_patterns 加 path("admin/", include("chat.admin_urls"))
server/tests/
└── test_admin_conversations.py  # 新增：非admin 403 / admin 跨用户可见 / 只读无写 / fork 归属

web/src/
├── pages/admin/conversations.vue       # 新增：列表 + 只读详情（drawer/dialog 或子视图）
├── api/adminConversations.ts           # 新增：listAdminConversations/getAdminConversationDetail/forkAdminConversation
├── components/layout/AppSidebar.vue     # 改：adminNavItems 加一项
└── types/...                            # 新增 AdminConversation 类型
```

### Pattern 1: Admin adrf APIView with IsSuperUser
**What:** 异步 view，`permission_classes = [IsSuperUser]`，依赖默认认证类（PAT+CookieJWT，见 STATE [07-02]）。不要照抄普通 chat view 的 `authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]` + `ChatAuthPermission`（那是开放/匿名模式专用）。
**When to use:** 所有三个 admin 端点。
**Example:**
```python
# Source: 综合 server/runners/views.py:57 (IsSuperUser 用法) + server/chat/views.py (adrf APIView)
from adrf.views import APIView
from rest_framework.permissions import IsAuthenticated  # 仅示意
from permissions.api_permissions import IsSuperUser

class AdminConversationListView(APIView):
    """管理员跨用户会话列表（只读，ADMVW-01）。"""
    permission_classes = [IsSuperUser]  # 非 superuser → 403

    async def get(self, request):
        items = await ConversationService.admin_list_conversations(
            owner_id=request.query_params.get("owner"),
            keyword=request.query_params.get("q", ""),
            page=int(request.query_params.get("page", 1)),
            page_size=int(request.query_params.get("page_size", 20)),
        )
        return Response(AdminConversationListSerializer(items, many=True).data)
```

### Pattern 2: Admin list service — 显式 NO owner filter + 元数据聚合
**What:** 与 Phase 8 `list_conversations`（`conversation_service.py:1339`，对已认证用户加 `created_by=user`）**相反**——admin 方法不加任何 owner 过滤，但要 `select_related("created_by","project")` + `annotate(message_count=Count("messages"))` 以 async-safe 地拿 owner 名与消息数。
**When to use:** `admin_list_conversations`。
**Example:**
```python
# Source: 参照 conversation_service.py:1339 (list_conversations) 但去掉 owner gate
from django.db.models import Count

@staticmethod
async def admin_list_conversations(*, owner_id=None, keyword="", page=1, page_size=20):
    qs = (
        Conversation.objects.filter(is_deleted=False)
        .select_related("created_by", "project")
        .annotate(message_count=Count("messages"))
        .order_by("-updated_at")
    )
    if owner_id:
        qs = qs.filter(created_by_id=owner_id)
    if keyword:
        qs = qs.filter(title__icontains=keyword)
    start = (page - 1) * page_size
    return [c async for c in qs[start:start + page_size]]
```
> 注：普通 `ConversationListView` 当前**无分页**（`views.py:333` 直接返回全量 list）。跨用户量更大，建议 admin list 用 `?owner=&q=&page=&page_size=` 手动切片（adrf APIView 非 DRF generics，无内置 paginator）。是否返回 total/分页元信息由实现决定（Claude's discretion）。

### Pattern 3: Admin fork-to-own — 整份深拷贝 + 改 owner + 重置 draft
**What:** 新 staticmethod，区别于 `fork_conversation_before_message`（`:751`）。
**When to use:** `admin_fork_to_own`。
**Example:**
```python
# Source: 改写自 conversation_service.py:751 fork_conversation_before_message
from copy import deepcopy

@staticmethod
async def admin_fork_to_own(conversation_id: str, admin_user) -> Conversation:
    # 管理员可 fork 任意会话：NOT owner-scoped（授权由 view 的 IsSuperUser 负责）
    source = await Conversation.objects.aget(id=conversation_id, is_deleted=False)

    fork_title = f"{source.title}（管理员副本）"[:200]
    forked = await Conversation.objects.acreate(
        project_id=source.project_id,
        title=fork_title,
        model=source.model,
        provider_credential_id_id=source.provider_credential_id_id,  # 续聊需要 provider 上下文
        created_by=admin_user,                       # ← 与 before_message fork 的关键差异
        status=Conversation.Status.DRAFT,            # ← 重置为草稿，管理员重新交互
    )
    # 拷贝全部消息（before_message fork 只拷贝 target 之前的；admin 拷贝全部）
    async for prior in Message.objects.filter(conversation=source).order_by("created_at"):
        await Message.objects.acreate(
            conversation=forked,
            role=prior.role,
            content=prior.content,
            tool_calls=deepcopy(prior.tool_calls),
            tool_call_id=prior.tool_call_id,
            metadata=deepcopy(prior.metadata),
            parts=deepcopy(prior.parts),
        )
    return forked
```
**只拷贝 Conversation + Message。** 不拷贝 `OrchestrationRun` / `CodingSession` / `CodingPlan` / `RepositoryRoutingTrace` / `ConversationIntentTrace`（这些是运行态/审计，复制会污染且无意义）。`status=draft` 确保新会话是干净可续聊态。

### Pattern 4: 前端只读 viewer（自建，不复用 store 组件）
**What:** admin 详情用轻量组件：遍历 `messages`，按 `role` 渲染气泡 + markdown 正文；无输入框/发送/编辑/删除。可参照 `ChatMessageBubble.vue` 的 markdown/parts 渲染思路，但不要直接挂载它（它读 `useChatStore`）。
**When to use:** `conversations.vue` 内点开某行 → drawer/dialog/子路由展示只读消息。

### Anti-Patterns to Avoid
- **复用 `ConversationService.aget_for_user` 给 admin 取数：** 它对已认证用户强加 `created_by=user`（`:713`），管理员会被自己 404。admin 必须用裸 `Conversation.objects.aget(id=...)`。
- **修改 `ConversationListSerializer` 加 owner 字段：** 普通 chat 路径与前端 store 依赖现有 shape；改它会回归 Phase 8。新建 admin 序列化器。
- **给 admin 端点用 404 表达"无权"：** Phase 8 用 404 防存在性泄漏；admin 入口是显式授权入口，`IsSuperUser` 拒绝就是 **403**（CONTEXT 明确要求 403）。
- **在前端传 `created_by`/owner 给 fork 端点：** owner 必须服务端从 `request.user` 取，避免越权伪造归属。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 管理员判定 | 自己查 `User.objects.filter(is_superuser=...)` | `IsSuperUser`（`api_permissions.py:21`） | 已有标准类，含未认证兜底 + 已被 `test_permissions.py:162` 覆盖 |
| 表格/排序/列定义 | 手写 `<table>` | `DataTable.vue` + TanStack `ColumnDef` | users.vue 同款，零成本一致体验 |
| 消息深拷贝字段 | 自己列字段 | 照抄 `fork_conversation_before_message` 的 deepcopy 字段集 | 漏 `parts`/`tool_calls` 会导致渲染缺失 |
| 错误处理/Toast | 自己 try/catch alert | `useErrorHandler` + `useToast` | users.vue 既有约定 |
| 续聊跳转 | 自己拼 chat 状态 | `router.push('/chat?conversation=<id>')` + `restoreFromURL`（`chat.ts:1958`） | chat 页已支持 `?conversation=` 恢复 |

**Key insight:** Phase 9 几乎是"组合既有积木"——风险点不在新技术，而在**别碰 Phase 8 锁定路径**。把 admin 逻辑严格隔离到新 view/service/serializer/url 文件里，回归面最小。

## Runtime State Inventory

> 本期为**新增功能**（greenfield 端点 + 页面），无 rename/refactor/migration，**不需要数据迁移**。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 无新增字段。`Conversation.created_by` 已由 Phase 8 落地（`models.py:50`，migration 0018/0019）。admin fork 写新行，不改既有数据 | None — 无迁移 |
| Live service config | 无 | None — 验证：admin 端点纯 DB 读 + 新建行 |
| OS-registered state | 无 | None |
| Secrets/env vars | 无 | None |
| Build artifacts | 无 | None — 仅新增 .py/.vue/.ts 文件 |

**无 schema 变更** → 本期不产生 Django migration（除非实现选择给 admin fork 加可选字段，当前设计不需要）。

## Common Pitfalls

### Pitfall 1: admin 端点误用 chat 的 OptionalJWT/ChatKey 认证
**What goes wrong:** 照抄 `ConversationListView` 的 `authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]` + `ChatAuthPermission`（`views.py:324`）。
**Why it happens:** 同 app 复制粘贴。那套是为"开放/匿名 chat 模式"设计的，会让匿名/ChatKey 请求进入。
**How to avoid:** admin 端点**不设** `authentication_classes`（用项目默认 PAT+CookieJWT），只设 `permission_classes = [IsSuperUser]`。参照 `server/runners/views.py:57`、`server/accounts/views.py`（MeView 等不写 authentication_classes）。
**Warning signs:** 匿名 curl 能拿到 admin 列表 / 200 而非 401。

### Pitfall 2: async 上下文惰性访问 FK 触发 SynchronousOnlyOperation
**What goes wrong:** 序列化时 `obj.created_by.username` 在 async view 里抛 `SynchronousOnlyOperation`。Phase 8 的 `ConversationListSerializer.get_provider_credential_id` 专门读 `_id` 列规避（`serializers.py:196`）。
**Why it happens:** adrf view 在 async 上下文，DRF 序列化器同步触发未预取的 FK。
**How to avoid:** service 层 `select_related("created_by","project")` 预取；序列化器用 `SerializerMethodField` 读已预取对象，或 view 内 `sync_to_async` 包裹序列化（参照 `accounts/views.py:192` `sync_to_async(lambda: Serializer(...).data)`）。
**Warning signs:** 测试报 `SynchronousOnlyOperation` / `You cannot call this from an async context`。

### Pitfall 3: message_count 用 Python len 而非 DB 聚合
**What goes wrong:** 每行会话 `[m async for m in messages]` 再 `len()` → N+1 查询，跨用户列表卡死。
**How to avoid:** `.annotate(message_count=Count("messages"))`（Conversation→Message 反向 related_name 见 `models.py`，Message FK 到 conversation）。
**Warning signs:** 列表端点随会话数线性变慢。

### Pitfall 4: fork 复制运行态导致脏数据
**What goes wrong:** 顺手复制 `OrchestrationRun`/`CodingSession`，新会话带着别人的运行态/PR 记录。
**How to avoid:** 只拷贝 `Conversation` + `Message`，`status=draft`。
**Warning signs:** 新 fork 会话进 chat 显示"运行中"/残留 coding 卡片。

### Pitfall 5: 回归 Phase 8 的 25 路径隔离套件
**What goes wrong:** 为方便给 `aget_for_user`/`list_conversations` 加 superuser 分支 → 直接违反 ISO-03（管理员在普通界面也只看自己），打破 `test_conversation_isolation.py::TestOwnerScoping::test_admin_no_bypass`（`:271`）。
**How to avoid:** admin 全走**新方法新端点**，普通方法一字不改。改完跑 `pytest server/tests/test_conversation_isolation.py`。
**Warning signs:** isolation 套件由绿转红。

## Code Examples

### Admin URL 挂载（物理分离）
```python
# server/chat/admin_urls.py（新增）
from django.urls import path
from .admin_views import (
    AdminConversationDetailView,
    AdminConversationForkView,
    AdminConversationListView,
)

urlpatterns = [
    path("conversations/", AdminConversationListView.as_view(), name="admin-conversation-list"),
    path("conversations/<uuid:conversation_id>/", AdminConversationDetailView.as_view(), name="admin-conversation-detail"),
    path("conversations/<uuid:conversation_id>/fork/", AdminConversationForkView.as_view(), name="admin-conversation-fork"),
]
```
```python
# server/friday/urls.py — api_patterns 内追加（与 :40 chat 并列）
path("admin/", include("chat.admin_urls")),   # → /api/admin/conversations/
```

### Admin 列表序列化器（含 owner + 消息数）
```python
# server/chat/serializers.py（新增；勿改既有 ConversationListSerializer）
class AdminConversationListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    space_id = serializers.UUIDField(source="project_id")
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    message_count = serializers.IntegerField()  # 来自 annotate
    owner_id = serializers.SerializerMethodField()
    owner_username = serializers.SerializerMethodField()
    owner_display_name = serializers.SerializerMethodField()

    def get_owner_id(self, obj):
        return str(obj.created_by_id) if obj.created_by_id else None

    def get_owner_username(self, obj):
        # created_by 已 select_related，async-safe
        return obj.created_by.username if obj.created_by_id else None

    def get_owner_display_name(self, obj):
        return getattr(obj.created_by, "display_name", "") if obj.created_by_id else ""
```

### 前端 api 模块
```typescript
// web/src/api/adminConversations.ts（新增）— 参照 web/src/api/users.ts 约定
import { get, post } from './client'

export interface AdminConversation {
  id: string
  title: string
  space_id: string
  status: string
  message_count: number
  owner_id: string | null
  owner_username: string | null
  owner_display_name: string
  created_at: string
  updated_at: string
}

export function listAdminConversations(params?: { owner?: string, q?: string, page?: number, page_size?: number }) {
  return get<AdminConversation[]>('/admin/conversations/', params as Record<string, string | number | undefined>)
}
export function getAdminConversationDetail(id: string) {
  return get<{ conversation: AdminConversation, messages: any[] }>(`/admin/conversations/${id}/`)
}
export function forkAdminConversation(id: string) {
  return post<{ id: string }>(`/admin/conversations/${id}/fork/`)
}
export default { listAdminConversations, getAdminConversationDetail, forkAdminConversation }
```

### 前端 sidebar 入口
```typescript
// web/src/components/layout/AppSidebar.vue — adminNavItems (:54) 追加
{ to: '/admin/conversations', label: '会话管理', icon: 'lucide--messages-square' },
```

### fork 后跳转续聊
```typescript
// conversations.vue 内
const { id } = await forkAdminConversation(row.id)
success('已 fork 到你的名下')
router.push(`/chat?conversation=${id}`)   // chat 页 restoreFromURL() 会 selectConversation(id)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 会话无 owner、所有人共享 | `Conversation.created_by` + 全路径 owner-gate | Phase 8（本里程碑） | Phase 9 必须在隔离之上做"管理员显式平行入口"，不能回退隔离 |
| 管理员靠 superuser bypass 看全部 | ISO-03 取消 bypass，管理员普通界面也只看自己 | Phase 8 [08-04] | Phase 9 的 admin 后台是替代 bypass 的合规入口 |

**Deprecated/outdated:** 无（功能为新增）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | admin fork `status` 重置为 `DRAFT` 且不拷贝运行态/coding/trace | Pattern 3 | 若用户期望"完整克隆含运行态"，需调整；但 CONTEXT 明确"归到自己名下再续聊"，draft 更合理。低风险（Claude's discretion 范围） |
| A2 | admin fork 拷贝 `provider_credential_id_id` + `model`（保留 provider 上下文） | Pattern 3 | 若源会话 pin 的凭证已禁用，续聊时普通路径会按四层解析回退（`ProviderConfigService`），不阻塞。低风险 |
| A3 | admin list 加 `?owner=&q=&page=&page_size=` 手动分页（现有普通 list 无分页） | Pattern 2 | 参数名/是否返回 total 属实现细节（Claude's discretion）。低风险 |
| A4 | 非管理员访问 admin 端点返回 **403**（IsSuperUser 语义），而非 Phase 8 的 404 | Summary/Anti-patterns | CONTEXT 明确要求 403；与隔离 404 语义不冲突（不同入口）。已确认，非真正假设 |

**说明：** A1–A3 落在 CONTEXT「Claude's Discretion」范围，可在 plan/实现阶段定稿，无需额外用户确认。

## Open Questions

1. **admin 只读详情是否展示 provider 解析链/routing trace？**
   - What we know: 普通 `ConversationDetailView.get`（`views.py:396`）会做四层 provider 解析 + routing trace + clarification 回灌（重）。
   - What's unclear: admin 只读是否需要这些。
   - Recommendation: **不需要**——admin 详情只返回 `{conversation, messages}`（轻量），降低耦合与查询成本。如需求方要求 provider 信息可后续加。

2. **fork 是否弹二次确认 dialog？**
   - Recommendation: 列表行内按钮直接 fork + Toast 即可（Claude's discretion）；如担心误触可用 reka-ui AlertDialog，参照 `CleanupDialog.vue` 风格。

## Environment Availability

> 纯代码/配置变更（新增端点 + 页面），无新增外部工具/服务依赖。
**Step 2.6: SKIPPED（no external dependencies identified）** — 复用既有 Django/Vue 栈、既有 DB 表、既有认证。

## Validation Architecture

> `workflow.nyquist_validation = true`（`.planning/config.json:20`）→ 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django>=4.8`（`server/pyproject.toml`） |
| Framework (frontend) | `vitest@^4` + `@vue/test-utils` + `happy-dom` |
| Config file | `server/pyproject.toml`（pytest/ruff）；前端 `web/vitest.config.*` |
| Quick run command | `cd server && uv run pytest tests/test_admin_conversations.py -x` |
| Full suite command | `cd server && uv run pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py` |
| 既有可复用脚手架 | `server/tests/conftest.py`：`superuser_and_token`/`superuser_auth_headers`（`:196`/`:211`）、`second_user_and_token`/`second_auth_headers`（`:171`/`:189`）、`project`（`:253`）；`test_conversation_isolation.py` 的 `owner_and_token`/`owner_headers`（`:149`/`:160`）+ `_acreate_conversation`/`_acreate_message`（`:58`/`:112`） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADMVW-01 | superuser GET list 能看到**他人**会话（owner 元数据 + message_count 正确） | integration | `pytest tests/test_admin_conversations.py -k admin_sees_all -x` | ❌ Wave 0 |
| ADMVW-01 | 非管理员（普通用户）GET admin list → **403** | integration | `pytest tests/test_admin_conversations.py -k non_admin_403 -x` | ❌ Wave 0 |
| ADMVW-01 | 匿名（无 token）GET admin list → 401 | integration | `pytest tests/test_admin_conversations.py -k anonymous -x` | ❌ Wave 0 |
| ADMVW-02 | admin 端点**不存在** patch/stream/delete（只读）；POST list(create)/DELETE detail → 404/405 | integration | `pytest tests/test_admin_conversations.py -k read_only -x` | ❌ Wave 0 |
| ADMVW-02 | superuser GET detail 返回 conversation+messages（他人会话也可读） | integration | `pytest tests/test_admin_conversations.py -k admin_detail -x` | ❌ Wave 0 |
| ADMVW-03 | superuser POST fork → 新会话 `created_by == admin`、status==draft、消息数==源 | integration | `pytest tests/test_admin_conversations.py -k fork_owner -x` | ❌ Wave 0 |
| ADMVW-03 | fork 后 admin 经普通 `/api/chat/conversations/<new>/` GET → 200（owner 续聊） | integration | `pytest tests/test_admin_conversations.py -k fork_then_owner -x` | ❌ Wave 0 |
| ADMVW-03 | 非管理员 POST fork → 403 | integration | `pytest tests/test_admin_conversations.py -k fork_non_admin -x` | ❌ Wave 0 |
| 回归 | Phase 8 隔离套件保持全绿（admin 端点不影响普通路径） | integration | `pytest tests/test_conversation_isolation.py` | ✅ 已存在 |
| 前端 | `conversations.vue` 含 `requiresAdmin` meta + DataTable 挂载 + fork 调用跳转 | unit | `cd web && pnpm vitest run src/pages/admin/__tests__/conversations.spec.ts` | ❌ Wave 0（参照 `codegraph/__tests__/playground.spec.ts:50` 校验 meta 的写法） |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/test_admin_conversations.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py`
- **Phase gate:** 后端两套全绿 + 前端 vitest 绿，再进 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/test_admin_conversations.py` — 覆盖 ADMVW-01/02/03 全部断言（非admin 403 / admin 跨用户可见 / 只读无写 / fork 归属 + status=draft + 消息数 / fork 后 owner 续聊 200）
- [ ] `web/src/pages/admin/__tests__/conversations.spec.ts` — requiresAdmin meta + DataTable + fork 跳转（参照 `playground.spec.ts`）
- [ ] 共享 fixtures **无需新建**：`conftest.py` 的 superuser/second/project + isolation 文件的 `_acreate_conversation`/`_acreate_message` 可直接复用（必要时把 helper 提到 conftest 或在新文件本地重定义）
- [ ] 框架安装：无需（pytest/vitest 已就绪）

## Security Domain

> `security_enforcement = true`，`security_asvs_level = 1`，`security_block_on = high`（`.planning/config.json:42`）。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | admin 端点物理分离 + 单一授权点 `IsSuperUser`；前端 `requiresAdmin` 仅 UX，安全边界在后端 |
| V2 Authentication | yes | 复用项目默认认证（PAT+CookieJWT，STATE [07-02]）；admin 端点不放宽认证（勿用 OptionalJWT/ChatKey） |
| V4 Access Control | **yes（核心）** | `IsSuperUser`（`api_permissions.py:21`）；越权（普通用户）→ 403、匿名→401。fork 的 owner 从 `request.user` 取，前端不可伪造 |
| V5 Input Validation | yes | `conversation_id` 用 `<uuid:...>` 路由约束；list `owner`/`q`/`page`/`page_size` 做类型/范围校验（page≥1，page_size 上限如 100，防大分页 DoS） |
| V6 Cryptography | no | 不涉及新加解密（凭证仍走既有 Fernet） |
| V7 Error/Logging | yes | admin 浏览/fork 落 structlog 审计事件（如 `admin_conversation_forked` owner_id/source_id）；勿在日志泄漏消息正文 |

### Known Threat Patterns for Django adrf + Vue admin
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 普通用户调 admin 端点查看/fork 他人会话 | Elevation of Privilege | `IsSuperUser` 权限类（服务端强制），测试断言 403 |
| 前端绕过 `requiresAdmin` 守卫直接打 API | Elevation of Privilege | 后端权限类是唯一真源；守卫只是 UX。测试用非 admin token 直打端点验证 403 |
| fork 时伪造 `created_by` 把会话挂到他人/提权 | Tampering/Spoofing | owner 只从 `request.user` 取，序列化器不接受 owner 入参 |
| 大 `page_size`/无过滤全表导出 | DoS / Info disclosure | page_size 上限 + 强制分页；`select_related`+`annotate` 防 N+1 |
| admin 误改 Phase 8 owner-gate 引入全局 bypass | Elevation of Privilege | admin 走独立方法/文件；回归跑 `test_conversation_isolation.py::test_admin_no_bypass` |

## Sources

### Primary (HIGH confidence) — 全部本仓库源码逐行核对
- `server/permissions/api_permissions.py:21` — `IsSuperUser`（管理员权限类标准）
- `server/chat/conversation_service.py:693-1348` — `ConversationService`（`aget_for_user`/`list_conversations`/`fork_conversation_before_message`）
- `server/chat/views.py:321-422` — `ConversationListView`/`ConversationDetailView`（认证/权限/owner-gate 模式）
- `server/chat/serializers.py:180-262` — `ConversationListSerializer`/`ConversationDetailSerializer`/`ConversationMessageSerializer`
- `server/chat/models.py:21-57` — `Conversation`（`created_by` SET_NULL、Status）
- `server/chat/urls.py` + `server/friday/urls.py:39-40` — chat url 挂载结构
- `server/accounts/views.py:301-329` — admin 列表/详情（内联 superuser 检查范本）
- `server/runners/views.py:57` / `server/system/views.py:24` — `IsSuperUser` 实际用法
- `server/tests/test_conversation_isolation.py` + `server/tests/conftest.py:171-253` — 隔离套件 + 共享 fixtures
- `web/src/main.ts:117` + `web/src/stores/auth.ts:30` — `requiresAdmin` → `isAdmin` = `is_superuser`
- `web/src/pages/admin/users.vue` — admin 列表页样板
- `web/src/api/users.ts` / `web/src/api/chat.ts` — api 模块约定
- `web/src/components/layout/AppSidebar.vue:54-61` — `adminNavItems` 导航
- `web/src/components/chat/ChatMessageArea.vue:26` — chat 组件 store 耦合（论证自建 viewer）
- `web/src/stores/chat.ts:244,1958` — `selectConversation` + `restoreFromURL`（fork 跳转）

### Secondary (MEDIUM confidence)
- 无（未依赖外部来源）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部既有资产，路径/行号逐一核对
- Architecture: HIGH — 复用 Phase 8 已验证的 adrf + 权限 + 序列化器模式
- Pitfalls: HIGH — 直接源自 Phase 8 代码注释（async FK、404 vs 403、owner-gate）与隔离套件
- Security: HIGH — 单一授权点 `IsSuperUser`，ASVS V4 为核心

**Research date:** 2026-06-09
**Valid until:** 2026-07-09（30 天；纯内部代码，栈稳定）
