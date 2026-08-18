---
quick_id: 260818-lta
phase: 260818-lta-validate-feature-point-module-intake-sch
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - server/services/process_runtime/blueprint_schema.py
  - server/services/process_runtime/blueprint_intake.py
  - server/services/process_runtime/blueprint_route.py
  - server/services/process_runtime/blueprint_confirm_gate.py
  - server/tests/services/process_runtime/test_blueprint_intake.py
  - server/tests/services/process_runtime/test_blueprint_route_feature_modules.py
  - server/tests/services/process_runtime/test_placement_units.py
  - server/tests/services/process_runtime/test_blueprint_confirm_gate.py
autonomous: true
requirements:
  - FP-MODULE-01
  - SUPPORT-CONF-01
  - UNSUITABLE-LOCK-01
user_setup: []
must_haves:
  truths:
    - "feature_segments 带 module/layer 时，feature_points[].module 有结构化值（不只是 description 文本）"
    - "多模块 feature_points → _requirement_spec_to_feature_list 产出真实 modules[] + 多 PlacementUnit（非假 modules:[{name:requirement}]）"
    - "blueprint funnel 调用 build_placement_units(..., merge_depends_on=False)，depends_on 只写 depends_on_units 边不并查合并"
    - "supporting 候选 confidence 来自 scores[sid] 经 _confidence_from_score，高分可为 high/medium"
    - "fitness.verdict=unsuitable 在快照构建/refresh 默认 removed=True；人工 add_repo 重纳后可 lock"
  artifacts:
    - path: "server/services/process_runtime/blueprint_schema.py"
      provides: "feature_points.items.properties.module optional string"
      contains: "\"module\""
    - path: "server/services/process_runtime/blueprint_intake.py"
      provides: "point[module] from segment.module|layer + LLM optional module"
      contains: "point[\"module\"]"
    - path: "server/services/process_runtime/blueprint_route.py"
      provides: "real modules[] + mega-unit guardrail + merge_depends_on=False + supporting score confidence"
      contains: "merge_depends_on=False|_confidence_from_score"
    - path: "server/services/process_runtime/blueprint_confirm_gate.py"
      provides: "unsuitable → auto-removed on build/refresh; human keep via add_repo"
      contains: "fitness_unsuitable|unsuitable"
    - path: "server/tests/services/process_runtime/test_blueprint_route_feature_modules.py"
      provides: "module→units / legacy description recover / supporting confidence tests"
  key_links:
    - from: "blueprint_intake._points_from_segments"
      to: "requirement_spec.feature_points[].module"
      via: "structured module field"
      pattern: "point\\[\"module\"\\]"
    - from: "_requirement_spec_to_feature_list"
      to: "build_placement_units"
      via: "modules[] + features_flat[].module"
      pattern: "modules|features_flat"
    - from: "_aapply_placement_funnel"
      to: "build_placement_units"
      via: "merge_depends_on=False"
      pattern: "merge_depends_on=False"
    - from: "_raw_candidates_from_placements"
      to: "place_units._confidence_from_score"
      via: "scores[sid]"
      pattern: "_confidence_from_score"
    - from: "_build_snapshot_entry / merge_gate_snapshot"
      to: "build_locked_associations"
      via: "removed=True skips unsuitable"
      pattern: "removed|fitness_unsuitable"
---

<objective>
修复蓝图路由 placement 把多模块功能点压成 1 个 PlacementUnit、supporting 恒 low、unsuitable 仍被 lock 的三条机制缺陷（Fix A/B/C）。

Purpose: 多模块需求应产生多 unit → 多 RepoRouterV2 调用 → 合理 primary/supporting；不适配仓默认不进锁定关联。
Output: schema+intake+route+confirm_gate 机制修复与单测；**禁止 git commit / stage**；**禁止改 files_modified 以外的脏文件**。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/templates/summary.md

⚠️ **git 纪律（NON-NEGOTIABLE）**
- **禁止** `git commit` / `git add` / stage。只改本计划 `files_modified` 内文件；工作树另有无关 dirty，勿触碰。
- **禁止** 重写 RepoRouterV2；**禁止** 重引入 `role_map`。
- **禁止** 为本任务 reopen/修复存量 blueprint 实例——只做机制，不做数据修复命令。

⚠️ **根因（已读代码确认）**
1. `_points_from_segments` 只把 `module`/`layer` 写进 description paragraph，从不设 `point["module"]`；schema 无 `module` 属性。
2. `_requirement_spec_to_feature_list` 读空 `fp.module`，伪造 `modules:[{name:"requirement"}]`；`build_placement_units` 全进 `_unassigned` → 1 unit。
3. `_aapply_placement_funnel` 未传 `merge_depends_on=False`（默认 True 可再并查合并）。
4. `_raw_candidates_from_placements` supporting 硬编码 `confidence="low"` → `_role_suggestion` 偏 `indirect`。
5. `_build_snapshot_entry` 恒 `removed=False`；`build_locked_associations` 只跳 `removed`，unsuitable 仍可 lock。
</execution_context>

