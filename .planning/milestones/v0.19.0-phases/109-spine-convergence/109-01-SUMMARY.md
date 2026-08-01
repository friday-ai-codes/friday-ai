---
phase: 109-spine-convergence
plan: 01
subsystem: testing
tags: [pytest, django, regression-guardrail, snapshot-testing, mcp, feishu]

# Dependency graph
requires:
  - phase: 105-107
    provides: 编排可稳定跑完并拿到可信路由结果（本 plan 的护栏建立在既有 SPA/MCP 编码链之上）
provides:
  - SPA 执行流四步（选仓 / 配分支 / 确认编码 / 飞书导出）共用同一个 CodingPlan.id 的端到端护栏
  - 非 owner 打 fan-out 与导出端点均 404 的 owner gate 对照断言
  - _create_bridge_session 一次建成 Conversation / chat CodingPlan / CodingSession 三对象的直接断言 + 三表各 +1 计数断言
  - chat @tool create_coding_plan / update_coding_plan 的签名 fixture 字节级漂移守护（SPINE-02 收窄前 baseline）
affects: [109-02, 109-03, 109-04, 109-05, SPINE-01, SPINE-02]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "护栏用例只 mock 最外层 IO 边界（飞书 HTTP 客户端工厂），业务 service 本体真跑"
    - "async service 在 sync pytest 用例内经 asgiref.async_to_sync 直调，配 django_db(transaction=True)"
    - "工具签名 snapshot 沿用 _generate_contract_fixtures + _REGENERATE_HINT 的显式再生成工作流"

key-files:
  created:
    - server/tests/test_spa_coding_chain_e2e.py
    - server/tests/mcp_tools/test_bridge_session.py
    - server/tests/agents/fixtures/create_coding_plan_signature.json
    - server/tests/agents/fixtures/update_coding_plan_signature.json
  modified:
    - server/tests/agents/_generate_contract_fixtures.py
    - server/tests/agents/test_tool_contracts.py

key-decisions:
  - "①② 步的锚点断言改用 GET coding-plan 详情返回的 id + 模型层 recommended_repository_ids 复核：CodingPlanSerializer 未暴露该字段，而本 plan 禁止改生产代码"
  - "导出步 mock 点选在 agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project（client 工厂），导出 service 的 markdown 组装与 feishu_doc_url 回填保持真实执行"
  - "fan-out 显式传 ${repo} 分支模板，既避免用例触发 LLM 分支命名，又能断言模板确实被应用"
  - "签名 baseline 只记录收窄前现状，不提前写 SPINE-02 的正向不变量断言（属 109-05 交付物）"

patterns-established:
  - "不变量护栏：把一次链路里所有步骤用过的锚点收进集合并断言集合大小为 1，锚点被换掉即变红"
  - "零回归锁：对裸 ORM 构造路径直接断言字段形状，未来加列忘带 default 会立即失败"

requirements-completed: [SPINE-01, SPINE-02]

coverage:
  - id: D1
    description: "SPA 执行流四步共用同一 CodingPlan.id 的端到端护栏（含四步锚点集合大小为 1 的不变量断言与 plan 侧反查一致性）"
    requirement: "SPINE-01"
    verification:
      - kind: e2e
        ref: "server/tests/test_spa_coding_chain_e2e.py#test_spa_coding_chain_four_steps_share_one_plan_id"
        status: pass
    human_judgment: false
  - id: D2
    description: "非 owner 打第 ③④ 步均 404（不泄漏 plan 存在性），且越权请求无副作用"
    requirement: "SPINE-01"
    verification:
      - kind: e2e
        ref: "server/tests/test_spa_coding_chain_e2e.py#test_spa_coding_chain_non_owner_gets_404_on_execute_and_export"
        status: pass
    human_judgment: false
  - id: D3
    description: "_create_bridge_session 三对象字段形状直接断言 + 三表各 +1 计数断言（MCP 零回归锁）"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/mcp_tools/test_bridge_session.py#test_create_bridge_session_builds_three_objects"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/mcp_tools/ (211 passed)"
        status: pass
    human_judgment: false
  - id: D4
    description: "chat @tool create_coding_plan / update_coding_plan 签名字节级漂移守护 baseline"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/agents/test_tool_contracts.py#test_create_coding_plan_signature_snapshot"
        status: pass
      - kind: unit
        ref: "server/tests/agents/test_tool_contracts.py#test_update_coding_plan_signature_snapshot"
        status: pass
    human_judgment: false

