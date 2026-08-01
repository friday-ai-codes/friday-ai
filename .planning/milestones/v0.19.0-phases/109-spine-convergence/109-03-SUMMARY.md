---
phase: 109-spine-convergence
plan: 03
subsystem: api
tags: [django, drf, adrf, async-orm, idempotency, projection, owner-gate, structlog, observability]

# Dependency graph
requires:
  - phase: 109-01
    provides: SPA 执行流四步共用同一 CodingPlan.id 的端到端护栏（本 plan 的收口用例直接扩写在该文件内）
  - phase: 109-02
    provides: CodingPlan.provenance / source_artifact_version_id 两列 + 无条件唯一约束 uniq_codingplan_source_artifact_version（幂等三件套的第 ① 件）
provides:
  - map_merged_plan_to_coding_plan 纯映射函数（§7 execution_plan → CodingPlan 四字段，含 create→add 枚举转换表 _ACTION_TO_CHANGE_TYPE）
  - PlanProjectionService.aproject —— ArtifactVersion → CodingPlan 的唯一幂等投影写入口（幂等三件套齐备）
  - PlanProjectionService.aresolve_conversation —— 只读归属解析，供端点在投影前做前置 owner 校验
  - PlanProjectionError（带稳定机器码 code）+ 两个取值 artifact_version_not_found / projection_requires_chat_entrypoint
  - POST /api/chat/coding-plans/from-artifact-version/（url name coding-plan-project-from-artifact-version）
  - ProjectPlanToCodingRequestSerializer / ProjectPlanToCodingResponseSerializer（响应七字段与 UI-SPEC 对齐）
  - 四个观测事件 plan_projection_started / completed / failed / idempotent_hit（category=caller, component=chat）
  - 「投影出一条记录即执行流四步全通」的 e2e 收口用例
affects: [109-04, 109-05, SPINE-01, SPINE-02, RELY-01]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "幂等三件套：DB 无条件唯一约束 + aget_or_create + except IntegrityError 重 aget —— 三者缺一分别导致重复行 / 用户 500"
    - "前置 owner 校验用只读解析入口：把归属判定放到写操作之前，越权请求不留垃圾对象"
    - "错误响应带稳定机器码 code：前端按 code 分支，绝不按 detail 文案匹配"
    - "「不存在」与「无权限」响应逐字节一致，并用对照断言锁住，阻断 ID 枚举探测"

key-files:
  created:
    - server/chat/plan_projection_service.py
    - server/tests/test_plan_projection_service.py
    - server/tests/test_plan_projection_api.py
  modified:
    - server/chat/views.py
    - server/chat/urls.py
    - server/chat/serializers.py
    - server/tests/test_spa_coding_chain_e2e.py

key-decisions:
  - "投影只做 chat 入口（裁决 D-3）：ArtifactVersion → ConvergenceSession → Conversation 三跳任一断裂即以 projection_requires_chat_entrypoint 显式拒绝，不建合成会话、不按 repository 反查 space"
  - "owner gate 落两道：投影前用只读 aresolve_conversation 判归属（防越权请求在他人会话下建出 CodingPlan），投影后复核落点作纵深"
  - "非 owner 复用 artifact_version_not_found 这一机器码与措辞，与「版本不存在」响应逐字节相同，并用对照断言锁死"
  - "IntegrityError 分支用 patch 做确定性覆盖：Django 的 get_or_create 内部已自带一次 IntegrityError→get 重试，真实并发下我们这一层多半不被触发，但它是 DB 约束存在时唯一能把落败方从 500 降级为幂等命中的兜底，必须有测试直达"
  - "知识库摄取显式带 initiated_by_user_id：aget_or_create 不像 aget_or_create_for_conversation 那样自带摄取调度，新建分支补一次并包在 best-effort 里（摄取失败不得让投影失败）"

patterns-established:
  - "枚举转换表旁必须写清「漏转换不会崩、只会静默显示错值」的失守机理，并要求测试同时断言 file_path 与 change_type 两个键"
  - "半可信 LLM 产物（ArtifactVersion.content）的映射函数恒不抛：isinstance 守卫 + 缺键降级为空结构，九种敌意输入有参数化用例"
  - "投影响应一次给全正文（tech_plan / affected_files / provenance），消除「点击→卡片出现」之间的二次往返与 runtime 刷新时序竞态"

requirements-completed: [SPINE-01]

