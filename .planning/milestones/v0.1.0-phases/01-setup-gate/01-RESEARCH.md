# Phase 1: 向导门禁与初始化状态检测 - Research

**Researched:** 2026-06-08
**Domain:** Django async DRF + Vue 3 Router Guard + vue-i18n
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **A. 状态接口**：路径 `GET /api/auth/setup/status/`，响应 `{needs_setup, is_initialized}`，权限 `AllowAny`，adrf APIView + `sync_to_async`，挂载 accounts app。
- **B. fail-closed + 防重入**：新增 `SetupNotInitialized` 可复用权限类；`POST /api/auth/setup/` 在 `transaction.atomic()` 内 double-check，存在 superuser 即 403；Phase 1 最小实现：未初始化时创建 superuser（密码增强留 Phase 2）。
- **C. 前端守卫**：`router.beforeEach` 加 setup 分支，`needs_setup=true` → 除 `/setup` 外全部重定向到 `/setup`；已初始化 → 访问 `/setup` 重定向到 `/login`；`/setup` 加入 `publicPages`；状态获取失败 fail-safe 按"已初始化"处理。
- **D. 向导外壳**：改造现有 `web/src/pages/setup.vue` 为外壳容器，沿用 glass 卡片风格，管理员表单 Phase 1 继续可用（Phase 2 增强 UX）。
- **E. i18n**：向导文案经 `vue-i18n` 取用（`setup.*` 命名空间），默认 zh-CN；若接入成本过高退化为 `main.ts` 内联 messages 对象亦可接受，但文案必须经 `$t()` 取用。

### Claude's Discretion
- 状态缓存落点（auth store vs 新建 setup store）。
- 权限类与锁工具的具体文件命名。
- 向导外壳的步骤指示器是否在 Phase 1 渲染。
- i18n catalog 的具体装载实现方式。

### Deferred Ideas (OUT OF SCOPE)
- 管理员创建的完整 UX（密码强度、二次确认、自动登录会话）→ Phase 2。
- LLM 供应商配置、Claude Code 绑定 → Phase 3。
- 安全密钥校验、飞书/RAG 可选步骤 → Phase 4。
- `entrypoint.sh` 迁移与向后兼容 → Phase 5。
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SETUP-01 | 系统检测到不存在任何超级管理员时，用户首次访问 Web 自动进入首启初始化向导 | 前端路由守卫 + `getSetupStatus()` 调用确定重定向逻辑 |
| SETUP-02 | 后端提供只读「初始化状态」接口，前端路由守卫据此放行 | `SetupStatusView` + `getSetupStatus()` + router guard 实现 |
| SETUP-03 | 向导完成后，初始化接口与界面对所有访问者关闭（403 或重定向到登录） | `SetupNotInitialized` 权限类 + guard 重定向 `/setup` → `/login` |
| SETUP-04 | 初始化接口 fail-closed 且防重入/并发保护 | `transaction.atomic()` + double-check + `SetupNotInitialized` permission |
</phase_requirements>

---

## Summary

Phase 1 是纯粹的「门禁层」，无业务逻辑，只需三样东西：一个只读状态接口、一个 fail-closed 写入接口（附防重入）、以及前端路由守卫根据状态分流。所有代码都在已知位置（`accounts` app + `main.ts`），模式完全可从既有代码推导。

后端新增两个视图（`SetupStatusView` + `SetupInitView`）、一个权限类（`SetupNotInitialized`），注册两条 URL，整体改动控制在 `server/accounts/` 内。前端新增 `web/src/api/setup.ts`（两个函数），在 `web/src/stores/auth.ts` 加一个 `needsSetup` ref，在 `web/src/main.ts` 的 `router.beforeEach` 加 setup 分支，在 `web/src/locales/zh-CN.json` 落地 `setup.*` 文案。

关键约束：`auth.ts` 中 `isInitialized` 指的是 `initAuth()` 是否已运行（**认证初始化**），不是系统是否已 setup。规划阶段须严格区分，避免命名混淆。

