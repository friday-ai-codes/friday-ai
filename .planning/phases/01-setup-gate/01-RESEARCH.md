# Phase 1: 向导门禁与初始化状态检测 - Research

**Researched:** 2026-06-08
**Domain:** Django async DRF + Vue 3 router guard + i18n wiring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**A. 初始化状态检测接口**
- 路径：`GET /api/auth/setup/status/`，响应 `{ "needs_setup": bool, "is_initialized": bool }`
- 权限 `AllowAny`，adrf `APIView` 异步视图，DB 查询 `await sync_to_async(User.objects.filter(is_superuser=True).exists)()`
- 挂载于 `accounts/urls.py`（`/api/auth/`）

**B. fail-closed 门禁 + 防重入**
- 新增可复用 DRF 权限类 `SetupNotInitialized`（accounts 下）：存在 superuser → 403
- 防重入：`transaction.atomic()` 包裹，事务内再次 `User.objects.filter(is_superuser=True).exists()` 复核
- SQLite：`select_for_update` 退化 no-op，事务内复核为主保险
- Phase 1 落地 `POST /api/auth/setup/`：已初始化 → 403；未初始化 → 原子事务内 `create_superuser`

**C. 前端路由守卫**
- `router.beforeEach` 加「初始化状态」分支，置于 `authStore.initAuth()` 之前/旁路
- 新增 `web/src/api/setup.ts`（`getSetupStatus()`），从 `web/src/api/index.ts` re-export
- 状态缓存推荐复用 auth store
- 守卫：`needs_setup=true` → 除 `/setup` 外全部重定向到 `/setup`；`needs_setup=false` → 访问 `/setup` 重定向到 `/login`
- `/setup` 加入 `publicPages`；容错：状态请求失败按「已初始化」处理

**D. 向导外壳范围与视觉**
- 复用 `web/src/pages/setup.vue`，改造为向导外壳（标题/步骤框架占位）
- 现有表单继续可用（接通新后端门禁），视觉沿用 glass 卡片风格

**E. i18n**
- 用户可见文案通过 `vue-i18n` 取用，默认 zh-CN，`setup.*` 命名空间
- 若接入成本过高，允许在 `main.ts` 内联 `messages.zh-CN` 对象，但文案必须经 `t()`/`$t` 取用

### Claude's Discretion

- 状态缓存落点（auth store vs 新建 setup store）
- 权限类与锁工具的具体文件命名
- 向导外壳的步骤指示器是否在 Phase 1 渲染
- i18n catalog 的具体装载实现

### Deferred Ideas (OUT OF SCOPE)

- 管理员创建的完整 UX（密码强度、二次确认、自动建立会话、不触发 must_change_password）→ Phase 2
- LLM 供应商配置、Claude Code 绑定 → Phase 3
- 安全密钥校验、飞书/RAG 可选步骤 → Phase 4
- `entrypoint.sh` 默认不再自动建号、保留运维命令、老部署不回退 → Phase 5
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SETUP-01 | 系统检测到不存在任何超级管理员时，用户首次访问 Web 自动进入首启初始化向导 | router.beforeEach 中的 setup 状态分支实现此功能 |
| SETUP-02 | 后端提供只读「初始化状态」接口，前端路由守卫据此放行 | `GET /api/auth/setup/status/` + authStore 缓存 |
| SETUP-03 | 向导完成（已创建管理员）后，初始化接口与界面对所有访问者关闭（403 或重定向） | `SetupNotInitialized` 权限类 + 守卫重定向到 `/login` |
| SETUP-04 | 初始化接口 fail-closed 且具备防重入/并发保护——存在 superuser 时一律拒绝 | `transaction.atomic()` 内双重检查，permission 类前置拦截 |
</phase_requirements>

---

## Summary

Phase 1 核心是「一次性门禁层」：在系统无 superuser 时放行向导，有 superuser 后永久锁闭。技术面很小，所有代码均在既有的 `accounts` Django app 和前端 `main.ts` 路由守卫内完成，无需新建 Django app 或 Vue 布局。

后端需要新增两个视图（`SetupStatusView` / `SetupInitView`）、一个可复用权限类（`SetupNotInitialized`）、两条 URL。前端需要新增 `api/setup.ts`、扩展 `authStore`（加 `systemNeedsSetup` 状态）、修改 `router.beforeEach` 守卫逻辑、以及为 i18n 创建第一个 zh-CN locale 文件。

