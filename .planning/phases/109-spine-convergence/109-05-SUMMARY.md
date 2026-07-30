---
phase: 109-spine-convergence
plan: 05
subsystem: api
tags: [django, structlog, pytest, llm-tools, schema-narrowing, authorization, projection, chat]

# Dependency graph
requires:
  - phase: 109-01
    provides: tests/agents/test_tool_contracts.py 的函数签名 snapshot 与 _REGENERATE_HINT 再生成流程（本 plan 的契约升级走这条既有工作流）
  - phase: 109-02
    provides: CodingPlan.provenance / source_artifact_version_id 两列 + uniq_codingplan_source_artifact_version 无条件唯一约束（arebind 的 fail-closed 依赖它真的存在）
  - phase: 109-03
    provides: PlanProjectionService.aproject / map_merged_plan_to_coding_plan / 投影端点（本 plan 让 chat @tool 成为同一 service 的第二个调用方）
  - phase: 109-04
    provides: 编排产出「进入编码」前端入口（SPA 因此不会在工具收窄后短暂失去唯一编码入口）
provides:
  - create_coding_plan / update_coding_plan 两个 @tool 的 schema 与函数签名删除 tech_plan / affected_files，新增必填 artifact_version_id
  - create_coding_plan 落库改走 PlanProjectionService（工具与 HTTP 端点共用唯一写入口）
  - PlanProjectionService.arebind —— 把既有 CodingPlan 重新指向新方案版本（re-bind 而非任意改写）
  - 归属判定下移进 service：aproject / arebind 均必填无默认值 actor_user_id，不匹配抛 artifact_version_forbidden（判定早于渲染正文）
  - 机器码 artifact_version_already_projected（re-bind 目标版本被占用，两层 fail-closed）
  - 观测事件 coding_plan_authoring_attempt_rejected（category=caller / component=agents）
  - tests/agents/test_coding_tools_schema_guard.py —— 正向不变量 + properties 键集合枚举双重守护
  - 两份签名 fixture 的契约升级（SPINE-02 的 review 证据）
  - conversation_service._get_tool_names 补齐编排工具 + 两份白名单一致性断言
