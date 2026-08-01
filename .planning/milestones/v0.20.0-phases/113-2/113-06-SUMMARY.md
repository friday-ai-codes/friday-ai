---
phase: 113-2
plan: 06
requirements: [FLOW-06, SCHEMA-02, BUS-03]
provides:
  - "`SettingKeys.BLUEPRINT_MERGE_CONFIG = \"blueprint.merge.config\"`（`system/models.py` **纯追加**，`git diff | rg \"^-\"` 为 0 行）。value 为 JSON `{\"citation_coverage_min\": float, \"max_merge_rounds\": int}`；缺配置/非 JSON/顶层为 list/空串/缺键/值类型错**六形态一律回落模块常量**（`_DEFAULT_CITATION_COVERAGE_MIN = 0.8` / `MAX_MERGE_ROUNDS = 2`）且不抛。读取只调既有 `settings_service.aget_json_setting`（`settings_service.py` 一行未改）"
  - "`blueprint_reconcile.coverage_gaps(blueprint) -> list[dict]`（**纯函数、恒不抛、`rg \"raise \"` 零命中**）：与 `blueprint_quality._iter_key_conclusion_citations` **同源三类遍历**（`current_state_analysis[].findings[]` → `repo_associations[].rationale.citations` → `impact_analysis.affected_features[]`，顺序一致），逐条产出**恒定三键** `{\"section\", \"index\", \"repository_id\"}`。`index` 是该条目在**本 section 遍历序**内的序号（与覆盖率分母逐条对齐）；`repository_id` 从条目自身/父条目解析（`affected_features` 取 `repository_ids[0]`），解析不到填空串。遍历实现**本模块自写**（不 import 受限模块私有 generator），判定复用同款 `_cited`（非空 list 即已引用）。有界 `_MAX_FINDINGS = 50`，已追加进 `__all__`"
  - "`blueprint_merge.decide_back_target(gaps) -> dict`（**纯函数，零 ORM，可直接单测**）：**恒定三键** `{\"back_target\": \"repo_plan\"|\"merge\"|\"\", \"back_repository_id\": str, \"gap_count\": int}`。能解析出仓的缺口按仓聚合 → 取缺口最多的仓回该仓 `repo_plan`（排序键显式化 `(-count, rid)`，同数时按仓 id 升序取定 ⇒ 同输入恒同归因）；全都解析不出仓 → 回 `merge`；`gaps` 为空 → 三键全空。`gap_count` 是**该归因对应的**缺口数（单仓档 = 该仓缺口数，融合档 = 全部缺口数）"
  - "`merge()` 新增**第四、第五种 `validation_status`**（既有 passed/failed/needs_clarification 三条出口的键集与语义**逐字未变**，113-05 那条 `set(result) == 七键` 形状断言仍绿）：① `\"retry\"`——覆盖率未达标且回退轮次未用尽，**不落版本**，额外键 `back_repository_id` / `gap_count`，`report = {coverage, min, gaps: <计数>, gap_locations: <前 30 条定位>}`；② `\"exhausted\"`——轮次用尽，**仍落版本**（`artifact_version_id` 非空）+ 额外键 `unresolved`（未决项定位清单，**只含 section/index/repository_id 标量**）/ `back_repository_id` / `gap_count` + 开一条 blocking 澄清线程。`_result` 加 `extra: dict | None` kwarg，只有这两条出口传它"
  - "覆盖率门位置：**`validate_blueprint` 通过之后、`add_version` 之前**（schema 非法的产物连归因都不做——缺口清单会指向一份本就非法的文档）。轮次判据 `attempt + 1 <= max_rounds`：attempt=0/1 → retry，attempt=2 → exhausted"
  - "`stage_state[\"merge\"]` 形状扩两键（只在覆盖率门出口写）：`unresolved: [{section,index,repository_id}]`（上界 `_MAX_UNRESOLVED = 30`）与 `last_attribution: {back_target, back_repository_id, gap_count}`；`count` 恒为 `attempt + 1`（轮次只在 `merge()` 单点递增，`{**state, ...}` 浅合并**整体回写**，回调路径永不触碰）"
  - "**四处 `open_thread` 的 `return_stage` 取值约定（B3）**：`blueprint_merge._aopen_clarification`（对账矛盾）与 `blueprint_merge._aopen_coverage_clarification`（覆盖率超界）一律 `\"merge\"`；`builtin_processes._abp_ensure_blocking_clarification` 传**本 stage 名**（`repo_plan` / `merge`）；`blueprint_repo_plan` 既有两处仍 `\"repo_plan\"`。漏传即让人审恢复退回阶段 1"
  - "distill 沉淀 hook `BlueprintMergeAdapter._adistill_context_entries(session)`（BUS-03）：读 `kind ∈ {decision, contract, api_surface}` 且 `status=\"active\"` 的总线条目（逐 kind 各调一次 `read_entries`，`limit=200`）→ `_distill_text` 拼**有界**（`_MAX_DISTILL_CHARS = 6000`）会话文本（只取 `conclusion/decision/summary/description/text/name` 首个命中字段）→ `MemoryDistiller().distill_to_draft(project_id=..., conversation_text=..., proposed_by=<真实 User>, initiated_by_user_id=str(user.id))`。**调用点：`passed` 与 `exhausted` 两条出口各一次；`retry` 中途不沉淀**（会话未定稿，此时产草案是噪声）"
  - "distill 的两条跳过条件（**都不伪造**）：① `session.created_by` 解析不到 User（`_aresolve_session_user`，本模块自写的 `@sync_to_async` 同款，不 import `blueprint_research_adapter` 私有名）→ 直接 return；② 项目归属解析不到（`_aresolve_bus_project_id` 取本会话总线条目上的 `project_id`——`ConvergenceSession` 无 project 列）→ 直接 return。整段 `except Exception` 吞掉 + `blueprint_context_distill_failed` warning"
  - "`technical_blueprint` stage graph **九 stage**（前七个一字未动）：`repo_plan`（`plan_dispatched`→self / `plan_complete`→`merge` / `needs_clarification`→self，`pausable=True`，`wait_status=\"waiting_event\"`）与 `merge`（`merged`→`STAGE_DONE` / `repo_rework`→`repo_plan` / `remerge`→self / `needs_clarification`→self，`pausable=True`，`wait_status=\"waiting_clarification\"`）。**114 接续点 = `merge.transitions[\"merged\"]`**：改成 `\"ai_review\"` 即可，无需改 engine"
  - "`_h_bp_repo_plan` event 白名单三值：`plan_dispatched` / `plan_complete` / `needs_clarification`（不透传 adapter 返回值）。调用面：`aplan_waves` → `dispatch_plans` → `aexpire_stale_waiters` + `aredispatch_waiting_repos`（**113-04 的 barrier 挂载点在此**，整段 try/except 不反噬）→ `acollect_repo_plans` → `aall_repo_plans_ready` → `build_stage_state(plans=, dispatched=, pending=, waves=<stage_state_summary>)`"
  - "`_h_bp_merge` event 白名单四值：`merged`（`passed` **与 `exhausted` 都走它**）/ `repo_rework`（`retry` 且 `back_target == \"repo_plan\"`）/ `remerge`（其余 `retry`）/ `needs_clarification`（`needs_clarification` / `failed` / 未知值 / 缺依赖）。⭐ 首个回填 `StageOutcome.current_artifact_version` 的蓝图 handler"
  - "entrypoint `build_blueprint_engine` deps **现六个属性**：`spec_gate` / `route` / `research` / `confirm_gate` / `repo_plan`（`BlueprintRepoPlanAdapter(node_execution_id=...)`）/ `merge`（`BlueprintMergeAdapter(node_execution_id=...)`）；docstring 名单同步（P-9 三方一致，有一条断言逐名核对 docstring / SimpleNamespace / handler getattr）"
  - "`blueprint_resume._STAGE_BLUEPRINT_STATUS = {\"repo_plan\": \"drafting\", \"merge\": \"drafting\"}` + `_resolve_stage_status(session)`（未登记 stage 含前七个与空串一律回落 `BlueprintStatus.RESEARCHING`）。**前七 stage 映射结果逐字等价 112**（它们不在表内 ⇒ 三处取值与改动前完全相同），由七条参数化端到端断言 + 七条纯函数断言背书。表值用字面量（本模块所有模型 import 都是 lazy，模块级表拿不到枚举），与枚举同值由 `test_stage_status_table_matches_enum` 锁死"
  - "`aresume_blueprint_session` 的 `WAITING_EVENT` 早退判据**已核实无需改**：`repo_plan` 的 `plan_dispatched` self-loop 走 `wait_status=\"waiting_event\"`，派发后 task 非终态 ⇒ 既有 `aall_research_tasks_terminal` 判据正确短路；真正卡死的形态（一个仓也没派出去且无在途容器）由新增的 `_abp_repo_plan_is_stuck` 转成 `needs_clarification` + 阻塞线程处置，**不需要**扩大 `blueprint_resume` 的改动面"
  - "**唯一非纯追加改动登记**：`builtin_processes.py` 的 `repo_confirmation.transitions[\"confirmed\"]`（`STAGE_DONE` → `\"repo_plan\"`）—— `git diff | rg \"^-\" | rg -v \"^---\" | rg -v \"^-\\s*#\"` **恰好 1 行**（另有 2 行被替换的「113 接续点」注释）"
