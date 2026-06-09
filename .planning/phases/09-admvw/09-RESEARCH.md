# Phase 9: 管理员会话管理后台（只读） - Research

**Researched:** 2026-06-09
**Domain:** Django adrf 异步 REST 端点 + DRF 权限 + Vue 3 admin 页面（既有代码库内部约定，非外部框架）
**Confidence:** HIGH（全部基于代码库实读，无外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 新增**独立的 admin 会话端点**（如 `/api/admin/conversations/`），与 Phase 8 锁定的普通 `/api/conversations/`（实际挂载在 `/api/chat/conversations/`）路径分离，互不影响：
  - list：跨用户列出所有会话（含 owner、title、project、status、updated_at、消息数等元数据），支持按 owner/关键字/分页过滤。
  - detail（只读）：返回会话 + 消息用于只读查看。
  - **只读**：admin 端点不提供 patch/send-message/stream/delete 等写操作（ADMVW-02）。
  - fork-to-own：新增 admin fork 端点，把任意会话**整份复制**为一份 `created_by = request.user`（发起的管理员）的新会话，返回新会话 id（ADMVW-03）。与 Phase 8 `fork_conversation_before_message`（继承源 owner）**不同**：admin fork 显式归属当前管理员。
- 权限：admin 端点用管理员权限类（沿用代码库既有 admin 约定）；非管理员访问 403。
- 审计/隔离：admin 只读浏览**不改变** Phase 8 普通路径的 owner 过滤。
- 前端新增 `web/src/pages/admin/conversations.vue`（路由 meta `requiresAdmin: true`），用 `PageContainer` + `PageHeader` + `DataTable`；只读消息查看；每行/详情提供「fork 到我的名下」→ 成功后跳转普通 chat 界面；入口挂到 admin 导航。

### Claude's Discretion
- admin 列表的具体过滤/分页参数、只读详情复用 chat 消息组件还是新建轻量只读视图、fork 后是否自动跳转/弹确认。
- admin 端点放在 chat app 还是新建 admin 模块（建议复用 chat app + 独立 admin views/urls 命名空间）。
- 测试组织（`test_admin_conversations.py` 等）。

### Deferred Ideas (OUT OF SCOPE)
- 绑定令牌执行 / RemoteTool（Phase 10/11）。
- admin 会话的导出/批量操作、审计可视化（本期不做）。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADMVW-01 | 管理员有专门「会话管理」后台视图，可浏览所有用户的会话 | 新增 `AdminConversationListView`（无 owner 过滤 queryset）+ `AdminConversationDetailView`；前端 `admin/conversations.vue` + `DataTable`；导航入口加到 `AppSidebar.vue` `adminNavItems`（§Architecture Patterns, §Frontend） |
| ADMVW-02 | 后台视图只读，管理员不能直接在他人会话续聊/交互 | admin 端点仅实现 `get`（list/detail），**不**实现 patch/post(send)/delete/stream；前端只读视图无输入框/发送/编辑/删除入口（§Pattern 2, §Don't Hand-Roll） |
| ADMVW-03 | 管理员可 fork 一份归到自己名下后再交互 | 新增 `ConversationService.admin_fork_to_own`（deep-copy 会话+消息，`created_by=admin`，status→DRAFT）+ `AdminConversationForkView`；前端调用后跳转 `/chat?conversation=<id>`（§Pattern 3, §Code Examples） |
</phase_requirements>

## Summary

本期是在 Phase 8（会话 owner 隔离，ISO-01..04 全绿）之上叠加一个**物理分离、显式管理员授权**的只读会话管理后台。核心难点不是技术，而是**纪律**：admin 端点必须是一组**全新的、平行的** view + url，绝不复用或改写 Phase 8 已锁定的 `/api/chat/conversations/` 路径——后者的 owner gate 是 ISO-03 的真源（"管理员在普通对话界面也只看自己"），任何在普通路径上加 superuser bypass 都会让 Phase 8 的 25 路径隔离套件回归 RED。

代码库的「管理员」约定明确且统一：**admin == `is_superuser`**。后端既有两种写法——内联 `if not request.user.is_superuser: return 403`（`accounts/views.py` 全部 admin 端点）和声明式 `IsSuperUser` 权限类（`permissions/api_permissions.py`）。前端 `authStore.isAdmin = user.is_superuser`，路由守卫 `requiresAdmin` 即检查它。**没有** `is_staff` / DRF `IsAdminUser` / 项目自有 admin permission 在用。本期推荐用声明式 `IsSuperUser` 权限类（更清晰、与 adrf 同步 permission 检查兼容、无 ORM 触发）。