# Metrics
duration: 24min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 01: 双脊柱合流回归护栏 Summary

**SPA 四步同一 plan_id 端到端护栏 + MCP 桥接三对象直接断言 + 两个 chat `@tool` 的签名 baseline，全部在任何 schema 改动之前先绿**

## Performance

- **Duration:** ~24 min
- **Tasks:** 3
- **Files created:** 4
- **Files modified:** 2
- **生产代码改动:** 0（`git diff --stat` 全部落在 `server/tests/` 之下）

## Accomplishments

- 补上 Wave 0 最大的护栏缺口：SPA 执行流四步此前各有独立测试，但没有任何一条锁住「四步都还挂在同一个 `CodingPlan.id` 上」。现在这条不变量由 `test_spa_coding_chain_four_steps_share_one_plan_id` 显式断言（四步锚点集合大小为 1 + plan 侧反查 session 数一致）。
- 护栏的 mock 面收得极窄：只把飞书 client 工厂换成假 client，`create_sessions_for_plan` 与导出 service 本体（markdown 组装、`feishu_doc_url` 回填）全部真跑，避免护栏被 mock 掏空。
- owner gate 对照用例锁住「越权与不存在同体」：非 owner 打 fan-out 与导出端点均 404，且飞书 client 根本没被构造、数据库无副作用。
- MCP 侧补上零回归直接锁：`_create_bridge_session` 用裸 ORM 一次建成 Conversation / chat CodingPlan / CodingSession，此前的 e2e 只断言了 CodingSession。现在三对象各有 ≥3 条字段断言，外加三张表各恰好 +1 的计数断言 —— 后续给 `CodingPlan` 加列忘带 `default` 时会立刻变红。
- 两个 chat `@tool`（create / update）此前零漂移守护，现已落 SPINE-02 收窄前的签名 baseline，任何入参增删都会显式变红并走 `_REGENERATE_HINT` 的再生成 + review 流程。

## Task Commits

1. **Task 1: SPA 四步同一 plan_id 端到端护栏** — `3a99e377` (test)
2. **Task 2: MCP 桥接三对象直接断言** — `be546558` (test)
3. **Task 3: chat @tool 创作入参签名漂移守护基线** — `7c09d1bd` (test)

## Files Created/Modified

- `server/tests/test_spa_coding_chain_e2e.py` — SPA ①②③④ 四步端到端护栏 + owner gate 对照用例（2 用例）
- `server/tests/mcp_tools/test_bridge_session.py` — `_create_bridge_session` 三对象字段形状 + 计数断言（1 用例）
- `server/tests/agents/fixtures/create_coding_plan_signature.json` — `create_coding_plan` 收窄前签名 baseline（含 `tech_plan` / `affected_files`）
- `server/tests/agents/fixtures/update_coding_plan_signature.json` — `update_coding_plan` 收窄前签名 baseline（含 `tech_plan` / `affected_files`）
- `server/tests/agents/_generate_contract_fixtures.py` — `main()` 追加两个签名的产出分支
- `server/tests/agents/test_tool_contracts.py` — 追加两个模块常量与两个 snapshot 用例（现共 13 个）

## Decisions Made

- **①② 步的断言口径调整**：计划原文要求断言 `GET /api/chat/coding-plans/{plan_id}/` 「`recommended_repository_ids` 原样透出」，但 `CodingPlanSerializer` 并不暴露该字段（前端经 chat 工具输出而非该 REST 端点拿到它），而本 plan 明令不改生产代码。改为断言详情端点返回 200 且 `id == plan_id`（这才是四步真正共用的锚点），并在模型层复核 `recommended_repository_ids` 未被链路改写。护栏意图（第 ①② 步以同一个 plan 为锚点）完整保留。
- **导出步的 mock 点**：选在 `agents.tools.feishu_doc_tools.create_feishu_doc_client_for_project`（client 工厂）。这是 `--disable-socket` 下唯一必须挡掉的触网点，导出 service 的其余逻辑保持真实路径。
- **分支模板显式传 `${repo}`**：既避开 `agenerate_default_branch_name` 的 LLM 调用，又能断言模板确实按仓渲染（而不是回退到共享分支名）。
- **不提前写正向不变量**：`"tech_plan" not in parameters["properties"]` 这类收窄后断言留给 plan 109-05，本 plan 只交付「漂移可见」。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task 1 步骤 2 的断言目标与生产代码实际不符**
- **Found during:** Task 1（SPA 四步端到端护栏）
- **Issue:** 计划要求断言 `GET /api/chat/coding-plans/{plan_id}/` 响应体里的 `recommended_repository_ids`，但 `chat/serializers.py::CodingPlanSerializer` 并未声明该字段（只有 id / conversation_id / title / tech_plan / affected_files / feishu_doc_* / 时间戳）。照原文写会直接 KeyError，而修复方式（给序列化器加字段）属于生产代码改动，被本 plan 明确禁止。
- **Fix:** 把 ①② 步的锚点断言改为「详情端点 200 且 `body["id"] == str(plan_id)`」，并额外从模型层断言 `recommended_repository_ids` 未被改写；注释写明该字段不经 REST 详情端点透出。
- **Files modified:** `server/tests/test_spa_coding_chain_e2e.py`
- **Verification:** `cd server && uv run pytest tests/test_spa_coding_chain_e2e.py -x` 全绿（2 passed, 16s）
- **Committed in:** `3a99e377`（Task 1 提交）