<context>
@.planning/STATE.md
@.cursor/rules/observability-logging.mdc
@server/services/process_runtime/blueprint_schema.py
@server/services/process_runtime/blueprint_intake.py
@server/services/process_runtime/blueprint_route.py
@server/services/process_runtime/placement_units.py
@server/services/process_runtime/place_units.py
@server/services/process_runtime/blueprint_confirm_gate.py
@server/tests/services/process_runtime/test_blueprint_intake.py
@server/tests/services/process_runtime/test_placement_units.py
@server/tests/services/process_runtime/test_blueprint_confirm_gate.py

## Locked decisions (cite in actions)

- **D-01 Fix A**：端到端恢复结构化 `module`；funnel 用 `merge_depends_on=False`；空 module 大列表有 guardrail（优先从 description 首段恢复模块名）。
- **D-02 Fix B**：supporting confidence = `_confidence_from_score(scores[sid], contested=False)`（或同阈值共享 helper），禁止硬编码 `"low"`。
- **D-03 Fix C**：`unsuitable` 在快照 build/refresh 默认 `removed=True`（reason=`fitness_unsuitable`）；人工 `add_repo` 重纳（`removed=False` + actions 留痕）后可 lock；不 reopen 存量门。
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Fix A — structured module end-to-end + merge_depends_on=False</name>
  <files>
    server/services/process_runtime/blueprint_schema.py,
    server/services/process_runtime/blueprint_intake.py,
    server/services/process_runtime/blueprint_route.py,
    server/tests/services/process_runtime/test_blueprint_intake.py,
    server/tests/services/process_runtime/test_blueprint_route_feature_modules.py,
    server/tests/services/process_runtime/test_placement_units.py
  </files>
  <behavior>
    - `_points_from_segments` with segment.module="模块A" → feature_point has module="模块A"（description enrichment 可保留）
    - layer-only segment → module falls back to layer string
    - `_requirement_spec_to_feature_list` with two distinct modules → modules[] has both names（无 "requirement" 假模块）；features_flat[].module 非空
    - 同 module 多 feature → build_placement_units 仍合并为 1 unit（回归）
    - 不同 module → unit_count &gt;= 2
    - legacy：module 空但 description 首段/paragraph 为模块名样式（如「模块X」或旧 intake "模块A / layer"）→ guardrail 恢复后 unit_count &gt; 1 when feature_count &gt;= 5
    - `_aapply_placement_funnel` path uses merge_depends_on=False；depends_on 模块间出现 depends_on_units 边且不并查塌缩（可单测 build_placement_units 直接断言，不必起完整 adapter）
    - LLM prompt 允许可选 module，但测试只断言 parser/mapper：items 含 module 时被写入 point；无 module 时不发明
  </behavior>
  <action>
    Per **D-01**:

    1. `blueprint_schema.py`：在 `requirement_spec.feature_points.items.properties` 增加可选 `"module": {"type":"string","description":"..."}`（非 required）。

    2. `blueprint_intake._points_from_segments`：从 `segment.get("module")` 取结构化模块名；空则 fallback `segment.get("layer")`；非空则 `point["module"]=stripped`（截断合理上限，与 title 同量级即可）。可继续把 module/layer 拼进 description 作可读性 enrichment。更新模块 docstring 映射表。

    3. LLM 路径：`adecompose_feature_points` 已把 LLM items 喂给 `_points_from_segments`——只要 mapper 读 module 即可。轻改 `_decompose_system_prompt`：当需求文本有模块/章节标题时可**可选**输出 `"module"`；严禁发明模块。JSON 示例可扩为含 optional module。解析侧勿发明。

    4. `blueprint_route._requirement_spec_to_feature_list`：
       - 保留 `id`（`fp.get("id")`）到 features_flat 若存在；
       - `description` 用已有 `_blocks_to_text(fp.get("description"))`（勿 `str(list)`）；
       - `module = str(fp.get("module") or "").strip()`；
       - **legacy recover**：若 module 空，从 description 首段文本启发式提取（优先整段像模块名 / 含「模块」前缀 / 旧 `"A / B"` 取第一段）；仍空则留空；
       - `modules[]` = 去重后的非空 module 名列表（`{"name": m, "summary": ""}`），**禁止**伪造 `"requirement"`；若全部为空 modules 可为 `[]`；
       - **mega-unit guardrail**：若 `len(features_flat) >= 5` 且非空 distinct modules 仍 &lt; 2（即将塌成单 `_unassigned`），发 sampling 事件 `blueprint_route_placement_mega_unit_guardrail`（kv：feature_count、unit_module_count、session 若可得则省略——此函数纯；在 `_aapply_placement_funnel` 调用处也可打 caller/sampling），并尽量用 description 恢复；若仍无法拆分，记录 degrade 原因字符串进 funnel `degrade_reasons`（如 `mega_unit_missing_modules`），**不要**静默假装多 unit。

    5. `_aapply_placement_funnel`：`build_placement_units(feature_list=feature_list, merge_depends_on=False)` per D-01。确认 `placement_units.py` 在 False 时写 `depends_on_units`（已有逻辑 L348+）——勿改 placement_units 除非测试证明边丢失。

    6. 观测：structlog + `category`（guardrail=`sampling`，decompose 既有 caller 保持）+ `component="process_runtime"`；best-effort，不反噬。

    7. 测试：新建 `test_blueprint_route_feature_modules.py`（import `_requirement_spec_to_feature_list`、`build_placement_units`）；扩展 `test_blueprint_intake.py` 覆盖 `_points_from_segments` module；在 `test_placement_units.py` 补一条 `merge_depends_on=False` 产生 depends_on_units 且 unit_count 不因 depends_on 塌缩。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/services/process_runtime/test_blueprint_intake.py tests/services/process_runtime/test_blueprint_route_feature_modules.py tests/services/process_runtime/test_placement_units.py -q --tb=short -x</automated>
  </verify>
  <done>
    新 intake 写入结构化 module；多模块 → 多 PlacementUnit；funnel 默认不并查合并 depends_on；legacy description 可恢复模块名；同模块仍合并。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Fix B — supporting confidence from V2 score</name>
  <files>
    server/services/process_runtime/blueprint_route.py,
    server/tests/services/process_runtime/test_blueprint_route_feature_modules.py
  </files>
  <behavior>
    - placement with supporting_repos + scores[sid]=0.8 → raw candidate confidence in {"high","medium"}（按 _confidence_from_score 阈值：&gt;=0.75 high）
    - scores[sid]=0.2 → confidence "low"
    - missing score → 仍有合理默认（沿用现有 router_base 默认 0.35 时 confidence low；勿硬编码字符串 "low" 作为唯一路径——应走 helper）
    - primary 仍用 placement.confidence，行为不变
  </behavior>
  <action>
    Per **D-02**：在 `_raw_candidates_from_placements` supporting 分支，从 `place_units` import `_confidence_from_score`（或抽到双方可 import 的小 helper，优先直接 import 现有函数，避免复制阈值）。设：
    `confidence = _confidence_from_score(float(scores.get(sid, 0.35) or 0.35), contested=False)`。
    删除硬编码 `"low"`。Primary 分支保持 `str(p.get("confidence") or "medium")`。
    在 `test_blueprint_route_feature_modules.py` 用 `BlueprintRouteAdapter()._raw_candidates_from_placements(...)` 断言高低分。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/services/process_runtime/test_blueprint_route_feature_modules.py -q --tb=short -k "supporting or confidence" -x</automated>
  </verify>
  <done>
    supporting confidence 随 score 变化；高分不再被钉死为 low。
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Fix C — unsuitable auto-remove at gate snapshot</name>
  <files>
    server/services/process_runtime/blueprint_confirm_gate.py,
    server/tests/services/process_runtime/test_blueprint_confirm_gate.py
  </files>
  <behavior>
    - `_build_snapshot_entry` with fitness verdict unsuitable → entry.removed is True 且 remove_reason 含 fitness_unsuitable（或等价常量）
    - `build_locked_associations` 对该 entry 不产出 association（既有 removed 跳过即可）
    - 人工重纳：entry.removed=False 且 actions 含 add_repo（after.removed False）→ merge/refresh 后仍 removed=False → lock 产出 association
    - suitable/partial 不自动 removed
    - merge_gate_snapshot：既有 removed=False 且无 human keep、fresh fitness 变为 unsuitable → 应变为 removed=True（覆盖「门先开、调研后判不适配」）
    - merge：human add_repo 已 keep 后，即使 fresh 仍 unsuitable，保留 removed=False
  </behavior>
  <action>
    Per **D-03**：

    1. `_build_snapshot_entry`：若 `verdict == "unsuitable"`，设 `removed=True`，`remove_reason="fitness_unsuitable"`（可同时留空 actions）。非 unsuitable 保持 `removed=False`。

    2. `merge_gate_snapshot`：在合并 fitness 面之后，对每条 updated：若 `fitness.verdict == unsuitable`：
       - 若 `_human_kept_despite_unsuitable(entry)`（判定：`actions` 中存在 `action=="add_repo"` 且 `after.removed is False`——表示人工重纳）→ **保留**现有 `removed`（通常 False）；
       - 否则强制 `removed=True`，`remove_reason` 设为 `fitness_unsuitable`（勿覆盖人工 `remove_repo` 已写的其它 reason 若已 removed——若已 removed=True 可不动 reason）。
       这样 refresh 在「先开门后出 unsuitable」时也会拦截，且不冲掉人工 keep。

    3. `build_locked_associations`：保持只跳 `removed`；**不要**仅凭 unsuitable 再拦一层（否则挡住人工重纳）。可选日志：跳过 unsuitable+removed 时 sampling 事件 `blueprint_confirm_gate_unsuitable_auto_removed`（count），best-effort。

    4. 观测：`category=sampling`（高频刷新）或 open_gate 路径已有 caller 事件旁记 `unsuitable_auto_removed_count`；component=`process_runtime`；脱敏无凭证。

    5. 测试写在 `test_blueprint_confirm_gate.py`：纯函数测 `_build_snapshot_entry` / `merge_gate_snapshot` / `build_locked_associations` 组合，无需 DB。
  </action>
  <verify>
    <automated>cd server &amp;&amp; uv run pytest tests/services/process_runtime/test_blueprint_confirm_gate.py -q --tb=short -k "unsuitable or locked_associations or merge_gate" -x</automated>
  </verify>
  <done>
    unsuitable 默认不进锁定关联；人工 add_repo 重纳后可 lock；无存量 gate reopen。
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| requirement_spec / feature_segments → placement | 不可信需求文本与 LLM 拆分输出进入路由 funnel |
| confirm-gate snapshot → locked repo_associations | 人工/自动裁决写入蓝图版本 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-lta-01 | Tampering | feature_points.module / LLM items | mitigate | schema 可选 string；LLM 禁止发明模块；空 module 不伪造 "requirement" |
| T-lta-02 | Elevation | unsuitable still locked | mitigate | snapshot/refresh 默认 removed；lock 跳 removed；人工 keep 需 add_repo 留痕 |
| T-lta-03 | Information disclosure | guardrail/unsuitable logs | mitigate | structlog kv only；无需求正文全文 dump；沿用 redact |
| T-lta-SC | Tampering | npm/pip installs | accept | 本任务零新依赖 |
</threat_model>