**Primary recommendation:** 后端用 `sync_to_async` 包装 `transaction.atomic()` 内的 double-check + create 实现原子防重入；前端守卫在 `authStore.initAuth()` 之前先检查 setup 状态，状态缓存直接加到 `authStore`（`needsSetup` + `setupStatusChecked` 两个 ref）避免新建 store。

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 初始化状态检测（is_initialized） | API / Backend | — | 唯一可信的 superuser 存在性判定；前端仅消费 |
| Fail-closed 门禁（SetupNotInitialized） | API / Backend | — | 防止前端绕过，需 DB-level 校验 |
| 防重入/并发保护（atomic + double-check） | Database / Storage | API / Backend | DB 事务串行化是底层保障，视图只负责触发 |
| 路由守卫分流（未初始化→/setup，已初始化禁入） | Browser / Client | — | 纯前端路由逻辑，backend 也有 403 兜底 |
| 初始化状态缓存（needsSetup） | Browser / Client | — | 避免每次路由跳转都请求后端 |
| 向导外壳页（/setup） | Browser / Client | — | SPA 页面，无 SSR |
| i18n 文案（setup.* namespace） | Browser / Client | — | vue-i18n 客户端渲染 |

---

## Standard Stack

### Core（全部已在项目中）
| Library | Version | Purpose | 来源 |
|---------|---------|---------|------|
| `adrf` | `>=0.1.12` | Django 异步视图 | [VERIFIED: pyproject.toml] |
| `djangorestframework` | `>=3.15` | DRF 权限类、Response | [VERIFIED: pyproject.toml] |
| `asgiref` | Django 依赖 | `sync_to_async` 桥接 ORM | [VERIFIED: 项目代码已用] |
| `django` | `>=5.1` | `transaction.atomic()` | [VERIFIED: pyproject.toml] |
| `vue-i18n` | `^11.2.8` | 前端国际化 | [VERIFIED: web/pnpm-workspace.yaml] |
| `unplugin-vue-i18n` | `^1.0.11` | locale 文件 HMR + 编译优化 | [VERIFIED: web/pnpm-workspace.yaml] |

**无需安装任何新依赖。** Phase 1 所有实现均使用已有依赖。

---

## Architecture Patterns

### System Architecture Diagram

```
浏览器请求
    │
    ▼
[router.beforeEach] ── 是否已检查 setup 状态?
    │                         │ 否
    │                    [GET /api/auth/setup/status/]
    │                         │ 响应 {needs_setup, is_initialized}
    │                    缓存到 authStore.needsSetup
    │
    ├── needs_setup=true AND 目标路径≠/setup ──► redirect /setup
    ├── needs_setup=false AND 目标路径=/setup ──► redirect /login
    │
    ▼ (其余路由正常走 initAuth + auth 守卫)
[authStore.initAuth()] ── GET /api/auth/me/
    │
    ▼
正常路由放行

POST /api/auth/setup/ (来自 setup.vue 表单)
    │
[SetupNotInitialized permission]
    │ 存在 superuser → 403 Forbidden（fail-closed）
    │ 不存在 superuser → 放行
    │
[SetupInitView.post()]
    │
[sync_to_async(_atomic_create_superuser)()]
    │   transaction.atomic()
    │   ├── User.objects.filter(is_superuser=True).exists()
    │   │       True  → return None（并发抢占，拒绝）
    │   │       False → User.objects.create_superuser(...)
    │   └── return user | None
    │
    ├── None → 409 Conflict（并发冲突）
    └── user → 201 Created
```

### 推荐项目结构（新增/修改文件）

```
server/accounts/
├── views.py                   # 新增 SetupStatusView, SetupInitView
├── urls.py                    # 新增 setup/status/ 和 setup/ 两条路由
├── permissions.py             # 新建：SetupNotInitialized 权限类
└── serializers.py             # 新增 SetupInitSerializer

web/src/
├── api/
│   ├── setup.ts               # 新建：getSetupStatus(), createSuperuser()
│   └── index.ts               # 新增 setup 模块 re-export
├── stores/
│   └── auth.ts                # 新增 needsSetup, setupStatusChecked refs + fetchSetupStatus()
├── locales/
│   └── zh-CN.json             # 新建（currently 仅有 .gitkeep）
└── main.ts                    # 修改：router.beforeEach 加 setup 分支
```

---

## Pattern 1: 异步 DRF 只读状态视图（SetupStatusView）

[VERIFIED: 源自 `server/accounts/views.py` 已有模式]

```python
# server/accounts/views.py
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

User = get_user_model()


class SetupStatusView(APIView):
    """只读初始化状态接口。

    GET /api/auth/setup/status/
    无需认证，响应 {needs_setup: bool, is_initialized: bool}。
    不泄露用户数量/用户名等敏感信息。
    """

    permission_classes = [AllowAny]

    async def get(self, request):
        is_initialized = await sync_to_async(
            User.objects.filter(is_superuser=True).exists
        )()
        return Response({
            "is_initialized": is_initialized,
            "needs_setup": not is_initialized,
        })
```

