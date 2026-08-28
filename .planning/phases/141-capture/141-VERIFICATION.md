---
phase: 141-capture
verified: 2026-08-28T08:05:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 141: Capture 账本与仓库挂钩 Verification Report

**Phase Goal:** 用户提交的会话问答始终先进入独立、脱敏、可归因的 Capture 账本，并尽可能关联仓库与可选项目
**Verified:** 2026-08-28T08:05:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

Phase 141 的合同是**持久化账本 + 唯一写入服务 + 挂钩失败仍落库 + caller 观测**，不是 MCP 工具。`report_session_knowledge` 在代码库中不存在，对应 Phase 142（MCP-01..04），不构成本阶段缺口。

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | 结构化问答落入独立 Capture（question / 可见 answer / 会话与来源元数据），不写成 `ProjectMemory` 或 Interaction Ledger 正文 | ✓ VERIFIED | `SessionCapture` 表 `initiative_session_captures`；`CaptureService.persist` 只 `SessionCapture.objects.create`。`test_persist_does_not_write_memory_or_ledger` 断言 `ProjectMemory` 计数不变且未调用 `arecord_tool_call`。writer 源码无 `MemoryService` / `arecord_tool_call`。 |
| 2 | `repository_id` / `project_id` 任一或同时缺失仍落库；git URL 无法解析时 `link_reason=repo_unresolved`，不静默跳过 | ✓ VERIFIED | `test_persist_without_project_or_repo` → `unanchored` 且双 FK 空。`test_unresolved_repo_still_persists` → 行存在、`repository_id is None`、`repo_unresolved`。`test_project_only_without_repo` / mismatch / unauthorized 均创建行。 |
| 3 | 模型、provider、token 计数不可得时保存字面 `unknown`，服务端不猜测补全 | ✓ VERIFIED | `_scalar_or_unknown` 仅空/空白→`unknown`，无 env/默认模型推断。`test_unknown_scalars` 覆盖 `None` / `""` / 空白。字段默认值同为 `unknown`。 |
| 4 | 写入经 `CaptureService` 脱敏并归因触发用户；caller 生命周期含 `duration_ms`；凭证/token/密钥不进 Capture、Ledger、日志 | ✓ VERIFIED | 入库前 `redact_secrets_in_text`；`initiated_by_user_id` 来自 actor。`test_redaction_and_actor`、`test_success_caller_lifecycle`、`test_failure_caller_lifecycle`、`test_no_body_or_secrets_in_logs`、`test_logger_failure_does_not_drop_capture`。INV-6 守卫仅放行 `capture_service.py`。 |

**Score:** 4/4 truths verified

补充（PLAN 增项，均已满足，不扩大 ROADMAP 合同）：幂等 first-write-wins（`test_idempotent_returns_existing`）；缺 `session_id` 用 `unspecified`；挂钩闭集 `link_reason`；授权走 `knowledge.access_scope` 而非 `RepositoryPermission`；无 eval/ingest sampling 事件。

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `server/initiatives/models/session_capture.py` | SessionCapture + 状态枚举，`db_table=initiative_session_captures`，可空 FK | ✓ VERIFIED | 实质性字段、`pending_eval` 默认、UniqueConstraint 三元组；从 `initiatives.models` 导出 |
| `server/initiatives/migrations/0015_session_capture.py` | 建表；FK SET_NULL；唯一约束 | ✓ VERIFIED | `on_delete=SET_NULL`；`uniq_session_capture_user_session_question` |
| `server/initiatives/services/capture_service.py` | INV-6 async persist | ✓ VERIFIED | `objects.create` + IntegrityError 回读；挂钩状态机；best-effort logger |
| `server/services/git_url.py` | `normalize_git_url` | ✓ VERIFIED | SSH→HTTPS + strip/lower/.git；被 `_resolve_repository` 调用 |
| `server/tests/initiatives/test_capture_service.py` | persist / 挂钩 / 幂等 / unknown / 脱敏 / 分离 | ✓ VERIFIED | 含 Wave 0 四用例；14 项全绿 |
| `server/tests/initiatives/test_capture_inv6_guard.py` | 唯一 writer + 禁止延迟入口 | ✓ VERIFIED | `_ALLOWED_WRITER`；禁止 `aschedule_ingestion` 等 |
| `server/tests/initiatives/test_capture_observability.py` | caller 生命周期与无正文 | ✓ VERIFIED | 5 项全绿 |
| `.planning/observability/LOGGING-SPEC.md` | 登记 `session_capture_persist_*`，不改 CallSource | ✓ VERIFIED | §10 三事件；注明评估 CallSource 留给后续阶段 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `capture_service.py` | `redact_secrets_in_text` | create 前对 question/answer；failed 的 `error=` | WIRED | persist try 块与 `_log_failed` |
| `capture_service.py` | `SessionCapture.objects.create` | `transaction.atomic` + `status=pending_eval` | WIRED | `_create_locked` |
| `capture_service.py` | `resolve_allowed_repository_ids` / `resolve_allowed_project_ids` | 决定是否写 FK | WIRED | `_resolve_link` |
| `capture_service.py` | `normalize_git_url` | URL 变体 filter | WIRED | `_resolve_repository` |
| `test_capture_inv6_guard.py` | `initiatives/services/capture_service.py` | `_ALLOWED_WRITER` | WIRED | 静态扫描 + writer 必须含 `objects.create` |
| `capture_service.py` | structlog | `except Exception: pass` 包住三事件 | WIRED | `_log_started/_completed/_failed` |

