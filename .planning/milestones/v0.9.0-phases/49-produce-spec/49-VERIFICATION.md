---
phase: 49-produce-spec
verified: 2026-06-17T02:30:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: # No — initial verification
human_verification:
  - test: "真 LLM 容器 / 真模型端到端：在配置真实 provider 的环境（或编码容器）下，对一个 facets.methodology=SDD 的真实仓走完整融合 → agenerate_specs_for_plan → LLMSddSpecSynthesizer.synthesize（不 mock）"
    expected: "LLMSddSpecSynthesizer 用真实 provider 解析 + build_chat_model 调真模型，返回符合 openspec change-proposal 结构（## Why / ## What Changes / ## Spec Deltas: ADDED/MODIFIED/REMOVED Requirements + Scenarios）的非空 markdown，落 Document(sdd_spec) 并 emit spec.drafted；融合不被阻断"
    why_human: "本 phase 真 LLM 路径仅构造 + 单测 mock（D-49-4，刻意对齐 LLMMergedPlanSynthesizer 已验范式），真容器/真模型 E2E 不在自动化范围；需真实 provider 凭证与运行环境，grep/单测无法覆盖真模型输出质量与 openspec 格式合规"
---

# Phase 49: 方案产 openspec spec + Document(sdd_spec) Verification Report

