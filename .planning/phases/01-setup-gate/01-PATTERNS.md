# Phase 01: 向导门禁与初始化状态检测 - Pattern Map

**Mapped:** 2026-06-08
**Files analyzed:** 11 (new/modified)
**Analogs found:** 11 / 11

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/accounts/views.py` | controller | request-response | `server/accounts/views.py` (自身) | exact — 追加到现有文件 |
| `server/accounts/permissions.py` | middleware | request-response | `server/system/permissions.py` | exact — 同为 `BasePermission` 子类 |
| `server/accounts/serializers.py` | utility | transform | `server/accounts/serializers.py` (自身) | exact — 追加到现有文件 |
| `server/accounts/urls.py` | route | request-response | `server/accounts/urls.py` (自身) | exact — 追加到现有文件 |
| `server/tests/test_setup.py` | test | request-response | `server/tests/test_auth.py` | exact — 同为 `@pytest.mark.django_db` 类风格 |
| `web/src/api/setup.ts` | utility | request-response | `web/src/api/users.ts` | exact — 同为 `get/post` 封装模块 |
| `web/src/api/index.ts` | route | request-response | `web/src/api/index.ts` (自身) | exact — 追加 re-export |
| `web/src/main.ts` | middleware | request-response | `web/src/main.ts` (自身) | exact — 修改 `router.beforeEach` |
| `web/src/stores/auth.ts` | store | event-driven | `web/src/stores/auth.ts` (自身) | exact — 追加两个 ref |
| `web/src/pages/setup.vue` | component | request-response | `web/src/pages/setup.vue` (自身) | exact — 改造为向导外壳 |
| `web/src/locales/zh-CN.json` | config | transform | 无现存 JSON（仅 .gitkeep） | N/A — 新建 |

---

## Pattern Assignments

### `server/accounts/views.py` — 追加 `SetupStatusView` + `SetupInitView`

**Analog:** `server/accounts/views.py`（自身），参考 `InvitationAcceptView` / `LoginView`

**Imports pattern** (lines 1-32，直接复用，仅追加 `transaction` + `IntegrityError`):
```python
from adrf.views import APIView
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
import structlog

User = get_user_model()
logger = structlog.get_logger(__name__)
```

**AllowAny + async GET 模式** (参考 `LoginView` lines 34-83，`LogoutView` lines 86-95):
```python
class SetupStatusView(APIView):
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
> 关键细节：`sync_to_async(queryset.exists)()` — 包装方法引用，不是调用结果。  
> 等价写法：`await User.objects.filter(is_superuser=True).aexists()`（Django 5.x 原生 async ORM）。

**AllowAny + async POST + serializer.is_valid 包装模式** (参考 `InvitationAcceptView` lines 249-291):
```python
class SetupInitView(APIView):
    permission_classes = [AllowAny, SetupNotInitialized]

    async def post(self, request):
        serializer = SetupInitSerializer(data=request.data)
        # KEEP: is_valid() 内 validate_username 执行 DB 查询
        await sync_to_async(serializer.is_valid)(raise_exception=True)
        try:
            user = await sync_to_async(_atomic_create_superuser)(
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
                display_name=serializer.validated_data.get("display_name", "系统管理员"),
            )
        except IntegrityError:
            return Response({"detail": "用户名已存在"}, status=status.HTTP_409_CONFLICT)

        if user is None:
            return Response({"detail": "系统已初始化，初始化接口已关闭"}, status=status.HTTP_409_CONFLICT)

        return Response({"detail": "管理员账户创建成功"}, status=status.HTTP_201_CREATED)
```

**事务内 double-check 防重入函数** (参考 `init_superuser.py` lines 40-62 + `scheduler.py` 事务模式):
```python
def _atomic_create_superuser(username: str, password: str, display_name: str):
    """在原子事务内创建 superuser，并发/重入安全。

    返回 None 表示已存在 superuser（并发冲突），由调用方返回 409。
    """
    with transaction.atomic():
        if User.objects.filter(is_superuser=True).exists():
            return None
        return User.objects.create_superuser(
            username=username,
            password=password,
            display_name=display_name,
            source=UserSource.SYSTEM.value,
        )
```

