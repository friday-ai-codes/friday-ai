---
phase: 26-multirepo-creds-mcp
plan: 04
subsystem: auth
tags: [git-credentials, rest, fernet, vue3, vue-i18n, isuperuser, write-only-token]

# Dependency graph
requires:
  - phase: 26-multirepo-creds-mcp (26-01)
    provides: GitInstanceCredential 模型（host 唯一 + Fernet 加密 token）+ resolve_git_token/aresolve_git_token 解析器
  - phase: 21-provider-credentials
    provides: common.encryption（encrypt_value/decrypt_value）Fernet 加密路径
provides:
  - 实例级 Git 凭证 REST CRUD（token write-only 加密、IsSuperUser、响应/日志无明文）
  - base-branch 校验取 token 改经统一解析器（实例池仓库也可校验）
  - 前端实例凭证管理页 + typed client（token 不回显）
  - 安全守护测试（后端无明文 token / 非管理员拒绝 + 前端不回显）
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "实例凭证读/写序列化器分离：读只含 has_token 布尔（无明文 token），写 access_token=write_only"
    - "字面段路由须在 router include 之前注册（git-instance-credentials 不被当作 repository id）"
    - "前端凭证表单 token 不回填、留空=不改、提交后清空（password 型）"

key-files:
  created:
    - server/tests/repositories/test_git_instance_credentials.py
    - web/src/api/gitInstanceCredentials.ts
    - web/src/pages/admin/git-credentials/index.vue
    - web/src/pages/admin/__tests__/git-credentials.spec.ts
  modified:
    - server/repositories/serializers.py
    - server/repositories/views.py
    - server/repositories/urls.py
    - web/src/api/index.ts
    - web/src/locales/zh-CN.json

key-decisions:
  - "读/写序列化器分离：GitInstanceCredentialSerializer（只读，无 token 字段）+ GitInstanceCredentialWriteSerializer（access_token write_only）"
  - "host 唯一性在视图层 aexists + IntegrityError 双兜底，给中文友好报错"
  - "空 access_token 的 PATCH 仅改 host/provider/label，绝不清空既有 encrypted_token"
  - "base-branch 校验改经 aresolve_git_token；TestConnectionView 验证入参 token 流程保持不变（非解析存储凭证）"

patterns-established:
  - "实例凭证 CRUD：adrf APIView（IsSuperUser），encrypt_value 写入、read 序列化器统一出口、日志仅记 host/has_token 布尔"
  - "前端管理页：vue-query + useI18n（zh-CN）+ has_token 徽标，token password 框不回填"

requirements-completed: [REPO-01]

# Metrics
duration: ~9min
completed: 2026-06-15
---

# Phase 26 Plan 04: 实例凭证 REST CRUD + 前端管理页 Summary

**实例级 Git 凭证 REST CRUD（token write-only Fernet 加密、IsSuperUser、API/DB/日志/前端全程无明文）+ Vue 3 管理页（has_token 徽标、token 不回显）+ base-branch 校验改经统一解析器**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-06-15T00:58:43Z
- **Completed:** 2026-06-15T01:07:35Z
- **Tasks:** 3
- **Files modified:** 9（4 created + 5 modified）

## Accomplishments
- 后端实例凭证读/写序列化器：读只含 `host/provider/label/has_token/时间戳`（无明文 token），写 `access_token` 为 `write_only`、host 归一小写。
- `GitInstanceCredentialsView`（list/create）+ `GitInstanceCredentialDetailView`（get/put/patch/delete），`IsSuperUser` 权限，`encrypt_value` 写入 `encrypted_token`，空 token 的 PATCH 不动既有 token，日志仅记 host/has_token 布尔。
- `perform_aupdate` 的 base-branch 校验改经 `aresolve_git_token(instance)`——使「无 per-repo token、仅靠实例池」的仓库也能做 base-branch 校验；`TestConnectionView` 验证入参 token 流程保持不变。
- 路由 `git-instance-credentials/` 与 `.../<uuid:credential_id>/` 注册在 `path("", include(router.urls))` 之前，避免被当作 repository id 匹配。
- 前端 `gitInstanceCredentialsApi` typed client（读类型无明文 token 字段）+ barrel 导出 + `/admin/git-credentials` 管理页（列表 has_token 徽标、新建/编辑 token password 不回填、删除二次确认、zh-CN 文案）。
- 安全守护测试全绿：后端 8 passed（DB 密文/响应无明文、has_token、空 token PATCH 不清空、非管理员 403、日志无明文）；前端 2 passed（列表仅徽标、编辑不回填 token、真实 zh-CN 文案守护）。