序列化复用：`ConversationListSerializer` / `ConversationDetailSerializer` 是普通 `serializers.Serializer`（非 ModelSerializer），可直接复用，只需在 admin 端为其补充 owner 字段（建议新建 `AdminConversationListSerializer` 子类/独立类，加 `owner` 嵌套 {id, username, display_name} 与 `message_count`，避免污染普通端契约）。fork-to-own 服务以既有 `fork_conversation_before_message` 为蓝本，但**复制全部消息**且 `created_by` 显式设为请求管理员。

**Primary recommendation:** 在 `chat` app 内新增 `admin_views.py` + `admin_urls.py`，挂载到 `/api/admin/conversations/`（顶层 `friday/urls.py` 的 `api_patterns` 加一行 `path("admin/", include("chat.admin_urls"))`）。所有 admin view 用 `permission_classes = [IsSuperUser]` + 默认认证类（不覆盖 `authentication_classes`，从而要求登录、拒匿名），只实现 `get` 与 fork 的 `post`。前端新增 `admin/conversations.vue` + `api/adminConversations.ts`，用轻量只读消息查看器（复用 `getMarkdownRenderer` + `hydrateLegacyMessage`，**不**复用重耦合 `chatStore` 的 `ChatMessageBubble`）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 跨用户会话列举（ADMVW-01） | API / Backend (`chat` app, admin views) | Database (无 owner 过滤的 queryset) | 列表权限与跨用户可见性必须服务端强制，前端只展示 |
| 只读会话详情 + 消息（ADMVW-01/02） | API / Backend (admin detail view) | Frontend（只读渲染） | 只读语义靠"不提供写端点"在后端兜底，前端只是不渲染入口 |
| 管理员鉴权（403 gate） | API / Backend (`IsSuperUser`) | Frontend（路由守卫 `requiresAdmin`，仅 UX 兜底） | 后端是唯一可信边界；前端守卫只是体验优化，不可作为安全依赖 |
| fork-to-own 深拷贝（ADMVW-03） | API / Backend (`ConversationService`) | Database (acreate 会话+消息) | 归属变更是数据写操作，必须服务端原子完成 |
| fork 后续聊 | Frontend (跳转 `/chat`) + 既有普通 stream 端点 | — | 续聊走 Phase 8 普通路径，admin 已是 owner，owner gate 自然放行 |

## Standard Stack

本期**不引入任何新依赖**。全部使用代码库既有栈。

### Core（既有，复用）
| 组件 | 位置 | 用途 | 复用方式 |
|------|------|------|----------|
| `adrf.views.APIView` | `server/chat/views.py` 已用 | 异步 DRF view 基类 | admin views 继承它，`async def get` |
| `permissions.api_permissions.IsSuperUser` | `server/permissions/api_permissions.py:21` | `is_superuser` 声明式权限类 | `permission_classes = [IsSuperUser]` |
| `ConversationService` | `server/chat/conversation_service.py:693` | 会话业务 facade（async staticmethod） | 新增 `admin_*` 方法，**不改**既有 owner-scoped 方法 |
| `ConversationListSerializer` / `ConversationDetailSerializer` | `server/chat/serializers.py:180,240` | 会话列表/详情序列化（plain Serializer） | 复用或派生加 owner 字段 |
| `ConversationMessageSerializer` | `server/chat/serializers.py:202` | 消息序列化（parts/content/tool_calls） | 直接复用于只读详情 |
| `DataTable` / `PageHeader` / `PageContainer` | `web/src/components/common/`, `layout/` | admin 列表页骨架 | 照 `admin/users.vue` 套用 |
| `getMarkdownRenderer` | `web/src/composables/useMarkdownRenderer` | markdown 渲染 | 轻量只读消息查看器复用 |
| `hydrateLegacyMessage` | `web/src/composables/useMessageParts` | parts/legacy 消息归一 | 只读查看器复用 |
| `useErrorHandler` / `useToast` | `web/src/composables/` | 错误/提示 | 照 `admin/users.vue` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `IsSuperUser` 权限类 | 内联 `if not request.user.is_superuser: return 403`（accounts 风格） | 两者均符合约定；权限类更声明、可测、复用；内联与 accounts 一致。**推荐 `IsSuperUser`**，但若 planner 倾向与 accounts 完全对齐也可内联 |
| 轻量只读消息查看器 | 复用 `ChatMessageBubble.vue` | `ChatMessageBubble`（1890+ 行）深度耦合 `chatStore`（选择/编辑/导出/流式），只读复用需大量 prop/store 解耦，风险高。**推荐新建轻量查看器** |
| 端点放 `chat` app（`chat/admin_urls.py`） | 新建 `admin` Django app | 新建 app 成本高、与既有 chat 模型耦合度反而更松散。**推荐 chat app 内独立 admin_views/admin_urls 命名空间** |

**Installation:** 无（无新包）。

## Package Legitimacy Audit

**N/A** — 本期不安装任何外部包（纯代码库内新增 view/serializer/service/Vue 组件）。无 `[SLOP]`/`[SUS]` 风险。

## Architecture Patterns