**结构化日志模式** (参考 `views.py` line 31, `RefreshTokenView` lines 128-132):
```python
logger.info("setup_init_success", username=username)
logger.warning("setup_init_conflict_concurrent")
```

---

### `server/accounts/permissions.py` — 新建 `SetupNotInitialized`

**Analog:** `server/system/permissions.py`（`BasePermission` 子类范式）

**Imports + 结构模式** (analog lines 14-25):
```python
from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

User = get_user_model()
```

**has_permission 同步 ORM 查询** (analog lines 28-44，`has_permission` 在 DRF 同步层调用，无需 async 包装):
```python
class SetupNotInitialized(BasePermission):
    """Fail-closed 门禁：存在任意 superuser 即拒绝（403）。

    供 SetupInitView 与 Phase 2 管理员创建接口共用，
    保证单一门禁来源，防止向导被用于重置/接管已有实例。
    """

    message = "系统已初始化，初始化接口已关闭"

    def has_permission(self, request, view) -> bool:
        # 注意：adrf 异步视图中 DRF 依然同步调用 has_permission，
        # ORM 查询在此处不需要 sync_to_async 包装。
        return not User.objects.filter(is_superuser=True).exists()
```

> **关键约束：**  
> - `SetupInitView` 同时设置 `permission_classes = [AllowAny, SetupNotInitialized]`  
>   — 先 AllowAny 允许匿名请求，再 SetupNotInitialized 按 DB 状态拒绝，确保返回 403 而非 401  
> - `has_permission` 内直接 ORM 查询是既有项目模式（`InvitationView.get_permissions()` 验证过，参见 `views.py` lines 208-212）

---

### `server/accounts/serializers.py` — 追加 `SetupInitSerializer`

**Analog:** `server/accounts/serializers.py`（自身），参考 `InvitationAcceptSerializer` (lines 83-89) + `AdminProfileUpdateSerializer` (lines 148-161)

**Serializer.Serializer 字段定义模式** (analog lines 83-89):
```python
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
```

**validate_field DB 查询模式** (analog `AdminProfileUpdateSerializer.validate_username` lines 154-161):
```python
    def validate_username(self, value):
        """用户名唯一性校验（在 sync_to_async 包装内的线程中安全执行）。"""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value
```

> **注意：** `serializer.is_valid()` 由调用方 `await sync_to_async(serializer.is_valid)(raise_exception=True)` 包装（参考 `InvitationAcceptView` line 257, `AdminProfileView.put` line 387），因此 validator 内 ORM 查询在 sync_to_async 线程中运行，安全。

---

### `server/accounts/urls.py` — 追加 setup 路由

**Analog:** `server/accounts/urls.py`（自身，lines 1-38）

**Import + urlpatterns 追加模式** (analog lines 1-38):
```python
# 在现有 from .views import (...) 块追加：
from .views import (
    # ... 现有 import
    SetupInitView,
    SetupStatusView,
)

urlpatterns = [
    # ... 现有路由（不修改）
    # 首启向导：初始化状态（AllowAny 只读）
    path("setup/status/", SetupStatusView.as_view(), name="setup-status"),
    # 首启向导：初始化写入（fail-closed + 防重入）
    path("setup/", SetupInitView.as_view(), name="setup-init"),
]
```

> 挂载后完整路径：`GET /api/auth/setup/status/` 和 `POST /api/auth/setup/`  
> — 与 `setup.vue` 中 `fetch('/api/auth/setup/status/')` 和 `fetch('/api/auth/setup/')` 完全对齐，**无需修改前端 URL**

---

### `server/tests/test_setup.py` — 新建后端测试

**Analog:** `server/tests/test_auth.py` (lines 1-80) + `server/tests/conftest.py`