affects:
  - "114（AI 对抗审查）：接续点是 `_TECHNICAL_BLUEPRINT_STAGES[\"merge\"].transitions[\"merged\"]`（现 `STAGE_DONE` → 改 `\"ai_review\"`）。超界会话的未决项在 `stage_state[\"merge\"][\"unresolved\"]`（含 `last_attribution`），版本**已落**且 `session.current_artifact_version` 已回填，审查侧可直接读；蓝图状态此时是 `drafting` 或 `needs_clarification`（`return_status=drafting`），`drafting → ai_reviewing` 是合法边"
  - "115（前端/时间线）：新增 structlog 事件 `blueprint_merge_coverage_gate_retry` / `blueprint_merge_coverage_gate_exhausted`（含 `coverage` / `min_ratio` / `gap_count` / `unresolved_count` / `back_target`）、`blueprint_context_distill_completed`、`blueprint_stage_drafting_map_skipped`、`blueprint_stage_clarification_open_failed`、`blueprint_repo_plan_waiter_maintenance_skipped`。阶段 2/3 的展示态是 `drafting`（不再是 `researching`）"
  - "所有 process 链（含旧 technical_plan / echo）：engine 现在**只在 handler 真产出版本时**才写 `session.current_artifact_version`（见 Deviation 1）。旧链行为只会变好（此前每次不产版本的转移都把指针抹成 NULL）"
  - "后续任何新增 blueprint stage：若其 `needs_clarification` 是 self-loop，**必须**保证返回该 event 时蓝图上有 open+blocking 线程（否则续驱会推到 `max_steps` 落 FAILED）。可直接复用 `builtin_processes._abp_ensure_blocking_clarification`"
key-files:
  created:
    - server/tests/services/process_runtime/test_blueprint_merge_gate.py
    - server/tests/services/process_runtime/test_blueprint_distill.py
    - server/tests/services/process_runtime/test_blueprint_status_stage_map.py
  modified:
    - server/system/models.py
    - server/services/process_runtime/blueprint_reconcile.py
    - server/services/process_runtime/blueprint_merge.py
    - server/services/process_runtime/builtin_processes.py
    - server/services/process_runtime/entrypoint.py
    - server/services/process_runtime/blueprint_resume.py
    - server/services/process_runtime/engine.py
    - server/tests/services/process_runtime/test_blueprint_process_graph.py
    - server/tests/delivery/test_blueprint_gate_api.py
completed: 2026-07-30
---

# Phase 113-2 Plan 06: 覆盖率门 / 归因回退 / 阶段 2-3 接线 收口 Summary