### System Architecture Diagram

```text
┌─────────────────────────── 普通对话路径（Phase 8 锁定，本期勿动）──────────────────────────┐
│  Browser /chat ──► /api/chat/conversations/...  ──► ChatAuthPermission                      │
│                                                  ──► ConversationService.aget_for_user(user) │
│                                                       └─ owner gate: created_by == user      │
│                                                          (无 superuser bypass = ISO-03)      │
└─────────────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────── 新增 admin 路径（本期，物理分离）───────────────────────────────────┐
│  Browser /admin/conversations                                                               │
│     │  (路由守卫 requiresAdmin → authStore.isAdmin = is_superuser，仅 UX 兜底)             │
│     ▼                                                                                        │
│  GET  /api/admin/conversations/            ──► IsSuperUser (403 if not superuser)           │
│       ?owner_id=&q=&limit=&offset=             └─► ConversationService.admin_list(...)       │
│                                                     └─ queryset: 无 owner 过滤（跨用户）     │
│       └─ resp: [{id,title,owner{id,username,display_name},project,status,                    │
│                  message_count,updated_at,...}]                                              │
│                                                                                             │
│  GET  /api/admin/conversations/<id>/       ──► IsSuperUser                                   │
│       └─► admin_get_with_messages(id)（无 owner 过滤）→ {conversation, messages[]}           │
│           (只读：无 patch/post-send/delete/stream)                                           │
│                                                                                             │
│  POST /api/admin/conversations/<id>/fork/  ──► IsSuperUser                                   │
│       └─► admin_fork_to_own(id, user=admin)                                                  │
│            └─ acreate Conversation(created_by=admin, status=DRAFT) + copy 全部 Message       │
│            └─ resp: {conversation_id: <new>}                                                 │
│                 │                                                                            │
│   前端拿到 new id ──► 跳转 /chat?conversation=<new id> ──► 走普通 stream（admin 即 owner）   │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```text
server/chat/
├── admin_views.py     # 新增：AdminConversationListView / DetailView / ForkView（仅 get/post fork）
├── admin_urls.py      # 新增：/conversations/ , /conversations/<uuid>/ , /conversations/<uuid>/fork/
├── conversation_service.py  # 新增 admin_list_conversations / admin_get_with_messages / admin_fork_to_own
├── serializers.py     # 新增 AdminConversationListSerializer（+owner +message_count）；复用 DetailSerializer/MessageSerializer
└── views.py / urls.py # 不动（Phase 8 锁定）

server/friday/urls.py  # api_patterns 加: path("admin/", include("chat.admin_urls"))

web/src/
├── pages/admin/conversations.vue        # 新增：DataTable 列表 + 只读抽屉/详情 + fork 按钮
├── components/admin/ReadonlyConversationView.vue  # 新增：轻量只读消息查看器（可选）
├── api/adminConversations.ts            # 新增：listAdminConversations / getAdminConversation / forkAdminConversation
└── components/layout/AppSidebar.vue     # 改：adminNavItems 加 { to:'/admin/conversations', label:'会话管理', icon:'lucide--messages-square' }
```

### Pattern 1: 独立 admin view（声明式 superuser 权限 + adrf async）
**What:** 全新 view，不碰 Phase 8 路径。权限用 `IsSuperUser`，认证用默认类（要求登录）。
**When to use:** 全部 admin 端点。
**Example:**
```python
# server/chat/admin_views.py
# Source: 综合 server/chat/views.py:321 + permissions/api_permissions.py:21
from adrf.views import APIView
from rest_framework.response import Response
from permissions.api_permissions import IsSuperUser
from .conversation_service import ConversationService
from .serializers import AdminConversationListSerializer

class AdminConversationListView(APIView):
    """管理员跨用户会话列表（只读，ADMVW-01）。

    不覆盖 authentication_classes —— 沿用 settings 默认
    [AccessTokenAuthentication, CookieJWTAuthentication]，匿名被拒。
    IsSuperUser 仅做属性判定，无 ORM 触发，adrf 同步 permission 检查安全。
    """
    permission_classes = [IsSuperUser]

    async def get(self, request):
        owner_id = request.query_params.get("owner_id") or None
        q = request.query_params.get("q") or ""
        conversations = await ConversationService.admin_list_conversations(
            owner_id=owner_id, q=q,
        )
        data = await sync_to_async(
            lambda: AdminConversationListSerializer(conversations, many=True).data
        )()
        return Response(data)
