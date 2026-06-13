---
phase: 17-varref
plan: 01
subsystem: workflow-engine
tags: [template-resolver, var-ref, fail-fast, structured-error, pytest]

# Dependency graph
requires: []
provides:
  - "解析核心模块 workflows/engine/template_resolver.py（TemplateResolutionError + 嵌套下钻 + 前缀分发 + 严格 nodes/未知前缀语义）"
  - "render_template / get_template_value 共享同一解析核心，错误语义一致"
  - "解析失败的 NodeExecution.error_message 契约：中文一句话 + 最后一行结构化 JSON（reference/reason/available/template）"
  - "get_previous_output 点分嵌套下钻（保留 default 不抛异常语义）"
affects: [17-02, 17-03, 17-04, phase-18-trigger, phase-20-validation, phase-21-error-display]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "纯函数解析核心（零 Django 依赖），ExecutionContext 薄委托"
    - "类型化异常承载结构化错误（继承 ValueError 保持调用方兼容）"
    - "error_message 编码：中文人类可读 + \\n + 机器可读 JSON 最后一行"

key-files:
  created:
    - server/workflows/engine/template_resolver.py
    - server/tests/workflows/test_template_resolver.py
  modified:
    - server/workflows/nodes/base.py
    - server/workflows/engine/scheduler.py
    - server/tests/workflows/test_error_handling.py

key-decisions:
  - "严格语义定界（OQ#1）：仅 nodes.* 与未知前缀严格化；input/trigger/global/context/config 字段缺失维持空串现状并有锁定测试"
  - "error_message 编码采纳 OQ#3 推荐：中文一句话 + 最后一行 ensure_ascii=False JSON，Phase 21 可直接 JSON.parse"
  - "render 模式下 $ 开头的非简写/非 JSONPath 形态（如 {{$foo}}）维持现状保留字面量，归属 JSONPath 家族不落 unknown_prefix"
  - "base.py 经方法内延迟导入 template_resolver，避免与 workflows.engine 包初始化形成循环依赖"
  - "get_previous_output 嵌套下钻前优先精确匹配含点号的历史扁平 key，双保险兼容"

patterns-established:
  - "TemplateResolutionError(template/reference/reason/available)：reason 四枚举 node_not_found | field_not_found | unknown_prefix | missing_field_path"
  - "available 候选只列键名（过滤 UUID 键只列 short_id，过滤后为空回退全部键），绝不含输出值（T-17-01）"

requirements-completed: [VAR-02, VAR-04]

# Metrics
duration: 25min
completed: 2026-06-13
---

# Phase 17 Plan 01: 模板变量解析核心重写 Summary

**模板解析失败从静默空串/字面量保留改为三分类显式报错（中文 + 结构化 JSON 落 error_message），并落地嵌套 dict/list 路径下钻，两 API 共享同一纯函数解析核心。**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-12T16:11:00Z
- **Completed:** 2026-06-12T16:36:00Z
- **Tasks:** 3/3
- **Files modified:** 5（新建 2 + 修改 3）

## Accomplishments

- 新建 `server/workflows/engine/template_resolver.py`（约 330 行）：纯函数解析核心，零 Django 依赖，pytest 零 DB 可测；`TemplateResolutionError` 四属性（template/reference/reason/available）且 `isinstance(err, ValueError)` 兼容既有调用方
- VAR-02 落地：节点 ID 不存在（含大小写近似提示）、字段不存在（含嵌套断路定位）、未知前缀、段数不足（missing_field_path，不误报未知前缀）四类显式报错；available 候选过滤 UUID 键只列 short_id、绝不含输出值
- VAR-04 落地：`{{nodes.x.data.name}}` 嵌套 dict 下钻、`items.0.name` list 数字索引；`get_previous_output` 同步支持嵌套但保留 default 不抛异常语义（直接调用方不受影响）
- `render_template` / `get_template_value` 薄委托同一核心，错误语义一致；`_resolve_jsonpath` 与 JSONPath 行为（含零匹配保留字面量）原样保留并有 characterization 测试
- scheduler 识别 `TemplateResolutionError`，error_message 写入"中文一句话 + 最后一行 ensure_ascii=False JSON"，集成测试锁定 Phase 21 消费契约
- 测试：新增专项单测 49 个（42 纯函数 + 7 ExecutionContext 集成层）+ 1 个端到端集成测试；`tests/workflows/` 全量 343 个测试全绿无回归

## Task Commits

Each task was committed atomically:

1. **Task 1: 新建 template_resolver.py 解析核心 + 全场景专项单测（TDD）**
   - RED: `a015dc8c` (test) — 失败测试先行
   - GREEN: `44646942` (feat) — 实现解析核心使全部用例通过