**一行结论**：阶段 2/3 正式接进 `technical_blueprint`（`repo_confirmation --confirmed--> repo_plan --plan_complete--> merge --merged--> STAGE_DONE` 四跳可达，`builtin_processes.py` 的非纯追加改动**恰好 1 行**、`_TECHNICAL_PLAN_STAGES` 零触碰、handler 7→9、`register_process_type` 仍 3），引用覆盖率门以可配阈值生效并按 `coverage_gaps` 定位做两档归因回退（合计 ≤2 轮，超界转 `exhausted`：**仍落版本 + 带未决项 + 开阻塞澄清，蓝图链全图零 `STAGE_FAILED` 出边**且有一条遍历全图值集合的运行时断言 + 旧链正向对照守着），`blueprint_resume` 的状态映射改成 stage-aware 且**只删了 4 行、全部落在 `_amap_blueprint_status` 内**（前七 stage 映射结果逐字等价 112，七条参数化回归断言背书），distill 只产 pending 草案（`append` / `confirm_draft` / hook 精炼三条反向零调用断言）；执行期另揪出两处会让阶段 2/3 **静默落 FAILED** 的真缺陷并修掉（engine 抹掉 artifact 指针 + 无阻塞线程的澄清 self-loop 打到步数上限）；**全量相位门 `uv run pytest tests/` → 8286 passed / 1 failed**（唯一失败是 113-02 已三次登记的 `skills/` 子模块守卫），`cd task && pytest` 263 passed，`makemigrations --check` 退出码 0。

## Accomplishments

- **引用覆盖率门（FLOW-06 后半 + SCHEMA-02 达标口）**：位置严格在 `validate_blueprint` 之后、`add_version` 之前。阈值走 `SettingKeys.BLUEPRINT_MERGE_CONFIG`，`system/models.py` 纯追加一个常量（`git diff | rg "^-"` 为 0 行）、`settings_service.py` 一行未改。⭐ 阈值可配**可证伪**：同一份覆盖率 0.5 的样本，配 `{"citation_coverage_min": 0.9}` 判 `retry`、配 `0.5` 判 `passed` —— 门写死模块常量时两条里必有一条红。配置畸形六形态（非 JSON / 顶层 list / 空串 / 值类型错 / 缺键 / 空 dict）参数化断言一律回落 0.8 且不抛（配置坏了不能卡死流水线）。分母为 0（空文档）返 1.0 过门，另有一条独立用例。
- **`coverage_gaps` 归因（OQ-4）**：与 `citation_coverage` **同源三类遍历、同序、同 `_cited` 判定**，只是产出定位而非布尔。三类 section 各能被定位到（一条断言同时覆盖 `current_state_analysis` 带仓 / `repo_associations` 带仓 / `impact_analysis` 无仓归属三种形态，并断言每条恒为三键）；六种畸形输入参数化断言恒返 list 不抛。`decide_back_target` 是零 ORM 纯函数：单仓档、融合档、混合取最多、空输入四条断言全在，排序键显式化故同输入恒同归因。
- **有界回退 + 超界出口（T-113-37 / OQ-3）**：`attempt=0` 不达标 → `retry` 且 `attempt == 1` 且**版本数不变**；`attempt=2` → `exhausted` 且**版本数 +1**、`unresolved` 非空且每条恒三键、DB 有 blocking `ai_clarification` 线程（`status=OPEN`、`return_stage == "merge"`）、`"failed"` 不出现在整个返回值的 JSON 里、会话未被落终态。轮次单点串行另有一条用例：连续两次 `merge()` 后 `count` 1→2，且 `routing` / `decomposition` / `repo_plan` 三个既有键仍在（浅合并整体回写不丢键）。
- **⭐ W3：蓝图链零 failed 出边写成图性质断言**：遍历 `_TECHNICAL_BLUEPRINT_STAGES` 全部 `transitions` 的**值集合**断言 `STAGE_FAILED not in`，与行号/diff 无关（任一 stage 引入 failed 出边即红）；配一条**正向对照**断言旧链 `_TECHNICAL_PLAN_STAGES["merge"].transitions.values()` 里仍有 `STAGE_FAILED`，证明该常量可被检出、上面那条不是恒真。旧链另有一条 `merge.exhausted == STAGE_FAILED` 的直接 import 比对（不猜字面量）。
- **两 stage 只加不改地接线**：`builtin_processes.py` 唯一非纯追加改动是 `confirmed` 那一行（验收 grep 输出恰好 1 行）。`_h_bp_repo_plan` 用**自写完成判据** `aall_repo_plans_ready`（绝不复用 `aall_research_tasks_terminal` 作完成判据，OQ-2）、event 走三元白名单、`stage_state` 摘要为空时整体不写（绝不半截键，有专门断言）、并把 113-04 的 **waiter 回收与重派挂载**落在此处（有两条断言：`aexpire_stale_waiters` 恰调 1 次；返回非空时 `aredispatch_waiting_repos` 收到该清单）。`_h_bp_merge` 回填 `current_artifact_version`（passed 与 exhausted 各一条断言非空）、`exhausted` 映射成 `merged`、七种 `validation_status`（含 `None` 与「完全没见过的状态」）参数化断言全部落在已登记 event 内。
- **⭐ B3 状态口径（T-113-43）**：`blueprint_resume` 的改动只删 4 行且**逐行都在 `_amap_blueprint_status` 内**（登记见下）。前七 stage 有**十四条**等价性断言（七条纯函数 + 七条端到端，逐个 stage 构造会话断言映射后仍是 `researching`）；阶段 2/3 两条断言 `drafting`。核心可证伪那条：`current_stage="repo_plan"` 的会话开 blocking 线程 → `needs_clarification` 且事件 payload 里 `return_status == "drafting"`（不是 researching）→ 线程 resolve 后二次映射**回 `drafting`**（显式 `!= researching`，即不退回阶段 1），并断言线程 `return_stage == "repo_plan"`；另配一条**阶段 1 对照组**（`repo_confirmation` 的会话阻塞→解除后仍回 `researching`，证明 112 行为逐字未变）。未登记 stage（空串 / `bogus_stage`）回落且不抛；`transition` 抛异常时映射不抛。
- **两 handler 经 service 转 `drafting`**：`_abp_mark_drafting` 一律走 `BlueprintLifecycleService.transition`（`rg "blueprint_status\s*=" builtin_processes.py` 零命中——不裸改状态字段），`blueprint_status` 为空串时先补一跳 `researching`（状态机入口边只有 `"" → researching`，直接跳 `drafting` 是非法边），已是 `drafting` 即跳过，整段 best-effort 吞异常。
- **distill 沉淀（BUS-03）**：⭐ 三条**反向零调用**断言（`MemoryService.append` / `MemoryService.confirm_draft` / `MemoryDistiller.distill_hook_writeback` 各被替换成计数替身，断言 `count == 0`）—— 「AI 不覆盖人工」这条纪律因此可证伪。`proposed_by` 断言是真实项目成员 User 实例、`project_id` 是真实 Project、`initiated_by_user_id` 是该 user id。kind 过滤有并列断言（三类有价值条目的正文**在** `conversation_text` 里，`finding` / `question` / `dependency_claim` 三条**不在**）；`superseded` 条目不进；`session.created_by` 为 None 与总线条目无项目归属两种「解析不到」各一条断言零调用且不抛；`distill_to_draft` 抛异常时 `merge()` 仍 `passed` 且版本已落；`retry` 中途不沉淀、零条目不调 LLM 各一条。
- **⭐ W1：SC-4 可量测**：把 `passed` 路径落库的 `ArtifactVersion.content` 写成一条 golden case（`tmp_path`），经 `call_command("evaluate_blueprint_golden", fixtures_dir=..., output_json=...)`（复用 111-04 的 command，**零指标算法内联**）跑出 report：断言 `total == 1` / `failed == 0`、`cases[0]["metrics"]` **同时含** `citation_coverage` 与 `target_repo_hit_rate` 两个数值键。⭐ 门槛可判定的反证：同一 case 的 `expected.min_citation_coverage` 改成 `1.01` 再跑 → `pytest.raises(CommandError)` 且该 case `passed is False`、`failures` 含「覆盖率」字样。全程无 LLM / 无网络 / 无 DB 写，在 `--disable-socket` 下跑通。
- **观测**：新增事件全部带 `category` + `component="process_runtime"`；覆盖率门两条走 `caller` + `level=warning`（含 `coverage` / `min_ratio` / `gap_count` / `unresolved_count` / `back_target` 计数，零正文），状态映射与 waiter 维护的降级走 `sampling`。未决项与澄清文本**只含段名/序号/仓 id**，有一条断言 responsibility 正文（`承担职责`）、findings 正文（`urls.py 已注册 router`）与引用串都**不在** `thread.body` 与 `unresolved` 里（T-113-42）。异常文本一律 `redact_secrets_in_text` + 截断 500。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `7ebe1267` | `SettingKeys.BLUEPRINT_MERGE_CONFIG` + `coverage_gaps` + `decide_back_target` + 覆盖率门与有界回退 + 超界带未决项 + distill hook |
| 2 | `ed19dad9` | 两 stage 与两 handler 追加（L 一行接续）+ entrypoint deps 与 docstring 名单 + `blueprint_resume` 的 stage→status 映射（B3） |
| 3 | `f6f76942` | 四个测试文件（覆盖率门 41 例 / distill 10 例 / stage 映射 29 例 / 等价性断言同步 45 例） |
| 3+ | `d8c607ce` | 执行期揪出的两处真缺陷修复（engine 抹指针 / 无线程的澄清 self-loop 打到步数上限）+ 正反两条指针断言 + confirm E2E 期望同步 |

