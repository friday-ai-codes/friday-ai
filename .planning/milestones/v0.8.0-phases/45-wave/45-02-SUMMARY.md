---
phase: 45-wave
plan: 02
subsystem: plan_orchestration / workflows
tags: [artifact-injection, wave, zero-regression, fail-soft, async-orm, prompt]
requires:
  - "Plan 45-01 produced_artifacts 结构化产物（提取落库已 ship）"
  - "RepoCodingTask.depends_on self-M2M（Phase 44 仓级依赖边）"
  - "AICodingNode dispatch 链 _dispatch_next_wave → _dispatch_wave → _run_repo_coding → _build_coding_prompt（Phase 44）"
provides:
  - "acollect_upstream_artifacts(async) 沿直接 depends_on 反查 + repository_id 排序"
  - "render_upstream_artifacts_section 纯函数（空 list → \"\" 零回归守卫）"
  - "coding.py dispatch 链 defaulted upstream_artifacts 透传注入"
  - "下游 wave 容器 prompt 含「上游产物 / 上游契约」段"
affects:
  - "下游 wave 编码 agent global context（消费上游仓 API 契约）"
tech-stack:
  added: []
  patterns:
    - "纯渲染 + 空守卫（镜像 _build_files_section `if not any(...): return \"\"`）"
    - "defaulted 参数透传保首发零回归（镜像既有 if files_section: 守卫）"
    - "async for depends_on.all() + JSON 列标量（async ORM 安全）"
    - "_dispatch_next_wave 收集段独立 try/except fail-soft 不冒泡"
key-files:
  created:
    - "server/services/plan_orchestration/artifact_injection.py"
    - "server/tests/services/plan_orchestration/test_artifact_injection.py"
  modified:
    - "server/services/plan_orchestration/__init__.py"
    - "server/workflows/nodes/ai/coding.py"
    - "server/tests/test_coding_node.py"
decisions:
  - "上游产物段插在 global_context 之后、分支信息之前（Open Q1 RESOLVED，最贴 D-08「项目背景之后」）"
  - "acollect 返回前按 repository_id 排序保多上游渲染确定性（Open Q2 RESOLVED）"
  - "仅 _dispatch_next_wave 收集注入（D-07 唯一收集点）；首发 _execute_with_branch 不传新参 → wave 0 各仓 [] → prompt 字节级零回归"
  - "render/collect 经局部 import（方法内）避免模块级循环依赖"
metrics:
  duration: "~15min"
  completed: "2026-06-16"
  tasks: 2
  files: 5
---

# Phase 45 Plan 02: 上游产物注入下游 wave（ARTIFACT-02）Summary

新建 `artifact_injection.py`（`acollect_upstream_artifacts` async 沿**直接** `depends_on` 反查上游 `produced_artifacts` + `render_upstream_artifacts_section` 纯文本渲染），在 `AICodingNode` 既有 dispatch 链以 defaulted 参数透传注入。下游容器 prompt（编码 agent 的 global context）由此能消费上游仓（如 wave1 后端）产出的 API 契约。零回归是命门——首发 wave 0 / 无上游 → prompt 与 Phase 44 字节级一致。

## What Shipped

### Task 1 — `artifact_injection.py` 收集 + 渲染 + barrel 导出（commits `8631ab3c` test / `d4bfb228` feat）
- 新建 `server/services/plan_orchestration/artifact_injection.py`（`from __future__`、中文模块 docstring、`__all__` 显式导出）。
- `async def acollect_upstream_artifacts(task) -> list[dict]`：`async for upstream in task.depends_on.all()`（async ORM 安全，仅**直接** `depends_on` 不做传递闭包 per D-06）读 `upstream.produced_artifacts or {}`（JSON 列标量），跳过空 / `available=False` 占位，返回前 `sorted(..., key=lambda a: a.get("repository_id",""))` 保确定性（Open Q2）。
- `def render_upstream_artifacts_section(artifacts) -> str`（纯函数，DB-free）：空 list → `""`（零回归命门，绝不渲染空标题）；否则逐行拼装「# 上游产物 / 上游契约」段——仓名（缺则 repository_id）、分支 / MR（非空才出）、OpenAPI / API 契约文件清单（非空才出标签 + 逐文件）、变更文件数（非 None 才出）。仅渲染白名单结构化字段为 Markdown 数据，绝不内联产物正文（T-45-05）。
- barrel `__init__.py` 追加两函数 import + `__all__`。
- DB-free 渲染单测 5 例：空串零回归 / 单上游契约段 / repository_id 回退 / 多上游各仓契约齐全 / 空契约字段省略标签。