coverage:
  - id: D1
    description: "§7 execution_plan → CodingPlan 四字段纯映射，create→add 枚举转换有穷举断言，半可信输入 fail-safe"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_mapping_action_to_change_type_enum_exhaustive（参数化 3 条，每条同断 file_path 与 change_type）"
        status: pass
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_mapping_fail_safe_on_semi_trusted_content（9 种半可信输入均不抛）"
        status: pass
    human_judgment: false
  - id: D2
    description: "同一方案版本重复投影只产一条 CodingPlan，并发路径同样只留一行且不抛异常"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_idempotent_projection_returns_same_plan_and_single_row"
        status: pass
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_concurrent_projection_yields_single_row_without_raising（asyncio.gather 真并发）"
        status: pass
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_concurrent_integrity_error_degrades_to_idempotent_hit（IntegrityError 分支直达）"
        status: pass
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_is_idempotent_across_two_requests"
        status: pass
    human_judgment: false
  - id: D3
    description: "方案版本更新后可新建投影，旧投影保留不被改写（历史可查）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_new_version_keeps_old_projection_intact"
        status: pass
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_idempotent_projection_does_not_rewrite_existing_row"
        status: pass
    human_judgment: false
  - id: D4
    description: "从投影出的 CodingPlan 经 source_artifact_version_id 两跳可追溯到 WorkItem（不去范式化）"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_traceability_two_hops_from_plan_to_work_item"
        status: pass
    human_judgment: false
  - id: D5
    description: "投影端点复用 owner gate：非 owner 与不存在统一 404 且响应逐字节一致，无 superuser bypass，越权不留垃圾对象"
    requirement: "SPINE-01"
    verification:
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_by_non_owner_returns_404_without_plan_body"
        status: pass
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_of_unknown_version_matches_non_owner_response（两条响应 json 相等）"
        status: pass
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_request_body_ignores_client_supplied_conversation（IDOR）"
        status: pass
    human_judgment: false
  - id: D6
    description: "投影限定 chat 入口：编排会话无 conversation 时以稳定机器码显式拒绝，不建合成会话"
    requirement: "SPINE-01"
    verification:
      - kind: unit
        ref: "server/tests/test_plan_projection_service.py#test_conversation_absent_raises_requires_chat_entrypoint"
        status: pass
      - kind: integration
        ref: "server/tests/test_plan_projection_api.py#test_projection_without_conversation_returns_stable_code（400 + code）"
        status: pass
    human_judgment: false
  - id: D7
    description: "投影出的 CodingPlan 能直接走完执行流四步（SPINE-01 服务端半边成立）"
    requirement: "SPINE-01"
    verification:
      - kind: integration
        ref: "server/tests/test_spa_coding_chain_e2e.py#test_projected_plan_completes_fanout_and_export"
        status: pass
    human_judgment: false

# Metrics
duration: 约 45min（含中断后接手）
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 03: 编排方案版本 → CodingPlan 惰性投影 Summary

**`delivery.ArtifactVersion` 可经幂等投影 service 与惰性端点变成 chat `CodingPlan`，投影出的一条记录即点亮执行流四步（fan-out 与飞书导出均实测通过）**

## Performance

- **Duration:** 约 45 min（Task 1 由前一执行器完成，本次接手收尾 Task 2 并完成 Task 3）
- **Tasks:** 3
- **Files created:** 3
- **Files modified:** 4
- **Tests:** 45 passed（映射 24 + service 10 + 端点 8 + e2e 3），回归 367 passed

## Accomplishments