> Task 1 与 Task 2 的 `<verify>` 都指向 Task 3 才创建的测试文件，故实际执行是「模块与测试一起做绿 → 按 task 边界分 commit」（与 113-05 同一形态）。第四个 commit 是 verification 阶段的偏差修复，不属任何单个 task。

## Files

- `server/system/models.py`（**纯追加** 5 行：`BLUEPRINT_MERGE_CONFIG` 常量 + 三行注释三件套，照既有两个 blueprint 键的范式）
- `server/services/process_runtime/blueprint_reconcile.py`（+~105 行：`coverage_gaps` + `_cited` + `_first_repository_id`，`__all__` 追加；`reconcile_cross_repo_apis` 一字未改）
- `server/services/process_runtime/blueprint_merge.py`（+~330 行：`decide_back_target` / `_aload_merge_config` / `_aopen_coverage_clarification` / `_adistill_context_entries` / `_aresolve_session_user` / `_aresolve_bus_project_id` / `_aadd_version` / `_coverage_question` / `_distill_text` + 覆盖率门与两条新出口 + `_result` 的 `extra` + `_build_stage_state` 的 `unresolved`/`attribution` + 模块与 `merge()` docstring 更新）
- `server/services/process_runtime/builtin_processes.py`（+~275 行，**1 行非纯追加**：`_abp_load_artifact` / `_abp_mark_drafting` / `_abp_has_open_blocking_threads` / `_abp_ensure_blocking_clarification` / `_abp_repo_plan_is_stuck` 五个 helper + `_h_bp_repo_plan` / `_h_bp_merge` 两 handler + 两个 StageDef + `confirmed` 一行）
- `server/services/process_runtime/entrypoint.py`（deps 两属性 + 两条 lazy import + docstring 名单 3 行改述）
- `server/services/process_runtime/blueprint_resume.py`（**受限追加**：`_STAGE_BLUEPRINT_STATUS` 表 + `_resolve_stage_status` helper + `_amap_blueprint_status` 内三处取值改为解析结果；**删除 4 行**，逐行登记见下）
- `server/services/process_runtime/engine.py`（Deviation 1：`current_artifact_version` 改成条件透传，7 行 `-` 全在 `advance` 的 transition 调用处）
- `server/tests/services/process_runtime/test_blueprint_merge_gate.py`（新建 41 例）
- `server/tests/services/process_runtime/test_blueprint_distill.py`（新建 10 例）
- `server/tests/services/process_runtime/test_blueprint_status_stage_map.py`（新建 29 例）
- `server/tests/services/process_runtime/test_blueprint_process_graph.py`（期望值同步 + 6 条新断言，45 例全绿）
- `server/tests/delivery/test_blueprint_gate_api.py`（confirm E2E 期望同步，见 Deviation 3）

## `blueprint_resume.py` 删除行逐行登记（B3 受限面自检）

`git diff | rg "^-" | rg -v "^---" | wc -l` → **4**（预算 ≤8）。逐行归属**全部在 `_amap_blueprint_status` 内**：

| # | 删除的行 | 归属 | 替换为 |
| - | -------- | ---- | ------ |
| 1 | `    """蓝图状态映射（CONTEXT 锁定）：阶段 0/1 全程 ``researching``；有 open+blocking` | 该函数 **docstring 第 1 行** | 改述为「按 stage 映射：前七 stage → researching，repo_plan/merge → drafting」 |
| 2 | `    线程时派生 ``needs_clarification`` 并带 ``return_status=researching``。` | 该函数 **docstring 第 2 行** | 同上（并说明 `return_status` 取同一映射结果） |
| 3 | `        target = BlueprintStatus.NEEDS_CLARIFICATION if blocked else BlueprintStatus.RESEARCHING` | **函数体**（target 三元） | `... if blocked else stage_status` |
| 4 | `            return_status=BlueprintStatus.RESEARCHING if blocked else None,` | **函数体**（return_status） | `return_status=stage_status if blocked else None,` |

