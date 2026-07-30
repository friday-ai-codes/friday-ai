---
phase: 113-2
plan: 05
requirements: [FLOW-06, SCHEMA-02, SCHEMA-03, SCHEMA-04, SCHEMA-05]
provides:
  - "`reconcile_cross_repo_apis(blueprint) -> dict`（`services/process_runtime/blueprint_reconcile.py`，**纯函数、顶层零 ORM/零 LLM、`rg \"raise \"` 零命中**）：入参是**完整蓝图 content dict**（只读 `repo_associations` 与 `api_contracts`），**恒定三键返回** `{gaps: [{repository_id, api, reason: \"no_provider\"}], conflicts: [{api, provider_repository_id, consumer_repository_id, field, provider_value, consumer_value}], missing_support_repos: [{repository_id, api, support_repository_id}]}`。单类结论上界 `_MAX_FINDINGS = 50`"
  - "对账判定口径：provider 定位**复用** `blueprint_repo_waves.match_api` 且同样跳过同仓自产自消（两处口径漂移会产出「预排说有 provider、对账说没有」的自相矛盾）；比对字段 `_CONFLICT_FIELDS = (\"method\", \"path\", \"request_schema\", \"response_schema\")`（`direction` 由 provided/consumed 分组本身承担，不比对）；**一侧未声明（None/空串/空容器）不算矛盾**（阶段 2 半成品契约是常态）；`method` 大小写不敏感"
  - "**needs_support 落位路径（B4，唯一口径）**：`api_contracts[i].data_source.availability`（枚举只有 `existing|needs_support`）+ `api_contracts[i].data_source.support_repository_id`。**无顶层 `availability` 字段**——两个模块的读写一律走 `data_source.*`，`rg 'get(\"availability\"' | rg -v data_source` 在两文件均零命中，且各有一条并列防回归断言（只写顶层键那条**不被识别**）"
  - "`BlueprintMergeAdapter(*, synthesizer=None, artifact_service=None, lifecycle_service=None, repo_plan_adapter=None, node_execution_id=\"\")`（全 keyword-only 懒装配）。`async def merge(session) -> dict` **恒定七键返回**：`{validation_status ∈ passed|failed|needs_clarification, artifact_version_id: str, attempt: int, back_target: str, report: dict, reconcile: {gaps,conflicts,missing_support_repos} 计数, stage_state: dict}`。⭐ `passed` 路径 `artifact_version_id` 必非空（113-06 回填 `StageOutcome.current_artifact_version` 的唯一来源）；`needs_clarification` / `failed` 一律 `back_target=\"merge\"`、`artifact_version_id=\"\"`、**不落版本**"
  - "四个模块级纯函数（零 ORM / 零 LLM，可直接单测）：`build_citation_pool(repo_plans, associations) -> (entries: list[dict], cite_map: dict[str,str])` / `project_repo_associations(locked_associations, cite_map) -> list` / `project_current_state(repo_plans, cite_map) -> list` / `derive_must_haves(*, requirement_spec, implementation_overview, api_contracts=None) -> dict`（三键 `truths`/`artifacts`/`key_links` 恒在）"
  - "citation id 约定：`CITATION_ID_PREFIX = \"cit_\"` + `sha1(raw)[:12]`（同一裸串恒得同一 id，重复调用逐字节一致）；池条目形状 `{citation_id, source_type: \"repo_file\", source_id, locator: {path}, title}`。⚠️ `build_citation_pool` **跳过已是 `cit_` 前缀的值**（否则第二轮把上一轮 id 当裸串再造一层池，幂等失效，见 Deviation 3）"
  - "承接口径（W2，三条）：`schema_version` ← `import BLUEPRINT_SCHEMA_VERSION`（**无字面量**）；`meta` ← 融合基线 `content[\"meta\"]` **整段浅合并承接**，只在缺 required 两键时兜底补 `title`（规格 goal 首句）/ `project_id`；`requirement_spec` 与 `citations` 同样承接基线（`citations` 与新池按 `citation_id` 并集去重）。基线 `requirement_spec` 非法即 fail-closed，**绝不改写规格门锁定的 WHAT**"
  - "四段起草的降级最小合法结构 `SECTION_FALLBACKS`（**过 schema，不是 `{}`/`None`/缺键**）：`implementation_overview → {\"requirement_narrative\": [], \"items\": []}`；`api_contracts → []`；`interaction_flows → []`；`impact_analysis → {\"business_impact\": [], \"affected_features\": []}`。单段失败只降级该段，**四段全失败才** `failed`（`report.reason == \"all_sections_failed\"`）"
  - "幂等口径（W6，只对 current 成立）：同一 content_hash 与**当前 current** 相同时不产生新 current 版本 —— 连续两次相同内容 → 版本数不变、返回同一 `artifact_version_id`。`produced_by_ref = f\"blueprint_merge#attempt={attempt}\"`（轮次可归因）。**不含**「历史出现过的 hash 都不翻版本」（A→B→A 会翻第三版，既有语义未改）"
  - "模块常量：`MAX_MERGE_ROUNDS = 2`（同名类属性 `BlueprintMergeAdapter.MAX_MERGE_ROUNDS`）、`_DEFAULT_CITATION_COVERAGE_MIN = 0.8`（本 plan **只定义不消费**）、`STAGE_STATE_KEY = \"merge\"`、`MERGE_SECTIONS` 四段名常量。`stage_state[\"merge\"]` 形状 `{count, status, degraded_sections: [str], gaps, conflicts, missing_support_repos}`（只存计数，< 2KB）"
  - "**adapter 不落 stage_state**（沿用 113-04 决策）：`merge()` 内重读会话新实例 → `{**state, \"merge\": {...}}` 浅合并整体产出，由 113-06 handler 单点持久化；回调路径永不触碰计数"
  - "结构字段权威来源（T-113-28）：`implementation_overview.items` 从 `repo_plan.impl_items` 权威搬（`change_type` / `files_touched` / `depends_on` 不交给起草侧改写），`wave` 取自 `build_api_waves`，起草侧只贡献 `modules` 分组与 `items[].feature_point_id`/`module_id` 映射层；`api_contracts` 骨架同样从 `apis_provided`/`apis_consumed` 搬，起草侧只补 `description`/`request_example`/`response_example`/`data_source` 补充字段"
  - "`_link_api_refs(flows, contracts)`（新增，见 Deviation 4）：把 `interaction_flows[].steps[].api_ref` 从接口名换算成真实契约 id，解析不到**删键**（悬空引用比没有更糟）"