**关键细节：**
- `sync_to_async(queryset.exists)()` — 包装的是 `exists` 方法引用，不是调用结果
- 等价写法：`await sync_to_async(lambda: User.objects.filter(is_superuser=True).exists())()`
- 若用 Django 5.x 原生 async ORM：`await User.objects.filter(is_superuser=True).aexists()` 同样可行（见 `server/system/views.py:37`）

---

## Pattern 2: fail-closed 权限类（SetupNotInitialized）

[VERIFIED: 源自 `server/system/permissions.py` 中 `BasePermission` 用法]

```python
# server/accounts/permissions.py（新建）
from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

User = get_user_model()


class SetupNotInitialized(BasePermission):
    """Fail-closed 门禁：存在任意 superuser 即拒绝（403）。

    供 SetupInitView 与 Phase 2 管理员创建接口共用，
    保证单一门禁来源，防止向导被用于重置/接管已有实例。
    """

    message = "系统已初始化，初始化接口已关闭"

    def has_permission(self, request, view) -> bool:
        # 注意：此方法在异步视图中由 DRF 同步调用；
        # adrf 会在后台线程运行，ORM 查询在 DRF permission check 时仍是同步的。
        return not User.objects.filter(is_superuser=True).exists()
```

**重要说明：** adrf 的权限类检查依旧是同步调用。`has_permission` 中的 ORM 查询不需要 `sync_to_async` 包装，因为 DRF 在执行 permission check 时使用同步路径。

---

## Pattern 3: 原子事务防重入写入（SetupInitView）

[VERIFIED: 模式来自 `server/workflows/engine/scheduler.py` + `server/system/views.py` 事务用法]

```python
# server/accounts/views.py（追加）
from django.db import transaction
from rest_framework import status


class SetupInitView(APIView):
    """首启初始化接口（fail-closed + 防重入）。

    POST /api/auth/setup/
    仅当无 superuser 时可调用（由 SetupNotInitialized 权限类前置拦截）。
    在原子事务内二次复核，确保并发/重复请求只成功一次。
    """

    permission_classes = [SetupNotInitialized]

    async def post(self, request):
        serializer = SetupInitSerializer(data=request.data)
        # KEEP: is_valid() 执行 DB 查询（用户名唯一性校验）
        await sync_to_async(serializer.is_valid)(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        display_name = serializer.validated_data.get("display_name", "系统管理员")

        user = await sync_to_async(_atomic_create_superuser)(
            username=username,
            password=password,
            display_name=display_name,
        )

        if user is None:
            # 事务内 double-check 发现已存在 superuser（并发抢占场景）
            return Response(
                {"detail": "系统已初始化，初始化接口已关闭"},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {"detail": "管理员账户创建成功"},
            status=status.HTTP_201_CREATED,
        )


def _atomic_create_superuser(username: str, password: str, display_name: str):
    """在原子事务内创建 superuser，并发/重入安全。

    SQLite 下 select_for_update 为 no-op，依赖 double-check + 用户名唯一约束。
    Postgres 下 transaction.atomic() 提供 READ COMMITTED 串行保障。
    返回 None 表示已存在 superuser（并发冲突），由调用方返回 409。
    """
    with transaction.atomic():
        # 事务内二次复核（double-check pattern）
        if User.objects.filter(is_superuser=True).exists():
            return None
        return User.objects.create_superuser(
            username=username,
            password=password,
            display_name=display_name,
            source=UserSource.SYSTEM.value,
        )
```

**并发安全性分析：**

| 场景 | SQLite | Postgres |
|------|--------|----------|
| 串行请求（正常） | ✅ double-check 生效 | ✅ double-check 生效 |
| 真并发（两请求同时通过 permission check 进入 view） | ⚠️ 两请求都进入事务，double-check 均为 False → 两个 superuser（但用户名唯一约束抛 IntegrityError → 回滚一个） | ✅ 事务串行化保护 |
| 重复 POST（superuser 已存在） | ✅ permission class 403 | ✅ permission class 403 |

**SQLite 并发说明：** SQLite 写锁（WAL 模式）在 `EXCLUSIVE` 级别序列化写事务，配合 `transaction.atomic()` 实际上可以防止真并发写冲突。即使如此，Django 模型上 `username` 的 `UNIQUE` 约束提供了最终保险——任何重复用户名都会触发 `IntegrityError`，由 Django 自动回滚并返回 500（需要捕获后返回 409）。

**实现建议：** 在 `SetupInitView.post()` 中捕获 `IntegrityError`：
```python
from django.db import IntegrityError

try:
    user = await sync_to_async(_atomic_create_superuser)(...)
except IntegrityError:
    return Response({"detail": "用户名已存在"}, status=status.HTTP_409_CONFLICT)
```

