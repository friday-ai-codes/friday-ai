---
phase: quick-260806-sif
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - web/src/components/project/warroom/ProjectMaterialsPanel.vue
  - web/src/components/project/warroom/ProjectBlueprintsCard.vue
  - server/services/process_runtime/blueprint_intake.py
  - server/tests/services/process_runtime/test_blueprint_intake.py
  - server/delivery/services/blueprint_lifecycle_service.py
  - server/tests/delivery/test_blueprint_confirm_state_api_sync.py
autonomous: true
requirements: [QUICK-260806-SIF]
must_haves:
  truths:
    - "项目工作台右栏不再渲染「交付物版本轨」区块，但 ArtifactTimeline 组件本身仍存在且 blueprints 页仍可用"
    - "新建蓝图成功后，同一 project_id 下处于 researching/drafting/pending_review/confirmed 的旧蓝图被标为 superseded；其它状态与其它项目的蓝图不被动"
    - "蓝图转移到 confirmed 后，api_contracts 中 provided+http 且 method/path 非空的契约在 ProjectStateApi 生成 status=planned、source=agent 条目；已存在同 (method,path) 条目不被覆盖"
    - "supersede 与契约回流任一失败都不阻断新蓝图创建 / confirmed 转移本身"
  artifacts:
    - path: "web/src/components/project/warroom/ProjectMaterialsPanel.vue"
      provides: "无 ArtifactTimeline 引用的项目资料面板"
    - path: "server/services/process_runtime/blueprint_intake.py"
      provides: "aseed_blueprint_artifact 后置的同项目旧蓝图 supersede（best-effort）"
    - path: "server/delivery/services/blueprint_lifecycle_service.py"
      provides: "confirmed 转移后的 API 契约回流（_async_state_apis_on_confirm）"
    - path: "server/tests/delivery/test_blueprint_confirm_state_api_sync.py"
      provides: "契约回流四类场景测试"
  key_links:
    - from: "server/services/process_runtime/blueprint_intake.py"
      to: "delivery.services.blueprint_lifecycle_service.BlueprintLifecycleService.transition"
      via: "supersede 唯一写口（INV-6）"
      pattern: "BlueprintLifecycleService\\(\\)\\.transition"
    - from: "server/delivery/services/blueprint_lifecycle_service.py"
      to: "initiatives.services.project_doc_service.ProjectDocService.upsert_state_api"
      via: "lazy import + defer_materialize 批量回流"
      pattern: "upsert_state_api"
---

<objective>
项目页与技术方案职责收敛（quick 260806-sif）：① 移除项目工作台右栏「交付物版本轨」区块；② 新蓝图创建时 supersede 同项目旧活跃蓝图；③ 蓝图 confirmed 后把 api_contracts 中 provided 的 HTTP 契约回流项目 API 清单（ProjectStateApi, status=planned, source=agent）。

Purpose: 项目工作台与蓝图查看器职责重叠收敛——蓝图列表卡（ProjectBlueprintsCard）已是项目侧唯一技术方案入口；「一项目一份活跃蓝图」预期由创建入口兜底；已确认蓝图的 API 承诺沉淀进项目结构化清单。
Output: 前端一处区块移除 + 后端两处 best-effort 钩子 + 新旧两个测试文件的用例。
</objective>

<execution_context>
⚠️ **git 纪律（最高优先级）**：工作树存在大量与本任务无关的在途改动（blueprint stage runner 等）。执行者必须：

- 每个任务只 `git add` 该任务 `<files>` 列出的具体文件路径，**绝不** `git add -A` / `git add .` / `git add server/` 之类的目录级 add。
- **不得改动**任何 git status 里已修改的脏文件，包括但不限于：`server/services/process_runtime/blueprint_merge.py`、`blueprint_resume.py`、`builtin_processes.py`、`engine.py`、`blueprint_review.py`、`server/mcp_tools/views.py`、`server/mcp_tools/serializers.py`、`server/delivery/services/blueprint_context_service.py`、`web/src/components/blueprint/**`。本任务全部落点（ProjectMaterialsPanel.vue、ProjectBlueprintsCard.vue、blueprint_intake.py、blueprint_lifecycle_service.py、test_blueprint_intake.py、新测试文件）均为干净文件。
- Commit 信息用简体中文 Conventional Commits（见各任务 done 给出的建议信息）。

观测规范：`.cursor/rules/observability-logging.mdc` —— structlog kv 事件、category/component、initiated_by_user_id、`redact_secrets_in_text` 脱敏、观测与 best-effort 逻辑绝不反噬业务。