affects:
  - "113-06（质量门 / 归因 / 回退 / stage 注册）：直接消费 `merge(session)` 的七键返回 —— `artifact_version_id` 回填 `StageOutcome.current_artifact_version`、`validation_status` 定出边、`stage_state` 原样落盘、`report.reconcile` 计数入事件 payload。覆盖率门读 `_DEFAULT_CITATION_COVERAGE_MIN` 与 `MAX_MERGE_ROUNDS` 两个模块常量（改接 `SettingKeys` 时替换取值处即可）；`coverage_gaps` 归因按 `blueprint_quality.citation_coverage` 的三类口径写，`__all__` 追加进 `blueprint_reconcile`。⚠️ `blueprint_resume.py` 本 plan **零触碰**，`merge → drafting` 映射仍归 113-06；澄清线程已带 `return_stage=\"merge\"`"
  - "114（AI 对抗审查）：蓝图 `api_contracts[].data_source.availability == \"needs_support\"` 是「需协作仓配合」的**唯一 schema 路径**（无顶层字段）；`citations` 全文档已 id 化且过引用完整性后置检查，重锚定可直接按 `citation_id` 溯源"
  - "115（前端查看器 / 时间线）：结构化事件 `blueprint_merge_started` / `blueprint_merge_completed` / `blueprint_merge_needs_clarification` / `blueprint_merge_section_degraded`（全部 `category=\"caller\"`、`component=\"process_runtime\"`、带 `session_id` 与 `initiated_by_user_id`，completed 带 `duration_ms`）；`degraded_sections` 可直接展示「哪一段是降级产物」"
key-files:
  created:
    - server/services/process_runtime/blueprint_reconcile.py
    - server/services/process_runtime/blueprint_merge.py
    - server/tests/services/process_runtime/test_blueprint_reconcile.py
    - server/tests/services/process_runtime/test_blueprint_merge_stage.py
  modified: []
completed: 2026-07-30
---

# Phase 113-2 Plan 05: 阶段 3 融合装配（六段 + 跨仓 API 对账） Summary

**一行结论**：融合落成两个新文件、零改动既有面（本 plan 恰好 4 个新文件，冻结面 22 项自检全零命中）——`blueprint_reconcile.py` 是顶层零 ORM/零 LLM、`rg "raise "` 零命中的对账纯函数（三键恒定返回，provider 定位复用波次预排的 `match_api` 同口径，可用性读写只走 `data_source.*` 且有并列防回归断言证明顶层同名键不被识别）；`blueprint_merge.py` 把六段拆成「两段确定性投影 + 四段分节起草 + 一段确定性派生」，投影同时填 `rationale.citations`（P-8 唯一防线，覆盖率断言 > 0）、引用池先建后填让全文档 citations 全部 `cit_` id 化并过引用完整性后置检查、单段失败降级为**过 schema 的最小合法结构**（`impact_analysis` 那条断言值恰好是两键而非 `{}`）、基线一律取最新 `version_no`、装配过 `validate_blueprint` 后经 `add_version` 落幂等版本并回带 `artifact_version_id`；48 例新测试全绿（23 零 DB 纯函数 + 25 装配面），`tests/{services/process_runtime,delivery,subagent,mcp_tools}` **1283 passed**（既有 1235 例零回归，唯一失败是 113-02 已登记的子模块守卫），且三条核心防线经变异验证逐一变红。

