---
phase: 104-tool-surface-closure
plan: 01
subsystem: mcp-tools
tags: [mcp, orchestration, delegate, schema-snapshot, unify]
requires:
  - "Phase 102: TOOL_SCHEMA_SNAPSHOT registered==snapshot 集合守卫 + skills 文档守卫"
  - "Phase 94: delegate_process_runtime + create_coding_plan 收敛先例"
provides:
  - "ImproveCodingPlanView 收敛 delegate_process_runtime（携带 feedback 的编排重跑产新 version）"
  - "map_canonical_to_coding_plan 落位 orchestration_delegate.py（104-02 删 planning_service.py 前置）"
  - "improve/create 对外契约定版进 serializer schema 描述"
  - "TOOL_SCHEMA_SNAPSHOT improve/create response 含 session_id/status（create 既有漂移修复）"
  - "全仓 planning_service / plan_orchestration 引用清单（104-02 删缝处置依据）"
affects:
  - "104-02（删 planning_service.py：improve_coding_plan 已无生产调用方）"
  - "104-03（E2E：improve 链路走统一编排）"
tech-stack:
  added: []
  patterns:
    - "MCP view 收敛 delegate 三件套：actor fail-closed 解析 + include_repos 单仓约束 + map_canonical 白名单映射"
    - "requirement_text 多段 markdown 结构（原始需求/最新方案摘要/用户反馈/补充上下文）表达改版语义"
key-files:
  created: []
  modified:
    - server/mcp_tools/serializers.py
    - server/mcp_tools/views.py
    - server/mcp_tools/orchestration_delegate.py
    - server/mcp_tools/planning_service.py
    - server/tests/mcp_tools/test_schema_snapshot.py
    - server/tests/mcp_tools/test_planning_tools.py
    - server/tests/mcp_tools/test_create_coding_plan_delegate.py
    - server/tests/knowledge/test_mcp_artifact_sources.py
decisions:
  - "improve 契约与 create 完全同型：同步 await 至 pause/terminal；partial+session_id 短路（不挂起不超时），写进 serializer docstring"
  - "map_canonical_to_coding_plan 随迁不留转发别名（per D 引用清零）；Repository 走 TYPE_CHECKING 引用"
  - "change_summary 定格式：编排改版 v{n}（status=...）：{feedback[:200]}；risk_delta 中性化 {added:[],reduced:[]}（响应键保留）"
  - "planning_service.build_coding_plan docstring 提及 map_canonical 处改写为不带符号名（满足零残留验证）"
metrics:
  duration: "~18min"
  completed: "2026-07-22"
  tasks: 3
  commits: 3
---

# Phase 104 Plan 01: improve_coding_plan 收敛统一编排 Summary

**One-liner:** improve_coding_plan 从确定性"往 steps 追加一行"假改版收敛到 delegate_process_runtime 编排重跑（feedback 三段块 → 新 McpCodingPlanVersion，响应含 session_id/status），契约定版进 schema 描述，snapshot improve/create 双修，测试全量迁移 fake delegate。

## Task 1: 全仓引用清单 + 契约定版 + snapshot 双修（commit ceb42613）

### 引用清单（UNIFY-03 前置，rg 排除 .planning/.claude）

| 符号 | 命中文件 | 处置去向 |
|------|----------|----------|
| `planning_service` | `server/mcp_tools/views.py` | 本 plan Task 2/3 收敛：import 减为仅 `build_repository_analysis`（UNIFY-02 在 104-02 随迁后归零） |
| `planning_service` | `server/tests/mcp_tools/test_create_coding_plan_delegate.py` | 本 plan Task 2 改 import 自 `orchestration_delegate`（已完成，引用已零） |
| `planning_service` | `server/mcp_tools/planning_service.py`（自身） | 104-02 整文件删除 |
| `plan_orchestration` | `docs/workflows/ai-plan-generation-deprecation.md:10` | 104-02 文案更新为 `process_runtime` |
| `plan_orchestration` | `server/services/plan_orchestration/`（空目录，rg 不命中文件） | 104-02 删除空目录 |

清单外新增引用（Phase 101–103 并发合入检查）：**无**。含 `--hidden` 复查结果一致。

### 契约定版 + snapshot

- `ImproveCodingPlanRequestSerializer` docstring：改版语义 = 携带 feedback 的编排重跑产新 version（current_version+1）；同步 await 至 pause/terminal（DONE→completed、FAILED→failed、research/clarify 在途短路 partial+session_id，不挂起不超时，partial 后凭 session_id 跟进）；context_chunks/max_steps 文档化为 accepted-but-advisory。
- `CreateCodingPlanRequestSerializer` docstring：补同型对照一句。
- `TOOL_SCHEMA_SNAPSHOT`：`create_coding_plan.response` 与 `improve_coding_plan.response` 末尾追加 `session_id`/`status`（create 修复既有漂移——运行时已返回但 snapshot 未收录）；`test_schema_snapshot.py` 整表断言同步镜像。只改 response 键列表、未增删工具名键，registered==snapshot 守卫与 skills 守卫保持绿（5 passed）。

## Task 2: map_canonical_to_coding_plan 随迁（commit 3a3969d7）