**测试文件头部 + @pytest.mark.django_db 类风格** (analog `test_auth.py` lines 1-20):
```python
"""首启向导门禁测试（SetupStatusView + SetupInitView）。"""

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()
```

**@pytest.mark.django_db class + fixtures 使用模式** (analog `test_auth.py` `TestLogin` lines 14-60):
```python
@pytest.mark.django_db
class TestSetupStatusView:
    """GET /api/auth/setup/status/ 测试。"""

    def test_status_not_initialized(self, api_client):
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is True
        assert response.data["is_initialized"] is False

    def test_status_initialized(self, api_client, admin_user):
        response = api_client.get("/api/auth/setup/status/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["needs_setup"] is False
        assert response.data["is_initialized"] is True
```

**api_client.post + format="json" 模式** (analog `test_auth.py` `TestLogin.test_login_success` lines 18-30):
```python
    def test_init_post_success(self, api_client):
        response = api_client.post(
            "/api/auth/setup/",
            {"username": "admin", "password": "admin1234"},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="admin", is_superuser=True).exists()
```

**conftest 需要更新的 `urls` fixture**（参考 `conftest.py` lines 212-271）：
```python
# conftest.py URLs 类中追加
setup_status = reverse("setup-status")
setup_init = reverse("setup-init")
```

---

### `web/src/api/setup.ts` — 新建 setup API 模块

**Analog:** `web/src/api/users.ts`（完全相同的封装风格）

**Imports + 接口定义模式** (analog `users.ts` lines 1-7):
```typescript
/**
 * Setup API 服务
 * 封装首启向导相关的 API 调用（无需认证）
 */

import type { SetupStatus, SetupInitRequest } from '~/types'
import { get, post } from './client'
```

**接口定义**（参考 `users.ts` 中 `SystemUser` 等 type import 方式，或内联定义）：
```typescript
export interface SetupStatus {
  needs_setup: boolean
  is_initialized: boolean
}

export interface SetupInitRequest {
  username: string
  password: string
  display_name?: string
}
```

**导出函数 + JSDoc 模式** (analog `users.ts` lines 9-35):
```typescript
/**
 * 查询系统初始化状态（AllowAny，无需认证）
 * 路由守卫在 initAuth() 前调用，fail-safe：异常时按已初始化处理
 */
export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}

/**
 * 首启初始化：创建管理员账号
 * Phase 1 最小实现；Phase 2 增强 UX（密码强度/二次确认/自动登录）
 */
export async function initSetup(data: SetupInitRequest): Promise<void> {
  return post<void>('/auth/setup/', data)
}
```

**default export 对象模式** (analog `users.ts` lines 63-71):
```typescript
export default { getSetupStatus, initSetup }
```

> **重要警告：** `setup.vue` 现有 POST 提交使用原始 `fetch`（不通过 `api/client.ts`），  
> 应继续保持此模式避免 403 触发全局 `auth:forbidden` 事件 → 跳转 `/403`。  
> `initSetup()` 供其他消费方（如测试、将来的封装层）使用，`setup.vue` 保持原始 `fetch`。

---

### `web/src/api/index.ts` — 追加 setup re-export

**Analog:** `web/src/api/index.ts`（自身，lines 1-32）

**双行 re-export 模式** (analog lines 5-29):
```typescript
// 在 index.ts 末尾追加（不修改现有内容）
export { default as setupApi } from './setup'
export * from './setup'
```

---

### `web/src/main.ts` — 修改 router.beforeEach + i18n

**Analog:** `web/src/main.ts`（自身，lines 1-113）