生产 MCP 调用链故意未接（Phase 142）。服务经 `initiatives.services` barrel 导出，测试直接调用 `persist`，对本阶段目标足够。

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `CaptureService._create_locked` | `question` / `answer` | 调用方参数 → `redact_secrets_in_text` → ORM create | 是（非空问答写入行；测试读回断言） | ✓ FLOWING |
| `CaptureService._create_locked` | `project` / `repository` | `_resolve_link` 查 `Repository`/`Project` + access_scope | 是（命中则绑 FK；失败写 reason 仍 create） | ✓ FLOWING |
| 生命周期日志 | `capture_id` / `link_reason` | 刚写入的 `CapturePersistResult` | 是（completed kv 白名单，无正文） | ✓ FLOWING |

无 UI 渲染面；无 hollow props。

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Capture + INV-6 + 观测 + Memory INV-6 + `report_project_knowledge` 回归 | `cd server && uv run pytest tests/initiatives/test_capture_service.py tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_observability.py tests/initiatives/test_memory_inv6_guard.py tests/mcp_tools/test_report_project_knowledge.py -q --tb=short` | 39 passed in 102.27s, exit 0 | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | Phase 141 / PLAN / SUMMARY 未声明 probe 脚本；非迁移探针阶段 | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| STORE-01 | 01–04 | 独立 Capture 账本，不写 Memory/Ledger 正文 | ✓ SATISFIED | 模型 + persist + 分离测试；MCP 提交面属 Phase 142 |
| STORE-02 | 01–02 | 双 FK 可空，无项目不拒写 | ✓ SATISFIED | 可空 FK + `unanchored`/`project_only` |
| STORE-03 | 01–03 | 仅 CaptureService；脱敏；`initiated_by_user_id`；禁旁路 create | ✓ SATISFIED | INV-6 守卫 + persist 实现 + 幂等 |
| STORE-04 | 01, 03 | 归一化 git URL 挂钩；失败仍落库并显式 reason | ✓ SATISFIED | HTTPS/SSH 参数化挂钩；`repo_unresolved`/`repo_ambiguous`/`repo_unauthorized` |
| STORE-05 | 01–02 | 未知标量记 `unknown` | ✓ SATISFIED | `_scalar_or_unknown` + 测试 |
| OBS-01 | 01, 04 | persist caller started/completed/failed + duration_ms；评估 sampling 本阶段不出现 | ✓ SATISFIED | 观测测试；LOGGING-SPEC 登记；无 `session_capture_eval` CallSource（Phase 143） |
| OBS-02 | 01–02, 04 | 入库前脱敏；密钥不进 Capture/Ledger/日志 | ✓ SATISFIED | redact + 日志白名单测试 |
| MCP-01..04 | — | `report_session_knowledge` | n/a Phase 142 | 代码无该工具名，符合 CONTEXT deferred |
| OBS-03 | — | RetrievalTrace | n/a Phase 144 | — |
| OBS-04 | — | 后台 re-bind | n/a Phase 143 | — |

无 REQUIREMENTS.md 映射到 141 但未被任何 PLAN `requirements:` 声明的孤儿项。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | `TBD`/`FIXME`/`XXX` in phase writer/tests | none | capture_service / capture tests / session_capture 模型无债务标记 |
| `server/tests/initiatives/test_capture_service.py` | 105–119 | `arecord_tool_call` monkeypatch 测「未调用」 | ℹ️ Info | writer 本就不导入 ledger；与 INV-6 forbidden 列表一起仍能锁分离，但该测本身较弱 |

**Disconfirmation 笔记（不构成缺口）：**

1. URL 挂钩对查询侧做 `normalize_git_url`，对库内 `Repository.git_url` 做 HTTPS 变体精确 filter，未对库内值再归一。仓库侧已有 `0031_convert_ssh_git_urls`，测试仓用 HTTPS 存储；SSH **入参**挂钩已覆盖。
2. `_can_bind_repository` 在 access_scope 之外再要求项目成员 ∩ `space.repositories`，写路径比只读 scope 更严。与 CONTEXT「未授权不绑 FK 仍落库」一致。
3. Wave 0 PLAN 曾要求测试当时为 RED；全波次执行后应变绿。当前 39 项通过，不以历史 RED 合同判失败。

### Human Verification Required

无。VALIDATION.md 声明本阶段全部自动化、无 frontend/UI。PLAN 中无 `<human-check>` 块。

### Gaps Summary

无。四条 ROADMAP Success Criteria 均在代码与测试中可观察为真。后续 MCP 入口、评估 sampling、召回回放按路线图分属 142–144，不作为本阶段 gap 或 deferred 未完成项。

---

_Verified: 2026-08-28T08:05:00Z_
_Verifier: Claude (gsd-verifier)_