最大风险点是守卫顺序（setup 状态检查必须在 `initAuth()` 之前，否则未初始化环境下 `/me` 会 401 导致陷入错误路径）和并发防重入（SQLite 下 `select_for_update` 不可用，必须依赖事务内再检查）。

**Primary recommendation:** 守卫分两阶段 — 先检测 setup 状态（一次，缓存在 authStore），状态决定后再走现有 initAuth 分支；后端权限类 + 事务内复核为双保险。

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 初始化状态读取 | API / Backend | Frontend Cache | 单一权威来源在 DB（superuser 是否存在），前端仅缓存一次 |
| fail-closed 门禁 | API / Backend | — | 安全约束必须在服务端执行，前端守卫是 UX 而非安全保证 |
| 防重入并发保护 | API / Backend (DB) | — | 属于数据一致性，只能在 DB 事务层保证 |
| 路由导航控制 | Frontend Server (SPA) | — | 路由守卫负责 UX 跳转，不承担安全职责 |
| 向导外壳渲染 | Frontend Server (SPA) | — | 纯前端 Vue 组件 |
| i18n 文案 | Frontend Server (SPA) | — | `vue-i18n` 客户端注入 |

---

## Standard Stack

### Core（均已在项目中安装，无需新增依赖）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `adrf` | `>=0.1.12` | Async DRF views | 已是项目 accounts 全部视图的基础，异步 ORM 桥接 [VERIFIED: 见 server/accounts/views.py:4] |
| `django.db.transaction` | Django 5.1 内置 | 原子事务防重入 | 标准 Django 原语，已在 system/views.py 使用 [VERIFIED: 见 server/system/views.py:503] |
| `rest_framework.permissions.BasePermission` | DRF 3.15 内置 | 可复用权限类基类 | 项目已有 `ProviderCredentialPermission` 同模式 [VERIFIED: 见 server/system/permissions.py] |
| `vue-i18n` | `^10.x`（pnpm catalog） | 前端国际化 | 已在 main.ts 注册，`useI18n` 已配置 auto-import [VERIFIED: 见 web/src/main.ts:7] |
| `unplugin-vue-i18n` | `^1.0.11` | 编译时 locale 优化 | 已配置 `include: ['src/locales/**']` [VERIFIED: 见 web/vite.config.ts:68-70] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asgiref.sync_to_async` | Django 5.1 内置 | ORM → async 桥接 | 所有后端 DB 访问路径（已是全项目约定） |
| `structlog` | 已在项目 | 结构化日志 | 视图层 info/warning 日志 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `sync_to_async` wrapping transaction | `adrf.decorators.sync_to_async` | 等价，项目统一用 `asgiref.sync_to_async` |
| authStore 内缓存 | 新建独立 `setupStore` | 避免样板，CONTEXT.md 推荐复用 authStore |
| JSON locale 文件 | YAML locale 文件 | `unplugin-vue-i18n` 两种均支持；JSON 无需额外依赖 |

### Installation

无需安装新依赖——所有依赖均已在项目中。

---

## Package Legitimacy Audit

> **本阶段无需安装任何外部包**，所有依赖均已在项目依赖树中。

本阶段不引入新 PyPI 或 npm 包，跳过 slopcheck 审查。

---

## Architecture Patterns

### System Architecture Diagram

```
Browser
  │
  │ 首次访问任意路由
  ▼
router.beforeEach (web/src/main.ts)
  │
  ├─[isSetupChecked=false]─► getSetupStatus()
  │                            GET /api/auth/setup/status/
  │                            ├─ 成功 → 缓存 needsSetup 到 authStore
  │                            └─ 失败 → fail-safe: needsSetup=false（已初始化）
  │
  ├─[needsSetup=true, to!=='/setup']─► redirect /setup
  ├─[needsSetup=false, to==='/setup']─► redirect /login
  │
  └─[needsSetup=false, 其余路由]─► 现有 initAuth() + publicPages 逻辑
                                    │
                                    ▼
                                 正常应用入口

Browser
  │ POST /api/auth/setup/  (setup.vue 表单提交)
  ▼
Django SetupInitView (server/accounts/views.py)
  │
  ├─[SetupNotInitialized 权限类]
  │    ├─ 存在 superuser → 403 Forbidden（fail-closed）
  │    └─ 无 superuser → 放行
  │
  └─[sync_to_async(_create_superuser_atomic)]
       │
       └─ transaction.atomic()
            ├─ 再次 User.objects.filter(is_superuser=True).exists()
            │   ├─ True → return None（并发重入被拒）→ 403
            │   └─ False → User.objects.create_superuser(...)
            │              └─ return user → 201