2. **Task 2: base.py 两 API 委托同一核心 + get_previous_output 嵌套下钻** - `92430be3` (refactor)
3. **Task 3: scheduler 结构化 error_message + 解析失败集成测试** - `06a8485f` (feat)

## Files Created/Modified

- `server/workflows/engine/template_resolver.py` - 解析核心：TemplateResolutionError、ResolutionSources、resolve_path（前缀分发 + nodes 严格嵌套下钻）、render_template、get_template_value；模块 docstring 明确严格语义定界
- `server/tests/workflows/test_template_resolver.py` - VAR-02/VAR-04 全场景专项单测（零 DB 纯函数）+ ExecutionContext 集成层 + JSONPath/非 nodes 前缀现状锁定测试
- `server/workflows/nodes/base.py` - render_template/get_template_value 改薄委托；删除 _resolve_simple_path 与旧 replace 闭包；get_previous_output 嵌套下钻；_resolve_jsonpath 零变更
- `server/workflows/engine/scheduler.py` - _execute_node except 分支识别 TemplateResolutionError 并写结构化 error_message（json.dumps ensure_ascii=False）
- `server/tests/workflows/test_error_handling.py` - 新增 TemplateRenderNode 测试节点 + TestTemplateResolutionError 集成测试（django_db）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 修复 scheduler.py / test_error_handling.py 既有 I001 导入排序问题**
- **Found during:** Task 3
- **Issue:** 两文件在 HEAD 即存在 ruff I001（导入块未排序）报错，阻塞计划验收标准"`uv run ruff check ... scheduler.py` 无报错"
- **Fix:** `ruff check --fix` 仅修复导入块排序（未做全文件 reformat，保持最小 diff）
- **Files modified:** server/workflows/engine/scheduler.py, server/tests/workflows/test_error_handling.py
- **Commit:** 06a8485f（随 Task 3 一并提交）

### 微小行为变化（随严格化自然产生，已记录）

- nodes 引用命中的字段值为 None 时，render 旧行为输出字符串 "None"（`str(None)`），新行为统一输出空串——与其他前缀 None→空串口径一致
- render 模式 `{{$foo}}`（$ 开头、非 `$.` 简写、不含 `[`）维持现状保留字面量，归属 JSONPath 家族，不落 unknown_prefix 严格语义（已写入模块 docstring 与实现注释）

## TDD Gate Compliance

- RED gate: `a015dc8c` test(17-01) — 测试先行并确认失败（模块不存在，collection error）
- GREEN gate: `44646942` feat(17-01) — 实现后 42 用例全绿
- REFACTOR: 无独立 refactor 提交（实现一次成型，无需清理）

## Verification

- `cd server && uv run pytest tests/workflows/test_template_resolver.py tests/workflows/test_error_handling.py tests/workflows/test_nodes.py tests/workflows/test_engine.py -q` → 103 passed
- `cd server && uv run pytest tests/workflows/ -q` → 343 passed（全量无回归）
- `cd server && uv run ruff check workflows/engine/template_resolver.py workflows/nodes/base.py workflows/engine/scheduler.py` → All checks passed
- `rg "^from django|^import django" server/workflows/engine/template_resolver.py` → 零匹配（解析核心零 Django 依赖）
- base.py 中 "无法解析则保持原样" 旧注释已随旧逻辑删除；`_resolve_jsonpath` 方法体 git diff 零变更

## Known Stubs

None — 无占位/stub，全部功能已接线并有测试覆盖。

## Threat Flags

无新增安全面：T-17-01（available 不泄露输出值）已由 Task 1 单测显式断言（`test_available_contains_only_keys_never_values`）；T-17-02/T-17-SC 维持 accept 处置，零新依赖。

## Next Phase Readiness

- 错误结构契约（reference/reason/available/template + 最后一行 JSON）已定稿并有集成测试锁定，Phase 21 可直接消费
- 非 nodes 前缀宽松语义有现状锁定测试，Phase 18（trigger 注入）/ Phase 20（保存校验）收紧时可直接改断言
- 17-02（short_id 保存路径）可直接复用本计划的双键兼容解析语义

## Self-Check: PASSED

- FOUND: server/workflows/engine/template_resolver.py（338 行 ≥ 120）
- FOUND: server/tests/workflows/test_template_resolver.py（430 行 ≥ 150）
- FOUND: .planning/phases/17-varref/17-01-SUMMARY.md
- FOUND: commit a015dc8c / 44646942 / 92430be3 / 06a8485f
