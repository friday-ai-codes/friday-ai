---
phase: 109-spine-convergence
plan: 07
subsystem: api
tags: [django, drf, structlog, pytest, fail-closed, provenance, feishu-export, dispatch-contract, chat]

# Dependency graph
requires:
  - phase: 109-02
    provides: CodingPlanProvenance 枚举与 CodingPlan.provenance 列（三处判定的唯一数据真源；default draft 让存量方案自动进入保守分支）
  - phase: 109-05
    provides: 两个 @tool 收窄后的入参形态与「归属判定下移进 service」的既有纪律（本 plan 的 gate 同样落在 service 而非视图）
  - phase: 109-01
    provides: tests/test_spa_coding_chain_e2e.py 四步护栏（本 plan 在其上补一条草稿被拦用例，并把原四步用例显式置为 orchestrated）
provides:
  - chat.coding_session_service.ERROR_CODE_DRAFT_REQUIRES_CONFIRM / ERROR_DRAFT_REQUIRES_CONFIRM 两个共享常量
  - chat.coding_session_service.DraftPlanRequiresConfirmError（带 code 属性的领域异常）
  - create_sessions_for_plan 新增关键字参数 acknowledge_unresearched（default False），gate 位于任何 session 创建之前
  - chat.serializers.CodingSessionsBatchCreateRequestSerializer.acknowledge_unresearched（BooleanField，default=False）
  - fan-out 端点 400 响应体 {code: draft_requires_explicit_confirm, detail: ...}（稳定机器码）
  - 观测事件 draft_plan_coding_confirmed / draft_plan_coding_rejected（category=caller、component=chat）
  - CodingExecutionSpec.unresearched（bool，default False）+ as_dict() 同名键，随 dispatch payload 跨进程下发
  - feishu.coding_plan_exporter._DRAFT_NOTICE + _compose_plan_markdown 的 provenance 驱动插入
affects: [109-08, RELY-01, Phase-110]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "防护必须落在服务端最内层：gate 放进 service 而非视图，因为视图只是调用方之一（还有工具、工作流节点、脚本）；验收里必须有一条直接调 service 的用例，否则「只在前端做防护」会伪装成已完成"
    - "拒绝要断言「没写进去」而不只是「返回了 400」：fail-closed 的实质是 DB 零写入，用 CodingSession 计数不变来锁，而不是只看状态码"
    - "允许清单 vs 拒绝清单是安全性差别而非风格差别：仅 orchestrated 免确认/免标注，未知取值与空值一律保守；用 `== draft` 会让任何新增枚举值默认放行"
    - "确认标志只认布尔 True（`is not True`）：truthy 字符串/数字不算确认，避免「传了个非空值就过」的软化路径"
    - "机器码与文案分离：客户端按 code 分支、绝不匹配 detail，一次文案微调不该让前端的错误分支静默失效"
    - "gate 排在权限门之后：先判权限再判草稿，否则 400 会让非授权调用方推断出「这个 plan 存在」"
    - "护栏改造要「两条都做」：把被 gate 打红的 e2e 用例置为 orchestrated 的同时必须补一条草稿被拦用例，否则护栏不再覆盖存量真实形态（迁移 default 是 draft）"

key-files:
  created: []
  modified:
    - server/chat/coding_session_service.py
    - server/chat/serializers.py
    - server/chat/views.py
    - server/feishu/coding_plan_exporter.py
    - server/tests/test_coding_plans_sessions_api.py
    - server/tests/test_coding_session_service.py
    - server/tests/test_spa_coding_chain_e2e.py
    - server/tests/test_coding_plan_exporter.py
    - server/tests/knowledge/test_triggers.py

