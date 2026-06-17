---
phase: 54-emit
plan: 01
subsystem: api
tags: [audit, emit, identity, permissions, on-commit, redaction]

requires:
  - phase: 53-auditevent-emit
    provides: AuditService.emit/aemit 单一写入入口 + taxonomy ACTION_* + _redact_audit_payload
provides:
  - accounts 身份操作审计 emit（建用户/启停/改资料/首启 superuser on_commit）
  - projects/members 成员增删改 + 角色变更审计 emit
  - projects 空间配置变更 + 仓库权限/关联变更审计 emit
  - 身份侧 SC-1 行落库测试 + SC-4 无噪音测试
affects: [54-02 凭证治理 emit, Phase 55 审计查询/导出]

tech-stack:
  added: []
  patterns:
    - "view 层 await 主操作成功后 await AuditService.aemit(actor=request.user, ...)"
    - "唯一显式 atomic 块（_atomic_create_superuser）用 transaction.on_commit + sync emit"
    - "凭证型配置字段仅记字段名集合 + redacted 布尔，secret/token 值绝不入载荷"
    - "启停/角色/权限仅值真正变更时 emit（SC-4 噪音控制）；删除前快照填 before"

key-files:
  created:
    - server/tests/audit/test_emit_identity.py
    - server/tests/audit/test_emit_no_noise_identity.py
  modified:
    - server/accounts/views.py
    - server/projects/members_views.py
    - server/projects/views.py

key-decisions:
  - "AdminProfileView.put（管理员改自己资料）保留 emit——用户名/显示名属安全相关身份变更，按 plan 任务与测试纳入；SC-4 无噪音聚焦读操作 + 改密"
  - "空间配置 has_secret 布尔键名含敏感段 secret 被 _redact_audit_payload 整体抹值——改用 redacted 键名规避（DB 仍无明文，语义不变）"
  - "InvitationAcceptView 公开端点匿名 actor → actor=None，source=invitation"

patterns-established:
  - "敏感 emit 载荷字段命名须避开脱敏敏感段（token/secret/password/credential/authorization）以免布尔/标识被误抹"

requirements-completed: [AUDITCOV-01]

duration: 25min
completed: 2026-06-17
---

# Phase 54 Plan 01: 身份/权限类敏感操作 emit Summary

**把 Phase 53 的 AuditService.aemit/emit 单一写入入口接线到 accounts（建用户/启停/改资料/首启 superuser）+ projects/members（成员增删改 + 角色变更）+ projects（空间配置 + 仓库权限/关联变更），产出全量审计记录（actor=request.user + 目标 + 前后值），凭证型字段仅记字段名 + redacted 布尔。**

## Accomplishments

- accounts：邀请建用户（actor=None/invitation）、首启 superuser（on_commit/system/actor=None）、用户启停（仅值变更 emit，activated/deactivated 分支）、管理员改资料（变更字段 diff）
- projects/members：成员添加 / 角色变更（写前读 old_role，仅变更 emit）/ 移除（删前快照 before）
- projects：空间飞书 plugin/IM/doc 配置 + webhook token 变更（统一 project.config_changed + metadata config_subtype，仅记字段名 + redacted，绝不落 secret/token）；仓库权限级别变更 + 关联/解绑（含批量）
- 全部 emit 引用 taxonomy ACTION_* 常量，无字符串字面量；autocommit 直接 aemit，唯一 atomic 块用 on_commit
- SC-1 行落库测试（13 例）+ SC-4 无噪音测试（4 例）全绿；既有 INV-6 grep 守护保持全绿

## Task Commits

1. **Task 1: accounts 身份操作 emit** - feat(54-01) accounts 身份操作接线
2. **Task 2: projects/members 成员增删改 + 角色变更 emit** - feat(54-01) 成员增删改与角色变更
3. **Task 3: projects 空间配置 + 仓库权限变更 emit** - feat(54-01) 空间配置与仓库权限变更
4. **Task 4: SC-1 行落库 + SC-4 无噪音测试** - test(54-01) 身份/权限 emit 与无噪音单测

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] has_secret 键名被脱敏入口误抹**

- **Found during:** Task 4（test_space_feishu_config_emits_no_secret 失败）
- **Issue:** 空间配置 emit 用 `has_secret: True` 布尔标识，但键名分段含敏感段 `secret`，被 Phase 53 `_redact_audit_payload` key-name 命中整体抹成 `[已脱敏]`，断言 `is True` 失败
- **Fix:** 把布尔键名 `has_secret` 改为 `redacted`（不含敏感段），语义不变、DB 仍无明文；同步更新测试断言
- **Files modified:** server/projects/views.py（7 处）、server/tests/audit/test_emit_identity.py
- **Verification:** `pytest tests/audit/test_emit_identity.py tests/audit/test_emit_no_noise_identity.py tests/audit/test_audit_inv6_guard.py` 17 passed

---

**Total deviations:** 1 auto-fixed
**Impact on plan:** 仅审计载荷字段重命名以规避脱敏键名误伤，无 scope creep；脱敏行为正确（佐证入口强制脱敏纵深防御有效）。

## Next Phase Readiness

- 身份/权限侧 emit（AUDITCOV-01）闭环；Plan 02 待落凭证治理 emit + purge 收口（AUDITCOV-02）
- 已确立约定：敏感 emit 载荷字段命名须避开脱敏敏感段——54-02 凭证侧载荷沿用（只传 provider_type/host/name/has_token→改 token_present 等非敏感键）

---
*Phase: 54-emit*
*Completed: 2026-06-17*