```
> 注意：`AdminConversationListSerializer` 若读 `owner.username` 等关联字段，需在 service 层 `select_related("created_by", "project")` 预取，并用 `sync_to_async` 包裹 `.data`（避免 async 上下文 `SynchronousOnlyOperation`，见 §Pitfall 1）。

### Pattern 2: 只读 = 不提供写端点（而非"加只读开关"）
**What:** ADMVW-02 的实现方式是 admin view **只定义 `get`**（list/detail）+ fork 的 `post`。不实现 `patch`/`delete`/send-message/`stream`。非法方法由 DRF 自动返回 405。
**When to use:** detail/list view。
**Anti-pattern:** 不要给普通 `ConversationDetailView` 加 `?admin=1` 之类旁路——那会把 admin 逻辑混进 Phase 8 锁定路径。

### Pattern 3: admin fork-to-own service（深拷贝 + 改归属）
**What:** 以 `fork_conversation_before_message`（`conversation_service.py:751`）为蓝本，但 (1) 复制**全部**消息（非 `created_at__lt` 截断），(2) `created_by` 显式 = 请求管理员，(3) `status` 重置为 `DRAFT`。
**When to use:** `AdminConversationForkView.post`。
**Example:**
```python
# server/chat/conversation_service.py （新增 staticmethod）
# Source: 蓝本 fork_conversation_before_message (conversation_service.py:751-823)
from copy import deepcopy
from chat.models import Conversation, Message

@staticmethod
async def admin_fork_to_own(conversation_id: str, admin_user) -> dict:
    """ADMVW-03：把任意会话整份复制为一份归属当前管理员的新会话。

    与 fork_conversation_before_message 区别：
      - created_by = 发起的管理员（显式归属，非继承源 owner）
      - 复制全部消息（不按 message_id 截断）
      - status 重置为 DRAFT（新副本，admin 续聊时由 stream 置 RUNNING）
    无 owner 过滤（调用方 IsSuperUser 已授权跨用户读取）。
    """
    source = await Conversation.objects.aget(id=conversation_id, is_deleted=False)
    fork_title = f"{source.title}（管理员副本）"[:200]
    forked = await Conversation.objects.acreate(
        project_id=source.project_id,
        title=fork_title,
        model=source.model,
        provider_credential_id_id=source.provider_credential_id_id,  # 可选：携带 pin；admin 可改
        created_by=admin_user,                                        # 关键：归属管理员
        status=Conversation.Status.DRAFT,
    )
    async for msg in Message.objects.filter(conversation=source).order_by("created_at"):
        await Message.objects.acreate(
            conversation=forked,
            role=msg.role,
            content=msg.content,
            tool_calls=deepcopy(msg.tool_calls),
            tool_call_id=msg.tool_call_id,
            metadata=deepcopy(msg.metadata),
            parts=deepcopy(msg.parts),
        )
    return {"conversation_id": str(forked.id)}
```
**决策点（planner 定）：** `provider_credential_id` 是否携带——携带便于 admin 直接续聊（status=DRAFT 可改）；置 null 则 admin 需重新选 Provider。推荐**携带**（与普通 fork 一致），admin 端 pin 语义因 status=DRAFT 不冻结。

### Pattern 4: 列表无 owner 过滤的 queryset（跨用户）
**What:** `admin_list_conversations` 走 `Conversation.objects.filter(is_deleted=False)` **不加** `created_by` 过滤，可选叠加 `owner_id` / `title__icontains` 过滤 + `select_related("created_by","project")` + `annotate(message_count=Count("messages"))`。
**Example:**
```python
@staticmethod
async def admin_list_conversations(owner_id=None, q="") -> list[Conversation]:
    from django.db.models import Count
    qs = (Conversation.objects.filter(is_deleted=False)
          .select_related("created_by", "project")
          .annotate(message_count=Count("messages")))
    if owner_id:
        qs = qs.filter(created_by_id=owner_id)
    if q:
        qs = qs.filter(title__icontains=q)
    return [c async for c in qs.order_by("-updated_at")]