---

## Pattern 4: URL 注册（accounts/urls.py）

[VERIFIED: 源自 `server/accounts/urls.py` 既有模式]

```python
# 在 server/accounts/urls.py 末尾追加（不修改现有 urlpatterns）
from .views import SetupStatusView, SetupInitView

urlpatterns = [
    # ... 现有 path(...)

    # 首启向导：初始化状态（AllowAny 只读）
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    # 首启向导：初始化写入（fail-closed + 防重入）
    path("setup/", SetupInitView.as_view(), name="setup-init"),
]
```

挂载后完整路径为：
- `GET /api/auth/setup/status/` — 对应 `setup.vue` 中 `fetch('/api/auth/setup/status/')`
- `POST /api/auth/setup/` — 对应 `setup.vue` 中 `fetch('/api/auth/setup/', {method: 'POST', ...})`

**路径与前端已有 setup.vue 硬编码路径完全对齐，无需改前端 URL。**

---

## Pattern 5: 前端 setup API 模块

[VERIFIED: 源自 `web/src/api/users.ts` 既有封装模式]

```typescript
// web/src/api/setup.ts（新建）

import { get, post } from './client'

export interface SetupStatus {
  needs_setup: boolean
  is_initialized: boolean
}

export interface SetupInitRequest {
  username: string
  password: string
  display_name?: string
}

/**
 * 查询系统初始化状态（AllowAny，无需认证）
 * 路由守卫在 initAuth() 前调用，fail-safe：异常时按已初始化处理
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}

/**
 * 首启初始化：创建管理员账号
 * Phase 1 最小实现，Phase 2 增强 UX（密码强度/二次确认/自动登录）
 */
export async function initSetup(data: SetupInitRequest): Promise<void> {
  return post<void>('/auth/setup/', data)
}

export default { getSetupStatus, initSetup }
```

**注意：** 当系统已初始化时 `POST /api/auth/setup/` 返回 403，`api/client.ts` 会触发 `auth:forbidden` 全局事件并重定向到 `/403`。`setup.vue` 中的提交逻辑应继续使用原始 `fetch`（如现有代码所示），或改用 `api/setup.ts` 并在调用方 `catch (ApiError)` 拦截 403 做自定义处理，避免全局重定向。

**推荐：setup.vue 的 POST 提交逻辑保持使用原始 `fetch`（不通过 api/client.ts），与现有代码一致。**

---

## Pattern 6: router.beforeEach 加 setup 分支

[VERIFIED: 源自 `web/src/main.ts` 既有守卫结构]

```typescript
// web/src/main.ts 修改：router.beforeEach
import { getSetupStatus } from '~/api/setup'

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // ── Step 1：初始化状态检测（每次 app 首次守卫触发时检查一次）──
  if (!authStore.setupStatusChecked) {
    try {
      const status = await getSetupStatus()
      authStore.needsSetup = status.needs_setup
    }
    catch {
      // fail-safe：后端不可达时按「已初始化」处理，防止误导向向导重置生产实例
      authStore.needsSetup = false
    }
    authStore.setupStatusChecked = true
  }

  // ── Step 2：setup 路由守卫 ──
  if (authStore.needsSetup && to.path !== '/setup') {
    // 未初始化：除 /setup 外任意路由 → 重定向到向导
    return next('/setup')
  }
  if (!authStore.needsSetup && to.path === '/setup') {
    // 已初始化：试图访问向导 → 重定向到登录页
    return next('/login')
  }

  // ── Step 3：原有认证守卫（不变）──
  if (!authStore.isInitialized) {
    await authStore.initAuth()
  }

  const publicPages = ['/login', '/force-change-password', '/403', '/oidc/callback', '/invite', '/setup']
  const authRequired = !publicPages.some(p => to.path === p || to.path.startsWith(`${p}/`))

  // ... 其余逻辑不变
})
```

**`/setup` 加入 `publicPages`：** 确保未登录用户访问向导时不被 auth 守卫拦截到 `/login`（未初始化阶段没有用户可登录）。

---

## Pattern 7: auth store 扩展（setup 状态缓存）

[VERIFIED: 源自 `web/src/stores/auth.ts` 既有 Pinia 写法]

```typescript
// web/src/stores/auth.ts — 追加两个 ref
const needsSetup = ref(false)           // 系统是否需要 setup（由路由守卫写入）
const setupStatusChecked = ref(false)   // 是否已检查过 setup 状态（每次 app 启动只查一次）

// $reset() 中需重置
function $reset() {
  // ... 现有重置
  needsSetup.value = false
  setupStatusChecked.value = false
}

// return 中暴露
return {
  // ... 现有
  needsSetup,
  setupStatusChecked,
}
```

