---
phase: 104-tool-surface-closure
plan: 02
subsystem: mcp-tools
tags: [mcp, orchestration, extra-evidence, seam-retirement, unify]
requires:
  - "104-01: improve 收敛 delegate + map_canonical_to_coding_plan 随迁 + 引用清单"
  - "Phase 102: 编排召回扩容（收敛后工具质量不降级）"
provides:
  - "mcp_tools/repository_analysis_service.py：确定性证据采集器随迁独立模块（analyze 响应契约不变）"
  - "extra_evidence 全链接线：delegate_process_runtime → start_orchestration stage_state → merge prompt/trace"
  - "Create/Improve 带 analysis 时注入 McpRepositoryAnalysis.summary（analysis_id 从仅挂 FK 升级为真实证据输入）"
  - "planning_service.py 删除 + services/plan_orchestration/ 空目录删除 + docs 残留清理（全仓零残留）"
  - "test_patch_target_guard.py：stale patch target importlib 防线（5 文件覆盖 + 空集防御）"
affects:
  - "104-03（E2E：analyze→create 证据链可验）"
tech-stack:
  added: []
  patterns:
    - "stage_state 可选键注入：truthy 才写键，既有会话形态零扰动"
    - "patch target 守卫：正则提取 dotted-path 字面量 + importlib 最长前缀 + getattr 逐段解析"
key-files:
  created:
    - server/mcp_tools/repository_analysis_service.py
    - server/tests/services/test_process_runtime_extra_evidence.py
    - server/tests/mcp_tools/test_patch_target_guard.py
  modified:
    - server/mcp_tools/views.py
    - server/mcp_tools/orchestration_delegate.py
    - server/services/process_runtime/entrypoint.py
    - server/services/process_runtime/architect_merge_adapter.py
    - server/tests/mcp_tools/test_planning_tools.py
    - server/tests/mcp_tools/test_create_coding_plan_delegate.py
    - server/tests/mcp_tools/test_work_item_execution.py
    - docs/workflows/ai-plan-generation-deprecation.md
  deleted:
    - server/mcp_tools/planning_service.py
    - server/services/plan_orchestration/（空目录）
decisions:
  - "extra_evidence 键名定 decomposition.extra_evidence；证据形态 [{kind, analysis_id, summary}]；merge prompt 在「各仓调研产物」段后插补充证据段（json.dumps ensure_ascii=False）"
  - "_build_prompt 实际在 LLMMergedPlanSynthesizer 上（plan 文本写 ArchitectMergeAdapter 系笔误），测试按真实落点断言"
  - "随迁模块 docstring 不写 planning_service 字面量（满足 rg 零残留验证），改为「旧确定性 planning seam 模块」措辞"
metrics:
  duration: "~25min"
  completed: "2026-07-22"
  tasks: 3 (+1 orchestrator-added)
  commits: 4
---

# Phase 104 Plan 02: analyze 收敛 + 确定性缝退役 + 残留清零 Summary

**One-liner:** build_repository_analysis 随迁 repository_analysis_service.py 后删除 planning_service.py（build_coding_plan/improve_coding_plan 消亡），extra_evidence 三层接线（delegate→stage_state→merge prompt/trace）让 analyze 产物被编排实际消费，全仓 planning_service/plan_orchestration 零残留 + stale patch target 守卫落防。

## Task 1: build_repository_analysis 随迁 + planning_service.py 删除（commit 1b5beade）

- 新建 `server/mcp_tools/repository_analysis_service.py`（204 行 > min 120）：整体搬移 `build_repository_analysis` 及全部依赖符号——PROMPT 常量、`PlanningResult`、`_token_estimate`/`_usage`、`normalize_context_chunks`、`_module_groups`/`_entry_points`/`_test_paths`。模块 docstring 定位「确定性证据采集器（非 LLM 生成）」。
- `views.py` import 切换 `from .repository_analysis_service import build_repository_analysis`；AnalyzeRepositoryView 调用点与响应契约（analysis_id/repository_id/branch/analysis/evidence/run_id）不动。
- 删除 `planning_service.py`：`build_coding_plan`（DEPRECATED 无调用方）、`improve_coding_plan`（104-01 后无调用方）、`_files_from_requirement`（仅 build_coding_plan 使用）随文件消亡。删除前 rg 比对 104-01 清单：代码引用仅剩 views.py 一处（即本次切换点）。
- `test_analyze_repository_persists_artifact_and_replayable_trace` 不改断言原样通过（覆盖不丢失证明）：4 passed。

## Task 2: extra_evidence 编排消费接线 + 视图注入（commit cd29f1ee）

- `start_orchestration`：签名增 `extra_evidence: list[dict] | None = None`，truthy 时写 `stage_state["decomposition"]["extra_evidence"]`，不传不写键（其他入口零扰动）；docstring 补语义。
- `delegate_process_runtime`：签名增同名参数原样透传；`mcp_plan_delegate_started` 事件增 `extra_evidence_count` kv（caller 类既有事件扩字段，观测规范达标）。
- `LLMMergedPlanSynthesizer._build_prompt`：读 `decomposition.get("extra_evidence") or []`，非空时在「各仓调研产物」段后插入「调用方补充证据（repository analysis 等）」段；`merge()` 的 `EVENT_PLAN_MERGE_STARTED` payload 增 `extra_evidence_count`（trace 可见条数）。
- 视图注入：`CreateCodingPlanView` analysis 已加载时注入 `[{"kind": "repository_analysis", "analysis_id": ..., "summary": analysis.summary}]`；`ImproveCodingPlanView` 按 `plan.analysis_id` afirst 加载同型注入；不带 analysis 恒传 None（零行为变化，有专测钉住）。
- 新测试 `test_process_runtime_extra_evidence.py` 三层 5 例：stage_state 注入/不写键、prompt 含/不含补充证据段、delegate kwargs 透传（patch `services.process_runtime.start_orchestration` + engine/drive 双桩）。
- 端到端注入断言：`test_create_coding_plan_delegate.py` 增 2 例（带 analysis_id → captured extra_evidence 含 summary；不带 → None）；`test_planning_tools.py` improve 用例改造为 create 挂 analysis + improve 侧捕获 kwargs 断言。
- 验证：17 passed（三文件合跑）。