无 migration、无新增依赖、无 i18n 新文案。
</execution_context>

<context>
@web/src/components/project/warroom/ProjectMaterialsPanel.vue
@web/src/components/project/warroom/ProjectBlueprintsCard.vue（只改头注）
@server/services/process_runtime/blueprint_intake.py
@server/delivery/services/blueprint_lifecycle_service.py
@server/delivery/api/blueprint_list_views.py（`_aggregate` 的 Python 侧 project_id 过滤范式 + `_STATUS_FIELD` 常量技巧）
@server/initiatives/services/project_doc_service.py（`upsert_state_api` / `schedule_state_materialization`，⛔ 本任务不改此文件）
@server/initiatives/models/project_state_api.py（ApiStatus / ApiSource / 唯一约束）
@server/tests/services/process_runtime/test_blueprint_intake.py（现有 fixture：`_make_project` / `_counts` / `_latest_version`）
@server/tests/delivery/test_blueprint_review_threads.py（`_make_artifact(blueprint_status=...)` / `_db_status` 构造范式）
</context>

<tasks>

<task type="auto">
  <name>Task 1: 移除项目页「交付物版本轨」区块</name>
  <files>web/src/components/project/warroom/ProjectMaterialsPanel.vue, web/src/components/project/warroom/ProjectBlueprintsCard.vue</files>
  <action>
在 `ProjectMaterialsPanel.vue`（当前 155 行）做两处删除（per 锁定任务 1）：

1. 删除第 29 行的 `const ArtifactTimeline = defineAsyncComponent(...)` 导入。
2. 删除模板中第 83-84 行的 `<!-- 交付物版本轨 / 时间线（P7，只读）… -->` 注释与 `<ArtifactTimeline :space-id="project.space_id" artifact-type="technical_plan" />` 用法。
3. 顺带更新第 31-33 行 `ProjectBlueprintsCard` 的 defineAsyncComponent 上方注释：该注释说蓝图卡「排在 FeatureBoard 与『交付物版本轨』之前」且提及 P-17 条目重叠——版本轨已从本面板移除，重叠不复存在，把注释改写为只说明「蓝图是待审/在产的高时效资料，排在静态清单类分区前面」，删去版本轨/重叠相关表述。第 58-60 行模板注释同理精简。

在 `ProjectBlueprintsCard.vue` 头注中，把「## ⚠️ 与同一面板里既有『交付物版本轨』的条目重叠（P-17，必须靠文案区分）」一节改写为历史备注（说明版本轨区块已于本次收敛从项目资料面板移除，蓝图卡是项目侧唯一技术方案入口；ArtifactTimeline 仍服务于知识库 blueprints 页）。**只改注释，不改任何 script/template 行为**。

⛔ 不删除 `web/src/components/delivery/ArtifactTimeline.vue` 组件本身（blueprints 页等仍在引用）。⛔ 不动 `web/src/components.d.ts`（自动生成且已是脏文件）。无针对 ProjectMaterialsPanel 的测试文件，无需新增。
  </action>
  <verify>
    <automated>! grep -q "ArtifactTimeline" web/src/components/project/warroom/ProjectMaterialsPanel.vue && test -f web/src/components/delivery/ArtifactTimeline.vue && cd web && pnpm eslint src/components/project/warroom/ProjectMaterialsPanel.vue src/components/project/warroom/ProjectBlueprintsCard.vue</automated>
  </verify>
  <done>
ProjectMaterialsPanel.vue 无任何 ArtifactTimeline 引用；ArtifactTimeline.vue 组件文件仍存在；两个文件过 eslint。只 `git add web/src/components/project/warroom/ProjectMaterialsPanel.vue web/src/components/project/warroom/ProjectBlueprintsCard.vue`，提交信息：`refactor(web): 移除项目资料面板的交付物版本轨区块`。
  </done>
</task>

<task type="auto">
  <name>Task 2: 新蓝图创建时 supersede 同项目旧活跃蓝图</name>
  <files>server/services/process_runtime/blueprint_intake.py, server/tests/services/process_runtime/test_blueprint_intake.py</files>
  <action>
在 `blueprint_intake.py` 新增模块级私有 async 函数 `_asupersede_previous_blueprints(*, new_artifact, session, project_id) -> None`，并在 `aseed_blueprint_artifact` 中、`_amark_researching(artifact, session)` 之后调用它，调用整体再包一层 try/except（吞掉 + warning）保证 best-effort——单条乃至整体失败绝不阻断新蓝图创建（per 锁定任务 2）。

