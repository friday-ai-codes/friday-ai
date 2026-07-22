---
phase: 103-container-integration
plan: "04"
subsystem: server
tags: [project-context, dispatch, workflow, agent-04]
requires:
  - "103-01（_resolve_dispatch_user / dispatch_user 线传，本 plan 直接消费）"
provides:
  - "services/project_context_packer.py 共享 helper：prepend_project_context / aresolve_project_for_repo_branch / apack_dispatch_context"
  - "workflow _dispatch_wave 按 (project, branch) 解析一次项目上下文逐仓复用"
  - "_run_repo_coding prompt prepend + env_FRIDAY_TASK_PROJECT_CONTEXT 注入（与 chat 路径一致）"
affects: [workflow-coding-dispatch, chat-coding-dispatch, container-agent-context]
tech-stack:
  added: []
  patterns: ["派发链共享 helper 落 services 层（workflow 不 import chat）", "wave 层解析一次逐仓复用（project 维度去重缓存）", "fail-soft 空串 no-op"]
key-files:
  created:
    - server/tests/workflows/test_coding_dispatch_project_context.py
  modified:
    - server/services/project_context_packer.py
    - server/chat/coding_session_service.py
    - server/workflows/nodes/ai/coding.py
decisions:
  - "共享 helper 落 packer 模块本体（召回单一入口旁），docstring 标注勿在各自模块复制实现"
  - "apack_dispatch_context 收敛 None 守门 + strip + redact + fail-soft，chat 保留自己的外层 try/except（coding_session_id/component 归因不丢）"
  - "wave 去重按 str(project.id)——branch 在单次 wave 内恒定，project 维度去重即达成 (project, branch) 一次解析"
  - "project/dispatch_user 任一 None 直接跳过召回（不缓存空结果调用），复用测试 mock 断言 await_count==1 干净"
metrics:
  duration: "~11 分钟"
  completed: "2026-07-22"
---

# Phase 103 Plan 04: 工作流上下文对齐 Summary

**一句话**：chat 侧 `_prepend_project_context` / `_lookup_project_by_branch` 上提为 `services/project_context_packer.py` 三个共享 helper（chat 纯重构改引用，workflow 直接用不 import chat），`_dispatch_wave` 派发前按 (project, branch) 解析一次 `pack_project_context`（ProjectBranch 反查优先 + work_item 关联 fallback，user=triggered_by），逐仓复用传入 `_run_repo_coding` 做 prompt prepend + `env_FRIDAY_TASK_PROJECT_CONTEXT` 注入——工作流派发的编码容器与 Chat 派发一样"一上来即有项目上下文"。

## 完成任务

| Task | 名称 | Commit | 关键文件 |
| ---- | ---- | ------ | -------- |
| 1 | helper 上提 packer + chat 改引用（纯重构零行为变化） | `81956173` | services/project_context_packer.py, chat/coding_session_service.py |
| 2 | workflow _dispatch_wave 解析一次逐仓复用 + prompt/env 注入 + 测试 | `113ac520` | workflows/nodes/ai/coding.py, tests/workflows/test_coding_dispatch_project_context.py |

## 实现要点

- **共享 helper**（packer 模块内，`__all__` 同步导出）：
  - `prepend_project_context(prompt, context)`：从 chat 逐字迁移（空值短路语义不变）。
  - `aresolve_project_for_repo_branch(*, repository_id, branch_name)`：sync_to_async 包装保持；无分支名/无绑定 → None；多绑定取首个 fail-soft。
  - `apack_dispatch_context(project, user, *, query, conversation_id)`：project/user 任一 None → ""；`pack_project_context` → strip → `redact_secrets_in_text`；全程 try/except fail-soft 返回 ""，warning 事件 `dispatch_project_context_failed`（error_type + category="sampling"，component 由调用方 bind）。