## Task 3: 残留清零 + stale patch target 守卫（commit 2528409c）

- `services/plan_orchestration/` 核实为完全空目录后 rmdir。
- `docs/workflows/ai-plan-generation-deprecation.md:10` 文案 `plan_orchestration` → `process_runtime`（全文核查无其他残留）。
- 新增 `test_patch_target_guard.py`：正则提取 `monkeypatch.setattr("X.Y.Z")` / `mock.patch("X.Y.Z")` / 裸 `patch("X.Y.Z")` 的 dotted-path 字面量，importlib 最长可导入前缀 + getattr 逐段解析；覆盖 5 文件（test_planning_tools / test_create_coding_plan_delegate / test_mcp_artifact_sources / test_process_runtime_extra_evidence / tests 根目录 test_batch_pr）；空集防御断言 + 覆盖文件存在性断言 + 关键迁移路径显式钉住。4 passed。

## Extra Task（orchestrator-added）: test_work_item_execution fake 签名同步（commit 9175d1e6）

- Phase 103-01 给 `dispatch_execution` 加 `initiating_user` kwarg 后，测试内 3 处 fake `_dispatch_execution` 未同步导致 5 例失败；fake 签名统一补 `initiating_user=None`。
- `tests/mcp_tools/test_work_item_execution.py`：11 passed（此前 6 passed 5 failed）。

## 终验证据（rg 零残留）

```
$ rg -l "planning_service" --glob '!.planning/**' --glob '!.claude/**' .   # 零命中
$ rg -l "plan_orchestration" --glob '!.planning/**' --glob '!.claude/**' . # 零命中
$ test ! -d server/services/plan_orchestration                              # 目录不存在
$ test ! -f server/mcp_tools/planning_service.py                            # 文件不存在
```

## 测试结果

- `tests/mcp_tools/ + tests/services/test_process_runtime_extra_evidence.py`：**195 passed**（0 failed——含 extra task 修复后 work_item_execution 11 例全绿）。
- 编排面回归 `tests/services/ tests/delivery/ -k "process_runtime or orchestration or convergence"`：**59 passed**。
- `tests/knowledge/test_mcp_artifact_sources.py`：**19 passed**。
- ruff check / format：改动文件全部通过。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 随迁模块 docstring 含 planning_service 字面量**
- **Found during:** Task 1 验证（`! rg -q "planning_service" mcp_tools/ tests/` 失败）
- **Issue:** 新模块 docstring 提及来源文件名违反零残留验证
- **Fix:** 措辞改为「旧确定性 planning seam 模块」
- **Files modified:** `server/mcp_tools/repository_analysis_service.py`
- **Commit:** 1b5beade

**2. [Rule 1 - Bug] plan 指认的 `ArchitectMergeAdapter._build_prompt` 实际在 `LLMMergedPlanSynthesizer` 上**
- **Found during:** Task 2 测试首跑（AttributeError）
- **Issue:** 104-02-PLAN.md 与 must_haves key_links 写 `ArchitectMergeAdapter._build_prompt`，真实落点为同文件 `LLMMergedPlanSynthesizer._build_prompt`（静态方法）
- **Fix:** prompt 消费改动本就落在 `LLMMergedPlanSynthesizer._build_prompt`（正确落点），测试引用同步修正
- **Files modified:** `server/tests/services/test_process_runtime_extra_evidence.py`
- **Commit:** cd29f1ee

### 范围内新增（orchestrator 指派）

- extra task：`test_work_item_execution.py` fake 签名同步（见上），独立 commit 9175d1e6。

## 观测自检

- 新增 kv 仅 `extra_evidence_count`（`mcp_plan_delegate_started` caller 事件扩字段 + `EVENT_PLAN_MERGE_STARTED` payload 扩字段）；无新增 LLM 调用点、无新增召回面、无新增请求入口。
- 证据源为本实例 DB 确定性采集 summary（T-104-04 accept）；summary 本就返回同一调用方（T-104-05 accept）；T-104-06 mitigate 由 test_patch_target_guard.py 落实。

## Known Stubs

无。

## Threat Flags

无新增安全面（extra_evidence 边界在 plan threat_model 内，disposition 均已落实）。

## Self-Check: PASSED

- 文件存在：repository_analysis_service.py（204 行）/ test_process_runtime_extra_evidence.py / test_patch_target_guard.py 均在；planning_service.py 与 plan_orchestration/ 均不存在。
- 提交存在：1b5beade / cd29f1ee / 2528409c / 9175d1e6 均在 git log。
- 验证命令：mcp_tools 全量 195 passed；编排回归 59 passed；rg 双关键词零残留。