```

### Recommended Project Structure

后端（仅新增文件，不改动既有 app 结构）：

```
server/accounts/
├── views.py          # 新增 SetupStatusView, SetupInitView（追加到末尾）
├── permissions.py    # 【新建】SetupNotInitialized 权限类
└── urls.py           # 新增 setup/status/ 和 setup/ 两条 URL
```

前端（新增/修改文件）：

```
web/src/
├── api/
│   ├── setup.ts      # 【新建】getSetupStatus(), initSetup()
│   └── index.ts      # 追加 setup 模块的 re-export
├── stores/
│   └── auth.ts       # 追加 systemNeedsSetup, isSetupChecked, checkSetup()
├── locales/
│   └── zh-CN.json    # 【新建】setup.* 命名空间 zh-CN 文案
├── main.ts           # 修改：路由守卫 + i18n messages 引入
└── pages/
    └── setup.vue     # 改造为向导外壳（保留现有表单，更新文案为 $t()）
```

---

### Pattern 1: 后端 — 异步公开只读接口（`SetupStatusView`）

与 `LoginView` 完全同构，复用既有 async + AllowAny 模式：

```python
# server/accounts/views.py（追加）
# Source: 参照 accounts/views.py LoginView（line 34-83）

from adrf.views import APIView
from asgiref.sync import sync_to_async
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

User = get_user_model()

class SetupStatusView(APIView):
    """只读初始化状态接口。无认证可调用，返回系统是否已初始化。"""

    permission_classes = [AllowAny]

    async def get(self, request):
        # 判定：存在任意 is_superuser=True 用户即视为「已初始化」
        is_initialized = await sync_to_async(
            User.objects.filter(is_superuser=True).exists
        )()
        return Response({
            "is_initialized": is_initialized,
            "needs_setup": not is_initialized,
        })
```

**URL 注册**（`server/accounts/urls.py`）：

```python
from .views import SetupStatusView, SetupInitView

urlpatterns = [
    # ... 现有路由 ...
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    path("setup/", SetupInitView.as_view(), name="setup"),
]
```

---

### Pattern 2: 后端 — fail-closed 权限类（`SetupNotInitialized`）

```python
# server/accounts/permissions.py（新建文件）
# Source: 参照 server/system/permissions.py::ProviderCredentialPermission

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

User = get_user_model()


class SetupNotInitialized(BasePermission):
    """初始化门禁：存在 superuser 时拒绝所有请求（fail-closed）。

    设计意图：防止任何人在已有 superuser 后重新初始化/接管系统。
    供 SetupInitView 使用，可复用于 Phase 2 创建管理员端点。
    """

    message = "系统已完成初始化，向导入口已关闭"

    def has_permission(self, request, view) -> bool:
        # 同步权限检查，DRF 在 async view 里也走同步 permission check 路径
        return not User.objects.filter(is_superuser=True).exists()
```

> **注意**：DRF 的 `check_permissions()` 在 adrf async view 中仍以同步方式调用（adrf 封装了异步适配），无需在权限类里调用 `sync_to_async`。这与 `ProviderCredentialPermission` 的写法一致（直接访问 ORM）。

---

### Pattern 3: 后端 — 防重入原子事务（`SetupInitView`）

关键要点：`transaction.atomic()` + 事务内复核（双重检查模式）。

```python
# server/accounts/views.py（追加 SetupInitView）

from django.db import transaction

from .permissions import SetupNotInitialized
from .serializers import SetupInitSerializer  # 需新建，仅含 username/password