实现要点：

1. **候选收窄**（照 `blueprint_list_views._aggregate` 的既有范式）：lazy import `delivery.models.Artifact` 与 `delivery.artifacts.builtin_types.ARTIFACT_TYPE_TECHNICAL_PLAN`；queryset 为 `artifact_type=technical_plan`、排除 `new_artifact.id` 自身、排除空串状态、`select_related("current_version")`。⚠️ **INV-6 字段级守卫会命中 `filter(blueprint_status=...)` 字面 kwarg**（三条正则扫整个 server/，纯读 filter 形态也算）——必须照 `blueprint_list_views.py` 的 P-1 技巧：模块级常量 `_STATUS_FIELD = "blueprint_status"`，ORM 过滤一律 `exclude(**{_STATUS_FIELD: ""})` / `filter(**{_STATUS_FIELD + "__in": [...]})` 形态；对象读值用 `getattr(candidate, _STATUS_FIELD, "")`（模块 415 行已有 getattr 先例）。
2. **项目匹配在 Python 侧**：项目归属只在 `current_version.content["meta"]["project_id"]`，不是 DB 列。逐条读 `getattr(candidate.current_version, "content", None)`，取 `meta.project_id` 与入参 `project_id` 比对，不匹配跳过。蓝图总量小（一项目一份活跃蓝图预期），代价可接受。ORM 迭代经 `sync_to_async` 包裹取列表（本模块是 async 上下文）。
3. **状态白名单**：只对 `blueprint_status ∈ {RESEARCHING, DRAFTING, PENDING_REVIEW, CONFIRMED}`（`_ALLOWED_TRANSITIONS` 中仅这四态有 → superseded 合法边）的候选做 supersede；`ai_reviewing / needs_clarification / implementing / implemented / archived / failed / superseded` 一律计入 skipped_count 并记 debug 日志（category="sampling"），不强转。白名单过滤可直接进 queryset 的 `__in` 过滤（用 `_STATUS_FIELD` 常量拼 kwarg），skipped 数则以「同项目候选总数 − 白名单命中数」口径统计（需要第二次不带白名单的同项目匹配计数，或先取全部候选再在 Python 侧分流——选后者，一次查询）。
4. **逐条转移**：`await BlueprintLifecycleService().transition(candidate, BlueprintStatus.SUPERSEDED, initiated_by_user_id=<session.initiated_by_user_id or "system">, session=session)`（lazy import，INV-6 唯一写口；session 传新蓝图会话，让转移留 ConvergenceSessionEvent 痕）。每条独立 try/except `Exception`（含 `ValueError` / `ConcurrentBlueprintTransitionError`）：失败记 warning `blueprint_supersede_previous_item_failed`（artifact_id、error 经 `redact_secrets_in_text`），继续下一条。
5. **日志**：结束时记 `logger.info("blueprint_supersede_previous_completed", category="caller", component=_COMPONENT, project_id=..., new_artifact_id=..., superseded_count=..., skipped_count=..., initiated_by_user_id=..., duration_ms=...)`。⛔ 蓝图标题/需求正文不进日志。本模块在 `test_blueprint_log_redaction_guard._SCANNED_MODULES` 内：任何 `error=` 实参必须过 `redact_secrets_in_text`。

**测试**（追加到 `test_blueprint_intake.py`，沿用现有 fixture 与写法：`pytestmark = pytest.mark.django_db(transaction=True)`、`_make_project`、`sync_to_async` 数据工厂）。新增数据工厂 `_make_old_blueprint(project_id, status)`：`Artifact.objects.acreate(artifact_type="technical_plan", blueprint_status=status)` + 用 `build_skeleton(title=..., project_id=project_id, goal_text=...)` 建 `ArtifactVersion(artifact=..., version_no=1, content=...)` 并把 `artifact.current_version` 指过去（直接 ORM 建，绕过 service，测试文件豁免 INV-6）。调用面用 `aseed_blueprint_artifact(session=SimpleNamespace(id=..., initiated_by_user_id="tester"), requirement_text=..., project_id=...)` 直调。四个用例：

- 同项目 researching 与 pending_review 两份旧蓝图 → seed 后 DB 重读均为 `superseded`；
- 同项目 ai_reviewing 旧蓝图 → seed 后状态不变（仍 ai_reviewing）；
- 不同 project_id 的 researching 蓝图 → 不被动；
- patch `BlueprintLifecycleService.transition` 使 supersede 分支抛异常（注意别把 seed 自身跳 researching 那次也弄挂：patch 放在 seed 内部第一次转移之后，或 side_effect 按 to_status 判别——SUPERSEDED 才抛）→ `aseed_blueprint_artifact` 正常返回 artifact 且新蓝图落库。