## Accomplishments

- **FLOW-06 对账半边（纯函数，绝不静默拍板）**：`reconcile_cross_repo_apis` 三类结论恒定三键。provider 定位**复用** `blueprint_repo_waves.match_api` 并同样跳过同仓自产自消——有一条参数化断言把同一组 provided/consumed 同时喂给 `build_api_waves` 与本函数，比对「有 provider」的结论是否一致（口径漂移会产出任何单侧测试都逮不住的自相矛盾）。冲突条目**带 provider/consumer 双值**便于澄清问题直接引用；一侧未声明字段不算矛盾（阶段 2 半成品契约是常态，把「还没写」当「写错了」会刷满澄清噪声）。
- **⭐ B4 落位（两文件双向守住）**：可用性与协作仓的读、写、prompt 输出契约**一律走 `data_source.*`**。两个模块 `rg 'get("availability"' | rg -v data_source` 均零命中；`rg '"available"|"unknown"'` 零命中；对账侧有一条**并列断言**（只写顶层键那条不进 `missing_support_repos`、同语义写进 `data_source` 那条进），装配侧有一条断言 `item["data_source"]["availability"] == "needs_support"` **且** `"availability" not in item`。RepoPlan 专属键 `from_repository_id` 换算进 `data_source.from_service`/`support_repository_id` 后**不落蓝图顶层**（有专门断言）。
- **⭐ 确定性投影可断言「不经推理」**：起草替身四段全返空 dict（零贡献）后装配仍进行，`repo_associations` 与 `current_state_analysis` 完整产出且**逐字段相等**（`repository_id`/`repository_name`/`role`/`decided_by`/`confirmed_at_gate`/`responsibility`/`routing_evidence` 与锁定产物相等；`findings[].title`/`detail` 与 `repo_plan.current_state` 相等——投影**保留源键**而不只映射到 schema 键，正是为了让这条断言是「相等」而不是「大致包含」）。另有一条纯函数级断言：不传 session、不传起草器直接调两个投影函数即可产出结果。
- **⭐ P-8 唯一防线**：`project_repo_associations` 同时填 `rationale`（`text` + `citations`），`citations` 取「源 `rationale.citations` ∪ `fitness.citations`」并集——112 确认门只落后者，不并进来这类条目分子恒 0。3 个 association 的样本断言 `citation_coverage(blueprint) > 0` 且 `repo_associations[0].rationale.citations` 非空。
- **⭐ P-5 引用池先建后填**：`build_citation_pool` 走查七类证据面产出 `cit_` + `sha1(raw)[:12]` 池条目与 `raw → id` 映射；各段只填池内 id，池外裸串丢弃计数。基线池 id 追加**恒等映射**（否则 112 落的池内 id 会被当池外裸串丢掉，覆盖率归零）。运行时断言：装配产物过 `validate_blueprint` 为 `(True, None)`，且全文档每个 citations 值都是 `cit_` 前缀且都能在顶层池里找到（裸路径零残留）。block 级 `citations` 一律丢弃（见 Deviation 7）。
- **⭐ W2 三条承接 + 降级最小合法结构**：顶层 required 十一键齐全（断言 `set(BLUEPRINT_JSON_SCHEMA["required"]) <= set(assembled)`）；`schema_version` 用 import 常量（`rg '"blueprint/v1"'` 零命中）；`meta` 整段承接并断言基线的 `summary`/`revision_round`/`language` 三个非 required 键**未丢**。四段逐段各一条降级用例：其余三段仍产出、整体仍 `(True, None)`、`validation_status == "passed"`；`impact_analysis` 那条额外断言降级值**恰好** `{"business_impact": [], "affected_features": []}`。四段全抛才 `failed` 且不落版本（另一条用例）。
- **must_haves 确定性派生（111 无现成代码，本 plan 新写）**：形态照 `derive_execution_plan`（排序全部显式化，同输入逐字节一致）。`truths` 逐功能点模板化成断言句、`artifacts` 按 `path` 去重聚合、`key_links` 含实现项 `depends_on` 边与 `api_contracts` 的 provider→consumer 边；空输入时三键仍在且都是 `[]`（有专门断言：`== {"truths": [], "artifacts": [], "key_links": []}`）。
- **分节而非单次巨 prompt**：四段各一个 `_adraft_*`，各自 `with use_call_source(CallSource.BLUEPRINT_MERGE)`（`rg -c` = 5：四段 + 默认起草器内一次，contextvar token 式嵌套安全）。每段 prompt 用**可空串 section 插槽**（`_cross_repo_section` / `_unresolved_section` / `_citation_section` 无该类证据时恒为空串，prompt 与基础形态逐字一致）；system 与 human 分离。断言：起草器被调用 **4 次**、section 参数是四段名、四份 `human` 互不相同（可证伪「单次巨 prompt」）。
- **SCHEMA-03/04/05 形状断言**：`items[]` 逐项 `change_type` ∈ 枚举且 `wave >= 1`，跨 item 的仓内 `depends_on` 投影成蓝图 item id，`files_touched` 由 `change_type` 映射出 `action`；`flows[].steps[].seq` 递增、六要素字段（`component`/`api_ref`/`data_in`/`data_out`/`alternative_paths`/`trigger`）在位且 `api_ref` 已换算成真实契约 id；`api_contracts[]` 含 `request_example` / `response_example` / `data_source`。
- **INV-6 与观测**：本文件零 ORM 写——版本只经 `ArtifactService.add_version`、线程只经 `BlueprintLifecycleService.open_thread`（`return_stage="merge"` 硬编码 + 注释登记 B3，测试断言 `thread.return_stage == "merge"`）。四个结构化事件全部带 `category`/`component`/`session_id`/`initiated_by_user_id`，completed 带 `duration_ms`；异常文本一律 `redact_secrets_in_text` + 截断 500；澄清问题只列契约名与双方取值（有一条断言方案正文 `"写 view + serializer"` **不在** question body 里）；`_log` 整体 try/except 吞掉，观测绝不反噬主链。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `0ac30da3` | `blueprint_reconcile.py` 对账纯函数（三键恒定 / 复用 `match_api` / 只认 `data_source.*`）+ 23 例零 DB 测试 |
| 2 | `fd361d5e` | `blueprint_merge.py`（引用池 / 两段投影 / 四段分节起草 + 降级 / `derive_must_haves` / 对账接线 / 幂等落版本 / `_link_api_refs`） |
| 3 | `aa68fd37` | `test_blueprint_merge_stage.py` 25 例（投影逐字段一致 / 覆盖率 / 引用完整性 / 幂等 / 对账闭环 / 三段 schema 形状） |