> PLAN 预告的「三处硬编码」实际只需改两处：**初始化分支那处 `BlueprintStatus.RESEARCHING` 保持原样未删** —— 状态机的入口边只有 `"" → researching`，那一跳必须是 `researching`（把它换成 `stage_status` 会在阶段 2/3 首次映射时撞非法边 `"" → drafting`）。`aresume_blueprint_session` / `aresume_after_gate_action` / `adrive_blueprint_session_to_pause_or_terminal` / `_aload_artifact` / `_ahas_open_blocking_blueprint_threads` 五个既有函数的签名与语义**零改动**，`test_blueprint_status_stage_map.py::test_only_amap_blueprint_status_was_touched` 用 `inspect.signature` 逐一锁死。

## Decisions

- **`_result` 用 `extra` kwarg 追加归因键，而不是把七键扩成十键**：113-05 明文把「恒定七键」作为契约交付并留了一条 `set(result) == 七键` 的形状断言。把归因键无条件加进所有出口会撞它，且削弱「形状恒定」的价值。故 `passed` / `failed` / `needs_clarification` 三条既有出口的键集逐字未变，只有覆盖率门新开的两条带额外键。
- **`retry` 不落版本、`exhausted` 落版本**：中间产物（未达覆盖率、还要重来）进版本历史只会让 114 与人审面对一串半成品；而超界那一版是**会话的最终产物**，丢掉它等于把整轮工作作废（T-113-37 明令禁止）。
- **`retry` 中途不 distill**：会话尚未定稿，此时产项目记忆草案是噪声（且每轮都产会刷爆草案列表）。只在 `passed` / `exhausted` 两条终局出口沉淀。
- **`coverage_gaps` 的遍历自写而非 import 私有 generator**：`blueprint_quality.py` 是受限只读面，`_iter_key_conclusion_citations` 是它的私有名。复制遍历顺序 + 同款 `_cited` 判定并在 docstring 标同源，两处漂移的风险由「顺序一致」的注释与 `index` 对齐语义承担。
- **`affected_features` 的仓归属从 `repository_ids[0]` 解析**：PLAN 写「可能无仓归属 → 填空串」。实测该段 schema 有 `repository_ids`，能解析就解析（归因更准）；解析不到才留空串。融合档归因的用例因此构造**不带** `repository_ids` 的 feature。
- **`_STAGE_BLUEPRINT_STATUS` 用字面量而非枚举**：`blueprint_resume.py` 的所有 Django 模型 import 都在函数内（模块被 `callbacks.py` 等在 import 期拉起，加顶层模型 import 有循环风险），模块级表拿不到 `BlueprintStatus`。字面量与枚举同值由一条独立断言锁死（`_STAGE_BLUEPRINT_STATUS["repo_plan"] == BlueprintStatus.DRAFTING`），并断言**只有阶段 2/3 进表**（前七 stage 必须靠回落拿 `researching`）。
- **`_abp_has_open_blocking_threads` 探测失败 fail-open（返 False）**：与 `blueprint_resume` 的同款探测（fail-closed 返 True）刻意不同 —— 续驱侧那道 fail-closed 已经兜住「误放行不可逆」，handler 这道再 fail-closed 会让一次 DB 抖动把 stage 永久钉死在澄清态。
- **`_abp_repo_plan_is_stuck` 借 `aall_research_tasks_terminal` 只作活性探测**：PLAN 明令它不得作阶段 2 的**完成判据**（两 stage 共用同一 task，`mark_stale` 会让它短暂为假）。作「有无在途容器」的活性探测是另一回事，docstring 里把这条区分写死了。
- **distill 的项目归属取自总线条目而非会话**：`ConvergenceSession` 没有 project 列（113-05 Deviation 2 已实测），而 `BlueprintContextEntry` 有 project FK 正是为沉淀准备的。解析不到就跳过，不用会话 id 冒充 project id 去撞成员校验。
- **测试工厂复用 113-05 的 `test_blueprint_merge_stage`**：两个新测试文件 `from test_blueprint_merge_stage import ...`（同目录同 basedir，pytest 已把该目录插进 `sys.path`）。该目录无 `__init__.py`，加一个会改变 21 个既有测试模块的 collection 语义，故不加。
- **新测试文件的 `pytestmark` 只挂 `django_db`**：`asyncio_mode=auto` 会自动标记 async 用例；显式再挂 `pytest.mark.asyncio` 会让同文件里的纯函数用例刷「marked with asyncio but not async」警告。

## Deviations from Plan

共 6 处：2 处为**执行期揪出的真缺陷**（PLAN 未预告，不修则相位目标不可达）、1 处为被 PLAN 自身改动逼红的既有测试期望同步、2 处为 PLAN 前提与本仓事实不符的修正、1 处为范围外未修。

**1. [Rule 1 - 真缺陷] engine 把 `session.current_artifact_version` 抹成 NULL，阶段 2/3 永远找不到 artifact**

- **Found during:** verification（`tests/delivery/test_blueprint_gate_api.py` 的 confirm E2E 落 FAILED，排查到 merge 连 `blueprint_merge_started` 都没发）
- **Issue:** `ProcessEngine.advance` 把 `current_artifact_version=outcome.current_artifact_version` **无条件**透传给 `ConvergenceSessionService.transition`，而 `StageOutcome.current_artifact_version` 默认就是 `None`；service 用 `_UNSET` 哨兵区分「不改指针」与「显式置 None」，收到显式 `None` 就执行 `update_values["current_artifact_version_id"] = None`。⇒ **每一次不产版本的转移都把指针清成 NULL**。而阶段 2 的仓集（`acollect_locked_repos`）、阶段 3 的融合基线（`_aload_baseline`）、蓝图状态映射（`_amap_blueprint_status`）、阻塞线程探测全部靠这个指针找 artifact，且它们**都是 best-effort 吞异常的**——失效是彻底静默的：E2E 里表现为「repo_plan 判定无仓可拟 → 直进 merge → merge 说没有基线 → needs_clarification 自旋 → 步数上限 → FAILED」。这条同时说明 112 的状态映射从落地起就没真正生效过（第一次转移后就读不到 artifact 了）。
- **Fix:** `engine.py` 改为条件透传：`if outcome.current_artifact_version is not None: transition_kwargs["current_artifact_version"] = ...`（语义即「handler 没产版本 ⇒ 不动指针」，正是 `_UNSET` 哨兵存在的理由），并写明后果注释。配**正反两条**断言：不产版本的转移后指针原样保留；`_h_bp_merge` 真产版本时指针推进（证明不是把功能关掉）。`engine.py` 不在 prohibitions 也不在冻结清单；旧链只会变好（此前它的指针同样每步被抹）。
- **Files modified:** `server/services/process_runtime/engine.py`、`server/tests/services/process_runtime/test_blueprint_process_graph.py`
- **Commit:** `d8c607ce`