class SetupInitView(APIView):
    """首启初始化接口：创建第一个 superuser。

    fail-closed：存在 superuser 时一律 403（由 SetupNotInitialized 权限类拦截）。
    防重入：事务内二次检查确保并发/重复请求只可能成功一次。
    """

    permission_classes = [AllowAny, SetupNotInitialized]

    async def post(self, request):
        serializer = SetupInitSerializer(data=request.data)
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        display_name = serializer.validated_data.get("display_name", "系统管理员")

        # 原子创建：包裹在 sync_to_async + transaction.atomic() 中
        user = await sync_to_async(_create_superuser_atomic)(username, password, display_name)
        if user is None:
            # 并发情况下被另一个请求抢先初始化（事务内复核命中）
            return Response(
                {"detail": "系统已完成初始化，向导入口已关闭"},
                status=status.HTTP_403_FORBIDDEN,
            )

        logger.info("setup_superuser_created", username=username)
        return Response(
            {"user": UserSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


def _create_superuser_atomic(username: str, password: str, display_name: str):
    """在事务内创建 superuser，含二次检查防重入。

    返回值：
    - User 实例：创建成功
    - None：事务内复核发现已存在 superuser（并发重入）
    """
    with transaction.atomic():
        # 二次检查（事务内）—— SQLite 下 select_for_update 无效，
        # 依赖此处复核保证串行化；Postgres 下事务串行化自动生效
        if User.objects.filter(is_superuser=True).exists():
            return None

        return User.objects.create_superuser(
            username=username,
            password=password,
            display_name=display_name,
            source=UserSource.SYSTEM.value,
        )
```

**SQLite vs Postgres 行为**：
- SQLite（本地开发/测试）：写操作串行（一次只有一个写事务），`transaction.atomic()` + 复核足够
- Postgres（生产）：`transaction.atomic()` 默认 READ COMMITTED，事务内复核有效；对于这种一次性初始化（运行概率极低的并发），此方案已足够

---

### Pattern 4: 前端 — API 封装 `setup.ts`

```typescript
// web/src/api/setup.ts
// Source: 参照 web/src/api/users.ts 封装模式

import { get, post } from './client'

export interface SetupStatus {
  is_initialized: boolean
  needs_setup: boolean
}

export interface SetupInitRequest {
  username: string
  password: string
  display_name?: string
}

/**
 * 获取系统初始化状态（无认证可调用）
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}

/**
 * 执行首次初始化（创建 superuser）
 */
export async function initSetup(data: SetupInitRequest): Promise<{ user: unknown }> {
  return post<{ user: unknown }>('/auth/setup/', data)
}

export default { getSetupStatus, initSetup }
```

**`index.ts` re-export**（追加一行）：

```typescript
// web/src/api/index.ts（追加）
export { default as setupApi } from './setup'
export * from './setup'
```

---

### Pattern 5: 前端 — authStore 扩展（systemNeedsSetup 状态）

```typescript
// web/src/stores/auth.ts（在现有 state 区追加）

const systemNeedsSetup = ref<boolean | null>(null)  // null = 未检测
const isSetupChecked = ref(false)

/**
 * 检测系统初始化状态（应用启动时调用一次，结果缓存）
 * 容错：请求失败 → 按「已初始化」处理（fail-safe，安全优先）
 */
async function checkSetup(): Promise<void> {
  if (isSetupChecked.value) return
  try {
    const { needs_setup } = await getSetupStatus()
    systemNeedsSetup.value = needs_setup
  }
  catch {
    // 无法连接后端 → 按已初始化处理（不进向导）
    systemNeedsSetup.value = false
  }
  finally {
    isSetupChecked.value = true
  }
}

// 在 $reset() 中追加：
// systemNeedsSetup.value = null
// isSetupChecked.value = false

// 在 return {} 中追加：
// systemNeedsSetup, isSetupChecked, checkSetup
```

---

### Pattern 6: 前端 — 路由守卫修改

**关键顺序**：setup 检查 → （如需 setup 则拦截）→ initAuth → 现有逻辑。

```typescript
// web/src/main.ts 的 router.beforeEach（修改版）

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // ── Phase 1 新增：初始化状态检测（只在首次执行）──────────────
  if (!authStore.isSetupChecked) {
    await authStore.checkSetup()
  }

  // 未初始化 → 强制进向导（/setup 以外的路由全部拦截）
  if (authStore.systemNeedsSetup && to.path !== '/setup') {
    return next('/setup')
  }

  // 已初始化 → 禁止进入向导（静默重定向到登录页）
  if (!authStore.systemNeedsSetup && to.path === '/setup') {
    return next('/login')
  }
  // ── Phase 1 结束 ─────────────────────────────────────────────

  // 已有认证流程（不改动）
  if (!authStore.isInitialized) {
    await authStore.initAuth()
  }

  const publicPages = ['/login', '/force-change-password', '/403', '/oidc/callback', '/invite', '/setup']
  const authRequired = !publicPages.some(p => to.path === p || to.path.startsWith(`${p}/`))

  // ... 其余现有逻辑不变 ...
})
```

> **为何 setup 检查要在 `initAuth()` 之前**：全新未初始化实例没有任何用户，`/me` 必然返回 401。若先跑 `initAuth()`，会触发 token 刷新失败 → `auth:logout` 事件 → state reset，干扰后续 setup 流程。先检查 setup 状态，未初始化时直接拦截到 `/setup`，`initAuth()` 完全跳过。

---

### Pattern 7: i18n 接入（最低风险路径）

`unplugin-vue-i18n@1.0.11` 已在 `vite.config.ts` 配置：

```typescript
VueI18n({
  include: [resolve(__dirname, 'src/locales/**')],
}),
```

**结论**：该插件支持两种接入方式：
1. **显式导入**（推荐，最低风险）：创建 `zh-CN.json`，在 `main.ts` import 后传给 `createI18n`
2. **虚拟模块**：`import messages from '@intlify/unplugin-vue-i18n/messages'`（需插件版本支持，更动 main.ts 少）

推荐方式 1（与 CONTEXT.md "内联亦可接受" 一致，且最直观）：

**Step 1：** 创建 `web/src/locales/zh-CN.json`

```json
{
  "setup": {
    "title": "首次设置",
    "subtitle": "欢迎使用 Friday AI，开始初始化你的实例",
    "detecting": "正在检测系统状态…",
    "createAdmin": "创建管理员账户",
    "creating": "创建中…",
    "placeholder": "即将开始引导设置",
    "errors": {
      "serverUnreachable": "无法连接到服务器，请检查后端服务后重试"
    }
  }
}
```

**Step 2：** 修改 `web/src/main.ts`

```typescript
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en',
  messages: {
    'zh-CN': zhCN,
  },
})
```

**Step 3：** 在 `setup.vue` 中使用 `useI18n()`（已通过 AutoImport 自动导入）：

```typescript
const { t } = useI18n()
// 使用 t('setup.title') 等替换硬编码文案
```

---

### Anti-Patterns to Avoid

- **在 async DRF view 中直接调用 `transaction.atomic()` 上下文管理器**：必须包在 `sync_to_async` 包裹的同步函数内，否则 Django 的事务状态与异步线程不匹配。`server/system/views.py` 第 499-514 行展示了正确模式（`@sync_to_async def _set_default_atomic()`）。
- **在权限类 `has_permission` 里使用 `async def`**：DRF 权限检查路径在 adrf 下仍为同步；直接写同步 ORM 即可（见 `system/permissions.py`）。
- **在 `router.beforeEach` 中把 setup 检查放在 `initAuth()` 之后**：全新实例 `initAuth()` 会触发 401 → token refresh 失败 → logout 事件，干扰 setup 流程。
- **setup 状态请求失败时 `needsSetup = true`**：会导致已有生产实例在后端暂时不可达时误进向导，存在接管风险。应 fail-safe（按已初始化处理）。
- **`POST /api/auth/setup/` 仅依赖前置 permission 类而不做事务内复核**：permission 类检查与实际创建之间存在 TOCTOU 窗口，并发两个请求可能双双通过 permission 检查后同时创建 superuser。必须在事务内再次检查。

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 异步 ORM 访问 | 自己写 asyncio.run() 或 loop.run_until_complete() | `asgiref.sync_to_async` | 已是全项目约定，与 ASGI event loop 安全共存 |
| 原子写操作 | 乐观锁 + 重试逻辑 | `transaction.atomic()` + 事务内复核 | 已有 `system/views.py` 范式，项目标准做法 |
| 权限判断 | 在 view 里手写 `if User.objects.filter(...).exists()` | `SetupNotInitialized` 权限类 | 可复用（Phase 2 同一端点复用），DRF permission 机制标准语义 |
| i18n catalog | 硬编码中文字符串到 Vue 模板 | `vue-i18n` + `zh-CN.json` | CONTEXT.md E 决定：文案必须经 `t()`/`$t` 取用 |

---

## Common Pitfalls

### Pitfall 1: DRF `permission_classes` 中权限类的 ORM 查询为同步

**What goes wrong：** 在 adrf async view 的 `permission_classes` 中使用含 ORM 查询的权限类，开发者误以为需要 `async def has_permission`。

**Why it happens：** adrf 的 `APIView.check_permissions()` 内部将同步权限检查 dispatch 到同步上下文，权限类中直接调用同步 ORM 是安全的。

**How to avoid：** 权限类保持同步（继承 `BasePermission`，`has_permission` 为普通 `def`），直接调用 `User.objects.filter(...).exists()`。参见 `server/system/permissions.py` 全部方法均为同步 `def`。

**Warning signs：** 如果看到权限类中 `async def has_permission`，是错误写法。

---

### Pitfall 2: SQLite 下 `select_for_update` 静默 no-op

**What goes wrong：** 在防重入逻辑中使用 `User.objects.select_for_update().filter(...)` 期望在 SQLite 下也有锁效果。SQLite 的 `select_for_update` 不报错，但实际上不加行锁（Django 在 SQLite 下忽略该子句）。

**Why it happens：** Django 文档提及 `select_for_update` 在 SQLite 上是无效的，但不抛出异常。

**How to avoid：** 依赖「事务内复核」作为主保险，而非依赖 `select_for_update`。CONTEXT.md 决定 B 已明确此策略："SQLite 本地开发下 select_for_update 退化为 no-op，因此以'事务内复核 + 唯一性'双保险"。

---

### Pitfall 3: `router.beforeEach` 中对 `/setup` 的双向守卫顺序

**What goes wrong：** 如果先检查 `needs_setup = false → /setup 重定向到 /login` 的条件，而用户同时匹配多个规则，可能产生重定向循环。

**Why it happens：** `/login` 在 `publicPages` 中，但如果 `needs_setup = true` 而用户又被重定向到 `/login`，下一次守卫触发时会再重定向到 `/setup`。

**How to avoid：** 在 Phase 1 守卫代码中，两个 setup 分支（未初始化/已初始化）用互斥条件且优先于现有守卫代码返回。`/setup` 必须加入 `publicPages`（无认证即可访问），避免现有认证守卫再次拦截。

---

### Pitfall 4: `setup.vue` 的 `onMounted` 重复调用 status API

**What goes wrong：** `setup.vue` 当前在 `onMounted` 里调用 `GET /api/auth/setup/status/`，与路由守卫重复请求，且使用的是原始 `fetch` 而非 `api/setup.ts`。

**Why it happens：** `setup.vue` 是遗留代码，路由守卫是新增逻辑。

**How to avoid：** Phase 1 实施后，`setup.vue` 的 `onMounted` 检查是冗余的（守卫已保证只有 `needs_setup=true` 时才到达 `/setup`）。可以：(a) 保留原有 onMounted（无害，只是多一次请求）；(b) 简化为从 authStore 读取缓存状态。推荐方式 (a) 减少改动风险。

---

### Pitfall 5: `SetupInitSerializer` 缺失

**What goes wrong：** `SetupInitView` 需要一个接收 `username`/`password`/`display_name` 的 serializer，如果不新建，要么复用不匹配的 serializer，要么直接读 `request.data` 失去验证。

**How to avoid：** 新建 `SetupInitSerializer`（`server/accounts/serializers.py`），字段：`username: CharField`，`password: CharField(min_length=6)`，`display_name: CharField(required=False)`。Phase 2 可在此基础上增加密码强度校验。

---

## Code Examples

### 完整视图注册流

```python
# server/accounts/urls.py（新增部分）
from .views import SetupStatusView, SetupInitView