**i18n 创建 + messages 注入模式** (analog lines 28-33):
```typescript
// 修改现有 createI18n 调用，注入 zh-CN messages
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

**setup API import 追加**：
```typescript
import { getSetupStatus } from '~/api/setup'
```

**router.beforeEach 修改模式** (analog lines 52-88，在 `isInitialized` 检查之前插入 setup 分支):
```typescript
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // ── Step 1：初始化状态检测（每次 app 首次守卫触发时检查一次）──
  if (!authStore.setupStatusChecked) {
    try {
      const status = await getSetupStatus()
      authStore.needsSetup = status.needs_setup
    }
    catch {
      // fail-safe：后端不可达时按「已初始化」处理，
      // 防止误导向向导重置/接管生产实例
      authStore.needsSetup = false
    }
    authStore.setupStatusChecked = true
  }

  // ── Step 2：setup 路由守卫（必须在 initAuth 之前）──
  if (authStore.needsSetup && to.path !== '/setup') {
    return next('/setup')
  }
  if (!authStore.needsSetup && to.path === '/setup') {
    return next('/login')
  }

  // ── Step 3：原有认证守卫（不变，仅追加 /setup 到 publicPages）──
  if (!authStore.isInitialized) {
    await authStore.initAuth()
  }

  const publicPages = ['/login', '/force-change-password', '/403', '/oidc/callback', '/invite', '/setup']
  // ... 其余逻辑不变
})
```

> **顺序关键约束：** setup 状态分支必须在 `authStore.initAuth()` 之前。  
> `initAuth()` 调用 `GET /api/auth/me/`，全新部署无用户时 401 → token 刷新失败 → `auth:logout` 事件 → `$reset()` → `setupStatusChecked = false` → 无限循环（见 RESEARCH.md Pitfall 2）。

---

### `web/src/stores/auth.ts` — 追加 needsSetup + setupStatusChecked

**Analog:** `web/src/stores/auth.ts`（自身，lines 1-318）

**State 追加模式** (analog lines 14-22，在现有 ref 块末尾追加):
```typescript
// 在 State 区块末尾追加（lines 14-22 之后）
const needsSetup = ref(false)          // 系统是否需要 setup（路由守卫写入）
const setupStatusChecked = ref(false)  // 是否已检查过 setup 状态（每次 app 启动查一次）
```

**$reset 追加模式** (analog lines 280-289，在现有重置字段末尾追加):
```typescript
function $reset() {
  // ... 现有重置字段（不变）
  needsSetup.value = false
  setupStatusChecked.value = false
}
```

**return 追加模式** (analog lines 291-317，在 State 导出区追加):
```typescript
return {
  // ... 现有导出（不变）
  needsSetup,
  setupStatusChecked,
}
```

> **命名约束（来自 RESEARCH.md Pitfall 1）：**  
> - `isInitialized`（已有）= 认证状态是否已检查（`initAuth()` 完成标志）  
> - `needsSetup`（新增）= 系统是否需要首启 setup  
> - `setupStatusChecked`（新增）= setup 状态是否已查过  
> **不要混用，不要修改现有 `isInitialized` 含义**

---

### `web/src/pages/setup.vue` — 改造为向导外壳

**Analog:** `web/src/pages/setup.vue`（自身，lines 1-207）— 改造现有文件

**`<script setup>` 区块模式** (analog lines 1-88):
- 保留现有 `vee-validate` + `zod` + `useForm` + `handleSubmit` 表单结构
- 保留原始 `fetch` 提交（不替换为 `api/setup.ts` 的 `initSetup()`）
- 新增 `const { t } = useI18n()`（`useI18n` 由 unplugin-auto-import 自动注入，无需 import）
- 向导外壳在本阶段继续保持现有表单可用（Phase 2 增强）
- 提交成功后更新 store 状态：`authStore.needsSetup = false; authStore.setupStatusChecked = true`

**glass 卡片风格模式** (analog lines 91-201):
```vue
<div class="min-h-screen flex items-center justify-center relative overflow-hidden">
  <!-- 背景装饰 -->
  <div class="absolute inset-0 bg-mesh-gradient" />
  <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-primary/5 rounded-full blur-3xl -translate-y-1/2 translate-x-1/4" />

  <div class="relative z-10 w-full max-w-md mx-4">
    <!-- glass 卡片 -->
    <div class="bg-card/70 backdrop-blur-xl rounded-2xl border border-border/50 shadow-glass p-8">
      <!-- 图标 + 标题（可替换为 $t('setup.title')） -->
      <span class="icon-[lucide--settings] text-3xl text-primary" />
      <h1 class="text-2xl font-bold text-foreground mb-1">{{ t('setup.title') }}</h1>
    </div>
  </div>