- **SPINE-01 的服务端半边成立**：`test_projected_plan_completes_fanout_and_export` 把 plan 的来源从「手工造 `CodingPlan`」换成「打投影端点」，随后 fan-out 与飞书导出两步原样跑通、`CodingSession.coding_plan_id` 等于投影出的 plan id。这条用例与 109-01 的既有护栏形成对照：两条都绿即证明编排产出**无需改执行流**就能直连。
- **`create → add` 这个静默失守点被钉死**：§7 用 `action: create`，chat `affected_files` 用 `change_type: add`；既有 `_normalize_affected_files` 只改键名不转枚举，而 `TechPlanCard.vue` 原样渲染 —— 漏转换不崩不报错、只在界面静默显示成 `create`。转换表 `_ACTION_TO_CHANGE_TYPE` 是唯一防线，三个已知 action 各有一条**同时断言 `file_path` 与 `change_type`** 的用例（只断言 `file_path` 正是本坑的警示信号），未知/缺失/`None` 三形态回退 `modify`。
- **幂等三件套齐备且各自有测试直达**：DB 无条件唯一约束（109-02）+ `aget_or_create` + `except IntegrityError` 重 `aget`。并发路径落两条用例 —— `asyncio.gather` 真并发（断言恰好一路 `created=True`、DB 一行）与 patch 强制 `IntegrityError`（证明落败方降级为幂等命中而非 500）。
- **越权请求不留垃圾对象**：owner gate 落两道。投影**之前**先用新增的只读入口 `aresolve_conversation` 解析归属会话再判 owner —— 若只在投影后判，越权请求会先在他人会话下建出 `CodingPlan` 再被拒（数据污染 + 垃圾对象）。投影后再复核落点作纵深。
- **枚举探测面被对照断言封死**：非 owner 与「版本不存在」共用 `artifact_version_not_found` 机器码与同一句 `detail`，`test_projection_of_unknown_version_matches_non_owner_response` 直接断言两条响应 `json()` 相等 —— 任何一处措辞漂移都会重新打开探测面并立刻变红。
- **响应一次给全正文**：七字段与 UI-SPEC 的 `ProjectPlanToCodingResponse` 逐字段对齐，`tech_plan` / `affected_files` / `provenance` 直接随投影响应返回，前端点「进入编码」后可就地内嵌卡片，不必二次拉 runtime（消除点击到卡片出现之间的空窗与 runtime 刷新时序竞态）。
- **观测四事件在位**：`plan_projection_started` / `completed` / `failed` / `idempotent_hit`，全部 `category="caller"` + `component="chat"`，`completed` 带 `duration_ms` / `created` / `repo_count` / `provenance`，`failed` 的 `reason` 过 `redact_secrets_in_text` 后才落日志。全部包在 best-effort 里，观测失败不反噬投影。

## Task Commits

1. **Task 1: §7 execution_plan → CodingPlan 字段的纯映射函数** — `920fbbc6` (feat)（前一执行器完成）
2. **Task 2: PlanProjectionService 幂等投影唯一写入口 + 观测埋点** — `5fe4be3c` (feat)
3. **Task 3: 惰性投影端点（owner gate + 稳定机器码 + 响应直接带正文）** — `643d12c5` (feat)

## Files Created/Modified

- `server/chat/plan_projection_service.py`（新）— 纯映射函数 + `_ACTION_TO_CHANGE_TYPE` 转换表 + `PlanProjectionService`（`aproject` / `aresolve_conversation`）+ `PlanProjectionError` + 两个机器码常量
- `server/tests/test_plan_projection_service.py`（新）— 34 用例：映射穷举与 fail-safe（24）+ conversation / idempotent / concurrent / new_version_keeps_old / traceability 五组（10）
- `server/tests/test_plan_projection_api.py`（新）— 8 用例：200 全字段、未认证、幂等、非 owner 404、不存在与非 owner 响应对照、无 conversation 400、非 UUID 400、客户端指定 conversation 被忽略
- `server/chat/views.py` — `CodingPlanProjectFromArtifactVersionView`（两道 owner gate + 两类机器码映射 + `extend_schema`）
- `server/chat/urls.py` — 注册投影路由，置于 `coding-plans/<uuid:plan_id>/` 之前
- `server/chat/serializers.py` — `ProjectPlanToCodingRequestSerializer`（仅 `artifact_version_id`）与 `ProjectPlanToCodingResponseSerializer`（七字段）
- `server/tests/test_spa_coding_chain_e2e.py` — 新增 `spine_artifact_version` fixture 与投影链路收口用例

## Decisions Made

- **`IntegrityError` 分支用 patch 做确定性覆盖**：Django 的 `get_or_create` 内部本就带一次 `IntegrityError → get` 重试，真实并发下我们这一层多半吃不到异常。但 DB 约束在位时它是把落败方从 500 降级为幂等命中的唯一兜底（Django 那次重试 `DoesNotExist` 时仍会 re-raise），因此保留并用 patch 让该分支被确定性执行，而不是留一段没人跑过的代码。
- **前置 owner 校验单独开只读入口**：没有 `aresolve_conversation` 就只能「先投影再判权」，越权请求会在他人会话下留下 `CodingPlan`。该入口只读、不写库，端点用它判权后再调 `aproject`。
- **`initiated_by_user_id` 暂为带默认值的可选参数**：plan 明确前瞻 —— 109-05 让 chat `@tool` 成为第二个调用方时，它会变成必填的 `actor_user_id` 并把归属判定下移进 service。因此 docstring 里写的是「当前唯一调用方是端点、其视图有 owner gate」，而**不是**把「归属由调用方保证」写成长期契约。
- **知识库摄取显式补一次并带触发用户**：`aget_or_create` 不像 `aget_or_create_for_conversation` 那样自带 `aschedule_ingestion`，故在 `created=True` 分支显式调度，并按项目观测规范传 `initiated_by_user_id`（后台任务必须携带发起用户）。整段包在 best-effort 里，摄取失败不影响投影结果。
- **URL 顺序前置而非依赖转换器细节**：`from-artifact-version` 不是合法 UUID，Django 的 `uuid` 转换器本就不会匹配它，但仍把该 path 放在 `<uuid:plan_id>` 之前，让「不冲突」这件事不依赖对转换器实现的记忆，并在注释里点明理由。

