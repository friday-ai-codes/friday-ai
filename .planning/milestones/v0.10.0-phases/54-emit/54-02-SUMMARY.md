---
phase: 54-emit
plan: 02
subsystem: api
tags: [audit, emit, credentials, pat, feishu-sync, purge, redaction]

requires:
  - phase: 53-auditevent-emit
    provides: AuditService.emit/aemit 单一写入入口 + taxonomy ACTION_* + _redact_audit_payload
  - phase: 54-emit (plan 01)
    provides: 身份/权限 emit + 载荷字段命名避脱敏段约定
provides:
  - system Provider 凭证 CRUD 审计 emit（同步 perform_create/update/destroy 收口）
  - repositories Git 实例凭证 + per-repo Git 凭证 + 排除规则增删审计 emit
  - access_tokens PAT 创建/吊销审计 emit（明文不落审计、吊销幂等单条）
  - feishu webhook 自动同步(actor=None) + 人工重试(actor=user) 审计 emit
  - services/purge_reconcile v0.5 purge.started/completed 收口 AuditService
  - 凭证/数据治理侧 SC-2/SC-3 行落库 + 脱敏测试 + SC-4 无噪音测试
affects: [Phase 55 审计查询/导出]

tech-stack:
  added: []
  patterns:
    - "adrf+rest_framework.DefaultRouter 路由的 ViewSet 实际走同步 perform_create/update/destroy → 审计 emit 必须落同步面（AuditService.emit）"
    - "APIView 异步端点 await AuditService.aemit(actor=request.user, ...)"
    - "purge 同步埋点经 _emit_purge_audit 在 run_cleanup 异步调用点 aemit 收口（保留既有 logger.info）"
    - "PAT 吊销仅首吊 emit（幂等）；明文/token_hash 绝不入载荷，仅记前后缀指纹"

key-files:
  created:
    - server/tests/audit/test_emit_credentials.py
    - server/tests/audit/test_emit_purge_consolidation.py
    - server/tests/audit/test_emit_no_noise_credentials.py
  modified:
    - server/system/views.py
    - server/repositories/views.py
    - server/access_tokens/views.py
    - server/feishu/views.py
    - server/services/purge_reconcile.py
    - server/audit/services/taxonomy.py

key-decisions:
  - "ProviderCredentialViewSet 经 rest_framework.DefaultRouter 路由，POST/PUT/PATCH/DELETE 实际分派到 DRF 同步 create/update/destroy（非 adrf 异步 perform_a*）——审计 emit 落同步 perform_create/update/destroy 才命中执行路径；异步 perform_a* emit 保留作另一路径防御（单请求互斥，不双写）"
  - "凭证管理活跃实现在 repositories/views.py（RepositoryViewSet/SetAccessTokenView/GitInstanceCredential*/Exclusion*），projects/views.py 同名为 dead code——接线目标改为 repositories/views.py"
  - "Git 实例凭证更新 after 键名 token_changed 含敏感段 token 被脱敏入口误抹 → 改用 rotated（沿用 54-01 命名避段约定）"
  - "purge 收口落点选 run_cleanup 异步调用点而非同步 log_purge_event：后者同步函数在 async 上下文写 ORM 会触发 SynchronousOnlyOperation 被 fail-soft 吞掉而永不落库"
  - "飞书 webhook 自动同步 actor=None + source=feishu_webhook，仅派发成功(executions 非空)才 emit；人工重试 actor=request.user + source=api"

patterns-established:
  - "凭证类 ViewSet 接线审计前须先判定路由实际执行的是 DRF 同步面还是 adrf 异步面（取决于 router 类型），emit 落在真正执行的方法上"

requirements-completed: [AUDITCOV-02]

duration: 40min
completed: 2026-06-17
---

# Phase 54 Plan 02: 凭证治理类 emit + purge 收口 Summary

**把 AuditService 接线到 Provider/Git 实例/per-repo Git/PAT/飞书凭证与同步、排除规则增删，并把 v0.5 purge 埋点收口到 AuditEvent 单一写入入口，产出全量审计记录且凭证字段在 DB 绝无明文。**

## Accomplishments