**2. [Rule 2 - 缺失关键功能] 没有阻塞线程的 `needs_clarification` self-loop 会被续驱推到步数上限落 FAILED**

- **Found during:** verification（同一条 E2E）
- **Issue:** 续驱 helper 只在「`waiting_clarification` **且**有 open+blocking 线程**且**无待调研仓」时短路。112 的三个 pausable stage 都由 adapter 保证「返回 needs_clarification 时必有线程」，所以这条隐含不变量从没被写下来。而 `_h_bp_merge` 的 `failed` 路径（无基线 / schema 非法 / 四段全挂）**不开线程**——`needs_clarification` self-loop 于是被 advance 20 次后落 `advance_step_limit` **FAILED**：把「缺条件、等人处置」变成「流程失败」，蓝图成果一起报废，正是 PLAN 明令禁止的静默失败形态。
- **Fix:** 新增 `_abp_ensure_blocking_clarification(session, *, stage, reason)`（幂等：已有 open+blocking 就不叠开；`return_stage` 传本 stage 名，B3；问题文本只含 stage 名与**枚举化的 reason**，零正文；整段 best-effort）。`_h_bp_merge` 停在 `needs_clarification` 前调一次。同时给 `_h_bp_repo_plan` 加 `_abp_repo_plan_is_stuck`（本轮零派发零合成**且**无在途容器 ⇒ 再 advance 也不会有进展）→ 转 `needs_clarification` + 开线程，堵住同一类自旋。E2E 用例断言「停在澄清态必须有阻塞线程」。
- **Files modified:** `server/services/process_runtime/builtin_processes.py`、`server/tests/delivery/test_blueprint_gate_api.py`
- **Commit:** `d8c607ce`

**3. [Rule 3 - PLAN 改动逼红既有测试] `test_blueprint_gate_api.py` 的 confirm E2E 期望同步**

- **Found during:** verification
- **Issue:** `test_e2e_confirm_through_rest_drives_session_to_terminal` 断言 confirm 后 `session.status == DONE`——那是 112 世界的正确期望（`confirmed → STAGE_DONE`）。本 plan 把该出边改指 `repo_plan`，confirm 后当然不再直接终态。PLAN Task 2 ③ 只点名了 `test_blueprint_process_graph.py`，漏了这一条同类的 E2E。
- **Fix:** 改名 `..._drives_session_into_stage_two` 并把断言换成更强的一组：`current_stage ∈ {repo_plan, merge}`（确实接续了）+ `status != FAILED`（**绝不静默失败**）+ 停在澄清态时必有 open blocking 线程（守住 Deviation 2 的不变量）+ 原有的 `confirmed_at_gate` 断言保留。模块 docstring 第 10 条同步改述。
- **Files modified:** `server/tests/delivery/test_blueprint_gate_api.py`
- **Commit:** `d8c607ce`

**4. [Rule 1 - PLAN 前提不成立] `_amap_blueprint_status` 只改两处取值，初始化分支那处 `RESEARCHING` 保持原样**

- **Found during:** Task 2
- **Issue:** PLAN 说「把 `_amap_blueprint_status` 内**三处**硬编码的 `RESEARCHING` 换成解析结果（初始化 `:267`、target 三元 `:271`、`return_status` `:279`）」。但 `_ALLOWED_TRANSITIONS` 的入口边只有 `"" → researching`（实测 `blueprint_lifecycle_service.py:90`）——把初始化那一跳换成 `stage_status`，阶段 2/3 会话首次映射就会撞非法边 `"" → drafting`，`transition` 抛 `ValueError` 被 best-effort 吞掉，状态**永远停在空串**。
- **Fix:** 只改 target 三元与 `return_status` 两处；初始化分支保持 `RESEARCHING` 并加注释说明「先补这一跳，再由下面那次 transition 落到 stage 对应目标态（`researching → drafting` 是合法边）」。删除行因此是 4 行而非预算的 8 行。
- **Files modified:** `server/services/process_runtime/blueprint_resume.py`
- **Commit:** `ed19dad9`

**5. [Rule 3 - 验收 grep 与代码可读性冲突] 三处 docstring/注释改写以满足验收 grep**

- **Found during:** Task 1 / Task 2（跑验收 grep）
- **Issue:** 三条 grep 被**文档字面量**误伤：① `rg "\.append\(|confirm_draft|record_hook_writeback" blueprint_merge.py | rg -i memory` 命中 distill hook docstring 里那句「绝不调 `MemoryService.append` / `confirm_draft`」；② `rg "STAGE_FAILED" blueprint_merge.py` 命中 `merge()` docstring 里那句「绝不 `STAGE_FAILED`」；③ `rg "blueprint_status\s*=" builtin_processes.py` 命中 `_abp_mark_drafting` 里的**读**比较 `artifact.blueprint_status == BlueprintStatus.DRAFTING`（正则把 `==` 也匹配了）。三处都是语义合规、只是文字撞了 grep。
- **Fix:** ① 改述为「`MemoryService` 的 active 直写入口 / 人工确认入口 / IDE hook 精炼入口」并指向反向断言所在的测试文件（禁调纪律的可执行守护在测试里，不靠注释）；② 改述为「stage 终态 done，绝不落 failed 终态」；③ 抽出 `current = str(artifact.blueprint_status or "")` 局部变量再比较（等价改写，且顺带把 `artifact is None` 的判空提前，更清晰）。三条 grep 现均按预期为零。另外 `rg '"validation_status": "exhausted"'` 由 `merge()` docstring 的 Returns 段满足（返回值经 `_result` 位置参数构造，代码里不会出现该字面量）。
- **Files modified:** `server/services/process_runtime/blueprint_merge.py`、`server/services/process_runtime/builtin_processes.py`
- **Commit:** `7ebe1267` / `ed19dad9`