</div>
```

**错误提示 pattern** (analog lines 111-117):
```vue
<div
  v-if="setupError"
  class="flex items-center gap-2.5 p-3 rounded-xl bg-destructive/8 border border-destructive/15 text-destructive mb-5"
>
  <span class="icon-[lucide--alert-circle] text-base flex-shrink-0" />
  <span class="text-sm">{{ setupError }}</span>
</div>
```

**表单字段 pattern** (analog lines 120-196，`FormField` + `FormControl` + 图标前缀 Input):
```vue
<FormField v-slot="{ componentField }" name="username">
  <FormItem>
    <FormLabel class="text-foreground/80 text-sm font-medium">
      {{ t('setup.fields.username') }}
    </FormLabel>
    <FormControl>
      <div class="relative group">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 icon-[lucide--user] text-muted-foreground text-sm" />
        <Input type="text" class="pl-9" v-bind="componentField" />
      </div>
    </FormControl>
    <FormMessage />
  </FormItem>
</FormField>
```

**`<route>` 块模式** (analog lines 203-206，必须保留):
```vue
<route lang="yaml">
meta:
  layout: false
</route>
```

---

### `web/src/locales/zh-CN.json` — 新建 i18n 文案

**Analog:** 无（当前 `web/src/locales/` 仅含 `.gitkeep`）

**JSON 结构模式**（参考 vue-i18n 嵌套 namespace 约定）：
```json
{
  "setup": {
    "title": "首次设置",
    "subtitle": "欢迎使用 Friday AI，开始初始化你的实例",
    "loading": "正在检测系统状态…",
    "cta": "创建管理员账户",
    "submitting": "创建中…",
    "fields": {
      "username": "管理员用户名",
      "password": "密码",
      "confirmPassword": "确认密码"
    },
    "error": {
      "connection": "无法连接到服务器，请检查后端服务后重试",
      "default": "设置失败，请重试"
    }
  }
}
```

**main.ts 装载模式**（参考 RESEARCH.md Pattern 8，`vite.config.ts` 已配置 `VueI18n({ include: ['src/locales/**'] })`，但不会自动注入 messages，需手动 import）：
```typescript
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en',
  messages: { 'zh-CN': zhCN },
})
```

**在 setup.vue 中使用**（`useI18n` 已被 unplugin-auto-import 配置，无需手动 import）：
```vue
<script setup lang="ts">
const { t } = useI18n()
</script>
<template>
  <h1>{{ t('setup.title') }}</h1>
</template>
```

---

## Shared Patterns

### 1. adrf 异步视图 + sync_to_async ORM 桥接
**Source:** `server/accounts/views.py` lines 1-32, 40-83 (`LoginView`)
**Apply to:** `SetupStatusView`, `SetupInitView`
```python
# 包装 queryset 方法引用（不是调用结果）
is_initialized = await sync_to_async(
    User.objects.filter(is_superuser=True).exists
)()

# 包装 serializer.is_valid()（含 DB 查询的 validator）
await sync_to_async(serializer.is_valid)(raise_exception=True)