- **chat 纯重构**：私有 helper 零残留（rg 验证）；`_resolve_project_context_for_dispatch` 保留 bound_project 优先 → 分支反查 fallback 结构与外层 fail-soft（coding_session_id/component="chat" 归因日志不变）；dispatch_coding_task 注入两件套改调共享 `prepend_project_context`。coding_commit 短路、召回空不注入全部保持。
- **workflow 接入**：新增 `_resolve_wave_project_contexts`——对每仓 ProjectBranch 反查，None 时按 `config["work_item_id"]` 经 `ProjectWorkItemLink.objects.filter(work_item__work_item_id=...).select_related("project").afirst()` fallback（lazy import 防循环）；按 `str(project.id)` 缓存 `apack_dispatch_context(project, dispatch_user, query=branch_name)` 结果逐仓复用；单仓异常 fail-soft 空串（`wave_project_context_failed` warning），绝不阻断 dispatch。`_dispatch_wave` 在 openspec gate 后、构建 coding_tasks 前调用；`_run_repo_coding` 新增 `project_context: str = ""` 形参（默认空 → 非 wave/legacy 调用路径零回归），非空时 prompt prepend + metadata `env_FRIDAY_TASK_PROJECT_CONTEXT`（镜像 chat 两件套）。两个 `_dispatch_wave` 调用方（execute 首发 + aadvance 续 wave）无需改动——解析在内部完成。
- **测试**（新文件 6 例，复刻 test_remote_tool_dispatch.py 捕获 fixture 套）：绑定命中双注入 + 召回实参断言（project/user/query）、work_item fallback、同 project 两仓 `await_count==1` 复用断言、无 project / 无 dispatch_user / packer 抛异常三例 fail-soft（metadata 无键 + prompt 以 `# 项目背景` 开头逐字一致）。

## 验收结果

- `uv run pytest tests/workflows/test_coding_dispatch_project_context.py tests/test_remote_tool_dispatch.py tests/chat/test_coding_dispatch_context.py -q` → **16 passed** ✅
- `uv run pytest tests/chat -q` → **99 passed**（chat 零回归）✅
- 全部触及 `_dispatch_wave`/`_run_repo_coding` 的测试（exclusion_env / remote_tool / coding_node / base_url_passthrough / openspec_gate / coding_wave）→ **54 passed, 1 xfailed**（xfail 既有）✅
- `rg "import chat|from chat" workflows/nodes/ai/coding.py` 零命中（workflow 不 import chat）✅
- `rg "_prepend_project_context|_lookup_project_by_branch" chat/coding_session_service.py` 零残留 ✅
- 召回仍走 packer 单一入口（pack_project_context + RetrievalTrace 天然继承，无绕过）✅
- ruff check 全过；新增/改动段格式达标 ✅

## Deviations from Plan

**1. [范围外记录] 两个既有文件存在预存 ruff format 漂移**
- `ruff format --check` 对 `project_context_packer.py` / `coding_session_service.py` 报 would-reformat，经 `git show HEAD:` 对照确认漂移全部预存于本 plan 未触碰的既有代码段（含一处预存 I001 import 排序）；本 plan 新增段格式达标。
- 按 scope boundary 不顺手修，记录待后续统一 format。

其余按计划原样执行（含 apack_dispatch_context "project/user 任一 None → ''" 的计划定版语义）。

## Threat Model 落实

| Threat | Mitigation | 落点 |
|--------|------------|------|
| T-103-13 上下文携密钥进容器 | apack_dispatch_context 内 redact_secrets_in_text 强制（迁移自 chat 既有防线） | packer helper + chat 既有 test_recalled_context_is_redacted 覆盖 |
| T-103-14 非成员越权召回 | pack_project_context 内置 visibility fail-closed（helper 不绕过，单一召回入口） | packer + chat 既有 test_members_only_non_member_fail_closed |
| T-103-15 召回失败阻断派发 | 全链 fail-soft 空串 no-op + 专项测试 | _resolve_wave_project_contexts + test_packer_exception_fail_soft_dispatch_succeeds |

## Known Stubs

无。

## Self-Check: PASSED

- server/tests/workflows/test_coding_dispatch_project_context.py ✅ 三个共享 helper 可从 services 层 import ✅
- Commits `81956173`、`113ac520` 均在 git log ✅