> Task 2 的 `<verify>` 指向 Task 3 才创建的测试文件，故实际执行是「模块与测试一起做绿 → 分两个 commit（模块、测试）」。两个 commit 各自可独立回滚，但 Task 2 单独 checkout 时没有测试守护。

## Files

- `server/services/process_runtime/blueprint_reconcile.py`（新建 ~215 行：三段模块 docstring、`_CONFLICT_FIELDS`/`_MAX_FINDINGS` 常量、`reconcile_cross_repo_apis` + 8 个内部纯函数）
- `server/services/process_runtime/blueprint_merge.py`（新建 ~1080 行：六段模块 docstring、常量区（`MAX_MERGE_ROUNDS`/`SECTION_FALLBACKS`/枚举白名单）、`BlueprintSectionSynthesizer` Protocol + `LLMBlueprintSectionSynthesizer` + 复制的 `_content_to_text`/`_parse_json`、基元 helper（block/引用映射/摘要）、`build_citation_pool`、两个投影函数、`derive_must_haves`、`_MergeInputs` dataclass + 四段 prompt 构造、四段归一器、`_apply_needs_support`/`_link_api_refs`/`_pick_availability`、`BlueprintMergeAdapter` 15 个成员）
- `server/tests/services/process_runtime/test_blueprint_reconcile.py`（新建 23 例，零 DB 零 mock）
- `server/tests/services/process_runtime/test_blueprint_merge_stage.py`（新建 25 例，`django_db(transaction=True)` + `asyncio`，`_FakeSynthesizer` / `_FakeRepoPlanAdapter` 两个替身 + 6 个工厂）

## Decisions