断言一律 DB 重读（文件既有纪律）。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/services/process_runtime/test_blueprint_intake.py tests/delivery/test_blueprint_inv6_guard.py tests/delivery/test_blueprint_log_redaction_guard.py -x -q</automated>
  </verify>
  <done>
四个新用例 + 既有用例全绿；INV-6 守卫与日志脱敏守卫不因新代码转红。只 `git add server/services/process_runtime/blueprint_intake.py server/tests/services/process_runtime/test_blueprint_intake.py`，提交信息：`feat(server): 新蓝图创建时 supersede 同项目旧活跃蓝图`。
  </done>
</task>

<task type="auto">
  <name>Task 3: 蓝图 confirmed 后回流 provided HTTP 契约到项目 API 清单</name>
  <files>server/delivery/services/blueprint_lifecycle_service.py, server/tests/delivery/test_blueprint_confirm_state_api_sync.py</files>
  <action>
在 `BlueprintLifecycleService` 新增私有 async 方法 `_async_state_apis_on_confirm(self, artifact, *, initiated_by_user_id) -> None`，并在 `transition()` 中、`_apply_transition_sync` 成功且 `to_status == BlueprintStatus.CONFIRMED` 之后调用（放在 `_record_transition_event` 之后、`return artifact` 之前均可）；调用点整体 try/except `Exception` 吞掉——回流失败绝不反噬确认动作（per 锁定任务 3）。

方法实现：

1. **重读 content**：`await Artifact.objects.select_related("current_version").aget(id=artifact.id)` 取 `current_version.content`（⛔ 不信内存对象上可能过期的 current_version）；非 dict 直接返回。
2. **project_id**：`content["meta"]["project_id"]`；为空记 warning `blueprint_confirm_state_api_sync_failed`（reason="project_id_missing"）后返回。
3. **筛契约**：遍历 `content.get("api_contracts") or []`，只取 `isinstance(dict)` 且 `direction == "provided"` 且 `kind == "http"` 且 `str(method).strip()`、`str(path).strip()` 均非空的条目。零命中直接返回（不记 completed 事件也可，或 synced_count=0 照记——选照记，便于排障）。
4. **写入**：lazy import `from initiatives.services.project_doc_service import ProjectDocService` 与 `from initiatives.models.project_state_api import ApiStatus, ApiSource`（**函数体内 import**，避免 delivery → initiatives 顶层环）。循环内 `await ProjectDocService().upsert_state_api(project_id=..., method=..., path=..., description=str(contract.get("name") or ""), status=ApiStatus.PLANNED, source=ApiSource.AGENT, initiated_by_user_id=initiated_by_user_id, defer_materialize=True)`；返回 `(api, created)`——created 计入 synced_count，False 计入 skipped_count（`upsert_state_api` 是 get_or_create 语义，已存在的 (method, path) 条目不覆盖，现状条目优先、幂等，这正是期望行为，⛔ 不做 update）。循环结束后调一次 `await ProjectDocService().schedule_state_materialization(project_id, initiated_by_user_id)`（102-REVIEW MED-01 批量纪律）。
5. **日志**：成功记 `logger.info("blueprint_confirm_state_api_synced", category="caller", component="blueprint_lifecycle", artifact_id=..., project_id=..., synced_count=..., skipped_count=..., initiated_by_user_id=..., duration_ms=...)`；方法内部异常与调用点兜底均记 `blueprint_confirm_state_api_sync_failed` warning（error 经 `redact_secrets_in_text`）。⛔ 契约正文（name/path 之外的 description blocks、示例、request/response 结构）绝不进日志。

**测试**：新建 `server/tests/delivery/test_blueprint_confirm_state_api_sync.py`，`pytestmark = pytest.mark.django_db(transaction=True)`。构造范式参照 `test_blueprint_review_threads.py`（`_make_artifact(blueprint_status=BlueprintStatus.PENDING_REVIEW)`）与 `test_blueprint_intake.py` 的 `_make_project`（Project 需真实存在——ProjectStateApi 有 FK）。artifact 需带 `current_version`：直接 ORM 建 `ArtifactVersion(artifact=..., version_no=1, content=...)`（content 手拼 dict 即可：`{"meta": {"project_id": <真实 Project id>}, "api_contracts": [...]}`, 直接 ORM 创建不过 schema 校验）并 `artifact.current_version = version; asave()`。confirm 守卫要求 pending_review 且无阻塞线程——不开任何线程即可。四个用例：