**使用 auth store 而非新建 setup store 的理由：** 状态极简（2 个 ref），路由守卫已经 import `useAuthStore()`，无需新增模块依赖。与 CONTEXT.md Claude's Discretion 方向一致。

---

## Pattern 8: i18n zh-CN 文案装载

[VERIFIED: `vite.config.ts` 已配置 `VueI18n({ include: ['src/locales/**'] })`，`vue-i18n@^11.2.8` + `unplugin-vue-i18n@^1.0.11`]

`@intlify/unplugin-vue-i18n` 的 `include` 配置会将 `src/locales/**` 下的 JSON/YAML 文件转换为可 import 的模块，但不会自动注入到 `createI18n` 的 `messages`。**需要手动在 `main.ts` 中 import 并传入。**

```jsonc
// web/src/locales/zh-CN.json（新建）
{
  "setup": {
    "title": "首次设置",
    "subtitle": "欢迎使用 Friday AI，开始初始化你的实例",
    "loading": "正在检测系统状态…",
    "placeholder": "即将开始引导设置",
    "cta": "创建管理员账户",
    "submitting": "创建中…",
    "error": {
      "connection": "无法连接到服务器，请检查后端服务后重试"
    }
  }
}
```

```typescript
// web/src/main.ts 修改
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

**在 setup.vue 中使用：**
```vue
<script setup lang="ts">
const { t } = useI18n()  // useI18n 已被 unplugin-auto-import 自动注入，无需 import
</script>
<template>
  <h1>{{ t('setup.title') }}</h1>