- **`api_contracts` 只采纳 RepoPlan 里存在的契约**：起草侧只补 `description` / 请求响应示例 / `data_source` 补充字段，起草侧独有的契约条目**丢弃**。T-113-27/28 明确把「编造接口」列为 mitigate 项，而 `api_contracts` 会成为 114 审查与编码执行的输入基线。副作用：RepoPlan 无结构化接口时该段为空（这正是 113-06 覆盖率归因该点名的输入缺口，不是本段的 bug）。
- **投影保留源键 `title` / `detail`**：schema `additionalProperties` 默认允许，保留后「投影与上游逐字段一致」可被直接断言（相等而非包含），同时补齐 schema 要求的 `id`/`text`/`kind`/`citations`。
- **`current_state_analysis` 按 `repo_associations` 仓集过滤**（在 `merge()` 内，不在纯函数内）：后置检查 (c) 要求该段 `repository_id` 必须出现在 `repo_associations`，某仓有方案但未进关联清单时整份会判非法。纯函数保持「只吃 repo_plans」的单一职责，过滤义务写进其 docstring。
- **`requirement_spec` 承接基线、坏了就 fail-closed**：那是规格门锁定的 WHAT，融合无权改写。有一条用例构造非法基线（`goal` 不是数组）断言 `failed` 且版本数不变。
- **不新增 `ConvergenceSessionEvent` 类型**（沿用 113-03 决策）：`event_taxonomy.py` 是绝对冻结面且没有 `blueprint.merge.*` 常量，故本 plan 观测**只走 structlog**（四事件齐全），事件行补齐随 stage 注册归 113-06。
- **adapter 不落 `stage_state`**（沿用 113-04 决策）：返回浅合并结果由 113-06 handler 单点写；并行路径写单行 JSON 就是 prohibitions 点名的 lost-update 场景。
- **澄清线程幂等按「该 artifact 有 OPEN blocking 澄清就不叠开」**：融合每轮重进都会重跑对账，逐轮开线程会刷爆 HITL 面板；已有阻塞线程时会话本就停着，再开一条零收益。
- **block 级 `citations` 在归一时一律丢弃**：外来 block 的 citations 通常是裸串，留着会让引用完整性后置检查判**整份**非法；证据由外层条目（finding / item / contract / feature）的 `citations` 承载——那也正是 `citation_coverage` 的三类口径。

## Deviations from Plan

共 9 处：3 处为 PLAN 前提/签名与本仓事实不符的修正，2 处为实测暴露的必要补强，3 处为设计口径的显式收敛，1 处为范围外未修。

**1. [Rule 3 - PLAN 签名不足] `derive_must_haves` 增 `api_contracts: list | None = None` 第三个 keyword-only 入参**

- **Found during:** Task 2
- **Issue:** PLAN 给的签名是 `derive_must_haves(*, requirement_spec, implementation_overview)`，但同一段 action 又要求「`key_links` ← `items[].depends_on`（仓内）**与 `api_contracts` 的 provider→consumer 边**」——两个入参里没有任何信息源能给出 API 边。
- **Fix:** 增一个带默认值的 keyword-only（缺省 `None` 时只派生实现项依赖边，绝不编造 API 边）。测试两条都覆盖（含 provider→consumer 边那条）。
- **Files modified:** `blueprint_merge.py`、`test_blueprint_merge_stage.py`
- **Commit:** `fd361d5e` / `aa68fd37`

**2. [Rule 1 - PLAN 前提不成立] `meta.project_id` 兜底不能取 `str(session.project_id)`**

- **Found during:** Task 2
- **Issue:** PLAN 的 (c2) 写「`project_id`（取 `str(session.project_id)`）」，但 `ConvergenceSession` **没有** `project_id` 列（实测 `delivery/models/convergence_session.py`；`blueprint_lifecycle_service` 模块 docstring P10 也明写「Artifact 无 project FK，项目归属只在 `content.meta.project_id`」）。照 PLAN 写会 `AttributeError`，而这条路径正是「基线 meta 缺 required 键」时的最后防线。
- **Fix:** `_resolve_project_id(session)` 按「feature list 入口的 `decomposition.feature_meta.project_id` → 会话 id」兜底，并在 docstring 写明「正常路径根本走不到这里：基线 `meta` 已带该键」。有一条用例构造缺 `project_id` 的基线 meta 断言兜底非空且非 required 键未丢。
- **Files modified:** `blueprint_merge.py`
- **Commit:** `fd361d5e`

**3. [Rule 1 - 幂等实测缺口] `build_citation_pool` 必须跳过已是 `cit_` 前缀的值，否则融合不幂等**

- **Found during:** Task 3（幂等用例第一次跑就红）
- **Issue:** 第二次 `merge()` 的融合基线是**第一轮刚落的版本**，其 `fitness.citations` / `rationale.citations` 已是池内 id。走查它们时 `build_citation_pool` 把 `cit_xxx` 当成新裸串，又造一条 `cit_sha1("cit_xxx")` 条目 —— 引用池每轮膨胀一层，`content_hash` 每轮变化，`add_version` 的幂等**直接失效**（实测两次相同输入落了两个版本）。这是 PLAN 未预告的口子：PLAN 只交代了「基线池 id 要并union」，没交代「走查时要排除它们」。
- **Fix:** `_add` 内加 `not raw.startswith(CITATION_ID_PREFIX)` 过滤并写明理由。幂等用例随即变绿（版本数只 +1、两次 `artifact_version_id` 相同）。
- **Files modified:** `blueprint_merge.py`
- **Commit:** `fd361d5e`