urlpatterns = [
    # ... 现有路由 ...
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    path("setup/", SetupInitView.as_view(), name="setup"),
]
```

### 前端 authStore 集成（确认使用 Composition API defineStore）

`server/stores/auth.ts` 使用 `defineStore('auth', () => {...})` 的 setup store 形式（Composition API），新增 state 和 action 与现有 `user`、`isInitialized` 等 ref 并列即可，无需改变 store 定义风格。

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Django sync views | adrf async views + sync_to_async | Django 5.1 + adrf 0.1.12 | 所有新视图必须遵循异步模式 |
| 手写路由守卫中 superuser 检查 | 独立 permission 类 + 守卫缓存 | Phase 1 引入 | 可复用性、单一职责 |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | adrf async view 的 `permission_classes` 走同步 `has_permission`（DRF 同步分派） | Pattern 2 | 若为异步，需改为 `async def has_permission` + `sync_to_async` 包 ORM 查询 |
| A2 | `unplugin-vue-i18n@1.0.11` 配合 `include` 可直接 import JSON locale 文件并传给 createI18n | Pattern 7 | 若需额外配置，退化方案：内联 messages 对象到 main.ts（CONTEXT 允许） |

**两条 ASSUMED 项均有退化路径，不阻塞规划。**

---

## Open Questions

1. **`SetupInitView` 是否需要 `display_name` 字段？**
   - setup.vue 硬编码 `display_name: '系统管理员'` 传给后端
   - Phase 1 可接受，Phase 2 完善 UX 时再改
   - Recommendation：serializer 将 `display_name` 设为 optional，默认 `"系统管理员"`

2. **Phase 1 的 `POST /api/auth/setup/` 是否自动建立登录会话（set cookie）？**
   - CONTEXT 决定 D："现有 setup.vue 的管理员表单继续可用（接到新门禁 POST 后端）"
   - setup.vue 中提交后做 `authStore.isAuthenticated = true` 但依赖后端下发 cookie
   - Phase 1 的最小实现：返回 `user` 对象（201），**不**下发 JWT cookie（自动登录属 Phase 2 ADMIN-03）
   - setup.vue 的 `router.push('/')` 会被守卫拦截（已初始化后 `needs_setup=false`，未登录 → `/login`）
   - Recommendation：Phase 1 返回 201 + user，不自动登录；页面跳转到 `/login` 让用户手动登录即可（Phase 2 完善）

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14 + Django 5.1 | 后端视图 | ✓ | 见 server/.python-version | — |
| adrf | 异步视图 | ✓ | >=0.1.12 | — |
| Vue 3 + Vite | 前端 | ✓ | vue@^3.5.26 | — |
| vue-i18n | i18n | ✓ | ^10.x（pnpm catalog） | — |
| unplugin-vue-i18n | locale 编译 | ✓ | ^1.0.11 | 退化：内联 messages |
| pytest + pytest-django | 后端测试 | ✓ | pytest>=9.0.2 | — |

**Missing dependencies with no fallback：** 无。

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-django |
| Config file | `server/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `cd server && python -m pytest tests/test_setup.py -x -v` |
| Full suite command | `cd server && python -m pytest tests/ -v` |
| Frontend framework | vitest |
| Frontend quick run | `cd web && pnpm test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SETUP-01 | 无 superuser → 访问任意路由跳转到 /setup | frontend (router guard) | `pnpm test -- router` | ❌ Wave 0 |
| SETUP-02 | GET /api/auth/setup/status/ 返回正确 needs_setup 字段 | unit (backend) | `pytest tests/test_setup.py::TestSetupStatus -x` | ❌ Wave 0 |
| SETUP-02 | 有 superuser → is_initialized=true, needs_setup=false | unit (backend) | `pytest tests/test_setup.py::TestSetupStatus::test_status_after_superuser_created -x` | ❌ Wave 0 |
| SETUP-03 | 已初始化 → POST /api/auth/setup/ 返回 403 | unit (backend) | `pytest tests/test_setup.py::TestSetupInit::test_init_blocked_when_initialized -x` | ❌ Wave 0 |
| SETUP-03 | 已初始化 → 访问 /setup 路由被重定向到 /login | frontend (router guard) | `pnpm test -- router` | ❌ Wave 0 |
| SETUP-04 | 并发/重复 POST /api/auth/setup/ → 只有第一次成功，后续全部 403 | integration (backend) | `pytest tests/test_setup.py::TestSetupInit::test_concurrent_init_rejected -x` | ❌ Wave 0 |

### Backend 测试编写规范

参照 `server/tests/test_auth.py` 的 `@pytest.mark.django_db` + `api_client` 风格（`APIClient` 无需 `pytest-asyncio`，Django test runner 桥接异步视图）：

```python
# server/tests/test_setup.py（新建）