## Deviations from Plan

None —— plan 执行与原文一致，未触发 Rule 1–4。

两处**非偏离**的实现细化已记入 Decisions：① service 新增只读方法 `aresolve_conversation`（plan 正文在 Task 3 要求「优先在调 service 之前做一次前置 owner 校验」，该方法是这条要求的最小落法）；② `aschedule_ingestion` 补传 `initiated_by_user_id`（plan 给的调用形态未带该参数，但项目观测规范要求后台任务携带发起用户，属规范优先）。

## Issues Encountered

- **接手时的中断现场判定**：前一执行器已写完 `plan_projection_service.py` 的 service 实现，但 `test_plan_projection_service.py` 只加了 import、尚无 Task 2 任何用例。按要求先读后续 —— 未重写已有未提交代码，只补齐五组断言后一次跑绿（34 passed），再提交 Task 2。
- **`ruff format` 既有漂移**：`chat/serializers.py` 与 `tests/test_spa_coding_chain_e2e.py` 报 would-reformat，核对后确认是**改动前既有**的格式漂移（本仓 CI 只跑 `ruff check`），沿用 109-02 的处置口径：不做全文件重排，只把本 plan 新增代码块调到 `ruff format` 稳定形态（新增文件全部 `--check` 通过）。
- **`spectacular --fail-on-warn` 既有失败**：全仓 1184 条 schema 警告是既有状态，非本 plan 引入。改用不带 `--fail-on-warn` 生成并核验新端点已正确出现在 schema（`/api/chat/coding-plans/from-artifact-version/`），未新增任何警告。

## Verification Results

| 命令 | 结果 |
|---|---|
| `uv run pytest tests/test_plan_projection_service.py -q` | 34 passed |
| `uv run pytest tests/test_plan_projection_api.py -q` | 8 passed |
| `uv run pytest tests/test_plan_projection_service.py tests/test_plan_projection_api.py tests/test_spa_coding_chain_e2e.py -q` | **45 passed** |
| `uv run pytest tests/test_coding_plan*.py tests/test_coding_session*.py tests/mcp_tools/ tests/test_coding_plans_sessions_api.py tests/test_conversation_runtime.py -q` | **367 passed**（执行流与 MCP 侧零回归） |
| `-k` 选择器可选中数（共 34） | mapping 24 / conversation 4 / idempotent 3 / concurrent 2 / new_version_keeps_old 1 / traceability 1 |
| `uv run ruff check`（7 个改动文件） | All checks passed |
| `uv run python manage.py spectacular` | 新端点入 schema，无新增警告 |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-03-01（EoP，越权投影） | owner gate 两道：投影前 `aresolve_conversation` + `created_by_id` 标量比较 → 404；投影后复核落点。无 `is_superuser` bypass 分支 |
| T-109-03-02（信息泄漏，枚举探测） | 「不存在」与「非 owner」共用 `artifact_version_not_found` + 同一 `detail`；对照用例直接断言两条响应 `json()` 相等 |
| T-109-03-03（EoP，IDOR） | 请求序列化器**只有** `artifact_version_id` 一个字段；专门用例证明客户端多传 `conversation_id` 被完全忽略、投影落点不变 |
| T-109-03-04（DoS，半可信 content） | 映射函数全程 `isinstance` 守卫，9 种敌意输入参数化用例均不抛；写库前 `title[:200]` 截断 |
| T-109-03-05（Tampering，并发） | 幂等三件套齐备；`asyncio.gather` 真并发用例 + `IntegrityError` 分支直达用例，两条都断言 DB 仅 1 行且不抛 |
| T-109-03-06（Spoofing，provenance） | `orchestrated` 只由 service 写；请求体不含 `provenance`；响应序列化器为出参组装，无写路径 |
| T-109-03-07（信息泄漏，日志） | `plan_projection_failed` 的 `reason` 经 `redact_secrets_in_text` 后才落日志 |
| T-109-03-SC（供应链） | 零新增依赖，未执行任何包管理器安装命令 |