### Task 2 — coding.py dispatch 链 defaulted 透传 + `_build_coding_prompt` 零回归断言（commits `f977be7b` test / `36308309` feat）
- `_build_coding_prompt` 新增 `upstream_artifacts: list[dict] | None = None`：方法内局部 import render 函数，在 `global_context` append 之后、`分支信息` 之前算 `upstream_section`，**仅 `if upstream_section: parts.append(...)`**（守卫逐字对齐既有 `if files_section:`，空段绝不进 parts 否则 `"\n\n---\n\n".join` 多空白分隔 — Pitfall 2）。
- `_run_repo_coding` 新增 defaulted `upstream_artifacts`，调 `_build_coding_prompt` 处增传。
- `_dispatch_wave` 新增 `upstream_artifacts_by_repo: dict[str, list[dict]] | None = None`（默认 None 保首发 wave 0 零回归），循环按 `by_repo.get(repo_id, [])` 透传。
- `_dispatch_next_wave`（唯一注入收集点 D-07）：`tasks_by_repo` 建好后局部 import `acollect_upstream_artifacts`，`for repo_id, task in tasks_by_repo.items()` 收集，整段 `try/except` fail-soft（异常 → `log.warning("coding_upstream_collect_failed")` → 注入空段，绝不让回调 5xx，T-45-08），传 `upstream_artifacts_by_repo`。
- **首发 `_execute_with_branch` 调 `_dispatch_wave` 不改、不传新参**（默认 None → 各仓 [] → 零回归）。
- `test_coding_node.py` 新增 `TestBuildCodingPromptUpstreamInjection` 4 例：不传参逐字 == Phase 44 期望串 / None 与 [] 均逐字一致（防空段漂移）/ 带 upstream 含契约段 + 文件名 / 段位于 global_context 之后分支信息之前。

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/services/plan_orchestration/test_artifact_injection.py -x` | 5 passed |
| `pytest tests/test_coding_node.py -x` | 16 passed, 1 xfailed（既有 12 用例零回归 + 新增 4 注入/零回归用例） |
| `pytest tests/services/plan_orchestration tests/workflows -x` | 526 passed（无回归） |
| `ruff check`（改动源文件） | All checks passed |

## Security Notes

- T-45-05（Tampering / prompt injection）：渲染段仅列结构化白名单字段（仓名/分支/MR/契约文件路径/计数），作为数据呈现而非指令，绝不内联 raw_output 正文。
- T-45-07（Info Disclosure）：注入仅传路径/URL/计数；`_dispatch_next_wave` 收集日志仅记 error 字符串不记产物正文。
- T-45-08（DoS）：收集段 fail-soft（异常 → warning → 注入空段零回归降级），绝不冒泡使容器回调 5xx 重试风暴。
- async ORM 安全：`acollect_upstream_artifacts` 用 `async for ... depends_on.all()` + JSON 列标量，无裸 lazy-M2M。

## Known Stubs

None — 注入段由 collect/render 实际驱动；空产物/无上游走零回归空段（设计降级，非 stub）。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/artifact_injection.py
- FOUND: server/tests/services/plan_orchestration/test_artifact_injection.py
- FOUND commit 8631ab3c / d4bfb228 / f977be7b / 36308309