key-decisions:
  - "gate 抛领域异常而非塞进 CodingSessionsBatchResult.failed：gate 的语义是「整批拒绝、DB 零写入」，塞进 per-repo failed 列表会让它看起来像单仓失败，调用方可能继续往下走"
  - "三处判定（gate / 执行契约 / 导出）统一用允许清单：仅 orchestrated 免确认/免标注，draft 与未知取值和空值一律保守 —— 与前端保守默认（UI-SPEC §B.1）同一口径"
  - "test_coding_plans_sessions_api.py 的 coding_plan fixture 置为 orchestrated（plan 允许的两种修法之一），既有 6 类场景断言一行未改；草稿路径由新增的独立测试类覆盖，两件事不绞在一起"
  - "CodingExecutionSpec.unresearched 带默认值 False：frozen dataclass 新增无默认字段会破坏既有构造点；但 build_coding_execution_spec 内的计算默认是 True（取不到来源不等于可信）"
  - "service 侧 _context_user_id 把取不到记为 system（而非 109-05 coding_tools 里「system 视同取不到」）：两处用途不同 —— 那里是归属判定（哨兵不得放行），这里是留痕归因（无触发用户就该记 system）"
  - "_DRAFT_NOTICE 取 UI-SPEC §Copywriting Contract 的逐字文案，而非 RESEARCH §Code Examples 的示意版本（后者次行多了「过…环节」二字，与界面侧不逐字一致）"

patterns-established:
  - "允许清单的负控实测：把三处判定同时改成拒绝清单形态（`== draft`）重跑三条未知取值用例 → 3 failed，随后原样恢复（git status 空）—— 证明这三条用例精确命中「允许清单」这条性质，而不是同义重复当前实现"
  - "被 gate 打红的既有测试逐处注释「这是 gate 生效的预期连带影响，不是回归」+ 一句本用例真正在测什么：让后来者不会把补 ack 误读为「测试为了变绿而妥协」"

requirements-completed: [RELY-01]