**4. [Rule 2 - 缺失关键功能] 新增 `_link_api_refs`：把 `steps[].api_ref` 从接口名换算成真实契约 id**

- **Found during:** Task 2
- **Issue:** 契约 id 是服务端装配时才生成的（`api_{方向}_{仓短id}_{摘要}`），起草侧只知道接口名。不换算的话 SCHEMA-04 的「经哪个接口」这一环**跳不过去**（`api_ref` 按 schema 语义应引用 `api_contracts` 的契约 id），而留一个悬空 ref 比没有更糟（115 渲染会指向不存在的契约）。
- **Fix:** 装配前跑一次 `_link_api_refs(flows, contracts)`：按契约 id / name / path 建索引就地改写，解析不到就**删键**。测试断言 `steps[0]["api_ref"] in {contract ids}`。
- **Files modified:** `blueprint_merge.py`、`test_blueprint_merge_stage.py`
- **Commit:** `fd361d5e` / `aa68fd37`

**5. [Rule 1 - PLAN 测试用例内部矛盾] Task 3 用例 1 的「四段全抛」形态与 action 第 4 步不可同时成立**

- **Found during:** Task 3
- **Issue:** 用例 1 要求「四段全部抛异常 → **装配结果里**两段仍完整产出」，而 action 第 4 步定的是「四段全失败才返回 `{"validation_status": "failed"}`」—— failed 路径根本不装配，也不落版本，没有「装配结果」可查。
- **Fix:** 按 PLAN 用例自带的另一个选项（「**或返回空**」）落主用例：四段返空 dict（零贡献、无异常）→ 装配照常进行 → 断言两段逐字段一致 + 起草器确实被问过四次。另补两条使覆盖不缩水：① 四段全抛 → `failed` + `report.reason == "all_sections_failed"` + 版本数不变；② 纯函数级断言（不传 session、不传起草器直接调两个投影函数）。三条合起来比原用例更强。
- **Files modified:** `test_blueprint_merge_stage.py`
- **Commit:** `aa68fd37`

**6. [Rule 1 - 起草侧独有契约不采纳] `api_contracts` 骨架只从 RepoPlan 搬**

- **Found during:** Task 3（降级用例发现 `api_contracts` 为空）
- **Issue:** PLAN 把 `api_contracts` 列为「起草的四段」之一，但 T-113-27/28 又要求结构字段从 RepoPlan 搬、不让起草侧编造接口。两者的交集只能是「骨架来自 RepoPlan，起草侧只补描述与示例」。
- **Fix:** 按上述口径实现（起草侧独有的契约条目丢弃），并把测试工厂的默认 `repo_plan` 补上一条**仅本仓可见**的 `apis_provided`（名字带仓 id，跨仓天然不匹配），使各用例的 API 段非空而不会意外配出 provider/consumer 对。副作用已写入 Decisions 与 affects（RepoPlan 无结构化接口 ⇒ 该段为空，归 113-06 覆盖率归因）。
- **Files modified:** `blueprint_merge.py`、`test_blueprint_merge_stage.py`
- **Commit:** `fd361d5e` / `aa68fd37`

**7. [Rule 2 - 引用完整性防线补强] 归一时丢弃 block 级 `citations`**

- **Found during:** Task 2
- **Issue:** `validate_blueprint` 后置检查 (a) 递归走查**任何** `citations` 列表（含 `$defs/block` 的），起草侧 block 里的裸串会让整份判非法。而 PLAN 的引用池口径只覆盖了条目级 citations。
- **Fix:** `_sanitize_block` 只保留 schema 已知键并**丢弃 block 级 `citations`**（docstring 写明证据由外层条目承载，那也是覆盖率口径）。运行时断言「全文档 citations 值全部 `cit_` 前缀且都在池内」即由此成立。
- **Files modified:** `blueprint_merge.py`
- **Commit:** `fd361d5e`

**8. [Rule 3 - 验收 grep 与格式化冲突] 两处代码改写以满足「读写只走 `data_source.*`」的可 grep 性**

- **Found during:** Task 2（跑验收 grep）
- **Issue:** `ruff format` 会把 `str(plan_ds.get("availability") or drafted_ds.get("availability") or "")` 折行，使 `get("availability"` 落在**不含 `data_source` 字面量**的行上 —— 验收 grep `rg 'get("availability"' | rg -v data_source` 因此非零，尽管语义上读的确实是 `data_source` 层。
- **Fix:** 抽出 `_pick_availability(*candidates)`（循环变量名即 `data_source`，语义更清晰且逐行可 grep）；同理 `_adraft` 通用方法拆回四个 `_adraft_*` 各自持一个 `use_call_source(CallSource.BLUEPRINT_MERGE)`（满足「四段各自声明」且 `rg -c` = 5）。两处都是等价改写，无行为变化。
- **Files modified:** `blueprint_merge.py`
- **Commit:** `fd361d5e`

