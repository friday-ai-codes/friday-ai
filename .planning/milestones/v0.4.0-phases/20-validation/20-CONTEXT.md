# Phase 20: 保存即合法与模板修复 - Context

**Gathered:** 2026-06-13
**Status:** Ready for planning
**Mode:** Smart discuss（autonomous——orchestrator 基于代码勘察提出 grey-area 决策并采纳）

<domain>
## Phase Boundary

非法工作流在**保存 / 导入 / 模板创建**时就被结构化拒绝（不再"能保存、一执行就失败"）；新建统一 `WorkflowGraphValidator` 为唯一校验事实源，被 bulk-update、单节点/边 CRUD、导入、模板 loader、前端 dry-run 共用；4 个内置模板开箱即跑通；模板一致性有自动化测试守护。

**In scope（VAL-01/02/03、TPL-01/02/03）：**
- 后端统一 `WorkflowGraphValidator`：DAG 环/入口/孤立、edge 节点归属、handle 对 registry NodePort 合法性、节点 config schema、变量引用可解析性
- 全部写入路径接入同一校验，返回结构化错误（节点 id + 字段路径 + 原因）
- dry-run 校验接口 + 前端保存前调用 + IssuesPanel 真实展示（消除死代码）
- 修复 `daily_summary`、`code_review_pipeline` 断裂；4 模板开箱可执行
- 模板创建（loader）实例化前执行同一图校验
- 模板自动化校验测试（node type/必填/变量路径/handle 一致性）

**Out of scope：**
- 不改引擎执行语义（Phase 18 已收口）；保存校验是"运行前静态版"，复用 Phase 17 resolver 与 Phase 19 registry，但独立于运行态
- 不重写 IssuesPanel 视觉/交互体系，仅接通数据 + 必要的告警类型扩展
- `input.*` / `trigger.*` 变量引用维持 Phase 17 宽松边界，本阶段不收紧（仅 `nodes.*` 严格静态校验）
</domain>

<decisions>
## Implementation Decisions

### D-01 [统一校验器位置与形态] 新建 WorkflowGraphValidator 单一事实源
新建 `server/workflows/validation/graph_validator.py`（新包 `validation/`），`WorkflowGraphValidator` 类对"节点集 + 边集 + 各节点 config"做静态校验，返回结构化结果 `{errors: [...], warnings: [...]}`，每条含 `node_id`（或 edge_id）、`field_path`、`reason`、`severity`。被以下全部写入路径共用：bulk-update、单节点/边 CRUD、import、template loader、dry-run 接口。

### D-02 [校验规则集] 复用既有能力，不重造
- **DAG 结构**：复用 `DAG.validate()`（环/入口/孤立，dag.py L138-160）——校验器从待保存的节点/边构造内存 DAG 再调用。
- **边节点归属**：source/target 必须属于本 workflow 节点集。
- **handle 合法性**：source_handle ∈ 上游节点 `outputs`（含 ConditionNode `get_dynamic_outputs` 按 config 派生的分支 handle）；target_handle ∈ 下游 `inputs`（或 default）。事实源 `NodeRegistry`。
- **config schema**：复用 `BaseNode.validate_config()`（jsonschema），**补齐** `WorkflowNodeCreateSerializer` 新建路径缺口。
- **变量引用**：用 `template_resolver._TEMPLATE_VAR_RE` 扫描 config 字符串字段，对 `{{nodes.<id>.<path>}}` 做静态存在性校验（节点存在 + 字段在上游输出 schema 中）。

### D-03 [变量静态校验语义] nodes.* 严格、input/trigger 宽松
- `{{nodes.<id>.<field>}}`：节点不存在 → error；节点存在但上游输出 schema 中无该字段 → error（上游输出**无 schema 声明**时只校验节点存在性，字段层跳过，避免误报）。
- `{{input.*}}` / `{{trigger.*}}`：维持 Phase 17 宽松（不校验字段存在），本阶段不收紧。
- 错误 reason 复用 `TemplateResolutionError` 的 reason 枚举风格（node_not_found / field_not_found 等），保持前后端一致。

### D-04 [dry-run 接口] 独立 validate action
新增 `POST /api/workflows/{id}/validate/`（或对未持久化草图 `POST /api/workflows/validate/` 接收 nodes/edges），返回 `{errors: [], warnings: []}`，**不写库**。errors 阻断保存，warnings 仅提示。bulk-update/import/from-template 在写库事务前调用同一 validator，有 error 即结构化 400 拒绝。

### D-05 [保存失败语义] 结构化 400，合法不受影响
非法保存返回 HTTP 400 + `{errors: [{node_id|edge_id, field_path, reason, severity}]}`；合法工作流保存行为零变化（不新增误拒）。warnings 不阻断保存。

### D-06 [前端接线] saveWorkflow 调 dry-run → store → IssuesPanel
`useWorkflowsStore.saveWorkflow` 保存前（或 bulk-update 返回 400 时）把后端校验结果写入 `useWorkflowValidationStore`；扩展 `ValidationWarning` 类型超出当前唯一的 `schema_mismatch`（增 error/warning severity 与多 reason 类型）；`IssuesPanel` 由 store 驱动真实渲染。`handleWarningClick` 接画布居中可做最小实现或留 TODO（非阻断）。

