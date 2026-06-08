---
phase: 01-setup-gate
reviewed: 2026-06-08T15:55:00+08:00
depth: standard
files_reviewed: 12
files_reviewed_list:
  - server/accounts/permissions.py
  - server/accounts/serializers.py
  - server/accounts/views.py
  - server/accounts/urls.py
  - server/tests/test_setup_gate.py
  - web/src/api/setup.ts
  - web/src/api/index.ts
  - web/src/stores/auth.ts
  - web/src/locales/zh-CN.json
  - web/src/main.ts
  - web/src/pages/setup.vue
  - web/src/api/__tests__/setup.spec.ts
findings:
  critical: 0
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 01: Setup Gate — Code Review Report

**Reviewed:** 2026-06-08T15:55:00+08:00
**Depth:** standard
**Files Reviewed:** 12
**Status:** issues_found

## Summary

整体实现结构清晰，fail-closed 门禁逻辑在单请求场景下正确；`authentication_classes = []`、permission 顺序、路由守卫在 `initAuth()` 前执行等关键细节均处理到位。发现 2 个 Warning 和 4 个 Info，无 Critical/Blocker。

主要问题集中在两处：（1）`_atomic_create_superuser` 在 Postgres READ COMMITTED 下的并发逃逸；（2）`setup.vue` 的 `onMounted` 使用硬编码 raw fetch 而非 API 工具函数，与 submit handler 的有意为之不同，这里并无全局 403 事件的顾虑。

---

## Warnings

### WR-01: Postgres READ COMMITTED 下不同用户名并发可创建两个 superuser

**File:** `server/accounts/views.py:457-465`

**Issue:** `_atomic_create_superuser` 的防重入依赖 `transaction.atomic()` 内的再次查询 + IntegrityError 兜底。在 Postgres 默认的 READ COMMITTED 隔离级别下，两个并发事务都能在对方提交前读到"无 superuser"，随后分别以**不同用户名**各自 `create_superuser` 并提交成功。IntegrityError 只能捕获 **username UNIQUE** 冲突，对"不同用户名各建一个 superuser"的竞态无效。结果：数据库中出现两个 `is_superuser=True` 用户，违背"首启只能创建一个管理员"的业务约束。

SQLite 受 WAL 写锁串行化保护，此漏洞不影响 SQLite；但项目生产推荐 Postgres，该场景确实可复现（需两个并发请求在时间窗口内均通过权限检查）。

**Fix:** 在 Postgres 下，可在 `select_for_update()` 不可用时改用 `SERIALIZABLE` 事务或在应用层使用分布式锁（Redis `SET NX`）。最简兼容方案：在 atomic 块内对任意已知行加锁，迫使 Postgres 串行化——或改变数据模型，添加只允许单行的 DB 约束（例如在 `User` 表上加 partial unique index：`UNIQUE (is_superuser) WHERE is_superuser = TRUE`，由 migration 维护）。

临时缓解（不依赖锁）：

```python
# migration 中添加 Postgres partial unique index（SQLite 兼容此语法）
# 保证 DB 层面最多只有一个 is_superuser=True 的行
from django.db import migrations

class Migration(migrations.Migration):
    operations = [
        migrations.RunSQL(
            sql="""
            CREATE UNIQUE INDEX IF NOT EXISTS accounts_user_single_superuser
            ON accounts_user (is_superuser)
            WHERE is_superuser = TRUE;
            """,
            reverse_sql="DROP INDEX IF EXISTS accounts_user_single_superuser;",
        )
    ]
```

加上该约束后，第二个并发事务的 `create_superuser` 会触发 IntegrityError，已有的兜底逻辑即可正确处理。

---

### WR-02: `setup.vue` onMounted 使用硬编码 raw fetch 而非 API 工具函数

**File:** `web/src/pages/setup.vue:79`

**Issue:** `onMounted` 中使用 `fetch('/api/auth/setup/status/')` 硬编码路径查询初始化状态。与 `main.ts` 中路由守卫使用 `getSetupStatus()`（经 API client 的 `VITE_API_URL` 配置）不一致。如果 `VITE_API_URL` 配置了不同于同源的地址（跨域开发代理、自定义前缀等），raw fetch 会请求错误的端点而静默失败（`catch` 块将 `setupError` 设为连接错误，而路由守卫已经正确检查了状态）。另外：`onMounted` 调用完全多余——路由守卫在进入 `/setup` 前已经确保 `needsSetup=true`；唯一有价值的场景（另一标签页完成 setup 后当前标签页重检）本可复用 `getSetupStatus()` 实现。