coverage:
  - id: D1
    description: "草稿方案未经显式确认无法送编码，且拒绝时 DB 零写入（服务端 fail-closed，绕过前端也拒绝）"
    requirement: "RELY-01"
    verification:
      - kind: integration
        ref: "server/tests/test_coding_plans_sessions_api.py::TestCodingPlansSessionsDraftGate（6 条 `-k draft_gate`，全部直接打端点；缺字段 / 显式 false 两条均断言 CodingSession 计数不变）"
        status: pass
      - kind: unit
        ref: "server/tests/test_coding_session_service.py::TestCreateSessionsForPlan::test_draft_gate_blocks_direct_service_call_with_zero_writes（完全绕过视图与前端的最内层证据）"
        status: pass
      - kind: e2e
        ref: "server/tests/test_spa_coding_chain_e2e.py::test_draft_plan_fanout_blocked_without_acknowledge（存量真实形态打第 ③ 步 → 400 + 零写入，随后带 ack 放行）"
        status: pass
    human_judgment: false
  - id: D2
    description: "拒绝响应带稳定机器码 draft_requires_explicit_confirm，前端可按 code 分支而不必匹配文案"
    requirement: "RELY-01"
    verification:
      - kind: integration
        ref: "server/tests/test_coding_plans_sessions_api.py -k draft_gate（三条拒绝用例均断言 body[\"code\"]，另断言 detail 非空 —— 双键都在）"
        status: pass
      - kind: unit
        ref: "server/tests/test_coding_session_service.py::...::test_draft_gate_blocks_direct_service_call_with_zero_writes（断言 exc.code == ERROR_CODE_DRAFT_REQUIRES_CONFIRM，service 与 view 共用同一常量）"
        status: pass
    human_judgment: false
  - id: D3
    description: "编排产出的方案零摩擦：provenance == orchestrated 时确认标志被忽略，行为与今日一致"
    requirement: "RELY-01"
    verification:
      - kind: integration
        ref: "server/tests/test_coding_plans_sessions_api.py::...::test_draft_gate_orchestrated_plan_without_field_succeeds / test_draft_gate_orchestrated_plan_ignores_acknowledge_flag（不带与带 true 结果一致）"
        status: pass
      - kind: integration
        ref: "既有 6 类场景（3 仓全成功 / 部分成功 / 全失败 / 403→404 / 404 / 400）断言一行未改且全绿"
        status: pass
    human_judgment: false
  - id: D4
    description: "草稿经显式确认送出时，下发给 Runner/容器的执行契约携带「未经调研」标志"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_session_service.py::TestExecutionSpecUnresearchedFlag（5 条 `-k unresearched`：draft True / orchestrated False / 未知取值 True / coding_plan_id 为 None 的历史 session True 且不抛）"
        status: pass
      - kind: unit
        ref: "同类 test_unresearched_flag_present_in_dispatch_payload：env_metadata[\"execution_spec\"][\"unresearched\"] is True（跨进程边界的 payload 键确实存在）"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/test_coding_session_graph.py tests/test_coding_session_graph_e2e.py -q（dispatch 链零回归）"
        status: pass
    human_judgment: false
  - id: D5
    description: "草稿方案的飞书导出物正文顶部带「未经代码调研」告示；判定读 provenance 字段而非匹配正文文案；未知取值同样标注且不回显原始取值"
    requirement: "RELY-01"
    verification:
      - kind: unit
        ref: "server/tests/test_coding_plan_exporter.py -k draft（5 条：位置断言用 str.index / orchestrated 无告示 / 未知取值仍标注且 markdown 不含 weird_value / 空 tech_plan 兜底不受影响 / 双侧口径逐字一致）"
        status: pass
      - kind: integration
        ref: "cd server && uv run pytest tests/test_coding_plan_export_api.py -q（导出端点零回归）"
        status: pass
    human_judgment: false
  - id: D6
    description: "草稿送编码的确认与拒绝两条路径都有留痕，均带 category/component 与可归因触发用户"
    requirement: "RELY-01"
    verification:
      - kind: other
        ref: "源码级：`rg -n 'draft_plan_coding_(confirmed|rejected)' server/chat/coding_session_service.py` 各 1 处，共用 _log_draft_coding_gate（固定注入 category=caller / component=chat / coding_plan_id / user_id，整体 try/except 吞掉）"
        status: pass
    human_judgment: false
  - id: D7
    description: "SPA 四步护栏在 gate 落地后仍覆盖草稿形态：既有 draft 未确认被拦用例，也有置为 orchestrated 的四步连通性用例；acknowledge_unresearched 在任何一层都不存在 True 默认值"
    requirement: "RELY-01"
    verification:
      - kind: e2e
        ref: "server/tests/test_spa_coding_chain_e2e.py：test_draft_plan_fanout_blocked_without_acknowledge（①）+ spine_plan fixture 显式置 orchestrated 并注释「四步连通性护栏测编排方案正常路径，草稿路径由本文件 gate 用例覆盖」（②）"
        status: pass
      - kind: other
        ref: "源码级：`rg -n 'acknowledge_unresearched' server/chat/{serializers,views,coding_session_service}.py` 共 7 处命中，形态只有 `default=False` / `: bool = False` / `is not True` / `.get(..., False)`，无任何 True 默认值"
        status: pass
    human_judgment: false
  - id: D8
    description: "真实浏览器/真实飞书文档下的双侧观感：界面横幅与导出物告示是否读起来同一口径、草稿送编码的确认流程是否顺畅"
    verification: []
    human_judgment: true
    rationale: "本 plan 只交付服务端半边（界面横幅与确认弹层属 109-08）。双侧文案一致性已有字面量断言锁住，但「用户在界面与文档间是否真的建立了同一心智」只能在真实会话 + 真实导出文档里观察；此外 blockquote 经 markdown_to_blocks 转飞书 block 后的视觉呈现（⚠️ 与加粗是否保留）需实际导出一次确认"

# Metrics
duration: 25min
completed: 2026-07-30
status: complete
---

# Phase 109 Plan 07: RELY-01 服务端半边 —— 草稿送编码 fail-closed + 下游标志 + 导出告示 Summary

**草稿方案在服务端 fail-closed：未带显式确认的 fan-out 请求（含直接打端点、直调 service 两条绕过路径）整批拒绝且 DB 零写入，拒绝带稳定机器码 `draft_requires_explicit_confirm`；确认送出时 dispatch payload 携带 `unresearched` 标志；飞书导出物正文之前带与界面逐字一致的「未经代码调研」告示 —— 三处判定统一为允许清单（仅 `orchestrated` 免确认/免标注）。**

## Performance

- **Duration:** 约 25 min
- **Tasks:** 3
- **Files modified:** 9（0 新建）
- **Tests:** 新增 16 条（端点 gate 6 / service 层 gate 2 / 执行契约 5 ~~+~~ 含 dispatch payload 1 / 导出 5 中的 5、e2e 1），本 plan 验证面 **329 passed**