- 两条 provided+http 契约（method/path/name 齐全）→ `transition(..., CONFIRMED, initiated_by_user_id="u1")` 后 `ProjectStateApi.objects.filter(project_id=...)` 出两行，`status == "planned"`、`source == "agent"`、`description == 契约 name`；
- consumed、kind="event"、method 为空的三类契约混入 → 均不落行；
- 预先经 `ProjectDocService().upsert_state_api(..., status=ApiStatus.IMPLEMENTED, source=ApiSource.MANUAL)` 造一行同 (method, path) 条目 → confirm 后该行 status/source/description 原样（DB 重读逐字断言）；
- patch `ProjectDocService.upsert_state_api` 抛异常 → transition 正常返回且 DB 重读 `blueprint_status == confirmed`。

若 `upsert_state_api` 内部的 `schedule_doc_push` / 审计在测试环境有副作用（pytest-socket 网络隔离等）导致用例不稳，就地 patch 掉 `initiatives.services.doc_push_scheduler.schedule_doc_push`；优先不 patch、实跑验证 fail-soft。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/delivery/test_blueprint_confirm_state_api_sync.py tests/delivery/test_blueprint_review_threads.py tests/delivery/test_blueprint_inv6_guard.py -x -q</automated>
  </verify>
  <done>
四个新用例全绿；既有 confirm 守卫用例（review_threads）与 INV-6 守卫不回归。只 `git add server/delivery/services/blueprint_lifecycle_service.py server/tests/delivery/test_blueprint_confirm_state_api_sync.py`，提交信息：`feat(server): 蓝图确认后回流 provided HTTP 契约到项目 API 清单`。
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| 蓝图 content（半可信） | `api_contracts` 由 LLM/用户产出，method/path/name 直写 ProjectStateApi 行 |
| 日志面 | 契约正文与需求原文不得泄入日志 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-sif-01 | Tampering | `_async_state_apis_on_confirm` | mitigate | 只取 provided+http 且 method/path 非空的条目；写入经 `upsert_state_api`（INV-6 收口，含审计），get_or_create 不覆盖现状条目；model 字段 max_length 天然截断由 Django 校验兜底 |
| T-sif-02 | Info Disclosure | 新增日志点 | mitigate | error 实参一律过 `redact_secrets_in_text`；契约正文/需求原文只记计数标量（synced/skipped/goal_len 口径） |
| T-sif-03 | DoS | supersede 全表扫描 | accept | 先按 artifact_type + 非空状态 + 状态白名单收窄索引扫描，Python 侧才读 content；蓝图量级小（一项目一活跃蓝图），与 `blueprint_list_views._aggregate` 同代价口径 |
| T-sif-04 | E of Privilege | supersede 误伤他项目蓝图 | mitigate | project_id 逐条精确比对 `meta.project_id`；状态机 `_ALLOWED_TRANSITIONS` 守卫非法边直接 ValueError 跳过 |
</threat_model>

<verification>
- 前端：ProjectMaterialsPanel.vue 零 ArtifactTimeline 引用；`web/src/components/delivery/ArtifactTimeline.vue` 未删。
- 后端：`cd server && uv run pytest tests/services/process_runtime/test_blueprint_intake.py tests/delivery/test_blueprint_confirm_state_api_sync.py tests/delivery/test_blueprint_review_threads.py tests/delivery/test_blueprint_inv6_guard.py tests/delivery/test_blueprint_log_redaction_guard.py -q` 全绿。
- git：`git log --oneline -3` 显示三条中文 Conventional Commits；`git status` 中在途脏文件（blueprint_merge.py / engine.py / mcp_tools 等）未被 add、未被改动。
</verification>

<success_criteria>
- 三个任务各自原子提交，提交只含各自 `<files>` 列出的路径。
- 观测规范达标：两个新事件（`blueprint_supersede_previous_completed` / `blueprint_confirm_state_api_synced`）带 category/component/initiated_by_user_id/duration_ms；失败路径 warning 且 error 已脱敏。
- 两处钩子均 best-effort：任何异常不阻断新蓝图创建 / confirmed 转移（有测试背书）。
- 无 migration、无新增依赖、无 i18n 新文案、`project_doc_service.py` 零改动。
</success_criteria>

<output>
完成后创建 `.planning/quick/260806-sif-supersede-api-api/260806-sif-SUMMARY.md`。
</output>