# 包装任意同步函数
user = await sync_to_async(_atomic_create_superuser)(username=..., password=...)
```

### 2. permission_classes = [AllowAny, CustomPermission] 双权限组合
**Source:** `server/accounts/views.py` `InvitationView.get_permissions` (lines 208-212)
**Apply to:** `SetupInitView`
```python
# AllowAny 先通过匿名认证，CustomPermission 按业务逻辑拒绝
# 确保匿名用户被拒绝时返回 403 而非 401
permission_classes = [AllowAny, SetupNotInitialized]
```

### 3. 事务 + double-check 防重入
**Source:** `server/accounts/management/commands/init_superuser.py` lines 40-62
**Apply to:** `_atomic_create_superuser` 辅助函数
```python
# 管理命令中的判定模式（无事务，但逻辑相同）：
if User.objects.filter(is_superuser=True).exists():
    return  # 已存在，跳过

# 视图中升级为事务内 double-check：
with transaction.atomic():
    if User.objects.filter(is_superuser=True).exists():
        return None  # 返回 None 触发 409
    return User.objects.create_superuser(
        username=username, password=password,
        display_name=display_name,
        source=UserSource.SYSTEM.value,
    )
```

### 4. 前端 `get/post` API 封装模式
**Source:** `web/src/api/users.ts` lines 1-71
**Apply to:** `web/src/api/setup.ts`
```typescript
// 最小封装：import get/post from client，返回类型泛型，JSDoc 说明
import { get, post } from './client'

export async function getSetupStatus(): Promise<SetupStatus> {
  return get<SetupStatus>('/auth/setup/status/')
}
```

### 5. Pinia ref + $reset 扩展模式
**Source:** `web/src/stores/auth.ts` lines 14-22, 280-317
**Apply to:** `needsSetup` + `setupStatusChecked` 追加
```typescript
// State 区块追加 ref
const needsSetup = ref(false)

// $reset() 追加重置
needsSetup.value = false

// return 追加导出
return { ..., needsSetup }
```

### 6. 路由守卫条件重定向模式
**Source:** `web/src/main.ts` lines 52-88
**Apply to:** setup 分支插入
```typescript
// 现有模式（认证重定向）：
if (authRequired && !authStore.isAuthenticated) {
  return next({ path: '/login', query: { redirect: to.fullPath } })
}

// setup 分支（插入在 initAuth 之前）：
if (authStore.needsSetup && to.path !== '/setup') {
  return next('/setup')
}
```

### 7. 测试 fixture + api_client.post 模式
**Source:** `server/tests/conftest.py` (lines 112-147), `server/tests/test_auth.py` (lines 14-60)
**Apply to:** `server/tests/test_setup.py`
```python
# fixture 使用：api_client（未认证），admin_user（已有 superuser）
@pytest.mark.django_db
class TestSetupXxx:
    def test_xxx(self, api_client, admin_user):
        response = api_client.post("/api/auth/setup/", data, format="json")
        assert response.status_code == status.HTTP_403_FORBIDDEN
```

---

## Anti-Patterns to Avoid

| 反模式 | 正确模式 | 来源 |
|--------|---------|------|
| `has_permission` 内用 `sync_to_async` | 直接同步 ORM 查询 | `system/permissions.py` line 43-44 |
| `router.beforeEach` 先调 `initAuth()` 再检查 setup | setup 分支必须在 `initAuth()` 之前 | `main.ts` lines 56-57 |
| `setup.vue` POST 用 `api/client.ts` 封装 | 保持原始 `fetch`，避免 403 触发全局重定向 | `setup.vue` lines 45-73, `client.ts` lines 144-156 |
| `/setup` 不加入 `publicPages` | 加入白名单，否则未登录守卫死循环 | `main.ts` line 61 |
| 新增 `isInitialized` 覆盖现有含义 | 使用 `needsSetup` + `setupStatusChecked` | `auth.ts` line 17 |

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `web/src/locales/zh-CN.json` | config | transform | `web/src/locales/` 目前只有 `.gitkeep`，无任何 JSON locale 文件 |

---

## Metadata

**Analog search scope:** `server/accounts/`, `server/system/`, `server/tests/`, `web/src/api/`, `web/src/stores/`, `web/src/main.ts`, `web/src/pages/setup.vue`
**Files scanned:** 11
**Pattern extraction date:** 2026-06-08