## Accomplishments

- **RELY-01 的服务端防护落在最内层**：gate 在 `create_sessions_for_plan` 函数最前面，先于任何 session 创建。因此三条路径一致地被拦：打 HTTP 端点、直调 service、以及既有测试里的老调用方。Pitfall 6 的警示信号（「验收只有前端测试，没有直接打端点的后端测试」）被显式消除 —— 6 条端点用例 + 1 条 service 直调用例，全部不涉及一行前端代码。
- **拒绝的实质是「没写进去」而非「返回了 400」**：缺字段与显式 `false` 两条用例都断言 `CodingSession` 计数不变；e2e 用例同样断言零写入后再用 `acknowledge_unresearched: true` 复跑一次证明放行。草稿是「有防护的应急路径」，不是被禁用的路径。
- **`false` 与缺字段等价、只认布尔 `True`**：判定写成 `acknowledge_unresearched is not True`，truthy 的字符串/数字都不算确认。搭配 serializer 的 `default=False`，形成「唯一确认来源是客户端显式传布尔 true」。
- **三处判定统一为允许清单，并有负控实测背书**：gate / `CodingExecutionSpec.unresearched` / 导出告示都与 `CodingPlanProvenance.ORCHESTRATED` 做**不等于**比较。把三处同时改成拒绝清单形态（`== draft`）重跑三条未知取值用例 → **3 failed**，随后原样恢复（`git status` 空）。这证明那三条用例锁的是「允许清单」这条性质本身。
- **编排方案零摩擦**：`orchestrated` 时确认标志被完全忽略，带与不带结果一致（有对照用例）。这正是 109-08 前端保守默认（缺 `provenance` 视为草稿 ⇒ 可能多带一次 ack）能安全落地的前提。既有 6 类端点场景的断言**一行未改**。
- **下游携带**：`CodingExecutionSpec.unresearched` 进入 `env_metadata["execution_spec"]`，跨进程随 dispatch 下发。历史未迁移 session（`coding_plan_id` 为空）走保守分支 `True` —— 取不到来源不等于可信。
- **导出侧告示数据驱动**：`_compose_plan_markdown` 读 `provenance` 字段插入 `_DRAFT_NOTICE`，位置在技术方案正文之前（`str.index` 位置断言）。文案主句与次行前半段与界面侧逐字一致，写成测试里的字面量常量 —— 前端常量若变更而未同步，`test_draft_notice_matches_ui_side_copy` 会红。未知取值仍标注，且 markdown 中**不含**原始取值。
- **两条留痕在位**：`draft_plan_coding_confirmed`（带 `repo_count`）与 `draft_plan_coding_rejected`（带 `reason`）共用 `_log_draft_coding_gate`，固定注入 `category="caller"` / `component="chat"` / `coding_plan_id` / `user_id`，整体 `try/except: pass` 包裹，绝不反噬业务。

## Task Commits

1. **Task 1: fan-out 端点草稿 gate（fail-closed + 稳定机器码 + 留痕）** — `95fdd5a9` (feat)
2. **Task 2: 编码执行契约携带「未经调研」标志** — `c0e89746` (feat)
3. **Task 3: 飞书导出侧「未经代码调研」告示** — `645869e9` (feat)

## Files Created/Modified

**后端实现**

- `server/chat/coding_session_service.py` — 两个常量 + `DraftPlanRequiresConfirmError` + `_plan_requires_unresearched_confirm` / `_context_user_id` / `_log_draft_coding_gate` 三个 helper；`create_sessions_for_plan` 新增 `acknowledge_unresearched` 与函数首部 gate；`CodingExecutionSpec.unresearched` 与 `as_dict()` 补键；`build_coding_execution_spec` 的允许清单判定
- `server/chat/serializers.py` — `CodingSessionsBatchCreateRequestSerializer.acknowledge_unresearched`（`default=False`，注释写明「设 True 等于取消 RELY-01」）
- `server/chat/views.py` — 透传该字段、捕获领域异常映射 400 `{code, detail}`、`@extend_schema` 的 400 描述补机器码与重试指引；注释写明 gate 排在权限门之后的理由
- `server/feishu/coding_plan_exporter.py` — `_DRAFT_NOTICE` 常量（旁注双侧逐字一致的口径）+ `_compose_plan_markdown` 的三条判定纪律注释与插入