- 函数连同完整 docstring 整体剪切到 `orchestration_delegate.py`（`delegate_process_runtime` 之后）；`Repository` 类型走 `TYPE_CHECKING` import（文件已有 `from __future__ import annotations`）；`__all__` 追加导出。
- `views.py` 改从 `.orchestration_delegate` import（与 delegate import 合并一行）；`test_create_coding_plan_delegate.py:283` import 路径同步。
- `planning_service.py` 原函数删除、零残留（`build_coding_plan` docstring 的符号名提及改写为"``orchestration_delegate`` 的 canonical→旧字段映射 helper"）。
- 验证：django.setup import ok；`test_create_coding_plan_delegate.py` 6 passed；`rg map_canonical_to_coding_plan planning_service.py` 零命中。

## Task 3: ImproveCodingPlanView 收敛 + 测试迁移（commit 334930cf）

- `ImproveCodingPlanView.post` 重写，镜像 create 先例：plan/latest 加载与 404 分支不变；actor fail-closed 解析；`requirement_text` 三段 markdown（`## 原始需求` / `## 最新方案摘要（v{latest.version}）`（version 表列 json.dumps 截断 2000 字符）/ `## 用户改版反馈`，context_chunks 折入 `## 补充上下文` 第四段）；`delegate_process_runtime(include_repos=[repository_id], created_by=actor)` 无 feedback 专用参数；model_usage 落 MCP run；`map_canonical_to_coding_plan(requirement=plan.requirement)`（原需求，响应外形兼容）。
- 版本递增语义不变：`next_version = current_version + 1`；`plan_body=content or plan_payload`（回退语义镜像 create）；evidence 从 affected_files 推导；`change_summary=f"编排改版 v{next_version}（status={delegate.status}）：{feedback[:200]}"`；`risk_delta={"added": [], "reduced": []}`。
- ingestion 调度 / `_record_agent_decision` / `_record` 保留；`output_data` 末尾追加 `session_id`/`status`。
- `views.py` 不再 import `improve_coding_plan`（planning_service import 仅剩 `build_repository_analysis`；函数本体留待 104-02 随文件删除）。
- 测试迁移（同 task 闭环）：`test_planning_tools.py` improve 用例 create/improve 双 patch fake delegate（新增共享 `_make_fake_delegate` 构造器），断言更新为 session_id/status/feedback 前缀/risk_delta 键存在；**新增 partial 短路契约用例**（fake partial+空 content → 200、status=partial、session_id 非空、新 version 仍落库、plan_body 回退映射 payload）；`test_mcp_artifact_sources.py::test_trigger_improve_coding_plan` 加 fake delegate，ingestion 触发三元组断言不变。

## 测试结果

- `tests/mcp_tools/test_schema_snapshot.py` + `test_skills_snapshot_guard.py`：5 passed。
- `tests/mcp_tools/test_create_coding_plan_delegate.py`：6 passed。
- `tests/mcp_tools/test_planning_tools.py` + `tests/knowledge/test_mcp_artifact_sources.py`：23 passed。
- 整体 `tests/mcp_tools/ + tests/knowledge/test_mcp_artifact_sources.py`：198 passed，5 failed —— 全部为 `test_work_item_execution.py` 既有 rot（Phase 103-01 `48f98efd` 给 `dispatch_execution` 加 `initiating_user` 参数后测试内 fake 未同步签名），与本 plan 改动无关，已记 `deferred-items.md`。
- ruff check/format：全部通过。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] planning_service.py 残留符号名提及（docstring）**
- **Found during:** Task 2 验证（`! rg -q map_canonical_to_coding_plan` 失败）
- **Issue:** `build_coding_plan` 的 DEPRECATED docstring 提及 `map_canonical_to_coding_plan` 符号名，违反零残留验证
- **Fix:** docstring 措辞改写为不带符号名的等价描述
- **Files modified:** `server/mcp_tools/planning_service.py`
- **Commit:** 3a3969d7

**2. [Rule 3 - Blocking] planning_service.py import 块 ruff I001**
- **Found during:** Task 3 ruff 检查
- **Issue:** Task 2 剪切函数后 import 块遗留空行触发 I001
- **Fix:** `ruff check --fix` 自动修复
- **Files modified:** `server/mcp_tools/planning_service.py`
- **Commit:** 334930cf

### Deferred Issues

- `tests/mcp_tools/test_work_item_execution.py` 5 例既有失败（Phase 103-01 引入的 fake `_dispatch_execution` 签名 rot），范围外未修，详见 `deferred-items.md`。

## 观测自检

- improve 收敛后经编排链路：`mcp_plan_delegate_started/completed`（caller/mcp_tools，duration_ms/status/session_id）由 `delegate_process_runtime` 既有埋点覆盖；`McpToolView._record`（RequestMetric + run 关联）保持不变；无新增 LLM 调用点、无新增召回面；feedback/context_chunks 经 serializer max_length 限幅，编排产物经 map_canonical 显式白名单映射不透传内部键（T-104-01 accept / T-104-02 mitigate / T-104-03 accept 均落实）。

## Known Stubs

无。

## Self-Check: PASSED

- 文件存在：serializers.py / views.py / orchestration_delegate.py / 4 个测试文件均已核实。
- 提交存在：ceb42613 / 3a3969d7 / 334930cf 均在 git log。
- 验证命令：快照守卫 5 passed；delegate 测试 6 passed；planning+artifact 测试 23 passed；views.py 两符号均不再来自 planning_service。