注：`onSubmit` 中刻意使用 raw fetch 是有文档说明的设计（避免全局 `auth:forbidden` 重定向），本处 `onMounted` 无此需求。

**Fix:**

```typescript
// setup.vue — onMounted
import { getSetupStatus } from '~/api/setup'

onMounted(async () => {
  try {
    const status = await getSetupStatus()
    if (!status.needs_setup) {
      router.push('/login')
    }
  }
  catch {
    setupError.value = t('setup.error.connection')
  }
})
```

---

## Info

### IN-01: `SetupInitView.permission_classes` 中 `AllowAny` 冗余

**File:** `server/accounts/views.py:482`

**Issue:** `permission_classes = [AllowAny, SetupNotInitialized]` — DRF 对权限列表做 AND 校验；`AllowAny` 永远返回 `True`，不影响结果，只增加干扰。`authentication_classes = []` 才是控制 401 vs 403 行为的关键，注释已说明。

**Fix:**

```python
permission_classes = [SetupNotInitialized]
```

---

### IN-02: `test_setup_gate.py` 缺少用户名唯一性和并发防重入场景

**File:** `server/tests/test_setup_gate.py`

**Issue:** 测试覆盖了基本的 201/403/400 路径，但缺少：

1. **用户名重复校验**：`validate_username` 会返回 400，但无对应测试；
2. **并发防重入（WR-01 描述的场景）**：第二个并发请求以不同用户名提交的 409/403 结果无测试；
3. **`display_name` 字段**：成功创建后 DB 中 `display_name` 是否正确存储无断言。

**Fix:** 建议补充：

```python
def test_duplicate_username_returns_400(self, api_client):
    """username 已被占用时返回 400。"""
    User.objects.create_user(username="existinguser", password="pw")
    response = api_client.post(
        SETUP_INIT_URL,
        {"username": "existinguser", "password": "admin1234"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

def test_display_name_stored(self, api_client):
    """display_name 字段正确写入 DB。"""
    api_client.post(
        SETUP_INIT_URL,
        {"username": "admin", "password": "admin1234", "display_name": "超管"},
        format="json",
    )
    u = User.objects.get(username="admin")
    assert u.display_name == "超管"
```

---

### IN-03: `zh-CN.json` 中 `setup.error.default` 键未通过 `t()` 使用

**File:** `web/src/locales/zh-CN.json:15`

**Issue:** `setup.error.default: "设置失败，请重试"` 已定义，但 `setup.vue` 的错误兜底直接写了内联字符串 `'设置失败，请重试'`（第 69 行），未调用 `t('setup.error.default')`。该 i18n key 是死代码。

**Fix:**

```typescript
// setup.vue:69
setupError.value = e instanceof Error ? e.message : t('setup.error.default')
```

---

### IN-04: `setup.vue` onSubmit 中 `response.json()` 在检查 `response.ok` 之前调用

**File:** `web/src/pages/setup.vue:57-60`

**Issue:**

```typescript
const data = await response.json()   // ← 先解析
if (!response.ok) {
  throw new Error(data.detail || '设置失败')
}
```

若服务器返回非 JSON 响应（Nginx 502 返回 HTML、网关超时等），`response.json()` 抛出 JSON parse 错误，被 `catch` 捕获后显示 `'设置失败，请重试'`，而不是 `t('setup.error.connection')`。虽然最终用户看到的是可接受的错误文案，但两种情况（后端不可达 vs 后端返回业务错误）给出相同提示，影响排查。

**Fix:**

```typescript
if (!response.ok) {
  let detail = '设置失败'
  try {
    const data = await response.json()
    detail = data.detail || detail
  }
  catch { /* 非 JSON 响应，使用默认文案 */ }
  throw new Error(detail)
}
```

---

_Reviewed: 2026-06-08T15:55:00+08:00_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