---

**Total deviations:** 1 auto-fixed（1 blocking）
**Impact on plan:** 断言口径微调，护栏覆盖面与验收意图不变；无生产代码改动，无 scope creep。

## Issues Encountered

None —— 三个 task 均一次通过，无需 debug 循环。

## Verification Results

| 命令 | 结果 |
|---|---|
| `uv run pytest tests/test_spa_coding_chain_e2e.py -x` | 2 passed（16s，远低于 60s 上限） |
| `uv run pytest tests/mcp_tools/test_bridge_session.py tests/mcp_tools/test_execution_tools.py tests/mcp_tools/test_create_coding_plan_delegate.py -x` | 12 passed |
| `uv run pytest tests/agents/test_tool_contracts.py -x` | 13 passed |
| `uv run pytest tests/mcp_tools/ -q` | 211 passed（MCP 侧零回归） |
| `uv run pytest tests/test_spa_coding_chain_e2e.py tests/mcp_tools/test_bridge_session.py tests/agents/test_tool_contracts.py tests/test_coding_plans_sessions_api.py tests/test_coding_plan_export_api.py -q` | 33 passed |
| `uv run ruff check`（三个新增/修改文件） | All checks passed |
| `git diff --stat HEAD~3 HEAD` | 6 files changed, 549 insertions(+)，全部在 `server/tests/` 之下 |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-01-01（Information Disclosure） | `test_spa_coding_chain_non_owner_gets_404_on_execute_and_export` 断言 fan-out 与导出端点均 404（不是 403），并断言无 session 副作用 |
| T-109-01-02（护栏被 mock 掉） | 只 patch 飞书 client 工厂；`create_sessions_for_plan` 与 `export_coding_plan_to_feishu` 本体真跑，文件 docstring 写明该边界 |
| T-109-01-03（工具签名静默回退） | 两份 fixture 字节 diff + 失败消息带 `_REGENERATE_HINT`，契约变更必须留下一次可 review 的提交 |
| T-109-01-SC（供应链） | 零新增依赖，未执行任何包管理器安装命令 |

## Observability

本 plan 只新增测试代码，未新增 API 入口 / LLM 调用 / 召回 / 队列任务 / webhook，无埋点义务；被测生产路径（`create_sessions_for_plan`、`export_coding_plan_to_feishu`、`_create_bridge_session`）的既有 structlog 事件未改动。

## Known Stubs

None —— 无占位实现、无空数据源。

## User Setup Required

None —— 无外部服务配置需求。

## Next Phase Readiness

- Wave 0 护栏已全绿，SPINE-01 的投影 service 与 SPINE-02 的 schema 收窄可以安全动刀：任何打断「四步共用同一 plan_id」的改动会在 `test_spa_coding_chain_e2e.py` 变红。
- 109-02 可在 `tests/mcp_tools/test_bridge_session.py` 内追加新字段（`provenance` / `source_artifact_version_id`）的默认值断言，文件结构已为此预留说明。
- 109-05 做 schema 收窄时，两个签名 snapshot 会按设计变红 —— 按 `_REGENERATE_HINT` 再生成 fixture 并 review diff 即为契约升级；正向不变量断言（创作入参不存在于 schema）由 109-05 补。

## Self-Check: PASSED

4 个交付文件全部存在于磁盘；3 个 task commit（`3a99e377` / `be546558` / `7c09d1bd`）均可在 git 历史中检得。

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