**6. [Rule 3 - 范围外，未修] `tests/mcp_tools/test_skills_snapshot_guard.py::test_skill_files_discovered` 仍因子模块未 checkout 失败**

- **Found during:** verification
- **Issue:** 该守卫读 `skills/skills/*/SKILL.md`，本 worktree 的 `skills/` 子模块未 checkout。113-02 偏差 5 / 113-04 偏差 5 / 113-05 偏差 9 已三次登记，与本 plan 改动零因果（本 plan 未触碰 `mcp_tools/` 与 `task/`）。
- **Fix:** 按范围纪律不修。等价验收：`tests/mcp_tools/` 其余用例全绿，`cd task && pytest` 263 passed。
- **Files modified:** 无
- **Commit:** —

> ⚠️ 另一处**未修但已登记的既有风险**（不属本 plan 范围）：`_h_bp_repo_plan` 与 112 的 `_h_bp_repo_research` 同样存在「self-loop + wait_status 挂起但判据恒不满足」时依赖 `max_steps` 兜底的形态。本 plan 已用 `_abp_repo_plan_is_stuck` 堵住阶段 2 里「零派发零在途」这一最常见的卡死形态；`repo_research` 那条同源风险留给归属方（112）按需加固。

## 测试与验证

- `tests/services/process_runtime/test_blueprint_merge_gate.py`：**41 passed**（阈值可配两向 / 坏配置六形态参数化 / 分母为 0 / 单仓归因带 repo id / 融合归因 / 混合取最多 / 空 gaps 三键空 / `coverage_gaps` 三类定位 + 六种畸形输入 / retry 不落版本 / ⭐exhausted 仍落版本带 unresolved 且零 failed 且会话未终态 / 未决项与澄清文本零正文 / 轮次递增且既有键不丢 / 两 handler pass-through 与 deps 整体 None / D-W4 缺依赖返 needs_clarification / 正常路径落 stage_state / 半截键不写 / ⭐`current_artifact_version` 回填 / exhausted 映射 merged 且 `error is None` / 七形态 event 白名单参数化 / 两 stage 异常经 engine 落 failed 且 `error["stage"]` 正确 / 四跳可达 / ⭐W1 golden 可量测 + 门槛可判定反证）
- `tests/services/process_runtime/test_blueprint_distill.py`：**10 passed**（⭐三条反向零调用 + proposed_by 真实成员 / kind 并列过滤 / status 过滤 / 无 user 跳过 / 无项目归属跳过 / 抛异常不反噬 / exhausted 也沉淀 / retry 不沉淀 / 零条目不调 / 文本有界）
- `tests/services/process_runtime/test_blueprint_status_stage_map.py`：**29 passed**（⭐前七 stage 七条纯函数 + 七条端到端等价性 / 阶段 2/3 两条 drafting / 未知 stage 回落三条 + 两条端到端 / ⭐澄清恢复回 drafting 且 `return_status == drafting` / 阶段 1 对照组仍回 researching / 映射表与枚举同值 + 只登记阶段 2/3 / transition 抛异常不反噬 / 无版本指针 no-op / 受限面签名自检）
- `tests/services/process_runtime/test_blueprint_process_graph.py`：**45 passed**（旧链冻结快照未动 + ⭐旧链 `merge.exhausted == STAGE_FAILED` 直接 import 比对 / 九 stage 注册且 112 七个不少 / confirmed → repo_plan / merge.merged 是 114 接续点 / ⭐蓝图链零 failed 出边 + 正向对照 / 全图可达且无未定义 target / 五个 pausable 有 self-loop / handler 9 + 注册 3 / deps 三方名单一致 + 两链互不污染 / ⭐指针保留与推进正反两条 / 九个 handler pass-through 参数化）
- **PLAN verification 全量相位门**：`cd server && uv run pytest tests/ -q` → **8286 passed, 63 skipped, 26 deselected, 1 xfailed, 1 failed**（唯一失败是 Deviation 6 的子模块守卫；改动前基线同一命令是 8283 passed + 同一条失败，故**零新增失败**）
- `cd task && uv run pytest -q` → **263 passed, 3 skipped**（本 plan 未触碰 `task/`）
- `uv run python manage.py makemigrations --check --dry-run` → 退出码 **0**（零模型改动，只加 `SettingKeys` 常量）
- `uv run ruff check services/process_runtime/` → All checks passed；`ruff format --check` 两个 format 目标（`blueprint_merge.py` / `blueprint_reconcile.py`）已格式化；`ruff check system/models.py` 通过。**`builtin_processes.py` / `entrypoint.py` / `system/models.py` 全程未跑 `ruff format`**（守纯追加——执行中曾误跑一次并把旧链两处既有折行改掉，已逐字回滚，最终 diff 里 `_h_merge` 与 `_h_echo_draft` 一字未动）。`ruff check system/` 的 18 条报错全在 `system/views.py` 与 `system/migrations/0004_*.py`，两文件本 plan 零触碰（属既有欠债，按范围纪律不修）
- **冻结面自检**：`git diff --name-only afb3a877 HEAD` 共 12 个文件；`repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / blueprint_schema / blueprint_quality / blueprint_route / blueprint_spec_gate / blueprint_confirm_gate / blueprint_lifecycle_service / charter_service / settings_service / event_taxonomy / call_source / subagent/api/callbacks / task/core/knowledge_tools` 与 `^task/` `^web/` **全部零命中**
- **受限面 diff 计数**（`rg "^-" | rg -v "^---" | wc -l`）：`system/models.py` **0**（纯追加）／`entrypoint.py` **3**（全是 docstring 名单行）／`blueprint_resume.py` **4**（≤8，逐行登记见上，全在 `_amap_blueprint_status` 内）／`builtin_processes.py` 非注释 **1**（`"confirmed": STAGE_DONE`）／`engine.py` **7**（全在 `advance` 的 transition 调用处，Deviation 1）
- **相位收口自检**：`rg -c "^async def _h_bp_" builtin_processes.py` == **9**；`rg -c "^register_process_type\(" ...` == **3**；`git diff --stat agents/call_source.py` 为空（零新增 `CallSource`）
- **⭐ W3 运行时验收**（退出码 0）：`_TECHNICAL_BLUEPRINT_STAGES` 全部 `transitions` 值集合零 `STAGE_FAILED`，且 `_TECHNICAL_PLAN_STAGES["merge"].transitions["exhausted"] == STAGE_FAILED`（直接 `from services.process_runtime.registry import STAGE_FAILED` 比对，**未猜字面量**）→ 打印 `no failed edge in blueprint chain; old chain intact`
- **运行时验收 greps 逐条**：`BLUEPRINT_MERGE_CONFIG = "blueprint.merge.config"` 与 `# 消费方：...blueprint_merge.py（113）` 命中；`def coverage_gaps` 命中且 `blueprint_reconcile.py` 的 `rg "raise "` 零命中；`def decide_back_target` / `unresolved`(21) / `citation_coverage`(5) / `aget_json_setting`(3) / `distill_to_draft`(3) / `{**state`(2) 全命中；`blueprint_merge.py` 的 `STAGE_FAILED` 与「memory 相关的 append/confirm_draft/record_hook_writeback」**零命中**；`builtin_processes.py` 的 `STAGE_FAILED` 命中行全在 import、`_TECHNICAL_PLAN_STAGES` 区段与 reroute 的既有注释内（两个新 stage 与两个新 handler 一行未引入）；`current_artifact_version` 在 `_h_bp_merge` 回填处命中；`blueprint_status\s*=` **零命中**（不裸改状态字段）；`entrypoint.py` 的 `repo_plan=` / `merge=` 命中；`blueprint_resume.py` 的 `_STAGE_BLUEPRINT_STATUS` / `DRAFTING` 命中；`git diff --stat blueprint_quality.py blueprint_schema.py settings_service.py` 均为空