**9. [Rule 3 - 范围外，未修] `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 仍因子模块未 checkout 失败**

- **Found during:** verification
- **Issue:** 该守卫读 `skills/skills/*/SKILL.md`，本 worktree 的 `skills/` 子模块未 checkout。113-02 偏差 5 / 113-04 偏差 5 已两次登记，与本 plan 改动零因果（本 plan 未触碰 `mcp_tools/` 与 `task/`）。
- **Fix:** 按范围纪律不修。等价验收：`tests/mcp_tools/` 其余 231 例全绿。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/services/process_runtime/test_blueprint_reconcile.py`：**23 passed**（零 DB 零 mock —— 无 provider / 同仓自消 / 缺协作仓两形态 / ⭐顶层 availability 不被识别 / `method`·`request_schema`·`response_schema` 三类冲突 + 一侧缺值不算矛盾 / 完全闭环三键全空 / 9 种非法输入恒不抛 / ⭐与 `build_api_waves` 口径一致（参数化两向））
- `tests/services/process_runtime/test_blueprint_merge_stage.py`：**25 passed**（⭐投影零贡献仍逐字段一致 / 四段全抛才 failed 且不落版本 / 纯函数级投影 / ⭐覆盖率 > 0 / ⭐引用完整性 + 裸路径零残留 / ⭐基线读最新版本 / must_haves 三键·去重·空输入 / 分节 4 次 + 四份 prompt 互异 / ⭐单段降级参数化四条 + `impact_analysis` 两键断言 / 十一键 + meta 承接 + meta 兜底 / ⭐冲突开线程带 `return_stage` 且不落版本 + 澄清文本零方案正文 / 缺协作仓开线程 / ⭐needs_support 落 `data_source` 且顶层零残留 / 幂等两次版本数只 +1 / 非法基线 failed / 无基线 failed / 七键恒定形状 / SCHEMA-03·04·05 形状）
- **PLAN verification 全套**：`uv run pytest tests/services/process_runtime/ tests/delivery/ tests/subagent/ tests/mcp_tools/ -q` → **1283 passed, 2 skipped, 1 failed**（既有 1235 例零回归；唯一失败是 Deviation 9 的子模块守卫）
- `uv run python manage.py makemigrations --check --dry-run`：退出码 **0**（零模型改动）
- `uv run ruff check services/process_runtime/`：All checks passed；`ruff format --check` 两个新模块与两个测试文件均已格式化（本 plan 只对自己新建的 4 个文件跑过 format）
- ⭐ **变异验证（三条核心防线的证伪能力实测，非声明）**：
  1. 把 `_project_rationale` 的 `citations` 短路成 `[]` → `test_citation_coverage_is_positive_after_projection`（**P-8**）fail；
  2. 把 `_apply_needs_support` 改成写**顶层** `contract["availability"]` → `test_unprovided_consumed_gets_needs_support_under_data_source_only`（**B4**）fail；
  3. 把 `impact_analysis` 的降级值改成 `{}` → `test_impact_analysis_degradation_keeps_both_required_keys`（**W2**）fail。
  三处变异**已全部回滚**（`rg "MUTATION"` 零命中、回滚后 25 例全绿）。三条断言确实能逮住防线失效，不是恒真断言。
- **冻结面自检**：本 plan 三个 commit 触及的文件**恰好 4 个**（`git diff --name-only 0ac30da3~1 HEAD` 全部在两个新模块与两个新测试）；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / entrypoint / blueprint_schema / blueprint_quality / blueprint_route / blueprint_spec_gate / blueprint_confirm_gate / blueprint_resume / blueprint_lifecycle_service / charter_service / system/{models,settings_service} / event_taxonomy / call_source / subagent/api/callbacks / task/core/knowledge_tools` **零命中**；`git diff --name-only | rg "^web/|^task/"` 零命中
- **运行时验收（acceptance greps 逐条）**：`blueprint_reconcile.py` —— `^from delivery|objects\.|sync_to_async|ainvoke|build_chat_model` 零命中、`raise ` 零命中、四个结论键全命中、`data_source` 14 处、`"available"|"unknown"` 零命中、顶层 `get("availability"` 零命中、`match_api` 命中；`blueprint_merge.py` —— 四个纯函数全命中、`rationale` 13 处、`order_by("-version_no")` 命中、`session.current_artifact_version` 零命中、`use_call_source(CallSource.BLUEPRINT_MERGE)` = 5、不 import 冻结 analog、`artifact_version_id` 命中、顶层 availability 零命中、`BLUEPRINT_SCHEMA_VERSION` 命中且 `"blueprint/v1"` 字面量零命中、`"business_impact": []` 命中、`return_stage="merge"` 命中、`produced_by_ref=f"blueprint_merge#attempt=` 命中、`rg "对账|reconcile" | rg -i "ainvoke|llm"` 零命中

## Self-Check: PASSED

- 文件存在：4 个 key-files 全部命中（4 新建 / 0 修改）
- commit 存在：`0ac30da3` / `fd361d5e` / `aa68fd37` 均在 `git log`
- artifacts contains 断言：`def reconcile_cross_repo_apis` ∈ `blueprint_reconcile.py` ✓；`needs_support` ∈ `blueprint_reconcile.py` ✓；`def derive_must_haves` ∈ `blueprint_merge.py` ✓；`citation_coverage` ∈ `test_blueprint_merge_stage.py` ✓；`conflicts` ∈ `test_blueprint_reconcile.py` ✓
- key_links 断言：`validate_blueprint` ∈ `blueprint_merge.py`（装配后只读调用，该模块零改动）✓；`add_version` ∈ `blueprint_merge.py`（带 `produced_by_ref='blueprint_merge#attempt=N'`）✓；`reconcile_cross_repo_apis` ∈ `blueprint_merge.py`（装配前跑纯函数对账，非空即开澄清）✓
- must_haves truths 逐条：两段投影零起草贡献仍逐字段一致 ✓／投影同填 `rationale.citations` 且覆盖率 > 0 ✓／引用池先建后填、装配过 `validate_blueprint` 为 `(True, None)` ✓／对账纯函数且 needs_support 落 `data_source` 两键、缺协作仓进 `missing_support_repos` 抛澄清、字段不一致进 `conflicts` 绝不静默拍板、顶层字段与非法枚举变体零残留 ✓／`schema_version` 与 `meta` 承接 ✓／四段降级为过 schema 的最小合法结构 ✓／`must_haves` 确定性派生三键齐全 ✓／幂等只对 current 成立（连续两次版本数不变、返回同一 current）✓／`items[]` 带 `change_type`+`wave`、`interaction_flows` 覆盖六要素、`api_contracts` 含示例与数据来源 ✓

## Next Phase Readiness

- **113-06（质量门 / 归因 / 回退 / stage 注册）**：① `_h_bp_merge` 调 `BlueprintMergeAdapter(node_execution_id=...).merge(session)`，按 `validation_status` 定出边（`passed`/`failed`/`needs_clarification`），**用 `artifact_version_id` 回填 `StageOutcome.current_artifact_version`**（本蓝图链首个用到该字段的 handler），`stage_state` 原样落盘（adapter 不自己写）。② 覆盖率门读 `blueprint_quality.citation_coverage(content)` 与本模块的 `_DEFAULT_CITATION_COVERAGE_MIN`；接 `SettingKeys` 时只需替换取值处。③ `coverage_gaps` 归因请按 `citation_coverage` 的三类口径写并追加进 `blueprint_reconcile.__all__`；`current_state_analysis`/`repo_associations` 两类条目都带 `repository_id`，可直接定位到仓。④ `blueprint_resume.py` 本 plan **零触碰**，`repo_plan`/`merge` → `drafting` 的 stage→status 映射仍归 113-06；本 plan 开的澄清线程已带 `return_stage="merge"`。⑤ 超界转 `STAGE_DONE` 携未决项时，未决项清单可直接取 `report`（对账三键原文）与 `stage_state["merge"]["degraded_sections"]`。
- **114（AI 对抗审查）**：`needs_support` 的唯一 schema 路径是 `api_contracts[].data_source.availability`（**无顶层字段**）；全文档 citations 已 `cit_` id 化且过引用完整性检查，重锚定按 `citation_id` 溯源即可。
- **给后续 writer 的硬约束**：① 新增/改动 `api_contracts` 的可用性一律走 `data_source.availability`（枚举只有 `existing|needs_support`）+ `data_source.support_repository_id`，**绝不**引入顶层字段或 `available`/`unknown` 变体。② 任何段落新增 `citations` 必须经 `_map_citations` 换成池内 id（裸串直落会让整份判非法）；`repo_associations` 类条目的覆盖率口径是 `rationale.citations`，**不是** `fitness.citations`。③ 单段起草失败的降级值必须取 `SECTION_FALLBACKS`（过 schema 的最小合法结构），禁止 `{}`/`None`/缺键。④ 融合基线一律 `order_by("-version_no")`，绝不读会话钉住的那一版。⑤ 新增 `open_thread` 调用必须带 `return_stage="merge"`。⑥ 走查引用时必须排除已是 `cit_` 前缀的值，否则幂等失效（Deviation 3）。