- system：Provider 凭证 CRUD 收口到同步 `perform_create/update/destroy`（修正 adrf+DRF 路由实际执行面）+ toggle-active/set-default(on_commit) emit；载荷仅记 provider_type/scope/name，api_key/encrypted_config 绝不入审计
- repositories：Git 实例凭证 CRUD（rotated 标识换密钥）、per-repo Git 凭证增删、排除规则增删 emit（删前快照）
- access_tokens：PAT 创建（前后缀指纹）/吊销（首吊 emit 幂等）；明文 token / token_hash 绝不入载荷
- feishu：webhook 自动同步（actor=None/feishu_webhook，仅派发成功 emit）+ 人工重试（actor=user/api）
- services/purge_reconcile：`_emit_purge_audit` 在 run_cleanup 收口 purge.started/completed → ACTION_PURGE_*，保留既有结构化日志
- SC-2/SC-3 行落库 + 脱敏测试 + SC-4 无噪音测试全绿；audit 套件 66 passed；触及域回归 176 passed

## Task Commits

1. **Task 1: taxonomy purge 提升 + system Provider 凭证 emit** - feat(54-02) 凭证治理 emit 起步（54-01 提交内含 taxonomy promotion）
2. **Task 2/3: repositories Git 实例/per-repo 凭证 + 排除规则 emit** - feat(54-02): repositories Git 实例/per-repo 凭证与排除规则增删接线审计 emit（token 不落审计）
3. **Task 4/5: PAT + 飞书同步 + purge 收口 + 凭证测试** - feat(54-02): PAT/Provider/飞书同步/purge 审计 emit 接线 + 凭证脱敏测试

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Provider 凭证 emit 落在未执行的异步 perform_a***

- **Found during:** Task 4（test_emit_credentials TestProviderCredentialEmit 无 AuditEvent 落库）
- **Issue:** `ProviderCredentialViewSet` 经 `rest_framework.DefaultRouter` 路由，POST/DELETE 实际分派到 DRF 同步 `create/destroy → perform_create/perform_destroy`，而 emit 初接在 adrf 异步 `perform_acreate/adestroy`（该路径不被执行）
- **Fix:** 新增同步 `perform_create/perform_update/perform_destroy` 覆盖，用 `AuditService.emit` 收口；异步 emit 保留作另一路径防御（单请求互斥，不双写）
- **Verification:** `pytest tests/audit/test_emit_credentials.py::TestProviderCredentialEmit` 2 passed

**2. [Rule 1 - Bug] token_changed 键名被脱敏入口误抹**

- **Found during:** Task 3 测试（test_update_token_emits_token_changed 断言 `is True` 得 `[已脱敏]`）
- **Issue:** Git 实例凭证更新 after 键名 `token_changed` 含敏感段 `token`，被 `_redact_audit_payload` key-name 命中整体抹值
- **Fix:** 键名改 `rotated`（沿用 54-01 命名避段约定），语义不变
- **Verification:** audit 套件 66 passed

### Plan-vs-Code Discrepancy

**3. 凭证管理接线目标从 projects/views.py 改为 repositories/views.py**

- Plan 引用的 projects/views.py 中 RepositoryViewSet/SetAccessTokenView 等为 dead code；活跃实现在 repositories/views.py，已据此调整接线目标。

---

**Total deviations:** 2 auto-fixed bugs + 1 plan-vs-code 修正
**Impact on plan:** 无 scope creep；修正后 emit 落在真正执行路径，脱敏行为正确（佐证入口强制脱敏纵深防御有效）。

## Known Test Gaps (LOW)

- per-repo Git 凭证（RepositoryViewSet.acreate / SetAccessTokenView）emit 已接线但无专项单测（adrf 路由异步面，已接线于活跃 acreate）
- 飞书 webhook 自动同步 emit 未单测（驱动 TriggerDispatcher 较重），人工重试路径与 actor 分支逻辑已覆盖

## Next Phase Readiness

- 凭证/数据治理 emit（AUDITCOV-02）闭环；全敏感操作（AUDITCOV-01+02）已产出 AuditEvent
- Phase 55 可基于已落库的 AuditEvent 行构建查询 API + 前端视图 + 导出（AUDITUI-01/02）

---
*Phase: 54-emit*
*Completed: 2026-06-17*