</template>
```

**注意：** `useI18n` 已在 `vite.config.ts` AutoImport 中配置（`'vue-i18n': ['useI18n']`），无需手动 import。

---

## Anti-Patterns to Avoid

- **不要在 `has_permission` 中使用 `sync_to_async`：** DRF 的 permission check 在同步上下文中运行，直接执行 ORM 查询即可。
- **不要跳过 `publicPages` 添加 `/setup`：** 若 `/setup` 不在白名单，未登录用户访问向导时 auth 守卫会将其重定向到 `/login`，形成死循环（未登录 → /login → /setup? 不，无法进 setup）。
- **不要在路由守卫中 `await authStore.initAuth()` 在先再检查 setup 状态：** `initAuth()` 会调用 `GET /api/auth/me/`（需要 auth），若后端未初始化 `/me` 也会 401 → 触发 token 刷新失败 → dispatch `auth:logout` → 冗余事件。先检查 setup 状态，未初始化时短路，不执行 `initAuth()`。
- **不要对 `setup.vue` 的 POST 表单提交使用 `api/client.ts` 的封装 `post()`：** 403 会触发全局 `auth:forbidden` 事件重定向到 `/403`，破坏用户体验。提交逻辑保持原始 `fetch` 或在调用方显式 `catch ApiError` 并阻止事件传播。
- **不要遗忘 `IntegrityError` 捕获：** `create_superuser` 在并发相同用户名时抛出 `IntegrityError`，未捕获会返回 500；需捕获并返回 409。

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 异步 ORM 查询 | 自己管 DB 连接 | `sync_to_async(queryset.method)()` 或 `queryset.aexists()` | Django 5.x 提供原生 async ORM；adrf 的 `sync_to_async` 是已建立模式 |
| 事务串行化 | 内存锁/Redis 锁 | `transaction.atomic()` + double-check | DB 事务是 Django 中防并发写的标准工具；Redis 不保证与 DB 原子 |
| 权限判断 | 在 view 内 if-else | `SetupNotInitialized` permission class | 可复用到 Phase 2+；DRF 权限类提供标准 403 响应格式 |
| 路由守卫 i18n | 硬编码中文 | `vue-i18n $t()` | PROJECT 约束明确要求经 `$t()` 取用，`zh-CN.json` 管理变更 |

---

## Common Pitfalls

### Pitfall 1: `isInitialized` 命名混淆

**What goes wrong:** auth store 中已有 `isInitialized` ref，含义是「`initAuth()` 是否已执行完毕」（认证初始化状态），与「系统是否已 setup」完全不同。若规划阶段使用同一名称，会造成逻辑混乱。

**Why it happens:** 两个概念都叫"初始化"，自然产生碰撞。

**How to avoid:** 使用不同名称：
- `authStore.isInitialized` → 认证状态已检查（auth init）✅ 已存在，不要修改
- `authStore.needsSetup` → 系统需要首启 setup（system init）✅ Phase 1 新增
- `authStore.setupStatusChecked` → setup 状态已查过（cache flag）✅ Phase 1 新增

### Pitfall 2: `router.beforeEach` 顺序错误（setup 分支必须在 `initAuth` 之前）

**What goes wrong:** 若先调用 `authStore.initAuth()`，它会 `GET /api/auth/me/`。全新部署无任何用户，`/me` 返回 401，触发 token 刷新失败，dispatch `auth:logout` 事件，`authStore.$reset()` 被调用（包括 `setupStatusChecked = false`），产生无限重置循环。

**Why it happens:** `initAuth()` 假设后端有认证体系，而全新部署无 superuser 时 JWT 体系可能正常，但 `/me` 401 会导致非预期行为。

**How to avoid:** setup 状态分支必须在 `initAuth()` 之前执行，`needsSetup=true` 时直接 `return next('/setup')`，跳过 `initAuth()`。

### Pitfall 3: `has_permission` 返回 False 时 DRF 响应码不一致

**What goes wrong:** 未认证请求 + `AllowAny` → 200 OK；`SetupNotInitialized.has_permission` 返回 False → DRF 默认根据认证状态决定返回 403 还是 401（已认证用户 → 403，匿名用户 → 401）。

**How to avoid:** `SetupInitView` 预期是无认证调用，DRF 对匿名用户的权限拒绝默认返回 401（需要认证）。若希望统一返回 403，需在 settings 中调整或在视图中 override `permission_denied()`。**推荐：** `SetupInitView` 同时设置 `permission_classes = [AllowAny, SetupNotInitialized]`（先 AllowAny 允许匿名，再 SetupNotInitialized 拒绝已初始化），确保返回 403 而非 401。

### Pitfall 4: `setupStatusChecked` 在 SPA 路由跳转后被重复查询

**What goes wrong:** 每次路由跳转都调用 `getSetupStatus()`，产生不必要的后端请求。

**How to avoid:** `setupStatusChecked` flag 确保每次 app 启动只查一次。向导完成后（`POST /api/auth/setup/` 成功），手动更新 `authStore.needsSetup = false; authStore.setupStatusChecked = true`。

### Pitfall 5: SQLite 开发环境 `select_for_update` 抛异常

**What goes wrong:** SQLite 不支持 `SELECT ... FOR UPDATE`，调用会抛 `django.db.utils.NotSupportedError`。

**How to avoid:** Phase 1 不使用 `select_for_update()`，只用 `transaction.atomic()` + double-check。double-check 在 SQLite 下依赖 WAL 写锁串行化（实际够用），在 Postgres 下依赖事务 MVCC。`IntegrityError` 捕获作为最终兜底。

---

## Code Examples

### 完整 SetupInitSerializer

[VERIFIED: 源自 `server/accounts/serializers.py` 既有序列化器模式]

```python
# server/accounts/serializers.py 中新增
from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class SetupInitSerializer(serializers.Serializer):
    """首启初始化请求体校验。"""

    username = serializers.CharField(
        min_length=1,
        max_length=150,
        error_messages={"blank": "用户名不能为空"},
    )
    password = serializers.CharField(
        min_length=6,
        error_messages={"min_length": "密码至少 6 位"},
    )
    display_name = serializers.CharField(
        required=False,
        default="系统管理员",
        max_length=150,
    )

    def validate_username(self, value):
        """用户名唯一性校验（DB 查询，sync_to_async 调用者负责包装）。"""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value
```

### 前端 api/index.ts re-export

```typescript
// web/src/api/index.ts 末尾追加
export { default as setupApi } from './setup'
export * from './setup'
```

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Backend Framework | pytest + pytest-django + pytest-asyncio |
| Config file | `server/pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `cd server && uv run pytest tests/test_setup.py -v` |
| Full suite command | `cd server && uv run pytest tests/ -v --tb=short` |
| Frontend Framework | vitest |
| Frontend config | `web/vite.config.ts` (vitest integrated) |
| Frontend quick run | `cd web && pnpm test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SETUP-01 | 无 superuser 时访问任意页 → 重定向 /setup | e2e/integration | 路由守卫单元测试 | ❌ Wave 0 |
| SETUP-02 | GET /api/auth/setup/status/ 无认证返回 {needs_setup, is_initialized} | unit | `pytest tests/test_setup.py::TestSetupStatusView -x` | ❌ Wave 0 |
| SETUP-02 | 已初始化时 GET status 返回 is_initialized=true, needs_setup=false | unit | `pytest tests/test_setup.py::TestSetupStatusView::test_status_initialized -x` | ❌ Wave 0 |
| SETUP-03 | 存在 superuser 后 POST /api/auth/setup/ 返回 403 | unit | `pytest tests/test_setup.py::TestSetupInitView::test_init_post_403_when_initialized -x` | ❌ Wave 0 |
| SETUP-04 | 并发/重复 POST（已存在 superuser）均被拒绝 | unit | `pytest tests/test_setup.py::TestSetupInitView::test_concurrent_rejection -x` | ❌ Wave 0 |
| SETUP-04 | 未初始化时 POST 创建 superuser 成功 201 | unit | `pytest tests/test_setup.py::TestSetupInitView::test_init_post_success -x` | ❌ Wave 0 |

### Backend 测试骨架（参考 conftest 既有模式）

[VERIFIED: 源自 `server/tests/conftest.py` + `server/tests/test_auth.py`]

```python
# server/tests/test_setup.py（Wave 0 新建）
import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()


