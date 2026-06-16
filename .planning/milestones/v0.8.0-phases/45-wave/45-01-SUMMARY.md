---
phase: 45-wave
plan: 01
subsystem: plan_orchestration / delivery
tags: [artifact-extraction, wave, INV-6, fail-soft, async-orm]
requires:
  - "Phase 44 wave_progression._backfill_running_terminal（唯一 running→done 收口）"
  - "RepoCodingTask.produced_artifacts JSONField（Phase 44 已建字段）"
  - "SubAgentSession.task_result OneToOne（TaskResult git 产物字段）"
provides:
  - "build_produced_artifacts / classify_modified_files 纯函数（DB-free）"
  - "RepoCodingTaskService.record_produced_artifacts 单一写入入口（INV-6）"
  - "wave_progression 提取钩子（mark_done 后 fail-soft）"
  - "produced_artifacts 结构化产物（供 Plan 02 注入下游 wave）"
affects:
  - "Plan 45-02（下游 wave prompt 注入将消费 produced_artifacts）"
tech-stack:
  added: []
  patterns:
    - "纯函数提取 + 路径启发式归类（镜像 wave_layering.py）"
    - "service filter().update() 幂等覆盖写（无 status guard）"
    - "独立 try/except fail-soft 不冒泡"
    - "INV-6 字段级 grep 守护扩充"
key-files:
  created:
    - "server/services/plan_orchestration/artifact_extraction.py"
    - "server/tests/services/plan_orchestration/test_artifact_extraction.py"
  modified:
    - "server/services/plan_orchestration/__init__.py"
    - "server/services/plan_orchestration/wave_progression.py"
    - "server/delivery/services/repo_coding_task_service.py"
    - "server/tests/delivery/test_repo_coding_task_service.py"
    - "server/tests/delivery/test_repo_coding_task_inv6_guard.py"
decisions:
  - "record_produced_artifacts 不加 status guard（提取在 mark_done 后，task 已 done，加 status=RUNNING 会写 0 行）"
  - "提取段用局部 import 避免模块级循环依赖；OpenAPI 模式优先于通用契约桶匹配"
  - "INV-6 字段级守护用 `\\.produced_artifacts\\s*=(?!=)`——service kwarg 与 models 字段定义因无前导 `.` 天然不命中"
metrics:
  duration: "~25min"
  completed: "2026-06-16"
  tasks: 3
  files: 7
---

# Phase 45 Plan 01: 上游 wave 产物提取落库（ARTIFACT-01）Summary

上游仓 RepoCodingTask 进入 done 后，在 Phase 44 唯一收口 `_backfill_running_terminal` 的 `mark_done` 之后追加 fail-soft 提取段：取 `TaskResult` git 产物 → 纯函数 `build_produced_artifacts` 路径启发式归类（api_contracts/openapi/diff_summary）→ 经单一写入入口 `RepoCodingTaskService.record_produced_artifacts` 落 `produced_artifacts`，供 Plan 02 注入下游 wave。

## What Shipped

### Task 1 — `artifact_extraction.py` 纯函数 + barrel 导出（commit `f2e249ec`）
- 新建 `server/services/plan_orchestration/artifact_extraction.py`（镜像 `wave_layering.py` 纯函数风格：`from __future__`、中文模块 docstring 声明 DB-free、`__all__` 显式导出）。
- `classify_modified_files(modified_files) -> (api_contracts, openapi)`：纯字符串小写匹配，OpenAPI/Swagger 模式与后缀优先，否则归通用契约桶（`/api/`/`schema`/`.proto`/`.graphql(s)`/`contract`），`None` 按空列表处理、绝不抛。
- `build_produced_artifacts(*, repository_id, repository_name, task_result) -> dict`：`task_result=None` → `{available: False}` 占位；否则返回 branch/commit_sha/mr_url/modified_files/api_contracts/openapi/diff_summary。只取白名单字段，绝不落 raw_output/token（T-45-01）。
- barrel `__init__.py` 追加两函数 import + `__all__`。
- DB-free 单测 6 例（未保存内存 `TaskResult`）覆盖归类/git/占位/空文件/None/安全。

### Task 2 — `record_produced_artifacts` 写入入口 + INV-6 字段级守护（commit `d3bd73a8`）
- `RepoCodingTaskService.record_produced_artifacts` + `_record_produced_artifacts_sync`：用 `RepoCodingTask.objects.filter(id=task.id).update(produced_artifacts=..., updated_at=now())`，**无 status guard**（提取在 mark_done 后，task 已 done——Pitfall 4），覆盖式幂等。
- service 单测 `test_record_produced_artifacts`：done 状态写入成功（aget 重读相等）+ 重复写幂等。
- INV-6 守护扩充：新增正则 `\.produced_artifacts\s*=(?!=)` 字段级旁路写检测（D-14 / Pitfall 6），断言除 service writer 与 `delivery/models/` 外命中即 fail；既有守护用例零回归。

### Task 3 — `wave_progression` 提取钩子（fail-soft）（commit `30101cc1`）
- `_backfill_running_terminal` 在 `await service.mark_done(task)` 之后（仅 done 分支，不碰 mark_failed）追加独立 `try/except` 提取段。
- 复用循环已取出的 `sess`，`TaskResult.objects.filter(session=sess).afirst()` + `Repository.objects.filter(id=task.repository_id).afirst()`（async ORM 安全：`*_id` 标量 + afirst，无裸 lazy-FK），调纯函数 + `service.record_produced_artifacts`。
- 整段 `except Exception` → `logger.warning("coding_artifact_extract_failed", task_id, error)`，绝不冒泡（保 mark_done 成功后 task 仍正确 done、wave 推进/回调不受影响，T-45-04）；日志仅 task_id/error，不记产物正文。
- 保留既有三步顺序（回填→阻断→决策）；build/record 经局部 import 避免模块级循环依赖。

## Deviations from Plan

None — plan executed exactly as written. 唯一机械调整：ruff `I001` 自动排序了 Task 1 测试与 Task 3 局部 import 顺序（行为无关）。

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/services/plan_orchestration/test_artifact_extraction.py -x` | 6 passed |
| `pytest tests/delivery/test_repo_coding_task_service.py tests/delivery/test_repo_coding_task_inv6_guard.py -x` | 10 passed |
| `pytest tests/services/plan_orchestration tests/delivery -x`（Phase 44 零回归） | 332 passed |
| `ruff check`（4 改动源文件） | All checks passed |

## Security Notes

- T-45-01（Info Disclosure）：产物只取白名单字段（branch/commit_sha/pr_url/path/计数），单测断言不含 raw_output 正文/token；日志仅记 task_id/error。
- T-45-04（DoS）：提取段独立 fail-soft，无 TaskResult 走占位非异常路径，绝不让回调 5xx。
- INV-6：produced_artifacts 写库只经 service writer；字段级守护拦旁路写。

## Known Stubs

None — produced_artifacts 由提取钩子实际写入，无占位 stub。下游注入（消费方）为 Plan 45-02 范围。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/artifact_extraction.py
- FOUND: server/tests/services/plan_orchestration/test_artifact_extraction.py
- FOUND commit f2e249ec / d3bd73a8 / 30101cc1