## Task Commits

1. **Task 1: 实例凭证序列化器 + CRUD 视图 + 路由 + base-branch 解析器接线** - `47a522210` (feat)
2. **Task 2: 前端实例凭证 API 模块 + 管理页（token 不回显）** - `4a1bd27c1` (feat)
3. **Task 3: 守护测试（后端无明文 token + 前端不回显）** - `d18394869` (test)

## Files Created/Modified
- `server/repositories/serializers.py` - 新增 `GitInstanceCredentialSerializer`（读，含 has_token）+ `GitInstanceCredentialWriteSerializer`（access_token write_only、host 归一）
- `server/repositories/views.py` - 新增两个 CRUD 视图（IsSuperUser，encrypt_value）；base-branch 校验改经 `aresolve_git_token`
- `server/repositories/urls.py` - 注册 git-instance-credentials 路由（router include 之前）
- `web/src/api/gitInstanceCredentials.ts` - typed client（list/create/update/remove），读类型无明文 token 字段
- `web/src/api/index.ts` - barrel 导出 `gitInstanceCredentialsApi`
- `web/src/pages/admin/git-credentials/index.vue` - 实例凭证管理页（has_token 徽标、token 不回显）
- `web/src/locales/zh-CN.json` - `gitCredentials` 中文文案
- `server/tests/repositories/test_git_instance_credentials.py` - 后端安全守护（8 tests）
- `web/src/pages/admin/__tests__/git-credentials.spec.ts` - 前端守护（2 tests）

## Decisions Made
- 读/写序列化器分离：避免 ModelSerializer 把 `encrypted_token` 必填字段牵进写入校验，写用 plain Serializer + 视图侧加密，read 序列化器作 CRUD 唯一出口确保无明文 token。
- host 唯一性在视图层用 `aexists()` 预检 + `IntegrityError` 兜底，给「实例已存在，请编辑既有凭证」中文报错。
- 空 `access_token` 的 PATCH 仅 `token_changed=False` 改其它字段，绝不清空既有 token（威胁 T-26-15）。
- base-branch 校验经 `aresolve_git_token`；`TestConnectionView`（验证用户当场输入的 token）保持不接解析器（验证入参非解析存储凭证）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Task 1 首次 ruff 报 `F821 Undefined name GitPlatform`（视图 acreate 默认 provider 用到 `GitPlatform.GITLAB`）→ 在 views.py models import 补 `GitPlatform`，ruff 通过、`manage.py check` 干净。

## Threat Surface
本计划新增的实例凭证 CRUD 端点已在 PLAN `<threat_model>`（T-26-13..17）覆盖，并由守护测试逐项验证（响应/DB/前端/日志无明文 + 非管理员拒绝）。无计划外新增安全面。

## User Setup Required
None - no external service configuration required.（迁移 0036 由 26-01 提供，部署侧 `migrate` 后表即可用。）

## Next Phase Readiness
- REPO-01 用户可见闭环（集中管理实例凭证 + token 绝不明文返回）已落地；管理员可在 `/admin/git-credentials` 按 host CRUD 实例凭证。
- Phase 26 计划全部完成（26-01..05），v0.5.0 可评估收口。

## Self-Check: PASSED

- 文件全部存在：serializers.py / views.py / urls.py / test_git_instance_credentials.py / gitInstanceCredentials.ts / api/index.ts / git-credentials/index.vue / git-credentials.spec.ts / zh-CN.json / 26-04-SUMMARY.md
- 提交全部存在：`47a522210`（Task 1 后端 CRUD）、`4a1bd27c1`（Task 2 前端）、`d18394869`（Task 3 测试）
- 验证：后端 `pytest tests/repositories/test_git_instance_credentials.py` 8 passed；前端 `vitest git-credentials.spec.ts` 2 passed；`vue-tsc --noEmit` exit 0；`ruff check` 干净；`manage.py check` 无问题

---
*Phase: 26-multirepo-creds-mcp*
*Completed: 2026-06-15*