@pytest.mark.django_db
class TestSetupStatusView:
    """GET /api/auth/setup/status/ 测试。"""

    def test_status_not_initialized(self, api_client):
        """无 superuser 时：needs_setup=True, is_initialized=False。"""
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is True
        assert response.data["is_initialized"] is False

    def test_status_initialized(self, api_client, admin_user):
        """存在 superuser 时：needs_setup=False, is_initialized=True。"""
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is False
        assert response.data["is_initialized"] is True

    def test_status_no_auth_required(self, api_client):
        """无认证头也可调用（AllowAny）。"""
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestSetupInitView:
    """POST /api/auth/setup/ 测试。"""

    def test_init_post_success(self, api_client):
        """无 superuser 时 POST 成功创建管理员，返回 201。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "admin", "password": "admin1234", "display_name": "管理员"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="admin", is_superuser=True).exists()

    def test_init_post_403_when_initialized(self, api_client, admin_user):
        """存在 superuser 时 POST 返回 403（fail-closed）。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "new_admin", "password": "admin1234"},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_duplicate_post_rejected(self, api_client):
        """连续两次 POST 同一用户名：第一次成功，第二次被拒绝（已初始化）。"""
        data = {"username": "admin", "password": "admin1234"}
        resp1 = api_client.post("/api/auth/setup/", data, format="json")
        resp2 = api_client.post("/api/auth/setup/", data, format="json")
        assert resp1.status_code == status.HTTP_201_CREATED
        assert resp2.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_password_validation(self, api_client):
        """缺少 password 字段返回 400。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "admin"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_short_password_rejected(self, api_client):
        """密码少于 6 位返回 400。"""
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "admin", "password": "123"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
```

### Wave 0 Gaps

- [ ] `server/tests/test_setup.py` — 覆盖 SETUP-01..04 的全部后端用例（Wave 0 新建）
- [ ] `server/tests/conftest.py` — 确认 `urls` fixture 中加入 `setup_status = reverse("setup-status")` 和 `setup_init = reverse("setup-init")`
- [ ] 前端 setup guard 的单元测试（可选，CONTEXT.md 中未强制要求）

### Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/test_setup.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd-verify-work`

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | `AllowAny` on status（公开），`SetupNotInitialized` on init（fail-closed） |
| V3 Session Management | No（Phase 1 不设会话，留 Phase 2） | — |
| V4 Access Control | Yes | `SetupNotInitialized` permission class 确保已初始化实例无法被重置 |
| V5 Input Validation | Yes | `SetupInitSerializer` 校验 username/password 格式 |
| V6 Cryptography | No（Django `create_superuser` 内部用 `argon2`，不手写） | passlib[argon2] 已是项目标准 |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 向导接管攻击（已有生产实例上重调 POST /setup/） | Elevation of Privilege | `SetupNotInitialized` fail-closed：superuser 存在即 403，无论调用者 |
| 并发 race condition（两请求同时建管理员） | Tampering | `transaction.atomic()` + double-check；`IntegrityError` 捕获作最终保险 |
| 信息泄露（status 接口暴露用户数量） | Information Disclosure | 响应仅返回 `{needs_setup, is_initialized}` 布尔值，不含用户名/数量 |
| CSRF（公开 POST 接口） | Spoofing | 首启向导处于未登录状态，CSRF 保护此阶段不适用（无 session cookie）；adrf AllowAny 接口 CSRF 默认 exempt |

---

## Environment Availability

所有依赖均为项目既有组件，无外部服务依赖。

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Django / adrf | SetupStatusView, SetupInitView | ✓ | adrf>=0.1.12, django>=5.1 | — |
| DRF | permission_classes, serializers | ✓ | djangorestframework>=3.15 | — |
| vue-i18n | i18n 文案 | ✓ | ^11.2.8 | 退化为 main.ts 内联 messages |
| unplugin-vue-i18n | locale 文件编译 | ✓ | ^1.0.11 | — |

**Missing dependencies with no fallback:** 无

---

## Open Questions (RESOLVED)

1. **`SetupInitSerializer.validate_username` 中的 ORM 查询**
   - What we know: `serializer.is_valid()` 在 `sync_to_async` 包装内执行，validator 中的 `User.objects.filter().exists()` 是同步 DB 调用，在 `sync_to_async` 线程中运行（安全）
   - What's unclear: 若 Phase 2 改为 `await sync_to_async(serializer.is_valid)(raise_exception=True)` 调用方式，serializer 内部的 DB 查询是否需要特殊处理
   - Recommendation: 与现有 `InvitationAcceptView` 相同写法（`await sync_to_async(serializer.is_valid)(raise_exception=True)`），已被验证可用
   - RESOLVED: 采用 `await sync_to_async(serializer.is_valid)(raise_exception=True)`；serializer 内同步 ORM 在 sync_to_async 线程中执行，安全，风险=低。

2. **`has_permission` 同步 ORM 查询在 adrf 异步视图中是否安全**
   - What we know: adrf 文档说明 permission check 在同步上下文中调用（by DRF），不在事件循环内
   - What's unclear: 是否有 Django 5.x + adrf 版本组合导致此行为变化的边缘情况
   - Recommendation: 沿用现有项目中 `InvitationView.get_permissions()` 的同步判断模式，已验证可用
   - RESOLVED: `SetupNotInitialized.has_permission` 保持同步（DRF 在同步上下文调用权限检查），沿用 `InvitationView` 模式，风险=低。

---

## Sources

### Primary (HIGH confidence)
- [VERIFIED: server/accounts/views.py] — adrf APIView + sync_to_async + AllowAny 完整模式
- [VERIFIED: server/accounts/urls.py] — accounts URL 注册模式
- [VERIFIED: server/accounts/management/commands/init_superuser.py] — `User.objects.filter(is_superuser=True).exists()` 判定模式
- [VERIFIED: server/system/permissions.py] — BasePermission 权限类实现模式
- [VERIFIED: server/tests/conftest.py] — pytest fixtures 模式（api_client, admin_user）
- [VERIFIED: server/tests/test_auth.py] — 测试结构与断言模式
- [VERIFIED: web/src/main.ts] — router.beforeEach + publicPages + authStore 结构
- [VERIFIED: web/src/stores/auth.ts] — Pinia store（isInitialized、$reset 用法）
- [VERIFIED: web/src/api/users.ts] — API 模块封装模式
- [VERIFIED: web/src/pages/setup.vue] — 现有 setup 页面（路径约定、raw fetch 用法）
- [VERIFIED: web/vite.config.ts] — VueI18n unplugin 配置 + AutoImport useI18n
- [VERIFIED: web/pnpm-workspace.yaml] — vue-i18n@^11.2.8 + unplugin-vue-i18n@^1.0.11 版本

### Secondary (MEDIUM confidence)
- [CITED: Django docs 事务 + 并发写] — `transaction.atomic()` + double-check 是 Django 官方防重入建议模式
- [CITED: adrf README] — `has_permission` 在 DRF 同步层调用，permission class 内 ORM 查询无需 async 包装

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `has_permission` 在 adrf 异步视图中依然同步调用，ORM 无需 async 包装 | Pattern 2 | 低：已有 `InvitationView.get_permissions()` 同步 ORM 模式验证过，风险极低 |
| A2 | `@intlify/unplugin-vue-i18n` 不会自动注入 messages，需手动 import 到 `createI18n` | Pattern 8 | 中：若 plugin 在 `legacy: false` 模式下自动注入，手动 import 会导致重复（但会被覆盖）；可通过测试验证 |

**Table 2 条 ASSUMED 项风险均低，建议执行阶段直接实现并验证。**

---

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — 全部依赖已在项目中，版本已 VERIFIED
- Architecture: HIGH — 全部模式直接引用既有代码文件
- Pitfalls: HIGH — 来自代码阅读中发现的真实命名冲突与异步上下文问题
- Test Patterns: HIGH — 直接参照 `server/tests/conftest.py` + `test_auth.py`

**Research date:** 2026-06-08
**Valid until:** 2026-07-08（Django 稳定栈，30 天有效期）
