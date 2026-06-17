---
phase: 53-auditevent-emit
verification_type: goal-achievement
status: passed
verified_at: 2026-06-17
requirements: [AUDIT-01, AUDIT-02]
tests: "35 passed (tests/audit/)"
migrations: "makemigrations --check --dry-run → No changes detected"
success_criteria:
  SC-1: pass   # AuditEvent 表落库 + 单一 service 入口
  SC-2: pass   # append-only 不可篡改（模型层 + INV-6 grep 守护）
  SC-3: pass   # emit/aemit helper 可被任意操作调用 + fail-soft
  SC-4: pass   # 凭证/token 在 before/after 脱敏不落明文
---

# Phase 53 Verification — `AuditEvent` 模型 + emit 地基

## Verdict

**PASSED** — 阶段目标「立起统一不可篡改审计模型与 fail-soft emit 地基，供后续所有敏感操作复用」已达成。所有 4 项成功标准均经实际代码（`server/audit/`）与测试套件证实，非仅凭 SUMMARY 声明。AUDIT-01 / AUDIT-02 两个需求 ID 全部账实闭环。

## Phase Goal Achievement

目标聚焦三件事：①统一不可篡改审计模型；②fail-soft emit 地基；③可被后续敏感操作复用。三者均在 `audit` 叶子 app 中落地：`AuditEvent` append-only 模型（Plan 01）+ `AuditService.emit/aemit` 单一写入入口 + 强制脱敏 + fail-soft + action taxonomy（Plan 02）。模型零业务依赖，可被任意 app 无环 import，复用前提成立。

## Success Criteria — 逐项核验

### SC-1 — AuditEvent 表落库 + 单一 service 入口 ✅ PASS
- 模型 `server/audit/models/audit_event.py:36` 落 `audit_event` 表，字段全集与 SC 要求一致：`actor_id` / `actor_repr` / `action` / `target_type` / `target_id` / `target_repr` / `before` / `after` / `source` / `occurred_at` / `metadata`（+ 不可变 `recorded_at` 插入戳）。迁移 `0001_initial.py` 与模型逐字段对齐。
- 写入收口于单一入口 `AuditService.emit/aemit`（`audit_service.py:58`），唯一 `AuditEvent.objects.create`（`audit_service.py:95`），符合 INV-6 精神。
- 注册：`settings.py:104` INSTALLED_APPS 含 `"audit"`（accounts 之后）。
- 证据：`test_audit_model.py`（字段/索引/标量 actor）、`test_audit_service.py`（全字段持久化）。

### SC-2 — append-only 不可篡改（无 update/delete 业务路径）✅ PASS
- 模型层守护：`save()` 在 `_state.adding is False` 时抛 `AuditEventImmutableError`（`audit_event.py:88`），`delete()` 直接抛（`:92`）；首次 create 放行。
- grep 守护（第二道防线）：`test_audit_inv6_guard.py` 扫描 server 源码，断言除 `audit/services/audit_service.py` 外无旁路 `AuditEvent.objects.<write>` / 实例化 / `.save()`（负向前瞻排除 `AuditEventImmutableError`），并含 writer-actually-writes 反向断言防守护虚设。
- 证据：`test_audit_append_only.py`、`test_audit_inv6_guard.py`。

### SC-3 — emit helper 可任意调用 + fail-soft ✅ PASS
- `emit`（sync）/ `aemit`（async via `sync_to_async`）双面入口，关键字参数通用，可被任意敏感操作调用（`audit_service.py:61/113`）。
- fail-soft：`create` 整段 `try/except` 吞异常 + `logger.warning("audit.emit_failed", ...)` 不冒泡（`:110-111`）；warning 仅记 `action`/`target_type` 不记敏感载荷。
- 事务安全增强：`create` 包 `transaction.atomic()` savepoint，调用方事务内失败仅回滚 savepoint 不污染外层事务（MEDIUM-3 修复）。
- 证据：`test_audit_failsoft.py`（吞异常不冒泡 + warning + 主操作不受影响 + async fail-soft）。

### SC-4 — 凭证/密钥/token 脱敏不落明文 ✅ PASS
- 入口强制脱敏：`before`/`after`/`metadata` 均经 `_redact_audit_payload`（`audit_service.py:104-108`），调用方无法绕过。
- 脱敏覆盖：key-name 分段边界命中（token/secret/password/credential/api_key/access_token/private_key/encrypted_config/token_hash 等）+ 值级密钥正则（PEM/AKIA/ghp_/xox)/高熵 Shannon≥4.0 兜底，递归 dict/list/tuple/set 只抹命中叶子（`redaction.py`）。
- INV-3：`redaction.py` 复刻而非 import `sensitive_detect`/`work_item_service`，守 audit 叶子包零跨层硬依赖。
- 证据：`test_audit_redaction.py`（key-name/值级/高熵/嵌套/标量保留）、`test_audit_failsoft.py` 入口强制脱敏 + DB 无明文断言。

## Requirement Traceability

| Requirement | REQUIREMENTS.md | PLAN frontmatter | Codebase | 结论 |
|-------------|-----------------|------------------|----------|------|
| AUDIT-01 | `[x]` Complete @ Phase 53 | 53-01 (model), 53-02 (单一入口/INV-6) | 模型 + append-only 守护 + 单一写入 + grep 守护 | ✅ 账实 |
| AUDIT-02 | `[x]` Complete @ Phase 53 | 53-02 (emit/taxonomy/redaction) | emit/aemit + taxonomy + fail-soft + 脱敏 | ✅ 账实 |

PLAN frontmatter 的 requirement ID（AUDIT-01、AUDIT-02）与 REQUIREMENTS.md 完全对应，无遗漏、无悬挂 ID。

## Test & Migration Evidence

- `cd server && uv run pytest tests/audit/ -q` → **35 passed**（符合预期 ~35）。
- `uv run python manage.py makemigrations --check --dry-run` → **No changes detected**（无 schema 漂移）。
- 测试文件覆盖：model / append_only / taxonomy / redaction / service / failsoft / inv6_guard（7 个，全 SC 维度覆盖）。

## Review Status

`53-REVIEW.md` status: **clean**（0 BLOCKER / 0 HIGH）。原 3 MEDIUM + LOW-1/LOW-3 已修复并各自原子提交（含 tuple 脱敏绕过 MEDIUM-1、键名误伤 MEDIUM-2、事务污染 MEDIUM-3）；LOW-2 为明确的纵深防御设计取舍，已记为已知边界 deferred，不阻断本 phase。

## Gaps / Concerns

无阻断性缺口。已知非阻断边界（均不影响本 phase 目标达成，归 Phase 54 接线前定调）：
- LOW-2：值级脱敏对 <40 字符、无固定前缀、挂非敏感键名的明文密钥不命中（键名命中为主、值级为兜底的设计取舍）。
- 事务边界依赖调用方在主操作成功后 emit（建议 `transaction.on_commit`），savepoint 为机制兜底，Phase 54 接线评审须作硬性检查项。

## Final Status

**passed** — Phase 53 目标全部达成，4/4 成功标准经实际代码与 35 项测试证实，AUDIT-01/AUDIT-02 账实闭环，迁移无漂移，REVIEW clean。