<verification>
全量本任务相关测试（建议执行一次）：

```bash
cd server && uv run pytest \
  tests/services/process_runtime/test_blueprint_intake.py \
  tests/services/process_runtime/test_blueprint_route_feature_modules.py \
  tests/services/process_runtime/test_placement_units.py \
  tests/services/process_runtime/test_blueprint_confirm_gate.py \
  -q --tb=short
```

手动 grep 门禁（执行后自检，勿改无关文件）：

```bash
# supporting 不得再硬编码 low（该函数内）
rg -n 'confidence.: .low.' server/services/process_runtime/blueprint_route.py | rg '_raw_candidates|supporting' || true
rg -n 'merge_depends_on=False' server/services/process_runtime/blueprint_route.py
rg -n 'point\["module"\]|point\.get\("module"\)' server/services/process_runtime/blueprint_intake.py
rg -n 'fitness_unsuitable' server/services/process_runtime/blueprint_confirm_gate.py
```
</verification>

<success_criteria>
- Fix A/B/C 全部落地且上述 pytest 通过
- files_modified 以外文件零改动
- 无 RepoRouterV2 / role_map 回归；无 git commit/stage
</success_criteria>

<output>
Create `.planning/quick/260818-lta-validate-feature-point-module-intake-sch/260818-lta-SUMMARY.md` when execution finishes（本规划步骤不写 SUMMARY）。
</output>

## Source Audit

| SOURCE | ID | Item | Plan | Status |
|--------|-----|------|------|--------|
| GOAL | — | 多模块功能点不再塌成 1 PlacementUnit；supporting 置信度跟分；unsuitable 默认不 lock | 01 T1–T3 | COVERED |
| REQ | FP-MODULE-01 | 结构化 module 端到端 + merge_depends_on=False + guardrail | 01 T1 | COVERED |
| REQ | SUPPORT-CONF-01 | supporting 用 _confidence_from_score | 01 T2 | COVERED |
| REQ | UNSUITABLE-LOCK-01 | unsuitable 快照自动 removed；人工可重纳 | 01 T3 | COVERED |
| CONTEXT | D-01/D-02/D-03 | 三机制锁定决策 | 01 T1–T3 | COVERED |
| OUT | — | 不重写 RepoRouterV2 / 不引 role_map / 不 reopen 存量门 | — | EXCLUDED (constraint) |