```

### Anti-Patterns to Avoid
- **在 `/api/chat/conversations/` 加 superuser bypass**：直接破坏 ISO-03，回归 Phase 8 套件。admin 必须独立路径。
- **复用 `OptionalJWTAuthentication` / `ChatAuthPermission`**：那是 chat 路径的"开放模式"认证（允许匿名/X-Chat-Key），admin 端点严禁。用默认认证类（要求登录）。
- **依赖前端 `requiresAdmin` 做安全**：前端守卫只是 UX；真正 gate 是后端 `IsSuperUser`。
- **在 admin detail 触发惰性 FK**（`conversation.created_by.username` 在 async 上下文）→ `SynchronousOnlyOperation`。必须 `select_related` 预取 + `sync_to_async` 包 `.data`。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| superuser 鉴权 | 新写权限判断 | `permissions.api_permissions.IsSuperUser` | 已存在、已测、与代码库约定一致 |
| 会话/消息序列化 | 新 serializer 全套 | 复用 `ConversationDetailSerializer` + `ConversationMessageSerializer`，仅 list 端加 owner/message_count | 字段契约已与前端对齐（parts/content/tool_calls/status） |
| 只读 = 写保护 | 加 `read_only` 标志位/中间件 | 干脆不实现写方法（DRF 自动 405） | 最少代码、最难出错、ADMVW-02 天然满足 |
| 列表页骨架 | 自写表格 | `DataTable` + `PageHeader` + `PageContainer`（照 `admin/users.vue`） | 既有 admin 页一致体验 + TanStack Table |
| fork 深拷贝 | 从零写复制循环 | 以 `fork_conversation_before_message` 为蓝本改 3 处 | 复用经 Phase 8 验证的 deepcopy 字段集（tool_calls/metadata/parts） |
| markdown 渲染 | 自写解析 | `getMarkdownRenderer` + `hydrateLegacyMessage` | 与普通 chat 渲染同源 |

**Key insight:** 本期价值在"约束纪律"而非"造轮子"——99% 是组合既有资产，唯一需要新写的实质逻辑是 `admin_fork_to_own`（~25 行）和 admin list 的无过滤 queryset。

## Common Pitfalls

### Pitfall 1: async 上下文惰性 FK → SynchronousOnlyOperation
**What goes wrong:** admin list/detail 序列化时访问 `conversation.created_by.username` 触发同步 ORM。
**Why:** adrf async view 中 DRF 序列化默认同步访问关联对象。Phase 8 已踩过（`conversation_service.py:707` 注释、`serializers.py:196` 用 `_id` 列规避）。
**How to avoid:** service 层 `select_related("created_by","project")` 预取；序列化 `.data` 用 `sync_to_async(lambda: Serializer(...).data)()` 包裹（见 `accounts/views.py:192` MeView 范式）。
**Warning signs:** 测试报 `SynchronousOnlyOperation` / `You cannot call this from an async context`。

### Pitfall 2: admin 端点误用 chat 认证类放行匿名
**What goes wrong:** 复制 `ConversationListView` 时连 `authentication_classes = [OptionalJWTAuthentication, ChatKeyAuthentication]` 一起复制 → 匿名/X-Chat-Key 可达。
**Why:** `OptionalJWTAuthentication` 允许未认证（开放模式）。
**How to avoid:** admin view **不设** `authentication_classes`（用 settings 默认 `[AccessTokenAuthentication, CookieJWTAuthentication]`，强制登录）。`IsSuperUser` 会先拒匿名（`is_authenticated` False → 403/401）。
**Warning signs:** 非管理员/匿名拿到 200。

### Pitfall 3: 403 vs 404 语义混淆
**What goes wrong:** 套用 Phase 8「越权 → 404 不泄漏存在性」到 admin 端点。
**Why:** Phase 8 的 404 语义是针对**普通用户越权访问他人会话**（ISO-04 不泄漏）。admin 端点相反——管理员**有权**看全部，非管理员则应明确 **403**（"仅超级管理员"，与 accounts admin 端点一致）。
**How to avoid:** admin gate 用 `IsSuperUser` → 非管理员 **403**；管理员访问不存在的会话 → **404**（普通 not-found 语义）。不要把 admin 端点写成 404-everything。
**Warning signs:** 非管理员收到 404 而非 403；测试断言混乱。

### Pitfall 4: fork 后副本 status 与 pin 冻结冲突
**What goes wrong:** 复制时保留源 `status`（如 `completed`），新副本被 pin 冻结逻辑判为 frozen，admin 续聊改 Provider 被拒。
**Why:** `Conversation.Status` frozen 态（completed/stopped/error）拒改 `provider_credential_id`（`models.py:76-83`）。
**How to avoid:** fork 副本 `status = DRAFT`（新会话语义，可自由配置，admin 续聊由 stream 置 RUNNING）。
**Warning signs:** admin fork 后在 chat 界面改模型/Provider 被 frozen 拒绝。

### Pitfall 5: admin fork 复用普通 fork 端点导致 owner 继承错误
**What goes wrong:** 直接调 `fork_conversation_before_message` → 新会话 `created_by = 源 owner`（他人），admin 续聊立刻被 owner gate 404。
**Why:** 普通 fork 故意继承源 owner（`conversation_service.py:791` 注释）。
**How to avoid:** 必须用**新** `admin_fork_to_own`，`created_by = admin`。
**Warning signs:** admin fork 成功但跳转 chat 后 detail/stream 返回 404。

## Code Examples

### admin_urls.py（仅只读 get + fork post）
```python
# server/chat/admin_urls.py
# Source: 形态对齐 server/chat/urls.py
from django.urls import path
from .admin_views import (
    AdminConversationListView,
    AdminConversationDetailView,
    AdminConversationForkView,
)