import pytest
from rest_framework import status

@pytest.mark.django_db
class TestSetupStatus:
    """GET /api/auth/setup/status/ 端点测试。"""

    def test_status_uninitialized(self, api_client):
        """无 superuser → needs_setup=True, is_initialized=False。"""
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is True
        assert response.data["is_initialized"] is False

    def test_status_initialized(self, api_client, admin_user):
        """有 superuser → needs_setup=False, is_initialized=True。"""
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is False
        assert response.data["is_initialized"] is True


@pytest.mark.django_db
class TestSetupInit:
    """POST /api/auth/setup/ 端点测试。"""

    def test_init_success_when_uninitialized(self, api_client):
        """无 superuser → 创建成功，返回 201。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "admin", "password": "Password123"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "user" in response.data

    def test_init_blocked_when_initialized(self, api_client, admin_user):
        """已有 superuser → fail-closed 403。SETUP-03/04 核心断言。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "hacker", "password": "Password123"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_request_rejected(self, api_client):
        """重复 POST → 第一次成功，第二次 403（SETUP-04 防重入）。"""
        data = {"username": "admin", "password": "Password123"}
        r1 = api_client.post("/api/auth/setup/", data, format="json")
        r2 = api_client.post("/api/auth/setup/", data, format="json")
        assert r1.status_code == status.HTTP_201_CREATED
        assert r2.status_code == status.HTTP_403_FORBIDDEN
