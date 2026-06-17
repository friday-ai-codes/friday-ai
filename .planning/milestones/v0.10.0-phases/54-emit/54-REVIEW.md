---
phase: 54-emit
review_type: inline (subagents unavailable — unpaid-invoice block)
status: clean
reviewed_at: 2026-06-17
scope: server/{accounts,projects,system,repositories,access_tokens,feishu}/views.py + services/purge_reconcile.py + audit/services/taxonomy.py
findings:
  blocker: 0
  high: 0
  medium: 0
  low: 2
---

# Phase 54 Code Review（inline）

> 子代理因计费问题不可用，本评审为编排器内联人工核查 + 测试佐证。聚焦审计接线四类风险：
> ①INV-6 单一写入；②凭证明文不落审计；③emit 落在真正执行路径且主操作成功后；④无审计噪音。

## Verdict

**CLEAN** — 0 BLOCKER / 0 HIGH / 0 MEDIUM。执行期发现的 2 个 bug（Provider emit 落点错位、token_changed 键名误抹）已在执行中即时修复并测试佐证。剩余 2 个 LOW 为已知测试缺口，不阻断阶段目标。

## 核查维度

### ① INV-6 单一写入入口 ✅
- 所有新接线 emit 均经 `AuditService.emit/aemit`，无旁路 `AuditEvent.objects.<write>`。
- `tests/audit/test_audit_inv6_guard.py` 源码扫描守护全绿（含本 phase 新增写点）。

### ② 凭证明文不落审计 ✅（核心）
- Provider 凭证：after 仅 `provider_type/scope/scope_id/name`，api_key/encrypted_config 不入载荷 — `test_emit_credentials.py::TestProviderCredentialEmit` 断言 `PROVIDER_API_KEY not in payload`。
- Git 实例/per-repo 凭证：仅 `host/provider/provided/rotated`，密文 token 不入载荷 — 断言 `PLAINTEXT_TOKEN not in payload`。
- PAT：仅前后缀指纹 + name + expires_at，明文/token_hash 不入载荷 — 断言 `plaintext not in payload`。
- 入口 `_redact_audit_payload` 纵深兜底（即便调用方误传也抹）。

### ③ emit 落真正执行路径 + 主操作成功后 ✅
- system ProviderCredentialViewSet 经 rest_framework.DefaultRouter → 同步 perform_create/update/destroy 收口（已修正初版落在不执行的 adrf 异步 perform_a*）。
- 唯一显式 atomic 同步块（`_set_default_atomic`、superuser setup）用 `transaction.on_commit`；其余 await 主操作成功后 aemit。
- purge 收口落 run_cleanup 异步调用点（避免同步 log_purge_event 在 async 写 ORM 触发 SynchronousOnlyOperation 被 fail-soft 吞掉）。

### ④ 无审计噪音 ✅
- 读路径（凭证/PAT/排除规则 list）零 emit — `test_emit_no_noise_credentials.py` 全绿。
- PAT 吊销首吊才 emit（幂等）；用户启停/角色仅值变更 emit。

## Findings

### LOW-1 — per-repo Git 凭证 emit 无专项单测
- per-repo Git 凭证（`RepositoryViewSet.acreate` / `SetAccessTokenView`）emit 已接线于 adrf 异步活跃面，但无专项行落库测试。
- 影响：低。同类脱敏/落点模式已被 Git 实例凭证测试覆盖；接线已 manage.py check 通过。
- 处置：deferred（可在 Phase 55 或补测阶段补 1-2 例）。

### LOW-2 — 飞书 webhook 自动同步 emit 无单测
- webhook 自动派发成功 emit（actor=None/feishu_webhook）未单测（驱动 TriggerDispatcher 较重）；人工重试路径 actor 分支逻辑已审阅。
- 影响：低。emit 落点在 `if executions:` 成功分支，url_verification/duplicate/ignored/error 均不 emit（已审阅代码路径）。
- 处置：deferred。

## 已修复（执行期 auto-fix，见 54-02-SUMMARY Deviations）
1. Provider emit 落点从异步 perform_a* 迁到同步 perform_create/update/destroy（命中执行路径）。
2. `token_changed` → `rotated` 规避脱敏键名误伤。

## 结论
账实闭环，凭证脱敏与 INV-6 经测试证实，emit 落点正确。**status: clean**，不阻断 Phase 54 verify。