urlpatterns = [
    path("conversations/", AdminConversationListView.as_view(), name="admin-conversation-list"),
    path("conversations/<uuid:conversation_id>/", AdminConversationDetailView.as_view(), name="admin-conversation-detail"),
    path("conversations/<uuid:conversation_id>/fork/", AdminConversationForkView.as_view(), name="admin-conversation-fork"),
]
```

### 顶层挂载
```python
# server/friday/urls.py  api_patterns 内新增一行（与 "chat/" 并列）
path("admin/", include("chat.admin_urls")),
# → 端点前缀 /api/admin/conversations/
```

### AdminConversationListSerializer（加 owner + message_count）
```python
# server/chat/serializers.py （新增）
class _OwnerBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True)

class AdminConversationListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    space_id = serializers.UUIDField(source="project_id")
    title = serializers.CharField()
    status = serializers.CharField()
    message_count = serializers.IntegerField(read_only=True)  # 来自 annotate
    owner = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_owner(self, obj):
        u = obj.created_by  # 需 select_related("created_by") 预取
        if u is None:
            return None
        return {"id": str(u.id), "username": u.username, "display_name": u.display_name or ""}
```

### 前端 api 模块
```typescript
// web/src/api/adminConversations.ts
// Source: 形态对齐 web/src/api/users.ts
import { get, post } from './client'

export interface AdminConversationListItem {
  id: string
  title: string
  status: string
  message_count: number
  owner: { id: string, username: string, display_name: string } | null
  space_id: string
  created_at: string
  updated_at: string
}

