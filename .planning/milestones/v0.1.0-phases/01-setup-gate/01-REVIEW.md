---
phase: 01-setup-gate
reviewed: 2026-06-08T16:10:00+08:00
depth: standard
iteration: 2
files_reviewed: 14
files_reviewed_list:
  - server/accounts/permissions.py
  - server/accounts/serializers.py
  - server/accounts/views.py
  - server/accounts/urls.py
  - server/accounts/models.py
  - server/accounts/migrations/0006_add_single_superuser_constraint.py
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
  warning: 0
  info: 5
  total: 5
status: clean
---

# Phase 01: Setup Gate — Code Review Report (Iteration 2)

**Reviewed:** 2026-06-08T16:10:00+08:00
**Depth:** standard
**Files Reviewed:** 14
**Status:** clean（无 Critical / Warning；含 5 个 Info，均非阻塞）

## Summary

本次为 Re-Review，验证 gsd-code-fixer 对 WR-01、WR-02 的修复，并检查引入的新文件（`models.py`、Migration `0006`）是否产生回退。

**WR-01 已解决。** Migration `0006_add_single_superuser_constraint.py` 在 `users` 表上创建了 `partial unique index（WHERE is_superuser = TRUE）`，DB 层面保证并发不同用户名的创建请求中后提交者触发 `IntegrityError`，被 `SetupInitView` 已有的 409 兜底正确捕获。表名 `users` 与 `User.Meta.db_table = "users"` 一致；`reverse_sql` 完整；SQLite 3.8.9+/Postgres 均支持该语法。

**WR-02 已解决。** `setup.vue` 的 `onMounted` 已改用 `getSetupStatus()`（`~/api/setup`），遵循 `VITE_API_URL` 配置，消除了 raw fetch 硬编码路径问题。错误兜底使用 `t('setup.error.connection')`，与路由守卫一致。

无 Critical，无 Warning，无新增回退。原有 4 个 Info 项未修改，新增 1 个 Info（陈旧 docstring）。

---

## Info

### IN-01: `SetupInitView.permission_classes` 中 `AllowAny` 冗余（遗留）

**File:** `server/accounts/views.py:482`

**Issue:** `permission_classes = [AllowAny, SetupNotInitialized]` — DRF AND 语义下 `AllowAny` 恒为 True，无实际效果；`authentication_classes = []` 才是控制 401 vs 403 行为的关键。

**Fix:**
```python
permission_classes = [SetupNotInitialized]
```

---

### IN-02: 测试缺少用户名唯一性、display_name 断言场景（遗留）

**File:** `server/tests/test_setup_gate.py`

**Issue:** 缺少 username 已占用 → 400、成功后 `display_name` 落库验证等测试用例。

**Fix:**
```python
def test_duplicate_username_returns_400(self, api_client):
    User.objects.create_user(username="existinguser", password="pw")
    response = api_client.post(
        SETUP_INIT_URL,
        {"username": "existinguser", "password": "admin1234"},
        format="json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

def test_display_name_stored(self, api_client):
    api_client.post(
        SETUP_INIT_URL,
        {"username": "admin", "password": "admin1234", "display_name": "超管"},
        format="json",
    )
    u = User.objects.get(username="admin")
    assert u.display_name == "超管"
```

---

### IN-03: `zh-CN.json` 中 `setup.error.default` 键未通过 `t()` 使用（遗留）

**File:** `web/src/pages/setup.vue:70`

**Issue:** 兜底错误文案仍为内联字符串 `'设置失败，请重试'`，`setup.error.default` i18n key 是死代码。

**Fix:**
```typescript
setupError.value = e instanceof Error ? e.message : t('setup.error.default')
```

---

### IN-04: `onSubmit` 中 `response.json()` 在 `response.ok` 检查之前调用（遗留）

**File:** `web/src/pages/setup.vue:58-61`

**Issue:** 若服务器返回非 JSON 响应（502 HTML、网关超时等），`response.json()` 抛出 parse 错误后被 catch 捕获，显示 `'设置失败，请重试'` 而不是 `t('setup.error.connection')`，两种失败情形无法区分。

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

### IN-05: `_atomic_create_superuser` 注释描述 IntegrityError 兜底范围已过时（新增）

**File:** `server/accounts/views.py:455`

**Issue:** Migration `0006` 添加 partial unique index 后，`IntegrityError` 兜底已不止捕获 `username UNIQUE` 约束冲突，还覆盖了并发不同用户名创建 superuser 的竞态场景；第 454 行 "Postgres 依赖 READ COMMITTED 事务" 的说明也不再准确（DB 约束现在是核心保护）。

**Fix:**
```python
"""在原子事务内创建 superuser，并发/重入安全。

返回 None 表示已存在 superuser（并发冲突），由调用方返回 409。
DB 层面通过 partial unique index（accounts_user_single_superuser）
保证最多只有一个 is_superuser=True 行，覆盖 Postgres READ COMMITTED
下不同用户名的并发创建竞态；IntegrityError 作最终兜底（SETUP-04）。
不使用 select_for_update()——SQLite 不支持，会抛 NotSupportedError。
"""
```

---

_Reviewed: 2026-06-08T16:10:00+08:00_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 (re-review after WR-01/WR-02 fixes)_