```

### Sampling Rate

- **Per task commit：** `cd server && python -m pytest tests/test_setup.py -x`
- **Per wave merge：** `cd server && python -m pytest tests/ -x --tb=short`
- **Phase gate：** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `server/tests/test_setup.py` — 覆盖 SETUP-01..04（全部新建）
- [ ] `server/accounts/permissions.py` — `SetupNotInitialized` 权限类（新建）
- [ ] `server/accounts/serializers.py` — `SetupInitSerializer`（追加到现有 serializers）
- [ ] `web/src/locales/zh-CN.json` — 首个 locale 文件（新建）

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | `SetupNotInitialized` 权限类 fail-closed；事务内二次检查 |
| V3 Session Management | no (Phase 2) | 自动登录属 Phase 2 ADMIN-03 |
| V4 Access Control | yes | `AllowAny` + `SetupNotInitialized` 双层 permission |
| V5 Input Validation | yes | `SetupInitSerializer` 字段校验（username, password min_length） |
| V6 Cryptography | yes | `User.objects.create_superuser` 内部走 Django 默认密码哈希（pbkdf2/argon2） |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 已存在实例被攻击者访问 /setup 接管 | Elevation of Privilege | `SetupNotInitialized` 权限类一律 403；路由守卫静默重定向到 /login |
| 并发两个请求双双建号 | Tampering (data integrity) | `transaction.atomic()` + 事务内复核 |
| TOCTOU（permission 检查与创建之间的窗口） | Tampering | 事务内复核是主保险（permission 类 pre-check 是 UX，不是安全保证） |
| 密码信息泄漏 | Information Disclosure | 响应体仅返回 user 对象（不含密码），status API 不泄露用户名/数量 |

---

## Sources

### Primary (HIGH confidence)

- `server/accounts/views.py` — async DRF 视图模式（adrf + AllowAny + sync_to_async）[VERIFIED: 直接读取源码]
- `server/accounts/urls.py` — URL 注册模式 [VERIFIED: 直接读取源码]
- `server/system/permissions.py` — DRF BasePermission 子类模式 [VERIFIED: 直接读取源码]
- `server/system/views.py:499-514` — `sync_to_async` + `transaction.atomic()` 模式 [VERIFIED: 直接读取源码]
- `server/accounts/management/commands/init_superuser.py` — `User.objects.filter(is_superuser=True).exists()` 判定 [VERIFIED: 直接读取源码]
- `web/src/main.ts` — router.beforeEach + publicPages + i18n 注册现状 [VERIFIED: 直接读取源码]
- `web/src/stores/auth.ts` — authStore Composition API 结构 [VERIFIED: 直接读取源码]
- `web/src/api/users.ts` — API 封装模式 [VERIFIED: 直接读取源码]
- `web/vite.config.ts` — `unplugin-vue-i18n` 配置（include 路径） [VERIFIED: 直接读取源码]
- `server/tests/conftest.py` — pytest fixtures（api_client, admin_user）[VERIFIED: 直接读取源码]
- `server/tests/test_auth.py` — 后端测试风格（pytest.mark.django_db + APIClient）[VERIFIED: 直接读取源码]

### Secondary (MEDIUM confidence)

- Django 文档：SQLite 下 `select_for_update` 行为（训练数据，与代码实测一致）[ASSUMED]
- `unplugin-vue-i18n@1.0.11` include 选项语义（基于 vite.config.ts 配置推断）[ASSUMED]

---

## Metadata

**Confidence breakdown：**
- Standard stack：HIGH — 全部依赖已在项目中，直接验证
- Architecture：HIGH — 直接参照既有视图/测试/store 模式，无猜测成分
- Pitfalls：HIGH — 来自源码实测（SQLite select_for_update、adrf 权限同步调用）
- i18n 装载方式：MEDIUM — `unplugin-vue-i18n` 具体行为基于配置推断，退化路径已预备

**Research date：** 2026-06-08
**Valid until：** 2026-07-08（30 天，依赖均为稳定版）