## Self-Check: PASSED

- 文件存在：12 个 key-files 全部命中（3 新建 + 9 修改）
- commit 存在：`7ebe1267` / `ed19dad9` / `f6f76942` / `d8c607ce` 均在 `git log`
- artifacts contains 断言：`def coverage_gaps` ∈ `blueprint_reconcile.py` ✓；`_h_bp_merge` ∈ `builtin_processes.py` ✓；`blueprint.merge.config` ∈ `system/models.py` ✓；`_STAGE_BLUEPRINT_STATUS` ∈ `blueprint_resume.py` ✓；`drafting` ∈ `test_blueprint_status_stage_map.py`（多处）✓；`unresolved` ∈ `test_blueprint_merge_gate.py` ✓
- key_links 断言：`repo_plan=` ∈ `entrypoint.py` 且与 handler `getattr` 取名逐字一致（有专门断言）✓；`BLUEPRINT_MERGE_CONFIG` ∈ `blueprint_merge.py`（经 `aget_json_setting` 只调既有 getter）✓；`distill_to_draft` ∈ `blueprint_merge.py`（best-effort hook）✓
- must_haves truths 逐条：覆盖率门以 SettingKeys 阈值生效且缺配置回落 ✓／`coverage_gaps` 把未覆盖结论定位到具体仓并据此两档归因 ✓／有界回退合计 ≤2 轮且轮次单点串行 ✓／超界转 STAGE_DONE 带未决项开澄清且绝不 STAGE_FAILED、旧链 `merge.exhausted` 保持原样 ✓／追加两 stage 只加不改（handler 7→9、注册仍 3、`_TECHNICAL_PLAN_STAGES` 零触碰）✓／`_h_bp_merge` 回填 `current_artifact_version` 且 entrypoint deps 与 docstring 名单同步、等价性断言更新后通过 ✓／distill 产 pending 草案且 proposed_by 解析不到即跳过 ✓／状态映射 stage-aware 且 `return_status` 走同一映射 ✓／阶段 2/3 澄清恢复回 drafting 而非阶段 1 ✓／两 handler 经 `BlueprintLifecycleService` 转 drafting ✓／SC-4 经 `evaluate_blueprint_golden` 可量测且门槛可判定 ✓

## Next Phase Readiness

- **114（AI 对抗审查）**：① 接续点是 `_TECHNICAL_BLUEPRINT_STAGES["merge"].transitions["merged"]`——把 `STAGE_DONE` 改成 `"ai_review"` 并追加一个 StageDef 即可（transitions 是数据）；`merge` 现有 `pausable=True` / `wait_status="waiting_clarification"`，新 stage 照此形态。② 超界会话的输入面：版本**已落**、`session.current_artifact_version` 已回填、未决项在 `stage_state["merge"]["unresolved"]`（含 `last_attribution` 与 `degraded_sections`）。③ 蓝图状态此时是 `drafting` 或 `needs_clarification`（`return_status="drafting"`），`drafting → ai_reviewing` 与 `needs_clarification → ai_reviewing` 都是合法边；新 stage 若要另一状态口径，只需往 `blueprint_resume._STAGE_BLUEPRINT_STATUS` **加一行**（三处取值已统一走 `_resolve_stage_status`）。
- **给后续 writer 的硬约束**：① 新增 blueprint stage 若其 `needs_clarification` 是 self-loop，**必须**保证返回该 event 时有 open+blocking 线程 —— 直接复用 `_abp_ensure_blocking_clarification`（否则续驱推到 `max_steps` 落 FAILED）。② 新增 handler 若不产版本，**不要**在 `StageOutcome` 里给 `current_artifact_version` 传 `None` 以外的假值；engine 现在只在非 None 时才写指针，传假值会把会话指到错版本。③ 新增 `open_thread` 一律带 `return_stage=<本 stage 名>`。④ 阈值类运行时配置一律往 `SettingKeys.BLUEPRINT_MERGE_CONFIG` 的 JSON 里加键，**不新增 SettingKeys 常量**，读取只用 `aget_json_setting` 且**必须**有模块常量兜底。⑤ 沉淀类 hook 只许调 `distill_to_draft`；`proposed_by` / `project_id` 解析不到就跳过，绝不伪造。⑥ `builtin_processes.py` / `entrypoint.py` / `system/models.py` **不要跑 `ruff format`**（会把旧链既有折行改掉，破坏纯追加验收）。⑦ 未决项与澄清文本只许含段名/序号/仓 id 这类标量，绝不夹带结论正文。