**Phase Goal:** SDD 仓库的方案编排额外产出可追溯的 openspec spec draft 并持久化为内部生成文档
**Verified:** 2026-06-17T02:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP 成功标准 / SPEC) | Status | Evidence |
|---|---|---|---|
| 1 | SDD 仓经方案编排融合阶段额外产 openspec spec draft（SC#1 / SPEC-01） | ✓ VERIFIED | `agenerate_specs_for_plan` 解析 `PlanVersion.content.execution_plan[].repository_id` → 过滤 `Repository.facets["methodology"]=="SDD"` → 逐仓 `synthesize` + `create_draft`（`spec_generation.py:96-184`）；`_handle_pass` 在 `EVENT_PLAN_MERGE_COMPLETED` emit 之后调 `spec_generation_hook`（`architect_merge_adapter.py:253-263`）。`test_sdd_repo_full_chain_produces_spec` 真实 ORM 走 pass 分支断言产 1 个 SddSpec(draft) + Document(sdd_spec) + spec.drafted（PASS） |
| 2 | spec draft 落 `Document(sdd_spec, internal_generated)` 经 `DocumentService` 单一入口（SC#2 / SPEC-01 / INV-6） | ✓ VERIFIED | `DocumentService.create_internal_spec` 落 `Document(SDD_SPEC, INTERNAL_GENERATED, SNAPSHOT, external_ref="", feishu_tenant="")` + DocumentVersion，hash 不翻版本（`document_service.py:144-232`）。`test_document_inv6_guard`（2）grep 守护断言 Document/DocumentVersion 写入仅经 DocumentService；`test_sdd_spec_inv6_guard`（2）断言 SddSpec 仅经 SddSpecService。全 PASS |
| 3 | 非 SDD 仓 / 无 SDD 仓 / 异常 → 不产 spec，merge 仍 passed（SC#3 零回归） | ✓ VERIFIED | hook 内 `repo.facets.get("methodology") != "SDD"` → continue（`spec_generation.py:148`）。`test_non_sdd_repo_no_regression` / `test_no_matching_repo_no_spec` 断言 merge passed 且 SddSpec 计数 0、`current_plan_version` 已置；`test_architect_merge_adapter`（12）全量回归 PASS |
| 4 | spec draft 关联来源 `WorkItem` + `PlanVersion` + `Repository`，可追溯（SC#4 / SPEC-02） | ✓ VERIFIED | `SddSpec` 四 FK（document/repository/work_item/plan_version，`sdd_spec.py:47-105`）；`create_draft` 连 plan_version_id/repository/work_item（`sdd_spec_service.py:39-111`）。`test_sdd_repo_full_chain_produces_spec` 断言 `spec.repository_id==repo.id` 且 `spec.plan_version_id==result["plan_version_id"]`；work_item 全程可空对齐 INV-2（chat 自然语言） |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `server/delivery/models/sdd_spec.py` | SddSpec 脊柱模型 + 5 态枚举 + change_kind 枚举（零业务方法） | ✓ VERIFIED | 四 FK + `unique_together(plan_version, repository)` 幂等键 + indexes；仅 `__str__`，无 create/save 业务方法（守 INV-6） |
| `server/delivery/migrations/0018_sddspec.py` | SddSpec 建表迁移（跨 app FK 依赖 repositories） | ✓ VERIFIED | `CreateModel` 含四 FK + unique_together + 2 indexes；dependencies 含 `('repositories','0036_git_instance_credential')`；`makemigrations --check` → No changes detected |
| `server/delivery/services/document_service.py` | `create_internal_spec` 内部生成文档单一写入入口 | ✓ VERIFIED | async + `@sync_to_async` 锁定 + `transaction.atomic`；hash 相等不翻版本；external_ref="" 豁免飞书唯一约束 |
| `server/delivery/services/sdd_spec_service.py` | `SddSpecService.create_draft` 幂等单一写入 | ✓ VERIFIED | 幂等短路（命中既有不留孤儿 Document）+ get_or_create 兜底竞态 |
| `server/services/plan_orchestration/spec_generation.py` | SddSpecSynthesizer 协议 + LLMSddSpecSynthesizer + agenerate_specs_for_plan | ✓ VERIFIED | 逐仓 try/except 隔离；非 SDD 跳过；emit spec.drafted best-effort |
| `server/services/plan_orchestration/architect_merge_adapter.py` | `_handle_pass` best-effort 挂接 + 可注入 hook | ✓ VERIFIED | 构造延迟默认绑定真实 hook；merge.completed emit 后 try/except 吞 warning `sdd_spec_generation_failed` |
| `server/delivery/services/event_taxonomy.py` | `EVENT_SPEC_DRAFTED = "spec.drafted"` | ✓ VERIFIED | 入 `__all__` + ALL_EVENTS；payload {spec_id, repository_id, plan_version_id} |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `architect_merge_adapter._handle_pass` | `agenerate_specs_for_plan` | `spec_generation_hook`（默认真实，可注入 stub） | ✓ WIRED | `test_stub_hook_receives_canonical_plan_version_id` 断言 hook 被调一次且收到 canonical PlanVersion id |
| `agenerate_specs_for_plan` | `SddSpecService.create_draft` | synthesize → create_draft | ✓ WIRED | `spec_generation.py:153-158`；全链路测试落库 SddSpec |
| `SddSpecService.create_draft` | `DocumentService.create_internal_spec` | 未命中幂等时落 spec 正文 Document | ✓ WIRED | `sdd_spec_service.py:74-78` |
| `SddSpec` 模型 | Repository / PlanVersion / WorkItem / Document | ForeignKey | ✓ WIRED | 四 FK 定义 + 迁移 CreateModel 落地 |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `agenerate_specs_for_plan` | merged_plan | `PlanVersion.content`（真实 ORM 读取，afirst） | ✓（execution_plan 解析驱动逐仓） | ✓ FLOWING |
| `create_draft` → Document | content | LLMSddSpecSynthesizer.synthesize（单测 mock；真 LLM E2E deferred） | 单测 mock 固定 markdown；真模型输出待人验 | ⚠️ 真 LLM 路径见 Human Verification |

### Behavioral Spot-Checks / Probe Execution