export function listAdminConversations(params?: { owner_id?: string, q?: string }) {
  const qs = new URLSearchParams(params as Record<string, string>).toString()
  return get<AdminConversationListItem[]>(`/admin/conversations/${qs ? `?${qs}` : ''}`)
}
export function getAdminConversation(id: string) {
  return get(`/admin/conversations/${id}/`)
}
export function forkAdminConversation(id: string) {
  return post<{ conversation_id: string }>(`/admin/conversations/${id}/fork/`, {})
}
```

### 前端 fork → 跳转 chat
```typescript
// admin/conversations.vue 内
async function forkToOwn(id: string) {
  const { conversation_id } = await forkAdminConversation(id)
  success('已复制到我的名下')
  router.push(`/chat?conversation=${conversation_id}`)  // 走普通 chat（admin 即 owner）
}
```
> 跳转参数：`chat.vue` 用 `chatStore.restoreFromURL()` 恢复会话（`pages/chat.vue:21`）。planner 需确认 URL query 键名（grep `restoreFromURL` 实现确定是 `?conversation=` 还是 `?id=`）。

### 导航入口
```typescript
// web/src/components/layout/AppSidebar.vue  adminNavItems 数组新增
{ to: '/admin/conversations', label: '会话管理', icon: 'lucide--messages-square' },
```
（已被 `v-if="isSystemAdmin"` 包裹，自动只对管理员可见。）

## State of the Art

| Old Approach | Current Approach | When | Impact |
|--------------|------------------|------|--------|
| 管理员在普通 chat 看全部（superuser bypass） | 普通路径所有人只看自己（ISO-03）+ 独立只读后台 | Phase 8/9（v0.2.0） | 本期不得在普通路径恢复 bypass |
| 普通 fork 继承源 owner | 普通 fork 仍继承；admin fork 显式归属管理员 | 本期新增 | 两套 fork 并存，语义分离 |

**Deprecated/outdated:** 无（本期纯新增）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | admin == `is_superuser`（无 `is_staff`/`IsAdminUser`/项目自有 admin permission） | Summary, Standard Stack | 低——已 grep 全 `server/**/*.py` 确认：admin 端点全用 `is_superuser`，前端 `isAdmin=is_superuser`。若 planner 发现 `is_staff` 用例需复核（grep 已覆盖，未见） |
| A2 | fork 副本应携带 `provider_credential_id` 且 status=DRAFT | Pattern 3 | 低——若携带导致 admin 无该凭证权限可置 null；status=DRAFT 必需（避免 pin 冻结） |
| A3 | chat.vue 用 `?conversation=` query 恢复会话 | Code Examples | 中——需 planner grep `restoreFromURL` 确认确切键名，否则跳转后不自动选中会话 |
| A4 | 列表分页：既有 `/api/chat/conversations/` 返回**无分页**纯数组（无 DRF 全局 PAGE_SIZE 配置），admin 列表可同样返回数组或手写 limit/offset | §Pattern 4 | 低——已确认 settings 无 `DEFAULT_PAGINATION_CLASS`；CONTEXT 称"分页与现有列表一致"即无分页。大数据量下可加手写 limit/offset（Claude's discretion） |

## Open Questions

1. **fork 后是否弹确认对话框？**
   - 已知：CONTEXT 列为 Claude's discretion。
   - 不清楚：直接 fork+跳转 vs 先确认。
   - 推荐：直接 fork + toast 提示 + 跳转（最少摩擦）；如担心误点可加轻确认。
2. **只读详情用抽屉(drawer)还是独立路由 `/admin/conversations/[id]`？**
   - 推荐：抽屉/对话框（DataTable 行点击展开），避免新路由 + 复用列表上下文。Claude's discretion。
3. **`?conversation=` 查询键名确认**（见 A3）——planner 在 plan 阶段 grep `restoreFromURL`（`web/src/stores/chat.ts`）确定。

## Environment Availability

**SKIPPED** — 本期为纯代码库内新增（Django view/serializer/service + Vue 组件），无外部工具/服务/运行时依赖。测试用既有 pytest（后端）/ vitest（前端）框架。

## Validation Architecture

> `workflow.nyquist_validation: true` → 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework (backend) | `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django>=4.8`（见 STACK；`server/tests/`） |
| Framework (frontend) | `vitest@^4` + `@vue/test-utils` + `happy-dom`（`web/`） |
| Config file | `server/pyproject.toml`（pytest）/ `web/vitest.config.*` |
| Quick run (backend) | `cd server && uv run pytest tests/test_admin_conversations.py -x` |
| Full suite (backend) | `cd server && uv run pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py -q` |
| Frontend run | `cd web && pnpm vitest run src/pages/admin/__tests__/conversations.spec.ts` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADMVW-01 | 管理员 GET list 看到**全部用户**会话（含他人 owner） | integration | `pytest tests/test_admin_conversations.py::test_admin_list_sees_all_users -x` | ❌ Wave 0 |
| ADMVW-01 | 非管理员 GET admin list → **403** | integration | `pytest tests/test_admin_conversations.py::test_non_admin_list_403 -x` | ❌ Wave 0 |
| ADMVW-01 | 匿名 GET admin list → 401/403（拒绝） | integration | `pytest tests/test_admin_conversations.py::test_anonymous_denied -x` | ❌ Wave 0 |
| ADMVW-01 | 管理员 GET detail 看他人会话 + 消息（200） | integration | `pytest tests/test_admin_conversations.py::test_admin_detail_other_user -x` | ❌ Wave 0 |
| ADMVW-02 | admin detail/list view 无 patch/delete/post-send → **405** | integration | `pytest tests/test_admin_conversations.py::test_admin_readonly_no_write -x` | ❌ Wave 0 |
| ADMVW-02 | 不存在 admin 端点的 stream/send 路径（路由层缺失） | integration | `pytest tests/test_admin_conversations.py::test_admin_no_stream_route -x` | ❌ Wave 0 |
| ADMVW-03 | 管理员 fork 他人会话 → 新会话 `created_by=admin` + 全部消息复制 | integration | `pytest tests/test_admin_conversations.py::test_admin_fork_creates_admin_owned_copy -x` | ❌ Wave 0 |
| ADMVW-03 | fork 副本 status=DRAFT 且不改源会话 | integration | `pytest tests/test_admin_conversations.py::test_admin_fork_status_and_source_intact -x` | ❌ Wave 0 |
| ADMVW-03 | 非管理员调 fork → 403 | integration | `pytest tests/test_admin_conversations.py::test_non_admin_fork_403 -x` | ❌ Wave 0 |
| 回归 (ISO-03) | 普通 `/api/chat/conversations/` 仍 owner-scoped（admin 也只看自己） | integration | `pytest tests/test_conversation_isolation.py -q`（既有，必须全绿） | ✅ 既有 |
| 前端 (ADMVW-01) | `conversations.vue` 含 `requiresAdmin` meta + DataTable 挂载 | unit | `pnpm vitest run src/pages/admin/__tests__/conversations.spec.ts` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_admin_conversations.py -x`
- **Per wave merge:** `uv run pytest tests/test_admin_conversations.py tests/test_conversation_isolation.py -q`（admin 新增 + Phase 8 回归一起）
- **Phase gate:** 后端两套 + 前端 spec 全绿后才 `/gsd-verify-work`。