**测试**

- `server/tests/test_coding_plans_sessions_api.py` — 新增 `TestCodingPlansSessionsDraftGate`（6 条，`-k draft_gate` 可选中）+ `draft_coding_plan` fixture；`coding_plan` fixture 置为 `orchestrated` 并注释原因
- `server/tests/test_coding_session_service.py` — 新增 `TestExecutionSpecUnresearchedFlag`（5 条，`-k unresearched`）+ `TestCreateSessionsForPlan` 两条 gate 用例；三处既有调用补 `acknowledge_unresearched=True` + 逐处注释
- `server/tests/test_spa_coding_chain_e2e.py` — 新增 `test_draft_plan_fanout_blocked_without_acknowledge`；`spine_plan` fixture 显式置 `orchestrated` 并在 docstring 写明「两条用例缺一即视为护栏失守」
- `server/tests/test_coding_plan_exporter.py` — `_create_plan` 工厂加 `provenance` 入参；新增 5 条 `-k draft` 用例与两个界面侧文案字面量常量
- `server/tests/knowledge/test_triggers.py` — 两处 `create_sessions_for_plan` 调用补确认 + 注释

## 被 gate 打红的三个测试文件：逐文件处置结果

| 文件 | 处置 | 结果 |
|---|---|---|
| `server/tests/test_spa_coding_chain_e2e.py` | ① 新增 `test_draft_plan_fanout_blocked_without_acknowledge`（draft 未确认 → 400 + `code` + 零写入，再带 ack 放行）；② `spine_plan` fixture 显式置 `orchestrated`，docstring 写明两条缺一即护栏失守 | ①② **两条都做** |
| `server/tests/knowledge/test_triggers.py`（2 处调用） | 两处补 `acknowledge_unresearched=True` + 注释「gate 生效的预期连带影响，不是回归；本用例测的是摄取触发/零投递语义，不是 gate」 | 完成 |
| `server/tests/test_coding_session_service.py::TestCreateSessionsForPlan`（3 处调用） | 三处补 `acknowledge_unresearched=True` + 各自注释本用例真正在测什么（分支模板渲染 / 仓库归属校验 / per-repo 事务独立性） | 完成 |

plan 明令禁止的两条「省力修法」均未触碰：无任何 `True` 默认值（源码级 `rg` 断言）；e2e 护栏不是「一律置 orchestrated 而不补草稿用例」。

## Decisions Made

- **gate 抛异常而非返回 failed 项**：语义是整批拒绝，塞进 `CodingSessionsBatchResult.failed` 会让它看起来像 per-repo 失败，调用方可能继续往下走。异常带 `code` 属性，view 与 service 共用同一常量。
- **`coding_plan` fixture 置 orchestrated 而非给 4 条既有用例逐个补 ack**（plan 允许的两种修法之一）：既有 6 类场景测的是端点自身语义，补 ack 会让每条用例的请求体多一个与被测意图无关的键；置 orchestrated 后既有断言一行未改，草稿路径由独立测试类覆盖，两件事不绞在一起。
- **service 侧 `_context_user_id` 把取不到记 `system`**：与 109-05 `coding_tools._context_user_id`（把 `"system"` 视同取不到）刻意不同 —— 那里是**归属判定**（哨兵身份不得放行），这里是**留痕归因**（无触发用户就该如实记 `system`）。两个同名 helper 用途不同，各自注释在位。
- **`_DRAFT_NOTICE` 取 UI-SPEC 的逐字文案**：RESEARCH §Code Examples 的示意版本次行写作「未经过仓库路由…环节」，与界面侧不逐字一致。plan Task 3 明确以 UI-SPEC §Copywriting Contract 为准，按后者落地。
- **`unresearched` 字段默认 `False` 但计算默认 `True`**：dataclass 默认值是为了不破坏既有构造点（frozen dataclass 新增无默认字段会 `TypeError`）；`build_coding_execution_spec` 内的初值是 `True`，取不到来源即保守。两个「默认」朝向不同，注释写明。

## Deviations from Plan

### 主动补强（超出 plan 字面要求，均为验收强度而非新增范围）