无独立 probe 脚本（本 phase 非 migration/CLI 工具 phase）。行为校验经真实 ORM 单测覆盖（transaction=True），见下方测试结果。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| SPEC-01 | 49-01/02/03/04 | SDD 仓融合阶段产 openspec spec draft，落 Document(sdd_spec, internal_generated) 经 DocumentService 单一入口（INV-6） | ✓ SATISFIED | Truths 1/2 + INV-6 双 grep 守护 |
| SPEC-02 | 49-01/02/04 | spec draft 关联来源 WorkItem + PlanVersion，可追溯 | ✓ SATISFIED | Truth 4，SddSpec 四 FK + create_draft 关联 |

无 ORPHANED 需求（REQUIREMENTS.md Phase 49 仅映射 SPEC-01/SPEC-02，均被 plan 声明覆盖）。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| architect_merge_adapter.py | 21 | docstring `partial.research_task.xxx`（散文占位 "xxx" 示例，非 debt marker） | ℹ️ Info | 无影响；Phase 42 既有 docstring 描述 lazy-FK 范式，非未完成标记 |

无 TODO/FIXME/XXX debt marker 落在 Phase 49 新增/修改代码。docstring 中 "本 phase 不实现 / 归 Phase 50" 为 scope 边界声明（对齐 ROADMAP Phase 50-52），非债务。

### 测试 / 命令实证（verifier 自跑）

- `tests/delivery/test_sdd_spec_service.py` + `test_sdd_spec_inv6_guard.py` + `test_document_inv6_guard.py` + `test_create_internal_spec.py` + `tests/services/test_spec_generation.py` + `test_event_taxonomy_alignment.py` + `test_spec_generation_merge_hook.py` + `test_architect_merge_adapter.py` → **42 passed**
- `tests/delivery/test_document_service.py` + `tests/services/test_plan_orchestration_engine_merge.py`（回归）→ **19 passed**
- 合计 **61 passed**（与 SUMMARY 声明一致）
- `python manage.py makemigrations --check --dry-run` → **No changes detected**（迁移与模型同步，干净）
- `ruff check`（7 个 Phase 49 文件）→ **All checks passed!**

### Human Verification Required

#### 1. 真 LLM 容器 / 真模型端到端 spec 生成

**Test:** 在配置真实 provider 的环境（或编码容器）下，对一个 `facets.methodology="SDD"` 的真实仓走完整融合 → `agenerate_specs_for_plan` → `LLMSddSpecSynthesizer.synthesize`（**不 mock**）。
**Expected:** 用真实 provider 解析 + `build_chat_model` 调真模型，返回符合 openspec change-proposal 结构（`## Why` / `## What Changes` / `## Spec Deltas`: ADDED/MODIFIED/REMOVED Requirements + Scenarios）的非空 markdown，落 `Document(sdd_spec)` 并 emit `spec.drafted`；融合返回不被阻断。
**Why human:** 本 phase 真 LLM 路径仅构造 + 单测 mock（D-49-4，刻意对齐 `LLMMergedPlanSynthesizer` 已验范式），真容器/真模型 E2E 不在自动化范围；需真实 provider 凭证与运行环境，grep/单测无法覆盖真模型输出质量与 openspec 格式合规。

### Gaps Summary

无阻断性 gap。Phase 49 的 4 条 ROADMAP 成功标准与 SPEC-01/SPEC-02 在代码与真实 ORM 测试层面均已闭合：双 INV-6 收口（Document/SddSpec 各有 grep 守护）、幂等（unique_together + create_draft 短路）、fail-soft 双保险（hook 内逐仓 + `_handle_pass` 外层 try/except）、零回归（非 SDD/无仓/异常 merge 仍 passed）全部有真实测试断言并自跑通过（61 passed），迁移与 ruff 干净。

唯一未自动覆盖项为真 LLM 容器/真模型 E2E——此为 D-49-4 刻意 deferred 的范式一致决策（与 v0.7 `LLMMergedPlanSynthesizer` 同款），非实现缺失。按决策树 Step 9，存在非空 human verification 项 → 整体 `status: human_needed`（所有可程序化校验的真相均已 VERIFIED）。

---

*Verified: 2026-06-17T02:30:00Z*
*Verifier: Claude (gsd-verifier)*
