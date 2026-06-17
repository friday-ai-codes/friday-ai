---
phase: 49-produce-spec
subsystem: api
tags: [sdd_spec, openspec, document, plan_orchestration, inv6, event_taxonomy]

# Dependency graph
requires:
  - phase: 48-sdd-detect
    provides: Repository.facets["methodology"]="SDD" 打标
  - phase: 42-plan-orchestration
    provides: ArchitectMergeAdapter 融合通过路径 + PlanVersion/PlanSession
  - phase: 30-document
    provides: Document/DocumentVersion + DocumentService 写入收口范式
provides:
  - SddSpec 脊柱实体（5 态枚举 + unique_together 幂等键 + 0018 迁移）
  - DocumentService.create_internal_spec + SddSpecService.create_draft（双 INV-6 收口）
  - spec_generation（SddSpecSynthesizer + LLMSddSpecSynthesizer + agenerate_specs_for_plan）
  - EVENT_SPEC_DRAFTED + ArchitectMergeAdapter._handle_pass best-effort 挂接（fail-soft）
affects: [50-spec-lifecycle, 51-coding-gate, 52-spec-pr]

requirements-completed: [SPEC-01, SPEC-02]

# Metrics
plans: 4
completed: 2026-06-17
---

# Phase 49: 方案产 openspec spec + Document(sdd_spec) Summary

**SDD 仓库方案融合通过后 best-effort 逐仓产 openspec spec draft：落 SddSpec(draft) 脊柱 + Document(sdd_spec, internal_generated) 经双单一写入入口（INV-6），关联 WorkItem/PlanVersion/Repository 并 emit spec.drafted；非 SDD / 异常零回归 fail-soft**

## 成功标准达成（ROADMAP Phase 49）

1. ✅ SDD 仓经方案编排融合阶段额外产 openspec spec draft（`agenerate_specs_for_plan` 逐 SDD 仓 synthesize → create_draft，从 `_handle_pass` best-effort 挂接）
2. ✅ spec draft 落 `Document(document_type=sdd_spec, source_kind=internal_generated)`，经 `DocumentService.create_internal_spec` 单一入口写入（INV-6 grep 守护通过）
3. ✅ 非 SDD 仓不产 spec（facets.methodology!="SDD" 跳过；守护测试断言 merge 仍 passed 零回归）
4. ✅ spec draft 关联来源 `WorkItem` + `PlanVersion` + `Repository`（SddSpec 四 FK + create_draft 关联齐全）

## Plans 完成

| Plan | 内容 | 关键提交 |
|------|------|----------|
| 49-01 | SddSpec 模型 + 枚举 + 0018 迁移 + DocumentService.create_internal_spec | `28493f950` `ffa36804c` `766583fe5` |
| 49-02 | SddSpecService.create_draft（幂等单一写入）+ SddSpec INV-6 grep 守护 | `9e6efe154` `b1344bc46` `d7bc55382` |
| 49-03 | EVENT_SPEC_DRAFTED + spec_generation（synthesizer + agenerate_specs_for_plan）+ 对齐守护 | `f468dfd18` `e2c9d2726` `951e2cbca` |
| 49-04 | _handle_pass best-effort 挂接 + 可注入 hook + 全链路守护 | `36730de61` `9123f13d6` |

## 测试结果

全 phase 收口套件 **61 passed**（含既有 test_architect_merge_adapter / engine merge / document_service / 三个 INV-6 守护回归）：

- `tests/delivery/`：create_internal_spec(6)、sdd_spec_service(4)、sdd_spec_inv6_guard(2)、document_inv6_guard(2)、document_service(全回归)
- `tests/services/`：spec_generation(6)、event_taxonomy_alignment(3)、spec_generation_merge_hook(7)、architect_merge_adapter(12)、plan_orchestration_engine_merge(回归)

`ruff check` 全绿；`makemigrations --check --dry-run` 干净（无待生成迁移）。

## 关键决策与不变量

- **INV-6 双收口**：Document(sdd_spec) 只经 DocumentService，SddSpec 只经 SddSpecService，各有 grep 守护
- **INV-2**：work_item 全程可空（chat 自然语言需求）
- **幂等**：unique_together(plan_version, repository) DB 约束 + create_draft 短路（命中既有 SddSpec 不留孤儿 Document/不翻版本）
- **fail-soft 双保险**：hook 内逐仓 try/except + _handle_pass 外层 try/except，融合返回绝不受 spec 生成影响
- **真 LLM E2E deferred**：LLMSddSpecSynthesizer 仅构造 + 单测 mock（对齐 LLMMergedPlanSynthesizer）
- spec 状态机/评审/前端 → Phase 50；编码 gate → Phase 51；spec↔PR 关联 → Phase 52

## Deviations

1 项 Rule 1 自修：Plan 02 `sdd_spec_service.py` docstring 字面量 ``Document(sdd_spec)`` 触发 Document INV-6 grep 误报，改写措辞（行为不变，`d7bc55382`）。无 scope creep。

## Self-Check: PASSED

- 关键文件存在：sdd_spec.py / 0018_sddspec.py / sdd_spec_service.py / spec_generation.py / 各测试
- 全部任务提交存在于 git log
- 61 测试通过；ruff + makemigrations --check 干净

---
*Phase: 49-produce-spec*
*Completed: 2026-06-17*