**1. [Rule 2 - Missing Critical] service 层直调 gate 的用例**

- **Found during:** Task 1（plan 第 5 条只要求端点侧用例；第 6 条只要求修既有三处调用）
- **Issue:** 端点用例证明「HTTP 边界上拦住了」，但 gate 的设计要点是它落在 **service 内**（视图只是调用方之一）。若后人把 gate 从 service 上移到视图里，端点用例仍全绿 —— 而工具 / 工作流节点 / 脚本这些调用方就都失守了。这正是 109-05 已识别过一次的形状（「判定留在调用方意味着每个新调用方都要重新实现一遍」）。
- **Fix:** 新增 `test_draft_gate_blocks_direct_service_call_with_zero_writes`（断言异常类型 + `code` + `CodingSession` 计数为 0）与 `test_draft_gate_ignored_for_orchestrated_plan`（service 层的零摩擦对照）。
- **Files modified:** `server/tests/test_coding_session_service.py`
- **Committed in:** `95fdd5a9`

**2. 允许清单的负控实测**

plan 只要求「未知取值 → 需确认/仍标注」各一条用例。参照 109-04/109-06 建立的纪律（护栏断言最容易写成「断言当前实现」），实际把三处判定同时改成拒绝清单形态（`!= ORCHESTRATED` → `== DRAFT`）重跑三条未知取值用例：**3 failed**（端点 gate / 执行契约 / 导出各一），随后原样恢复，`git status` 为空、三条复跑全绿。这证明「允许清单」这条性质有真实的锁，而不是三条与当前实现同义的重复断言。

**3. e2e 草稿用例追加「确认后放行」的后半段**

plan 第 6 条表格只要求 e2e 新增「draft 未确认被拦」。实测里补了同一条用例内带 `acknowledge_unresearched: true` 复跑一次并断言 200 + created 数量 —— 否则这条用例只锁住了「草稿被拦」，而 RELY-01 的另一半（草稿是**保留**的应急路径，不是被禁用的路径）在 e2e 层无锁。

### 未做（有意，附理由）

- **`ruff format` 的既有格式漂移不整体重排**：`chat/coding_session_service.py` 等文件在 HEAD 上即存在多处 `ruff format` would-reformat（本仓 CI 只跑 `ruff check`，见 109-02 / 109-05 已记录的同一结论）。本 plan 只把**新增行**调整到 `ruff format` 稳定形态（逐一核对后 `--diff` 在新增行上零输出），整体格式化属超范围噪音。
- **未改前端**：界面横幅 / 折叠态徽标 / 送编码确认弹层与按 `code` 分支的 toast 属 109-08（UI-SPEC §B/§C）。本 plan 的服务端 gate **不依赖**前端确认作为屏障 —— 前端弹层落地前，草稿送编码在服务端就已是拒绝态。

---

**Total deviations:** 3 主动补强（1 missing-critical 补测、1 负控实测、1 用例补后半段），0 架构变更，0 Rule 4 触发
**Impact on plan:** 全部围绕本 plan 已交付性质的验收强度，无范围扩张。三个 task 各一次提交完成，未触发任何拆分。

## 显式不覆盖的出口（写进 SUMMARY 以免后续审计误判为遗漏）

`ArchitectMergeAdapter._maybe_bind_plan_to_project` → `ProjectDocService.append_research_note` 这条镜像出口只承载**编排产物**（其来源必然是编排链路，`provenance` 永远是 `orchestrated`，不可能是草稿），因此 RELY-01 的双侧标注不需要覆盖它。RELY-01 的两个出口就是：界面（`TechPlanCard`，109-08）与飞书导出（`_compose_plan_markdown`，本 plan）。

## Issues Encountered

- **`test_coding_plan_exporter._create_plan` 需要能写入 choices 之外的值**：未知取值分支要造 `provenance="weird_value"`。Django 模型层不做 `choices` 校验（校验在 form/serializer 层），因此工厂直接透传该 kwarg 即可，无需 `queryset.update` 绕行。工厂的 `provenance=None` 缺省仍走 DB default `draft`（保留存量真实形态作为默认造数形状）。
- **测试日志里的 qdrant `SocketBlockedError` / `background_task_failed`**：既有噪音（`aschedule_ingestion` 在 `--disable-socket` 下触网被挡，路径本身 best-effort）。109-02 / 109-05 已记录同一现象，未处置。