### Wave 0 Gaps
- [ ] `server/tests/test_admin_conversations.py` — 覆盖 ADMVW-01/02/03 + 非管理员 403 + 匿名拒绝 + fork 归属。复用 `test_conversation_isolation.py` 的 `_acreate_conversation(owner=...)` / JWT helper 范式（`AsyncClient` + `RefreshToken.for_user`）。
- [ ] `web/src/pages/admin/__tests__/conversations.spec.ts` — requiresAdmin meta + DataTable + 只读无写入入口断言（照 `codegraph/__tests__/playground.spec.ts` 范式）。
- [ ] 回归保障：`test_conversation_isolation.py` 不改、必须保持全绿（admin 端点不得削弱普通路径隔离）。
- 框架已就绪（pytest/vitest 既有），无需安装。

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1` → 本节适用。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | admin 路径与普通路径物理分离；信任边界在后端 `IsSuperUser` |
| V2 Authentication | yes | 沿用默认 `[AccessTokenAuthentication, CookieJWTAuthentication]`；admin 端点不放行匿名 |
| V4 Access Control | **yes（核心）** | `IsSuperUser` 权限类做服务端授权；非管理员 403；前端 `requiresAdmin` 仅 UX 兜底，**不可作安全依赖** |
| V5 Input Validation | yes | fork 路径参数 `<uuid:conversation_id>` 由 URLconf 强校验；list 过滤参数 `owner_id`(UUID)/`q`(字符串 icontains，ORM 参数化无注入) |
| V7 Error Handling/Logging | yes | admin 跨用户访问建议 `logger.info("admin_conversation_viewed", admin_id=..., conversation_id=...)` 留痕（CONTEXT 称审计可视化不在本期，但**轻量结构化日志**符合既有约定 `common.logging`） |
| V6 Cryptography | no | 本期不处理凭证明文/加密（provider_credential 仅 FK 引用，沿用既有 Fernet） |

### Known Threat Patterns for {Django adrf + DRF}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 非管理员调用 admin 端点（垂直越权） | Elevation of Privilege | `IsSuperUser`（服务端强制，403） |
| 经普通路径加 superuser bypass 绕过 ISO-03 | Elevation of Privilege | 物理分离 admin 路径；回归套件 `test_conversation_isolation.py` 守卫；grep 守卫"源码 0 处 is_superuser bypass on chat path" |
| fork 把他人会话写成自己名下后冒充（归属混乱） | Tampering/Repudiation | fork 显式 `created_by=admin`（设计即归属变更，非伪造）；建议审计日志留痕 admin_id+源会话 |
| 列表过滤参数注入 | Tampering | ORM `filter(title__icontains=q)` 参数化；`owner_id` 用 UUIDField 校验 |
| 匿名/X-Chat-Key 访问 admin | Spoofing | 不复用 `OptionalJWTAuthentication`/`ChatAuthPermission`；用默认要求登录的认证类 |

## Sources

### Primary (HIGH confidence) — 代码库实读
- `server/chat/conversation_service.py` — `aget_for_user`(697)、`fork_conversation_before_message`(751)、`list_conversations`(1338)、`create_conversation`(717)：owner gate + fork 蓝本
- `server/chat/views.py` — `ConversationListView`(321)、`ConversationDetailView`(381)、`ConversationMessageForkView`(982)：adrf view + auth/permission 范式
- `server/chat/serializers.py` — `ConversationListSerializer`(180)、`ConversationDetailSerializer`(240)、`ConversationMessageSerializer`(202)：可复用契约
- `server/chat/models.py` — `Conversation`(21, created_by FK + Status enum)、`Message`(98)：deepcopy 字段集
- `server/permissions/api_permissions.py:21` — `IsSuperUser` 权限类
- `server/accounts/views.py` — admin 端点全用 `is_superuser` 内联检查（301/312/369/408）；`MeView`(187) sync_to_async `.data` 范式
- `server/accounts/permissions.py`、`server/system/permissions.py` — 确认无其他 admin 权限类（仅 SetupNotInitialized / ProviderCredentialPermission）
- `server/friday/settings.py:277-283` — DEFAULT_AUTHENTICATION_CLASSES（AccessToken+CookieJWT）/ PERMISSION（IsAuthenticated）；无 PAGINATION
- `server/friday/urls.py:22-61` — api_patterns 挂载结构（chat/ 等）
- `server/accounts/serializers.py` — User 有 `username`/`display_name`/`is_superuser`
- `web/src/stores/auth.ts:30` — `isAdmin = user.is_superuser`
- `web/src/main.ts:117` — `requiresAdmin` 守卫
- `web/src/pages/admin/users.vue` — admin 列表页范式（DataTable/PageHeader/PageContainer/useErrorHandler/useToast）
- `web/src/api/users.ts` — api 模块范式
- `web/src/components/layout/AppSidebar.vue:54-61` — `adminNavItems`（导航入口，`isSystemAdmin` gate）
- `web/src/components/chat/ChatMessageBubble.vue`(1-70) — 确认重耦合 `chatStore`（不宜直接复用做只读）
- `web/src/pages/chat.vue:21` — `restoreFromURL` 跳转恢复
- `server/tests/test_conversation_isolation.py` — Phase 8 隔离套件（回归基线 + 测试 helper 范式）

### Secondary / Tertiary
- 无外部检索（本期零外部依赖，全部 HIGH 置信代码库实证）。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部既有资产，grep + 实读确认
- Architecture: HIGH — 端点/权限/序列化/服务范式均有现成蓝本
- Pitfalls: HIGH — 多数来自 Phase 8 已记录的踩坑（async FK、403/404、pin frozen）
- Admin 约定（is_superuser）: HIGH — 全 `server/**/*.py` grep 确认无 is_staff/IsAdminUser 用例

**Research date:** 2026-06-09
**Valid until:** 2026-07-09（代码库内部约定稳定；若 Phase 8 路径被改动需复核回归基线）