## Observability

按 `.cursor/rules/observability-logging.mdc` §新功能提交前自检逐条核对：

- **生命周期事件 + `duration_ms`**：`plan_projection_started` / `completed` / `failed` / `idempotent_hit` 四事件在位，`completed` 与 `failed` 均带 `duration_ms`。
- **`category` / `component`**：四事件全部 `category="caller"` + `component="chat"`，未新增 `component` 取值。
- **绑定触发用户**：端点走中间件注入 + 显式传 `initiated_by_user_id=str(request.user.id)`；service 默认值 `"system"` 覆盖后台调用；后台摄取任务同样显式携带该值。
- **脱敏**：异常文本经 `redact_secrets_in_text`；日志中无凭证、无上游响应体。
- **不反噬业务**：全部埋点与知识库摄取包在 `except Exception: pass` 内。
- **未新增 `call_source`**（本 plan 无 LLM 调用点）、**未新增召回**、未新增队列任务或 webhook。
- **无高频循环 INFO 刷屏**：投影是用户点击触发的低频调用类事件，全量记录合适。

## Known Stubs

无占位实现。以下是**按 plan 设计**分派到后续 plan 的下游接线，不是本 plan 的 stub：

- 前端 `OrchestratedPlanCard.vue`、`projectPlanToCodingPlan` action、`TechPlanCard` 草稿告示条属 **109-04**（本 plan 明令不动前端）。
- chat `@tool` 作为第二个投影调用方、`initiated_by_user_id` 升级为必填 `actor_user_id` 并在 service 内落归属判定（机器码 `artifact_version_forbidden`）属 **109-05**。
- workflow / MCP 入口的编排产出投影**刻意不做**（裁决 D-3）：当前以 `projection_requires_chat_entrypoint` 显式拒绝，覆盖其余入口是后续 plan 的事，不是这里悄悄猜一个 space。
- `CodingPlan → MergeRequest` 半段本 phase **不建 FK**，沿用既有 `pr_url` + `(repository, source_branch)` 弱对齐（109-RESEARCH §7 结论 1），已写进 service docstring。
- `tech_plan` 沿用 `render_merged_plan_markdown` 的飞书 lark_md 方言（`•` 项目符号在 GFM 下显示为纯文本），按 UI-SPEC §Unresolved 第 7 条**接受现状**；若 UAT 判观感不可接受，处置方式是给该函数加 `flavor` 参数，**仍不 fork 渲染器**。

## User Setup Required

None —— 无外部服务配置需求，零新增迁移、零新增依赖。

## Next Phase Readiness

- **109-04（前端）可直接消费**：投影端点已返回 UI-SPEC 约定的七字段，`ProjectPlanToCodingResponse` 逐字段对齐，前端投影后就地内嵌 `TechPlanCard` 不需要二次拉取。
- **109-05（工具 schema 收窄）的前置条件已满足**：SPINE-01 的替代路径在服务端成立（投影一条记录即四步全通，有 e2e 用例背书），可以开始收窄编排工具 schema。
- ⚠️ **提醒 109-05**：`aproject` 的 `initiated_by_user_id` 目前带默认值，其安全性建立在「唯一调用方是有 owner gate 的端点」之上。新增第二个调用方时**必须**同步把归属判定下移进 service（plan 正文已给出机器码 `artifact_version_forbidden`），否则 `@tool` 路径会绕过 gate。
- ⚠️ **提醒后续**：投影的 conversation 解析依赖 `ArtifactVersion.produced_by_session_id` 这个**字符串软引用**（P2 才升级为 FK）。历史数据里该字段可能不是 UUID 字面量，service 已用 try/except 兜住，改动该字段语义时需同步这一处。

## Self-Check: PASSED

- 三个新建文件均存在于磁盘：`server/chat/plan_projection_service.py`、`server/tests/test_plan_projection_service.py`、`server/tests/test_plan_projection_api.py`。
- 三个 task commit 均可在 git 历史中检得：`920fbbc6` / `5fe4be3c` / `643d12c5`。
- 两次新提交 `git diff --diff-filter=D` 均无文件删除。
- 未修改 `.planning/STATE.md` 与 `.planning/ROADMAP.md`（编排器职责）。

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