## Verification Results

| 命令 | 结果 |
|---|---|
| `uv run pytest tests/test_coding_plans_sessions_api.py tests/test_spa_coding_chain_e2e.py tests/knowledge/test_triggers.py tests/test_coding_session_service.py -q` | **80 passed**（Task 1 验收面） |
| `uv run pytest tests/test_coding_plans_sessions_api.py -k draft_gate -q` | **6 selected / 6 passed**（≥6 达标） |
| `uv run pytest tests/test_coding_session_service.py -k unresearched -q` | **5 selected / 5 passed**（≥4 达标） |
| `uv run pytest tests/test_coding_plan_exporter.py -k draft -q` | **5 selected / 5 passed**（≥4 达标） |
| `uv run pytest tests/test_coding_session_service.py tests/test_coding_session_graph.py tests/test_coding_session_graph_e2e.py -q` | **59 passed**（dispatch 链零回归） |
| `uv run pytest tests/test_coding_plan_exporter.py tests/test_coding_plan_export_api.py -q` | **22 passed**（导出端点零回归） |
| `uv run pytest tests/test_coding_plans_sessions_api.py tests/test_coding_session_service.py tests/test_coding_plan_exporter.py tests/test_coding_plan_export_api.py tests/test_spa_coding_chain_e2e.py tests/knowledge/test_triggers.py tests/test_plan_projection_api.py tests/mcp_tools/ -q` | **329 passed**（plan 全量验证面） |
| `uv run ruff check`（9 个改动文件） | All checks passed |
| `rg -n 'acknowledge_unresearched' chat/{serializers,views,coding_session_service}.py` | 7 处命中，无任何 `True` 默认值 |
| `rg -n 'provenance' feishu/coding_plan_exporter.py` | 3 处（1 判定 + 2 注释），无把原始取值拼进 markdown 的代码 |
| 负控：三处判定改为拒绝清单（`== DRAFT`） | **3 failed**（三条未知取值用例各一），已原样恢复且复跑 3 passed，`git status` 空 |

## Threat Model Coverage

| Threat ID | 落法 |
|---|---|
| T-109-07-01（EoP，绕过 gate 创建 session） | gate 在 `create_sessions_for_plan` 函数最前面；端点侧两条拒绝用例 + service 直调用例均断言 `CodingSession` 计数不变（DB 零写入） |
| T-109-07-02（Tampering，确认标志被软化） | `acknowledge_unresearched is not True` —— 只认布尔 `True`；`false` 与缺字段各有独立用例；`orchestrated` 时该字段被忽略（两条对照用例证明带与不带结果一致） |
| T-109-07-03（Repudiation，草稿送编码无痕） | `draft_plan_coding_confirmed`（`coding_plan_id` / `user_id` / `repo_count`）与 `draft_plan_coding_rejected`（`coding_plan_id` / `user_id` / `reason`）两条，均 `category="caller"` / `component="chat"`，best-effort 包裹 |
| T-109-07-04（Info Disclosure，导出文档回显） | 不把 `provenance` 原始取值写进 markdown（有 `weird_value not in content` 断言）；沿用既有 `_md_escape` 脱敏纵深，未新增任何上游文本直写面 |
| T-109-07-05（Info Disclosure，gate 泄漏存在性） | gate 在 service 内、调用点位于视图 owner gate 与项目级 ownership **之后**；非 owner 打第 ③ 步仍是 404（`test_spa_coding_chain_non_owner_gets_404_on_execute_and_export` 全绿，且断言零副作用） |
| T-109-07-06（Spoofing，未知 provenance 取值） | 三处判定统一允许清单，各有一条未知取值用例；负控实测证明改成拒绝清单会让这三条转红 |
| T-109-07-SC（供应链） | 零新增依赖，未执行任何包管理器安装命令 |

## Observability