### D-07 [模板修复] 对齐真实节点输出契约
- `daily_summary`：`{{nodes.fetch_data.output}}` → `{{nodes.fetch_data.body}}`（http_request 实际输出 body）；`{{nodes.summarize.output}}` → ai_prompt 真实文本字段（`text` 或 `response`，执行期按 prompt.py 输出定）。
- `code_review_pipeline`：当前 http→ai_code_review default 边不符 `ai_code_review`（需 coding_result.merge_requests）契约。修复方向：使其符合 `ai_code_review` 输入契约（提供 coding_result/merge_requests，target_handle=coding_result），notify 引用真实字段（`review_report` 等）；具体链路重构由 executor 依 code_review.py 实现定，**终态须开箱执行到业务预期**。

### D-08 [模板校验测试] graph_validator 测试 + 模板零 error 守护
新建 `server/tests/workflows/test_graph_validator.py`；扩展 `test_template_loader.py`：每个内置模板经 validator 零 error，且人为注入断裂（坏 node_type / 缺必填 / 坏变量路径 / 坏 handle）→ 测试失败。

### D-09 [模板 loader 校验] 实例化前同一校验
`acreate_workflow_from_template` 在建库前调用 `WorkflowGraphValidator`，非法模板拒绝创建并返回结构化错误（与保存同源）。

### Claude's Discretion
- validator 的内部分层/wave 划分、dry-run 接口对"未持久化草图"vs"已存 workflow"的入参形态、IssuesPanel 类型扩展的精确 schema、code_review_pipeline 的具体链路重构方案、handle 合法性对动态输出节点的覆盖范围——交 planner/executor 依代码现状定夺。
</decisions>

<code_context>
## Existing Code Insights（勘察结论，RESEARCH 将深化）

**无统一校验器**：`WorkflowGraphValidator` 不存在（仅规划文档提及）。

**现有 DAG 校验**：`DAG.validate()`（dag.py L138-160，环/入口/孤立）**仅在执行启动调用**（scheduler.py L328-335），保存路径不调用。

**写入路径校验缺口**（views.py + serializers.py）：
- bulk-update（views.py L606-632 / `_bulk_update_nodes_and_edges` L230-316）：新建节点走 `WorkflowNodeCreateSerializer`（仅校验 node_type，**绕过 config jsonschema**）；边无 handle/归属校验；无 DAG/变量校验。
- 单节点 POST（L500-542）：仅 node_type。单边 POST（L548-604）：验节点归属，无 handle 校验。
- import（L460-494）：仅检查键存在 + node_type。
- from-template（L645-668 → loader.py L198-283）：无 config/DAG/变量校验，缺边仅 warning 跳过。

**可复用**：`BaseNode.validate_config()`（base.py L568-575，jsonschema）；`template_resolver`（`_TEMPLATE_VAR_RE` L37、`TemplateResolutionError` reason 枚举 L43-70、`_resolve_nodes_path` nodes 严格语义）；`NodeRegistry` + `NodePort.schema`（base.py L48-60）；`ConditionNode.get_dynamic_outputs`（condition.py L85+）。

**模板断裂**：
- `daily_summary.json` L37 `{{nodes.fetch_data.output}}`（http 实际输出 body/status_code/headers/ok，无 output）；L50 `{{nodes.summarize.output}}`（ai_prompt output 是 array，宜用 text）。
- `code_review_pipeline.json` L57-59 http→ai_code_review default 边不符契约（ai_code_review 需 coding_result.merge_requests，code_review.py L215-228/311-327）；L49 `{{nodes.review.output}}` 字段不存在（实际 review_report/issues_count/approved/reviewed_mrs）。
- `code_generation`/`feishu_full_pipeline` 相对健康。

**前端死代码**：`useWorkflowValidationStore`（web/src/stores/，仅 schema_mismatch 类型，**无任何 addWarning 调用方**）；`IssuesPanel.vue`（`v-if="hasWarnings"` 永远 false）；`saveWorkflow`（useWorkflowsStore L373-404）直接 bulk-update 无 dry-run。

**测试缺口**：无 graph validator 测试；test_template_loader.py 不校验图合法性/变量/可执行性。
</code_context>

<specifics>
## Specific Ideas

- 终态：保存 DAG 环/无入口/孤立/坏 edge/坏 config/坏变量引用 → 结构化错误（节点 id + 字段路径 + 原因）；合法保存不受影响。
- 前端保存前 dry-run，IssuesPanel 真实展示后端 warnings/errors。
- 任一内置模板（含 daily_summary、code_review_pipeline）创建后不改配置即可执行到业务预期。
- 注入断裂的模板让 TPL-02 测试失败。
- loader 实例化前用与保存相同的 validator。
</specifics>

<deferred>
## Deferred Ideas

- `input.*` / `trigger.*` 变量引用的严格静态校验（收紧 Phase 17 宽松边界）——本阶段不做。
- IssuesPanel 点击告警画布居中的完整交互——可最小实现或留 TODO。
- 校验规则的可配置/可扩展插件化——本阶段固定规则集。
</deferred>

---

*Phase: 20-validation*
*Context gathered: 2026-06-13 via smart discuss (autonomous)*