affects: [109-06, SPINE-02, RELY-01, Phase-110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "能力边界在 schema 层收紧，prompt 只是配套文案：schema 是 LLM 可见能力的唯一定义处，「删入参」才是达成手段，prompt 改写只防止模型被引导去构造注定失败的调用"
    - "归属判定下移进 service 而非留在各调用方：判定留在调用方意味着每个新调用方都要重新实现一遍，而工具路径已经漏了一次；视图侧 gate 降级为纵深"
    - "必填无默认值的 actor_user_id：带默认值（含 \"system\"）会让漏传的调用方静默获得哨兵身份从而绕过判定 —— 那正是本 blocker 的成因形状"
    - "归属判定必须早于渲染正文：arebind 会把来源版本 content 渲染成 tech_plan 写进调用方自己的 plan，判定晚一步即构成跨会话读取他人完整方案正文"
    - "唯一约束的两层 fail-closed：async 前置查询（不依赖后端能力）+ IntegrityError 兜底（依赖 DB 约束真的存在），缺任一层都会在某类后端上静默改写他人投影"
    - "枚举式键集合相等断言优于具名否定断言：只防两个具体名字挡不住「换个名字的正文入参」，键集合白名单让任何新增入参都必须先显式登记"

key-files:
  created:
    - server/tests/agents/test_coding_tools_schema_guard.py
  modified:
    - server/agents/tools/coding_tools.py
    - server/chat/plan_projection_service.py
    - server/chat/views.py
    - server/chat/conversation_service.py
    - server/chat/config.py
    - server/agents/intent_router.py
    - server/agents/tools/repository_relevance.py
    - server/agents/tools/chat_tools.py
    - server/feishu/cards/bot_cards.py
    - server/tests/agents/fixtures/create_coding_plan_signature.json
    - server/tests/agents/fixtures/update_coding_plan_signature.json
    - server/tests/test_coding_tools.py
    - server/tests/test_plan_projection_service.py
    - server/tests/test_plan_projection_api.py
    - server/tests/test_chat_tools.py
    - server/tests/test_conversation_service_fragment_extraction.py
    - server/tests/test_conversation_service_prompt_fragments.py
    - server/tests/test_project_context_line.py

key-decisions:
  - "两个门一起收窄（裁决 D-1）：只收 create 会让模型改走 update 把任意正文写进既有方案，等于没收窄"
  - "update_coding_plan 的归属主体只取请求上下文，绝不退回「被改写 plan 的会话创建者」：plan 定位入参由模型提供，退回等于让攻击者通过挑选他人 plan_id 自选身份"
  - "create_coding_plan 允许在无请求上下文时退回 conversation.created_by_id：该 conversation_id 由 chat_runner 闭包注入、模型改不了，是真实身份而非哨兵；两个来源都取不到时拒绝，不退化为 system 放行"
  - "recommended 解析结果为空时保留投影聚合出的仓库列表（新 recommended_source=projected），不用空列表清空：编排来源自带目标仓，清空等于把 fan-out 目标抹掉"
  - "执行半边完整保留：repository_id / recommended_repository_ids 两个入参与返回 payload 的 10 键一个不动，SPINE-02 只砍创作半边"
  - "conversation_service._get_tool_names 即使在生产代码中无调用方也补齐编排工具：留一份「挂 create 不挂来源产出方」的清单就是留一条随时可能生效的死路"

patterns-established:
  - "契约升级 = 一次显式提交：签名 snapshot 按设计变红后经 _generate_contract_fixtures 再生成，diff 必须只含预期收窄（本次逐字核对：仅删 tech_plan / affected_files、增 artifact_version_id，其余键 annotation/default/kind 未变）"
  - "跨会话拒绝要断言「没写进去」而不只是「抛了异常」：arebind 用例直接断言用户 B 的 plan.tech_plan 未被写入用户 A 的标题与文件路径"
  - "错误文本只回显机器码与固定引导语：越权/无来源的 ToolResult.error 不含他人方案正文的任何片段（有断言锁）"
  - "视图 gate 被绕过时 service 判定仍生效：端点用例以 mock 放行视图侧 owner gate，证明真正的门在 service 且同形映射 404"

requirements-completed: [SPINE-02]

coverage:
  - id: D1
    description: "两个 @tool 的 schema 与函数签名均不存在 tech_plan / affected_files，artifact_version_id 必填 —— 模型结构上无法徒手编写方案正文"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/agents/test_coding_tools_schema_guard.py（正向不变量 + 键集合枚举 + 函数签名断言，13 用例）"
        status: pass
      - kind: unit
        ref: "server/tests/agents/test_tool_contracts.py（两份签名 snapshot 契约升级后全绿）"
        status: pass
    human_judgment: false
  - id: D2
    description: "落库统一走 PlanProjectionService（唯一写入口），无来源 / 非法来源 / 跨会话尝试一律 fail-closed 并留痕 coding_plan_authoring_attempt_rejected"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_tools.py -k reject（5 用例：空串 / 未知 UUID / content 非 dict / 跨会话 / update 无来源）"
        status: pass
    human_judgment: false
  - id: D3
    description: "归属判定在 service 内，工具与 HTTP 端点共享同一道门：跨会话投影 / re-bind 一律 artifact_version_forbidden，他人正文既不写入也不回显"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py -k forbidden（5 用例，含「用户 B 的 plan.tech_plan 未被写入用户 A 正文」与 actor_user_id 无默认值的签名断言）"
        status: pass
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_service_gate_still_returns_404_when_view_gate_bypassed"
        status: pass
    human_judgment: false
  - id: D4
    description: "update_coding_plan 收窄为 re-bind：换来源即换正文；目标版本被占用时两边都不改写（artifact_version_already_projected）"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_tools.py -k update（7 用例）+ tests/test_plan_projection_service.py::test_rebind_* （3 用例）"
        status: pass
    human_judgment: false
  - id: D5
    description: "执行半边零回归：返回 payload 10 键键形冻结、推荐仓库四种来源（+projected）不变、MCP 两条链与 SPA 四步护栏全绿"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_tools.py::TestCreateCodingPlan::test_create_coding_plan_payload_key_set_is_frozen"
        status: pass
      - kind: e2e
        ref: "cd server && uv run pytest tests/mcp_tools tests/test_spa_coding_chain_e2e.py tests/agents -q（435 passed）"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/test_coding_plans_sessions_api.py tests/test_coding_plan_export_api.py tests/test_plan_projection_api.py -q"
        status: pass
    human_judgment: false
  - id: D6
    description: "两份工具白名单一致：凡挂载 create_coding_plan 的清单必须同时挂 start_plan_research 与 start_feature_solution（模型不会陷入「被要求带来源却拿不到来源」）"
    requirement: "SPINE-02"
    verification:
      - kind: unit
        ref: "server/tests/test_chat_tools.py::test_indexed_tool_names_mount_orchestration_with_create_coding_plan / test_conversation_service_tool_names_mount_orchestration_with_create"
        status: pass
    human_judgment: false
  - id: D7
    description: "prompt 与 8 处文案改为「投影而非撰写」口径，且不再出现教模型撰写正文的表述"
    verification:
      - kind: unit
        ref: "server/tests/test_conversation_service_prompt_fragments.py::test_coding_guidance_no_longer_teaches_model_to_author_plan_body（负向断言：分步实现步骤 不出现）"
        status: pass
      - kind: unit
        ref: "server/tests/test_conversation_service_fragment_extraction.py / test_project_context_line.py（文案断言随新口径升级）"
        status: pass
    human_judgment: false
  - id: D8
    description: "对话侧真实观感：模型在收窄后的工具集下确实先走编排、再点投影，不会反复尝试构造正文"
    verification: []
    human_judgment: true
    rationale: "prompt 对 LLM 行为的实际影响只能在真实对话里观察；测试只能锁文案与 schema，锁不住模型的实际选择路径"

# Metrics
duration: 45min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 05: 双脊柱合流 —— 两个门一起收窄 Summary

**在 schema 层删掉 `tech_plan` / `affected_files` 两个创作入参、改为必填 `artifact_version_id`，落库统一走 `PlanProjectionService` 并把归属判定下移进 service，同时补上让这条性质不可静默回退的正向不变量 + 键集合枚举双重守护。**

## Performance

- **Duration:** 约 45 min（含中断后接手）
- **Started:** 2026-07-30T07:40:11Z（Task 1 提交时刻）
- **Completed:** 2026-07-30T08:32:00Z
- **Tasks:** 3
- **Files modified:** 19（1 新建 + 18 修改）

## Accomplishments

- **SPINE-02 达成（结构上不可能）**：`create_coding_plan` / `update_coding_plan` 的 `parameters.properties` 与函数签名均不再存在 `tech_plan` / `affected_files`；`artifact_version_id` 必填。`create` 的 `required` 恰为 `{space_id, conversation_id, artifact_version_id}`，`update` 的 `required` 为 `{artifact_version_id}`（plan 定位仍在 handler 内二选一）。
- **唯一写入口**：`create_coding_plan` 落库改调 `PlanProjectionService().aproject(...)`，不再调 `aget_or_create_for_conversation`；`update_coding_plan` 语义改为 re-bind，走新增的 `PlanProjectionService.arebind`。已无调用方的 `_normalize_affected_files` 一并删除。
- **归属判定下移进 service**：`aproject` / `arebind` 的 `actor_user_id` 必填且**无默认值**，判定在渲染 / 写入任何正文之前，不匹配抛 `artifact_version_forbidden`（措辞与「不存在」一致，不泄漏存在性）。视图侧 owner gate 保留为第二道纵深，`artifact_version_forbidden` 与 `artifact_version_not_found` 同形映射 404。
- **双重守护防回退**：新建 `tests/agents/test_coding_tools_schema_guard.py`（具名否定 + `properties` 键集合枚举相等 + 函数签名三层断言，13 用例），两份签名 fixture 完成契约升级作为 review 证据。
- **执行半边零回归**：返回 payload 的 10 键有键集合冻结断言；推荐仓库解析四种来源保留并新增 `projected` 分支（解析为空时不清空投影聚合出的目标仓）；MCP 两条链与 SPA 四步护栏全绿（`tests/mcp_tools` + `tests/test_spa_coding_chain_e2e.py` + `tests/agents` = 435 passed）。
- **消灭死路**：`conversation_service._get_tool_names.full_tools` 补上两个编排工具（计数 9 → 11），并把「挂 create ⇒ 必挂两个编排工具」变成对两份清单各一次的断言。

## Task Commits

1. **Task 1: 两个门一起收窄 —— schema 与实现改为只接受编排来源** — `61fc5e30` (feat)
2. **Task 2: SPINE-02 正向不变量守护 + 签名 fixture 契约升级 + 工具单测重写** — `b7d82000` (test)
3. **Task 3: 11 处影响面同步 —— prompt / 两份白名单 / 文案 / 断言测试** — `5e01578f` (refactor)

## 签名 snapshot diff review 结论

两份 fixture 的 diff **只反映预期的 schema 收窄，未夹带任何意外字段变化**（逐字核对通过）：

`create_coding_plan_signature.json`
- 删除：`affected_files`（`list[dict[str, str]]`）、`tech_plan`（`str`）
- 新增：`artifact_version_id`（`str`，无默认值 → `default: null`，`POSITIONAL_OR_KEYWORD`）
- 未变：`space_id` / `conversation_id`（`str`，无默认）、`repository_id`（`str`，`''`）、`recommended_repository_ids`（`list[str] | None`，`None`）—— 三键的 `annotation` / `default` / `kind` 逐字未动

`update_coding_plan_signature.json`
- 删除：`affected_files`、`tech_plan`
- 新增：`artifact_version_id`（`str`，无默认）
- 未变：`coding_plan_id` / `session_id`（`str`，`''`）

再生成可复现：重跑 `DJANGO_SETTINGS_MODULE=friday.settings uv run python -m tests.agents._generate_contract_fixtures` 后 `git diff --stat` 与提交前完全一致（4 insertions / 14 deletions），说明 fixture 内容由签名唯一决定、无手工编辑痕迹。`_generate_contract_fixtures.py` 本身无需改动。

## Files Created/Modified

**新建**
- `server/tests/agents/test_coding_tools_schema_guard.py` — SPINE-02 正向不变量守护（含文件 docstring 说明「锁的是结构上不可能，而非 prompt 里不建议」与三层守护的分工）

**后端实现**
- `server/agents/tools/coding_tools.py` — 两个 `@tool` 收窄；`_log_authoring_rejected` / `_context_user_id` 两个 helper；落库走投影 service；删 `_normalize_affected_files`
- `server/chat/plan_projection_service.py` — 新增 `arebind` + `_assert_owner`；`aproject` 签名收紧为必填 `actor_user_id`；新增两个机器码常量
- `server/chat/views.py` — 端点传 `actor_user_id=`；注释写明「真正的门在 service，这里是第二道」

**prompt / 文案（8 处）**
- `server/chat/conversation_service.py` — `_CODING_GUIDANCE` + per-turn hint 改「先编排产出方案版本，再投影」；`_get_tool_names.full_tools` 补编排工具
- `server/chat/config.py` / `server/agents/intent_router.py` / `server/agents/tools/repository_relevance.py` / `server/agents/tools/chat_tools.py` — 四处描述统一为「投影而非生成方案」
- `server/feishu/cards/bot_cards.py` — `📝 生成编码方案` → `📝 进入编码方案`；`update` 同步改为 `✏️ 切换编码方案来源`

**测试**
- `server/tests/test_coding_tools.py` — 全量重写为新签名（34 用例，含 `-k reject` 5 条与 `-k update` 7 条）
- `server/tests/test_plan_projection_service.py` — 5 组既有用例完成 `actor_user_id` 迁移（Task 1）+ `forbidden` / `rebind` 两组新增（Task 2）
- `server/tests/test_plan_projection_api.py` — 新增「视图 gate 被绕过时 service 判定仍返回同形 404」
- `server/tests/test_chat_tools.py` — 白名单一致性断言 ×2 + 硬编码计数 9 → 11
- `server/tests/test_conversation_service_fragment_extraction.py` / `test_conversation_service_prompt_fragments.py` / `test_project_context_line.py` — 4 处文案断言升级（含「不再教模型撰写正文」负向断言）

## Decisions Made

- **`update_coding_plan` 的归属主体只取请求上下文**：`coding_plan_id` / `session_id` 由模型提供，若退回「被改写 plan 的会话创建者」，攻击者可通过挑选他人 `plan_id` 自选身份（EoP）。取不到即拒绝并留痕。
- **`create_coding_plan` 可退回 `conversation.created_by_id`**：`conversation_id` 由 chat_runner 从模型可见入参剔除后闭包注入，模型改不了它，是真实身份而非哨兵。两个来源都取不到时拒绝，绝不退化为 `"system"` 放行。
- **新增 `recommended_source="projected"`**：推荐仓库解析为空时保留投影从 `execution_plan[].repository_id` 聚合的值。编排来源自带目标仓，用空列表覆盖等于把 fan-out 目标抹掉。
- **`test_coding_tools.py` 全量重写而非逐条改参**：所有 `TestCreateCodingPlan` 用例都需要一条完整来源链（WorkItem → Artifact → ArtifactVersion + 带 `conversation` 的 ConvergenceSession），造数形状变了，逐条补参会留下互相矛盾的 fixture。逐条覆盖意图（不产 session、三段校验、四种推荐来源、dual-id 兼容键）在重写后逐一保留并有对应用例。
- **不改 `mcp/`、`server/mcp_tools/` 与文档**：`rg -n "create_coding_plan" skills task docs mcp` 的 6 处命中经逐处核对**全部指实体 B**（MCP HTTP 端点，入参为 `repository_id` / `requirement` / `analysis_id` / `context_chunks`），与本 plan 收窄的 chat `@tool`（实体 A）同名不同物 ⇒ 按 Task 3 D 节如实记录该核对结论，本 plan 不改这些文档，也不需重新发 npm 包。

## Deviations from Plan

### 主动补强（超出 plan 字面要求，均为验收强度而非新增范围）

**1. [Rule 2 - Missing Critical] `_context_user_id()` 显式拒绝 `"system"` 哨兵身份**
- **Found during:** Task 1（归属判定下移）
- **Issue:** plan 要求「取不到时不得退化为哨兵值放行」，但未规定若上下文里**本身**写着 `"system"` 该怎么办 —— 后台任务上下文泄漏进工具调用时会以哨兵身份通过判定。
- **Fix:** `_context_user_id()` 把 `""` 与 `"system"` 一并视同取不到；`_assert_owner` 对空串 / 空白串同样拒绝。
- **Verification:** `test_forbidden_actor_cannot_be_sentinel_or_blank`（`""` / `"   "` / `"system"` 三种取值均抛 `artifact_version_forbidden`）。
- **Committed in:** `61fc5e30` / `b7d82000`

**2. [Rule 2 - Missing Critical] 端点侧补「视图 gate 被绕过」用例**
- **Found during:** Task 2 D 节
- **Issue:** plan 要求的「非 owner → 404」用例 109-03 已有，但它命中的是**视图侧** owner gate，无法证明 Task 1 C 节交付的 service 内判定真的生效 —— 视图 gate 若被后人删掉，该用例仍会绿。
- **Fix:** 新增用例以 mock 放行视图侧只读解析，让请求真的进到 `aproject`，断言仍返回同形 404、响应体无正文、零写入。
- **Files modified:** `server/tests/test_plan_projection_api.py`
- **Committed in:** `b7d82000`

**3. [Rule 1 - Bug] `update_coding_plan` 的中文标签一并更新**
- **Found during:** Task 3 B
- **Issue:** plan 只点名改 `create_coding_plan` 的标签，但 `update` 的 `✏️ 更新编码方案` 在收窄后同样口径错误（它不再「更新方案内容」，而是切换来源版本）。
- **Fix:** 改为 `✏️ 切换编码方案来源`。
- **Committed in:** `5e01578f`

**4. 新增用例：re-bind 到自己已绑定的版本不被唯一约束前置查询误伤**
- **Found during:** Task 1 B（`arebind` 的 `exclude(pk=plan.pk)`）
- **Issue:** 前置查询若漏 `exclude(pk=...)`，「re-bind 到当前版本」这个幂等操作会被自己占用的行判为冲突。plan 未要求该用例，但那正是这行 `exclude` 唯一的存在理由。
- **Fix:** `test_rebind_to_same_version_is_allowed`。
- **Committed in:** `b7d82000`

### 未做（有意，附理由）

- **`ruff format` 的既有 6 个文件不做整体格式化**：`agents/intent_router.py` / `agents/tools/repository_relevance.py` / `chat/conversation_service.py` / `feishu/cards/bot_cards.py` 与两个文案测试文件在 **HEAD 上即为未格式化状态**（用 `git show HEAD:<path> | ruff format --check --stdin-filename` 逐一确认）。本 plan 只核对**新增行**自身格式干净（`ruff format --diff` 的改动点均不落在新增行上），整体格式化属超范围噪音，按 scope boundary 不做。

---

**Total deviations:** 4 主动补强（2 missing-critical、1 bug、1 补测），0 架构变更
**Impact on plan:** 全部围绕本 plan 已交付性质的验收强度，无范围扩张。计划的 Task 3 拆分预案（8 处文案 + 4 处断言分两次提交）未触发 —— 质量衰减信号未出现，Task 3 一次提交完成。

## Issues Encountered

- **接手时的红绿判定**：上一执行器在 Task 2 中途中断，留下三份未提交改动。接手后先跑 `tests/agents/test_coding_tools_schema_guard.py + test_tool_contracts.py + test_plan_projection_service.py`（68 passed）确认 Task 2 的 A/B/D 三节已完成，只剩 C 节（`test_coding_tools.py` 重写，22 用例全红）与端点侧一条 —— 据此续做，未重写任何已有未提交代码。
- **`test_coding_tools.py` 的 `conversation` fixture 缺 `created_by`**：收窄后工具会用 `conversation.created_by_id` 作为归属主体回退，`created_by=None` 会被判定拒绝。修法是给 fixture 补 `plan_owner` 用户，而不是给判定开口子。
- **`update_coding_plan` 的用例必须绑定请求上下文**：该 handler 的归属主体只取 contextvars（见 Decisions），因此新增 `as_owner` fixture 用 `structlog.contextvars.bind_contextvars` 绑定并在 teardown 复位。
- **后台知识库摄取在测试中报 `SocketBlockedError`**：`pytest-socket` 阻断网络导致 qdrant 摄取失败并打 `background_task_failed` 日志。该路径本身是 best-effort（`except: pass`），不影响用例结果，属既有噪音，未处置。

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SPINE-02 的实质交付完成：创作路径在 schema 层不存在，且有三层守护（键集合枚举 / 签名 snapshot / 行为断言）防未来静默回退。
- 归属判定已收在 service 内，后续任何新调用方（工作流节点、MCP 侧若将来接入）都必须显式传 `actor_user_id`，漏传是 `TypeError` 而不是静默放行。
- 遗留给后续 plan / phase：
  - `arebind` 目前只覆盖 chat 入口（沿用 109-03 裁决 D-3 的 `projection_requires_chat_entrypoint` 边界），workflow / MCP 入口的投影仍未支持。
  - 编排在途阶段的可见性（109-04 已明确整块留给 Phase 110）不在本 plan 范围。
  - `ruff format` 的既有未格式化文件（6 个）如需统一，建议单独一次纯格式化提交，避免与语义改动混在同一 diff。

## Self-Check: PASSED

- 新建文件存在：`server/tests/agents/test_coding_tools_schema_guard.py`
- 三个 task 提交均可在 `git log` 中定位：`61fc5e30` / `b7d82000` / `5e01578f`
- `git diff --name-only | rg 'server/mcp_tools|^mcp/'` 无输出（未越界）
- `rg -n '分步实现步骤' server/chat/conversation_service.py | rg -v '^[0-9]+:[[:space:]]*#'` 无匹配

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