- **新增两个事件**：`draft_plan_coding_rejected` / `draft_plan_coding_confirmed`，均 `category="caller"`、`component="chat"`（在 LOGGING-SPEC §5 既有清单内，未造新 component）。字段：`coding_plan_id`、`user_id`、拒绝侧 `reason`、确认侧 `repo_count`。
- **触发用户可归因**：`user_id` 取 `structlog.contextvars` 中由统一中间件在 DRF 认证后注入的值，取不到记 `system`。fan-out 是 HTTP 入口 ⇒ 走中间件自动注入，无需显式 `initiated_by_user_id`。
- **不反噬业务**：`_log_draft_coding_gate` 整体 `try/except: pass`；gate 的拒绝路径先留痕后抛异常，留痕失败不影响拒绝行为。
- **无新增 LLM 调用点**（未新增 `call_source`）、**无新增召回**（无 `RetrievalTrace` 义务）、**无新增队列任务 / webhook**。fan-out 端点是既有入口，`RequestMetric` 的 QPS/错误率/时长由中间件层自动覆盖（新增的 400 分支自动纳入错误率）。
- **无脱敏义务**：新增字段均为内部 UUID、布尔与闭集机器码，不含凭证、不含方案正文。导出告示是固定常量文案，不回显上游取值。

## Known Stubs

无占位实现。以下是**按 plan 设计**分派到后续 plan 的下游接线，不是本 plan 的 stub：

- 界面侧草稿横幅 / 折叠态徽标 / 送编码确认弹层 / 按 `code` 分支的 toast 属 **109-08**（UI-SPEC §B/§C）。服务端半边已可独立工作 —— 前端未落地时草稿送编码就已被拒绝，不存在「等前端补齐才安全」的窗口。
- `CodingExecutionSpec.unresearched` 的**容器侧消费**（任务执行器据此调整策略）留后续：本 phase 的契约是「标志出现在 dispatch payload 里」，plan 明确容器侧消费与否不在范围内。

## User Setup Required

None —— 零新增依赖、零迁移、零外部服务配置。

## Next Phase Readiness

- **109-08 可直接对接**：请求体字段名 `acknowledge_unresearched`（布尔）、拒绝响应 `{code: "draft_requires_explicit_confirm", detail: ...}`、`orchestrated` 时字段被忽略 —— 三条后端契约（UI-SPEC §前端数据契约变更 第 3/4/5 条）均已落地并有用例锁。
- ⚠️ **提醒 109-08 执行者**（承 109-06 Next Phase Readiness）：`runtime.provenance` 是 `runtime.coding_plan` 的第三个消费点，**必须过 `runtime.plan_id === props.codingPlanId` 守卫**。漏守卫会把别的方案的 `provenance` 渲染到本卡上 —— 草稿被漏标是安全性方向的失守。`TechPlanCard` 的两个既有 computed 是可逐字沿用的形状。
- ⚠️ **不可协商的不变量**：前端在任何代码路径下都不得自行填 `acknowledge_unresearched: true`（不缓存、不记忆、不因「刚才确认过」而复用）。服务端 gate 落在 session **创建**上，单仓重试同样创建 session、同样被拦，因此重试路径也必须走弹层。
- **存量方案将集体出现草稿标注**：迁移 `default="draft"` ⇒ 历史 `CodingPlan` 送编码都会先被拦一次、导出物都会带告示。这是 **RELY-01 的预期行为**（存量确实全是徒手产物），**不是回归** —— UAT/VERIFICATION 请如实记录。
- **遗留给 UAT 的人工判断**：blockquote 经 `markdown_to_blocks` 转飞书 block 后的视觉呈现（`⚠️` 与加粗是否保留、引用块样式）需实际导出一次确认；界面与文档的口径一致性观感同上（见 coverage D8）。

## Self-Check: PASSED

- 9 个改动文件均存在于磁盘且已提交（`git status --short` 除 SUMMARY 外为空）
- 三个 task commit 均可在 `git log` 中定位：`95fdd5a9` / `c0e89746` / `645869e9`
- `git diff --diff-filter=D --name-only HEAD~3 HEAD` 无输出（三次提交零文件删除）
- 未修改 `.planning/STATE.md` 与 `.planning/ROADMAP.md`（编排器职责）
- 负控实测后的源码已原样恢复（`git status` 空 + 三条用例复跑 3 passed）

---
*Phase: 109-spine-convergence*
*Completed: 2026-07-30*
