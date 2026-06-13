# Phase 20: 保存即合法与模板修复 - Research

**Researched:** 2026-06-13
**Domain:** Django/DRF 工作流静态图校验（编辑态契约）+ 模板契约修复 + Vue3/Pinia 校验 UI 接线
**Confidence:** HIGH（全部结论基于本仓库源码勘察，关键文件逐行核对；无外部依赖、无版本不确定性）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 统一校验器位置与形态**：新建 `server/workflows/validation/graph_validator.py`（新包 `validation/`），`WorkflowGraphValidator` 类对"节点集 + 边集 + 各节点 config"做静态校验，返回 `{errors: [...], warnings: [...]}`，每条含 `node_id`（或 `edge_id`）、`field_path`、`reason`、`severity`。被 bulk-update、单节点/边 CRUD、import、template loader、dry-run 接口共用。
- **D-02 校验规则集（复用既有能力，不重造）**：
  - DAG 结构：复用 `DAG.validate()`（环/入口/孤立，dag.py L138-160）——从待保存节点/边构造内存 DAG 再调用。
  - 边节点归属：source/target 必须属于本 workflow 节点集。
  - handle 合法性：source_handle ∈ 上游 `outputs`（含 ConditionNode `get_dynamic_outputs` 派生分支）；target_handle ∈ 下游 `inputs`（或 default）。事实源 `NodeRegistry`。
  - config schema：复用 `BaseNode.validate_config()`（jsonschema），补齐 `WorkflowNodeCreateSerializer` 新建路径缺口。
  - 变量引用：用 `template_resolver._TEMPLATE_VAR_RE` 扫描 config 字符串字段，对 `{{nodes.<id>.<path>}}` 做静态存在性校验。
- **D-03 变量静态校验语义**：`nodes.*` 严格（节点不存在 → error；节点存在但上游输出 schema 无该字段 → error；上游输出**无 schema 声明**时只校验节点存在性，字段层跳过避免误报）；`input.*`/`trigger.*` 维持 Phase 17 宽松；reason 复用 `TemplateResolutionError` 枚举风格。
- **D-04 dry-run 接口**：新增 `POST /api/workflows/{id}/validate/`（或对未持久化草图 `POST /api/workflows/validate/` 收 nodes/edges），返回 `{errors, warnings}`，**不写库**。errors 阻断保存、warnings 仅提示。写入路径在写库事务前调用同一 validator。
- **D-05 保存失败语义**：非法保存返回 HTTP 400 + `{errors:[{node_id|edge_id, field_path, reason, severity}]}`；合法工作流保存行为零变化；warnings 不阻断。
- **D-06 前端接线**：`saveWorkflow` 保存前（或 bulk-update 400 时）写入 `useWorkflowValidationStore`；扩展 `ValidationWarning` 类型（超出当前唯一 `schema_mismatch`，增 error/warning severity 与多 reason）；`IssuesPanel` 由 store 驱动真实渲染；`handleWarningClick` 可最小实现或留 TODO。
- **D-07 模板修复（对齐真实节点输出契约）**：`daily_summary`：`{{nodes.fetch_data.output}}` → body；`{{nodes.summarize.output}}` → 真实文本字段（`text`/`response`）。`code_review_pipeline`：使其符合 `ai_code_review` 输入契约（提供 coding_result/merge_requests，target_handle=coding_result），notify 引用真实字段（`review_report` 等）；链路重构由 executor 依 code_review.py 定，终态须开箱执行到业务预期。
- **D-08 模板校验测试**：新建 `server/tests/workflows/test_graph_validator.py`；扩展 `test_template_loader.py`：每个内置模板经 validator 零 error，且人为注入断裂（坏 node_type/缺必填/坏变量路径/坏 handle）→ 测试失败。
- **D-09 模板 loader 校验**：`acreate_workflow_from_template` 在建库前调用 `WorkflowGraphValidator`，非法模板拒绝创建并返回结构化错误（与保存同源）。

### Claude's Discretion
- validator 的内部分层/wave 划分；dry-run 接口对"未持久化草图"vs"已存 workflow"的入参形态；`IssuesPanel`/`ValidationWarning` 类型扩展的精确 schema；`code_review_pipeline` 的具体链路重构方案；handle 合法性对动态输出节点的覆盖范围。

### Deferred Ideas (OUT OF SCOPE)
- `input.*`/`trigger.*` 变量引用的严格静态校验（收紧 Phase 17 宽松边界）——本阶段不做。
- `IssuesPanel` 点击告警画布居中的完整交互——可最小实现或留 TODO。
- 校验规则的可配置/可扩展插件化——本阶段固定规则集。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VAL-01 | 统一 `WorkflowGraphValidator`（DAG 环/入口/孤立、edge 归属与 handle、config schema、变量可解析性），多写入路径共用 | §标准栈 + §架构 Pattern 1/2/3；复用 `DAG`（dag.py L138-197）、`BaseNode.validate_config`（base.py L567-575）、`template_resolver`（_TEMPLATE_VAR_RE、reason 枚举）、`NodeRegistry`、`ConditionNode.get_dynamic_outputs` |
| VAL-02 | 非法保存（含新建 config 不合 schema）返回结构化错误（节点 id + 字段路径 + 原因），不再"能保存一执行就失败" | §架构 Pattern 4（写入路径接入）；闭合 `WorkflowNodeCreateSerializer` config 缺口（serializers.py L241-265）；bulk-update `_bulk_update_nodes_and_edges`（views.py L230-316）事务内拒绝 |
| VAL-03 | 前端 dry-run + `IssuesPanel` 真实展示校验警告/错误（消除死代码） | §前端接线；`useWorkflowValidationStore`（无调用方）、`IssuesPanel.vue`（`v-if=hasWarnings` 永 false）、`saveWorkflow`（useWorkflowsStore.ts L373-404 无 dry-run） |
| TPL-01 | 任一内置模板创建后零改配置可执行到业务预期（修复 daily_summary、code_review_pipeline 断裂） | §模板修复（已逐字段核对 http.py/prompt.py/code_review.py 真实输出契约） |
| TPL-02 | 模板自动化校验：node type 存在、必填齐全、变量节点 ID/字段在上游 schema 中、edge handle 与端口一致 | §测试架构；扩展 `test_template_loader.py`；**关键约束见 Pitfall 2/3（无 schema 输出无法触发字段层校验）** |
| TPL-03 | 模板 loader 实例化前执行与保存相同的图校验，非法拒绝并返回结构化错误 | §架构 Pattern 4；`acreate_workflow_from_template`（loader.py L198-283）建库前接入 validator |
</phase_requirements>

## Summary

本阶段是纯后端校验内聚 + 模板契约修复 + 前端接线，**零新增第三方依赖**：所需能力（`jsonschema`、`DAG`、`template_resolver`、`NodeRegistry`、`NodePort.schema`、DRF）均已在仓库内。核心工作是把散落的、互不一致的"半校验"（serializer 单字段校验、执行期 `DAG.validate`）收敛成一个**纯函数式、零 ORM、零 DB 可测**的 `WorkflowGraphValidator`，并在所有写入路径（bulk-update / 单节点·边 CRUD / import / template loader / dry-run）写库前调用同一事实源。

最大技术风险不在"怎么写校验"，而在"**怎么不误伤合法工作流**"。代码勘察揭示三处反直觉事实，若直接照搬直觉规则会把现有可跑的 `code_generation` 模板判为非法：(1) `collect_inputs` 对 `target_handle="default"` 的边做**扁平合并**上游输出（routing.py L227-238），因此 `ai_coding → ai_code_review` 的 default 边即便下游无 `default` 输入端口也是合法的；(2) 多数节点输出端口**无 `schema` 声明**（如 `http_request`），字段层静态校验对它们必须跳过，否则 daily_summary 修不修都会误报/漏报；(3) `code_review_pipeline` 的断裂是**结构性契约不符**（`http_request` 根本产不出 `merge_requests`），不是改个字段名能解决的，需要链路重构。

**Primary recommendation:** 建 `server/workflows/validation/graph_validator.py` 纯函数核心（仿 `template_resolver` 的"零 DB plain-dict 入参"范式）；DAG 结构校验通过新增 `DAG.from_node_edge_dicts()`（或 validator 内置内存构图）复用现有 `has_cycle/get_entry_nodes/validate`；handle 校验把 `"default"` 列为恒合法白名单；变量校验仅对 `nodes.*` 且仅在上游输出端口声明了 `schema` 时才下钻字段层。模板修复中 `daily_summary` 是字段重命名（低风险），`code_review_pipeline` 需把链路改为"触发器/上游提供 `coding_result.merge_requests` + 边 `target_handle=coding_result`"（中风险，需 executor 决断）。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 图静态校验规则（环/入口/孤立/handle/config/变量） | API/Backend（services 层纯函数） | — | 校验是后端契约事实源，前端只是消费者；必须服务端权威（VAL-01/02） |
| dry-run 校验端点 | API/Backend（DRF action） | — | 复用同一 validator，保证 dry-run 与真实保存同源（Pitfall 5） |
| 写入路径接入（bulk-update/CRUD/import/loader） | API/Backend | DB（事务回滚） | 写库前校验、error 即 400 + 回滚 |
| 模板契约修复 | API/Backend（模板 JSON + 节点实现核对） | — | 输出契约是节点实现的事实，模板必须对齐 |
| 校验结果展示（IssuesPanel/store） | Browser/Client（Pinia + Vue） | API（错误来自 400 body 或 dry-run 响应） | 纯展示与状态管理，无业务逻辑（VAL-03） |
| dry-run 触发（保存前/400 时） | Frontend（store action） | API | saveWorkflow 接线 |

## Standard Stack

### Core（全部已在仓库，无需安装）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `jsonschema` | 已依赖（base.py L9 `import jsonschema`） | config schema 校验 | `BaseNode.validate_config` 已用，复用即可（D-02） |
| Django DRF + `adrf` | django>=5.1, adrf>=0.1.12 | dry-run action / 400 结构化错误 | 既有 ViewSet `@action` 范式（views.py 多处） |
| `structlog` | 已依赖 | 校验事件日志 | 全仓统一（CLAUDE.md 约定） |
| `pytest`+`pytest-asyncio`+`pytest-django` | pytest>=9.0.2 | 后端测试 | 既有 `tests/workflows/` 397 例基线 |
| `vitest`+`@vue/test-utils` | vitest^4 | 前端 store/组件测试 | 既有前端测试栈 |

**仓库内可复用资产（事实源，逐行核对）：**

| 资产 | 位置 | 用途 |
|------|------|------|
| `DAG` / `DAG.validate()` / `has_cycle()` / `get_entry_nodes()` | `server/workflows/engine/dag.py` L44-197 | 环/入口/孤立校验；当前仅 `from_workflow`/`afrom_workflow` 从 ORM 构图，**需补内存构图** |
| `BaseNode.validate_config(config)` | `server/workflows/nodes/base.py` L567-575 | jsonschema 校验，返回 `list[str]` |
| `BaseNode.inputs/outputs`（`NodePort`） | base.py L48-60, L544-545 | handle 合法性事实源；`NodePort.schema` 为字段层校验依据 |
| `ConditionNode.get_dynamic_outputs(config)` | `server/workflows/nodes/control/condition.py` L84-103 | 动态输出 handle（`branch_0..N` + `default_branch`，缺省 `else`） |
| `template_resolver`（`_TEMPLATE_VAR_RE`、`VALID_PREFIXES`、`TemplateResolutionError`、`_resolve_nodes_path`、`_INDEX_SUFFIX_RE`） | `server/workflows/engine/template_resolver.py` L31-237 | 变量扫描正则 + reason 枚举（`node_not_found`/`field_not_found`/`unknown_prefix`/`missing_field_path`） |
| `NodeRegistry.get(node_type)` / `get_all_schemas()` / `get_all()` | `server/workflows/nodes/registry.py` | 节点类型/端口/schema 查询（单例、自动发现、缓存） |
| `rewrite_template_refs` | `server/workflows/templates/loader.py` L63-99 | （仅作参考——变量扫描正则口径一致性比对） |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 内存复用 `DAG` 的环/入口检测 | 在 validator 内重写 DFS 环检测 | **不推荐**——`DAG.has_cycle` 已有"条件分支非 default handle 回退边不算环"的精细语义（dag.py L162-193，审批驳回回环），重写必丢失；复用避免双轨语义漂移 |
| 复用 `template_resolver.resolve_path` 做变量校验 | 调用现有解析核心传"空 outputs" | **不可行**——resolver 需要真实 `previous_outputs` 值；静态校验只有"节点 + 端口 schema"，必须新写"schema 模式"扫描（见 Pattern 3），但 reason 枚举/正则复用 |

**Installation:** 无。本阶段不安装任何包。

## Package Legitimacy Audit

> 本阶段**不安装任何外部包**。所用 `jsonschema`/`structlog`/DRF/`adrf`/`pytest*`/`vitest` 均为既有依赖（见 `server/pyproject.toml` / `web/package.json`）。无新增 registry 依赖 → slopcheck 不适用。

| Package | Registry | Disposition |
|---------|----------|-------------|
| （无新增） | — | N/A |

## Architecture Patterns

### System Architecture Diagram

```text
                       ┌─────────────────────────────────────────────┐
   编辑器保存/导入/模板  │   写入路径（views.py / loader.py）              │
   ────────────────────▶│  bulk-update · 单节点·边 CRUD · import ·       │
                        │  from-template · POST /validate（dry-run）     │
                        └───────────────────┬─────────────────────────┘
                                            │ nodes[] + edges[] + 各 config
                                            ▼
                        ┌─────────────────────────────────────────────┐
                        │  WorkflowGraphValidator.validate(...)         │  ← 唯一事实源（纯函数, 零 ORM）
                        │   (server/workflows/validation/graph_validator.py)│
                        ├─────────────────────────────────────────────┤
                        │ 1. 内存构图 → DAG.has_cycle/entry/orphan      │──复用 dag.py
                        │ 2. edge 归属：src/tgt ∈ 节点集                 │
                        │ 3. handle：src_handle∈outputs(+dyn);          │──NodeRegistry / get_dynamic_outputs
                        │            tgt_handle∈inputs ∪ {"default"}     │
                        │ 4. config：BaseNode.validate_config(jsonschema)│──base.py
                        │ 5. 变量：_TEMPLATE_VAR_RE 扫描 nodes.* 严格    │──template_resolver 正则+reason
                        └───────────────────┬─────────────────────────┘
                                            │ {errors:[{node_id|edge_id, field_path, reason, severity}], warnings:[]}
                          errors 非空 ──────┤
                                            ▼
                   ┌────────────────┐                ┌─────────────────────────────┐
                   │ 写入路径：      │  HTTP 400 +    │ dry-run：直接返回 200 +       │
                   │ raise → 事务回滚 │  errors body   │ {errors, warnings}（不写库）  │
                   └────────────────┘                └──────────────┬──────────────┘
                                                                    ▼
                                              ┌────────────────────────────────────┐
                                              │ 前端 saveWorkflow / dry-run          │
                                              │  → useWorkflowValidationStore        │
                                              │  → IssuesPanel.vue 渲染 errors/warns  │
                                              └────────────────────────────────────┘
```

### Recommended Project Structure

```text
server/workflows/
├── validation/                      # 新包（D-01）
│   ├── __init__.py                  # 导出 WorkflowGraphValidator / ValidationIssue / 构图 helper
│   └── graph_validator.py           # 纯函数核心：零 ORM、plain dict 入参、pytest 零 DB 可测
├── engine/dag.py                    # 增 from_node_edge_dicts()（或在 validator 内构图）
├── api/
│   ├── views.py                     # bulk_update/node·edge CRUD/import/from_template 接入；新增 validate action
│   └── serializers.py               # WorkflowNodeCreateSerializer 补 config schema 校验（或交给 validator）
└── templates/{daily_summary,code_review_pipeline}.json   # 修复
server/tests/workflows/
├── test_graph_validator.py          # 新建（D-08，纯单元 + 少量 django_db 接入测试）
└── test_template_loader.py          # 扩展：每模板零 error + 注入断裂失败（TPL-02）
web/src/
├── stores/useWorkflowValidationStore.ts   # 扩 ValidationWarning → ValidationIssue（severity+reason）
├── stores/useWorkflowsStore.ts            # saveWorkflow 接 dry-run / 解析 400
└── components/workflow/validation/IssuesPanel.vue  # 真实渲染 errors+warnings
```

### Pattern 1: 纯函数校验核心（仿 template_resolver 范式）

**What:** `WorkflowGraphValidator` 接收 plain dict 列表（不接收 ORM QuerySet），返回结构化结果。所有依赖（`NodeRegistry`、`DAG`）都不触 DB。
**When to use:** 这是 D-01 的核心；保证零 DB 单测（与 `routing.py`/`template_resolver.py` 一致的可测性）。
**Example（建议签名）:**

```python
# server/workflows/validation/graph_validator.py
from dataclasses import dataclass, asdict

@dataclass
class ValidationIssue:
    reason: str           # node_not_found / field_not_found / cycle / no_entry /
                          # orphan_node / edge_node_missing / invalid_source_handle /
                          # invalid_target_handle / config_schema_invalid / unknown_node_type ...
    severity: str         # "error" | "warning"
    field_path: str = ""  # 如 "config.user_prompt" / "edges[2].source_handle"
    node_id: str | None = None
    edge_id: str | None = None
    message: str = ""

class WorkflowGraphValidator:
    def validate(
        self,
        nodes: list[dict],   # 每项: {id|temp_id, short_id, node_type, config}
        edges: list[dict],   # 每项: {id?, source_node_id, target_node_id, source_handle, target_handle}
    ) -> dict:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        # 1) node_type 存在性  2) config jsonschema  3) DAG 结构
        # 4) edge 归属 + handle  5) nodes.* 变量静态校验
        ...
        return {
            "errors": [asdict(i) for i in errors],
            "warnings": [asdict(i) for i in warnings],
        }
```

### Pattern 2: 内存构图复用 DAG 结构校验

**What:** `DAG.from_workflow`/`afrom_workflow`（dag.py L54-108）从 ORM 构图；本阶段需从未持久化的 dict 构图。
**When to use:** DAG 环/入口/孤立校验（D-02 第 1 条）。
**Example:** 新增 `DAG.from_node_edge_dicts(nodes, edges)`，逐字符照搬 `from_workflow` 的 `incoming/outgoing/incoming_edges/_detect_back_edges` 逻辑，但 `DAGNode.node` 用轻量 duck-typed 对象承载 `id`/`node_type`/`name`（`DAG.validate` 只读这三个属性，dag.py L154/158）：

```python
from types import SimpleNamespace
# DAGNode.node 只需 .id/.node_type/.name；SimpleNamespace 足矣
node_obj = SimpleNamespace(id=nid, node_type=nd["node_type"], name=nd.get("name", nid))
```
构图后直接调 `dag.validate()`（返回 `list[str]`）+ `dag.has_cycle()`，把字符串结果映射成 `ValidationIssue(reason="cycle"/"no_entry"/"orphan_node")`。**复用而非重写**保留"条件分支回退边不算环"的精细语义（dag.py L162-193）。

### Pattern 3: 变量引用"schema 模式"静态校验

**What:** 扫描每个 config 的字符串字段，对 `{{nodes.<short_id>.<path>}}` 做静态存在性校验。
**When to use:** D-02 第 5 条 / D-03。
**关键规则（防误报，逐条）：**
1. 用 `template_resolver._TEMPLATE_VAR_RE`（L37）扫描；仅处理 `nodes.` 前缀；`input./trigger./global./context./config.` 跳过（D-03 宽松边界，本阶段不收紧）。
2. `$` 开头（JSONPath / `$.` 简写）**跳过**——`template_resolver` 对其宽松保留字面量（resolver L260-285），静态校验同样不收紧。
3. 节点 ID = `short_id`（变量引用用 short_id；edges 用 UUID——两套 id 空间，见 Pitfall 6）。`short_id` 不在节点集 → `node_not_found`（error）。
4. 字段层：**仅当**上游节点该输出端口 `NodePort.schema` 非空时，才校验首段字段 ∈ `schema["properties"]`；schema 为 `None` 时**只校验节点存在性，字段层跳过**（D-03 显式要求，否则误报，见 Pitfall 2）。
5. 剥离 `[n]`/`[-n]` 下标后缀（`_INDEX_SUFFIX_RE` L40）再取首段字段名。
6. reason 复用 `TemplateResolutionError` 枚举（`node_not_found`/`field_not_found`/`missing_field_path`），保持前后端一致（D-03）。
7. 上游输出端口选择：节点可能多端口（`default`+`error`）。建议取**所有输出端口 schema 的 properties 并集**做字段校验（更宽松、少误报）；具体口径交 planner（Discretion）。

### Pattern 4: 写入路径统一接入（事务前/事务内拒绝）

**What:** 五条写入路径都调同一 validator。
**接入点（逐一）：**

| 路径 | 文件:行 | 接入方式 |
|------|---------|----------|
| bulk-update | views.py L606-632 → `_bulk_update_nodes_and_edges` L230-316 | 在 `transaction.atomic()` 内、`_resolve_short_ids` 收敛后用**最终 short_id 空间**构造校验输入，校验失败 `raise ValidationError({"errors": [...]})` → 自动回滚 → DRF 400（见 Pitfall 6 关于何时校验）|
| 单节点 POST/PUT/PATCH | views.py L500-542（`nodes`/`node_detail`）| `WorkflowNodeSerializer.validate` 已做 config schema（serializers.py L226-238），**但 `WorkflowNodeCreateSerializer` 缺**（L241-265 仅校 node_type）→ 补 config 校验或调 validator 子集 |
| 单边 POST/PUT/PATCH | views.py L548-604 | 现仅验节点归属（L567-568），无 handle 校验 → 补 handle 子集校验 |
| import | views.py L460-494（`Workflow.afrom_json`）+ serializers.py L454-477（仅 node_type）| 入库前调 validator（afrom_json 内或 view 层）|
| from-template | views.py L645-682 → loader.py `acreate_workflow_from_template` L198-283 | 建库**前**用模板 nodes/edges + `template_to_short` 映射调 validator（D-09）|
| dry-run | 新增 `@action` | 直接调 validator，返回 `{errors,warnings}`，不写库（D-04）|

**async/sync 边界：** validator 是纯 CPU、无 DB → 在 async view 中可直接调用（首次触发 `NodeRegistry._ensure_initialized` 有一次性文件 IO，可接受；若严格可 `await sync_to_async(validator.validate)(...)`）。`bulk-update` 已整体走 `sync_to_async(_bulk_update_nodes_and_edges)`（views.py L620），在其同步函数体内同步调用 validator 最自然。

### Pattern 5: dry-run DRF action（两种形态）

**What:** D-04 两个端点。
**建议：**
- 已存 workflow：`@action(detail=True, methods=["post"], url_path="validate")` → `/api/workflows/{id}/validate/`。入参可选 `{nodes, edges}`（校验草图）或缺省取 DB 现状。
- 未持久化草图：`@action(detail=False, methods=["post"], url_path="validate")` → `/api/workflows/validate/`，必填 `{nodes, edges}`。
- **路由不冲突**：DRF `DefaultRouter`（urls.py L35）把 `detail=False` 的 list-route 注册在 `{pk}` detail-route 之前，`workflows/validate/` 不会被 `workflows/{pk}/` 吞掉。两个 action 都用同一 `WorkflowGraphValidator`，保证 dry-run 与真实保存同源（Pitfall 5）。

### Anti-Patterns to Avoid
- **重写 DAG 环检测**：必丢"条件分支回退边合法"语义（dag.py L162-193），导致审批驳回回环模板被误判循环依赖。
- **把 `target_handle="default"` 当真实端口校验**：会误伤 `ai_coding → ai_code_review` 这类 default 边（下游无 default 输入端口但靠 `collect_inputs` 扁平合并工作，见 Pitfall 1）。
- **对无 schema 的输出端口下钻字段层**：`http_request` 等输出端口 `schema=None`，强行校验会全量误报（见 Pitfall 2）。
- **校验时机早于 short_id 收敛**：bulk-update 会服务端重写 short_id（views.py L252、L287-303），在收敛前校验变量引用会用错 id 空间（Pitfall 6）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 环/入口/孤立检测 | 新写 DFS/拓扑 | `DAG.has_cycle()`/`get_entry_nodes()`/`validate()` | 已含条件回退边语义，重写漂移 |
| config 校验 | 手写字段必填检查 | `BaseNode.validate_config()`（jsonschema） | schema 已是节点事实源 |
| 变量占位符解析 | 自写 `{{}}` 正则 | `template_resolver._TEMPLATE_VAR_RE` + reason 枚举 | 与 Phase 17 运行态解析口径一致，前后端 reason 统一 |
| 动态输出 handle | 硬编码 condition 分支名 | `ConditionNode.get_dynamic_outputs(config)` | 分支数随 config 变；`else`/`default_branch` 可配 |
| 节点类型/端口查询 | 前端硬编码 / 重建注册表 | `NodeRegistry`（Phase 19 已为 SSOT） | 单例自动发现，避免漂移 |

**Key insight:** 本阶段几乎不写"新算法"——价值在**收敛与接线**：把已有的五块校验能力组合进一个事实源，并消除"serializer 半校验 + 执行期才 DAG.validate + 前端死代码"的三轨不一致。

## Runtime State Inventory

> 本阶段为代码/配置/模板 JSON 改动 + 测试，无 rebrand/迁移语义。逐类核对：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **无** —— 不改 DB schema、不迁移既有 `WorkflowNode.config`。校验是读侧；既有"已保存的非法工作流"不会被回溯改写（仅新保存被拦） | 无（注意：升级后既有非法工作流仍能加载/展示，只是再次保存时被拦——属预期，非回退） |
| Live service config | **无** —— 不涉及 n8n/Datadog/外部服务注册 | 无 |
| OS-registered state | **无** | 无 |
| Secrets/env vars | **无** —— validator 不读凭证 | 无 |
| Build artifacts | **无新增**。注意 `NodeRegistry` 依赖 `web/src/types/workflow/node-definitions/node-definitions.json`（registry.py L16-50）注入 ui_schema，但端口/schema 来自 Python 节点类本身，与本校验无关 | 无 |

## Common Pitfalls

### Pitfall 1: `target_handle="default"` 误判为非法端口
**What goes wrong:** 直觉规则"target_handle 必须 ∈ 下游 inputs"会把 `ai_coding → ai_code_review` 的 default 边判非法——因为 `ai_code_review.inputs` 只有 `coding_result`/`plan`，**没有 `default`**（code_review.py L215-230）。但该边在 `code_generation` 模板里**实际能跑**。
**Why:** `collect_inputs`（routing.py L227-238）对 `target_handle in ("default", "")` 走 `inputs.update(upstream)` **扁平合并**上游输出的顶层键。`ai_coding` 输出含顶层 `coding_result`/`merge_requests`/`plan`（coding.py L1338-1357），合并后 `get_input("coding_result")` 命中。
**How to avoid:** handle 校验把 `"default"`（及空串）列为**恒合法白名单**，只对非 default target_handle 校验 ∈ inputs。source_handle 同理（`"default"` 恒合法）。
**Warning signs:** TPL-02"每模板零 error"测试在 `code_generation`/`feishu_full_pipeline` 上失败。

### Pitfall 2: 对无 `schema` 输出端口做字段层校验 → 全量误报
**What goes wrong:** `http_request` 输出端口 `default`/`error` 的 `NodePort.schema=None`（http.py L83-86），实际输出键是 `{status_code, headers, body, ok}`（L133-138）。若静态校验对它下钻字段，`{{nodes.fetch_data.body}}` 会因"schema 无 properties"误报。
**Why:** 多数节点未声明输出 schema；`schema` 只在 `ai_prompt`/`ai_code_review`/`ai_coding` 等少数节点有（prompt.py L268-310、code_review.py L238-258、coding.py L175+）。
**How to avoid:** D-03 已锁定——**无 schema 时只校验节点存在性，字段层跳过**。
**Warning signs:** 修好的 daily_summary（`fetch_data.body`）仍报 `field_not_found`。

### Pitfall 3: TPL-02 "注入坏变量路径"必须用 schema-可校验的路径，否则测试假绿
**What goes wrong:** daily_summary 的真实断裂 `{{nodes.fetch_data.output}}` 和 `{{nodes.summarize.output}}` **都不会被字段层校验抓到**：`fetch_data` 是 http（无 schema → 跳过）；`summarize` 是 ai_prompt，而 `output` **确实是其声明字段**（prompt.py L281-293，`output` 是 OpenResponses 数组项）——校验通过，但运行时拼出的是数组字符串而非日报文本。即 **TPL-01（运行语义正确）≠ TPL-02（validator 零 error）**。
**Why:** 字段存在性校验只能抓"字段不在 schema"，抓不到"字段存在但语义/类型不对"。
**How to avoid:**
- TPL-01 修复（daily_summary → `body` / `text`）的正确性由**人工核对 + 可选执行级断言**保证，不能仅靠 validator。
- TPL-02 的"注入坏变量路径"用例必须注入 **schema-可判定**的断裂：如 `{{nodes.summarize.nonexistent_field}}`（ai_prompt 有 schema → `field_not_found`）或 `{{nodes.ghost_node.x}}`（`node_not_found`），而非 http 节点字段。
**Warning signs:** 注入断裂后 validator 仍零 error，测试不红。

### Pitfall 4: `code_review_pipeline` 是结构性契约不符，非字段重命名
**What goes wrong:** 当前链路 `webhook → http_request(fetch_pr) → ai_code_review(review) → notify`。`ai_code_review.execute` 需要 `coding_result.merge_requests`（code_review.py L311-328），但上游 `http_request` 输出只有 `{status_code, headers, body, ok}`，**永远产不出 merge_requests** → 运行时直接 `failed: 编码结果中无 merge_requests 数据`。且 `ai_code_review` 自身用 Friday `repository_id`+`mr_id` 经凭证拉 diff（L577-616），裸 PR webhook 给不出这些。此外 notify 的 `{{nodes.review.output}}`（pipeline L49）—— `ai_code_review` 输出 schema 是 `review_report/issues_count/severity_breakdown/approved`（L238-258），`output` 不在其中 → `field_not_found`（这条 validator 能抓）。
**Why:** `ai_code_review` 的设计契约是"审查 `ai_coding` 产出的 MR"（见 `code_generation` 模板 `ai_coding → code_review`），而 `code_review_pipeline` 试图用 http 拉 diff 喂它——契约错配。
**How to avoid（交 planner/executor 决断，D-07）：** 候选方案——
  - **方案 A（推荐，最小契约正确）**：去掉 http 节点，让触发器（webhook/manual）payload 直接携带 `merge_requests: [{mr_id, repository_id, repository_name, mr_url}]`，边 `trigger → review` 用 `target_handle="coding_result"`（或 default，靠扁平合并 + `ai_code_review` 对 `input_data.merge_requests` 的兜底分支 code_review.py L312-314）；notify 改引 `{{nodes.review.review_report}}` 等真实字段。模板 description 说明 webhook payload 形态。"业务预期"= 给定正确 payload 即审查并通知。
  - **方案 B**：把模板重构成含 `ai_coding` 上游的精简版（与 code_generation 重叠，价值低）。
  - 选定方案需保证 (1) validator 零 error；(2) "零改配置可执行到业务预期"（TPL-01）——注意 `repository_id` 必须是 Friday 已注册仓库 UUID + 配好凭证，这是模板**文档化前提**，非 config 默认值能填。**这是本阶段最大不确定点，建议 planner 先定终态语义再排 task。**

### Pitfall 5: dry-run 与真实保存校验不一致
**What goes wrong:** 若 dry-run 与写入路径各写一份校验逻辑，会出现"dry-run 绿、保存红"或反之，VAL-03 的面板失去意义。
**How to avoid:** 二者**调同一 `WorkflowGraphValidator` 实例方法**（D-04 已要求）；dry-run 与 bulk-update 传入**同口径**的 nodes/edges（尤其 short_id 空间一致，见 Pitfall 6）。
**Warning signs:** 集成测试中同一草图 dry-run 与 bulk-update 结果不一致。

### Pitfall 6: short_id 收敛时机 vs 变量校验 id 空间
**What goes wrong:** bulk-update 会服务端重写 short_id 并改写 config 中的 `{{nodes.<old>.*}}`（views.py `_resolve_short_ids` L162-227、`rewrite_template_refs` L287-303）。edges 用 **UUID**（`source_node_id`/`target_node_id`），变量引用用 **short_id**——两套 id 空间。若在收敛前校验变量引用，会用客户端旧 short_id 判定，与最终落库不一致。
**How to avoid:** 在 `_bulk_update_nodes_and_edges` 内，于 `_resolve_short_ids` + 引用重写**之后**、`commit` 之前用最终状态校验；或对 dry-run/草图明确约定"按 payload 自带 short_id 校验"。edge 归属/handle 校验用 UUID 空间，变量校验用 short_id 空间——validator 需同时接收两者（节点 dict 同时带 `id` 与 `short_id`）。
**Warning signs:** 含 short_id 重命名的保存被误报变量悬挂引用。

### Pitfall 7: `NodeRegistry.list_types()` 不存在（既有潜在 bug）
**What goes wrong:** `serializers.py` L213、L467 调用 `NodeRegistry.list_types()`，但 `registry.py` **无此方法**（只有 `get`/`get_all`/`get_all_schemas`/`get_by_category`/`get_ui_schema`）。该调用仅在"node_type 未知"错误分支触发，平时不暴露 → 一旦校验逻辑复用同名调用会 `AttributeError`。
**How to avoid:** validator 用 `NodeRegistry.get_all().keys()` 或 `[s["node_type"] for s in get_all_schemas()]` 列举类型；顺手可在本阶段补 `list_types()` 或修正 serializer 调用（小修，非范围蔓延）。
**Warning signs:** 触发未知 node_type 分支时 500 而非 400。

### Pitfall 8: 孤立节点判定对 `feishu_event_trigger` 的边界
**What goes wrong:** `DAG.validate` 孤立检查豁免 `manual_trigger`/`webhook_trigger`（dag.py L154-157），**不豁免** `feishu_event_trigger`。单触发器无边的草图会被判孤立。
**How to avoid:** 模板均连边（feishu_full_pipeline trigger 有出边），正常不触发；但 dry-run 编辑中途的草图可能误报——考虑把"孤立节点"降为 `warning`（severity）而非 error（交 planner 定 severity 映射，D-05 warnings 不阻断）。

## Code Examples

### handle 合法性校验（防误伤 default + 动态输出）

```python
# 伪代码，graph_validator.py 内
def _validate_handles(self, node_by_id, edges, issues):
    for idx, edge in enumerate(edges):
        src = node_by_id.get(str(edge["source_node_id"]))
        tgt = node_by_id.get(str(edge["target_node_id"]))
        if src is None or tgt is None:
            issues.append(ValidationIssue(
                reason="edge_node_missing", severity="error",
                edge_id=edge.get("id"), field_path=f"edges[{idx}]"))
            continue
        sh = edge.get("source_handle") or "default"
        th = edge.get("target_handle") or "default"

        # source_handle：default 恒合法；condition 用动态输出
        src_cls = NodeRegistry.get(src["node_type"])
        if sh != "default":
            out_names = {p.name for p in src_cls.outputs}
            if hasattr(src_cls, "get_dynamic_outputs"):
                out_names |= {p.name for p in src_cls.get_dynamic_outputs(src.get("config", {}))}
            if sh not in out_names:
                issues.append(ValidationIssue(
                    reason="invalid_source_handle", severity="error",
                    edge_id=edge.get("id"), field_path=f"edges[{idx}].source_handle",
                    message=f"source_handle '{sh}' 不在 {src['node_type']} 输出端口 {sorted(out_names)} 中"))

        # target_handle：default（扁平合并路径）恒合法，仅校验非 default
        if th != "default":
            tgt_cls = NodeRegistry.get(tgt["node_type"])
            in_names = {p.name for p in tgt_cls.inputs}
            if th not in in_names:
                issues.append(ValidationIssue(
                    reason="invalid_target_handle", severity="error",
                    edge_id=edge.get("id"), field_path=f"edges[{idx}].target_handle",
                    message=f"target_handle '{th}' 不在 {tgt['node_type']} 输入端口 {sorted(in_names)} 中"))
```

### config schema 校验（复用 BaseNode.validate_config）

```python
for nd in nodes:
    cls = NodeRegistry.get(nd["node_type"])
    if cls is None:
        issues.append(ValidationIssue(reason="unknown_node_type", severity="error",
                                      node_id=nd.get("id"), field_path="node_type"))
        continue
    for msg in cls.validate_config(nd.get("config", {})):  # base.py L567-575
        issues.append(ValidationIssue(reason="config_schema_invalid", severity="error",
                                      node_id=nd.get("id"), field_path="config", message=msg))
```

### 模板修复 diff（daily_summary，低风险字段重命名）

```text
daily_summary.json
  L37  "{{nodes.fetch_data.output}}"  →  "{{nodes.fetch_data.body}}"     # http 实际输出 body（http.py L136）
  L50  "{{nodes.summarize.output}}"   →  "{{nodes.summarize.text}}"      # ai_prompt 主文本字段（prompt.py L389/278）
```
> 注：`text` 在 ai_prompt 输出 schema 内（prompt.py L278），validator 通过；`body` 因 http 无 schema 而跳过字段层——两者修复后 validator 均零 error，**且运行语义正确**（这是 TPL-01 的真正目标，区别于 Pitfall 3）。

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 保存只校验 node_type（serializer 半校验），执行期才 `DAG.validate` | 保存即图校验（统一 validator） | 本阶段 | 非法工作流写库前被拦 |
| 前端 `useWorkflowValidationStore` 死代码（无调用方）、`IssuesPanel` 永不显示 | dry-run 驱动真实展示 | 本阶段 | VAL-03 落地 |
| 模板 `daily_summary`/`code_review_pipeline` 引用不存在字段/契约错配 | 对齐节点真实输出契约 | 本阶段 | TPL-01 开箱可跑 |

**Deprecated/outdated:** 无技术弃用；仅修正 `NodeRegistry.list_types()` 的潜在误用（Pitfall 7）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `code_review_pipeline` 方案 A（触发器 payload 携带 merge_requests + target_handle=coding_result）能满足"零改配置执行到业务预期" | Pitfall 4 | 若"业务预期"要求真实拉 PR diff，需 Friday 已注册仓库 + 凭证，模板无法纯 config 自足 → 需重新定义终态语义（建议 planner 与用户确认或在模板 description 文档化前提） |
| A2 | 变量字段校验取"所有输出端口 schema properties 并集"是可接受口径 | Pattern 3 | 若按单一 `default` 端口校验，可能对引用 `error` 端口字段误报；属 Discretion，planner 可调 |
| A3 | 孤立节点宜降为 warning 以避免编辑中途草图误报 | Pitfall 8 | 若保持 error，dry-run 在未连完边时频繁报错，影响体验；severity 映射交 planner（D-05） |
| A4 | bulk-update 在 short_id 收敛后、commit 前校验最稳妥 | Pitfall 6 | 若改在 serializer 层前置校验，含重命名的保存可能误报悬挂引用 |

## Open Questions

1. **`code_review_pipeline` 终态语义（最高优先级）**
   - 已知：`ai_code_review` 需 `coding_result.merge_requests` + 用 Friday `repository_id`/`mr_id` + 凭证拉 diff；http 节点产不出。
   - 不清楚："开箱执行到业务预期"是否接受"模板要求 webhook 提供正确 payload + 预注册仓库"作为前提（文档化），还是必须纯 config 自足。
   - 建议：planner 在排 task 前定终态（方案 A / B），必要时回到 discuss 与用户确认；这是 TPL-01 的不确定根源。

2. **dry-run 入参形态（草图 vs 已存）**
   - 建议：detail=True 收可选 `{nodes,edges}`、detail=False 收必填 `{nodes,edges}`；节点 dict 同时带 `id`/`short_id` 以覆盖 edge（UUID）与变量（short_id）两套 id 空间（Pitfall 6）。Discretion。

3. **severity 映射与 warnings 集合**
   - errors（阻断）：cycle / no_entry / edge_node_missing / invalid_handle / config_schema_invalid / unknown_node_type / node_not_found / field_not_found。
   - warnings（不阻断）候选：orphan_node（Pitfall 8）、可解析但类型存疑等。交 planner 定（D-05/D-06）。

## Environment Availability

> 本阶段为纯代码/配置/测试改动，**无新增外部依赖、服务、CLI**。`pytest`/`uv`（server）、`pnpm`/`vitest`（web）均为既有工具链。

Step 2.6: 仅依赖既有工具链，无新外部依赖需探测。

## Validation Architecture

> `.planning/config.json` `workflow.nyquist_validation: true` → 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | 后端 `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django`；前端 `vitest@^4` + `@vue/test-utils` |
| Config file | `server/pyproject.toml`（pytest/ruff/mypy）；`web/vitest.config.*`（既有） |
| Quick run command | `cd server && uv run pytest tests/workflows/test_graph_validator.py -x -q` |
| Full suite command | `cd server && uv run pytest tests/workflows -q`（基线 397 例，须零回归）；`pnpm -C web test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VAL-01 | 环/入口/孤立/handle/config/变量 各规则命中与放行（含 default 恒合法、无 schema 跳过字段） | unit（零 DB） | `uv run pytest tests/workflows/test_graph_validator.py -x` | ❌ Wave 0 |
| VAL-02 | bulk-update 非法 config/坏 handle → 400 结构化 errors；合法保存零变化（不误拒） | integration（django_db） | `uv run pytest tests/workflows/test_api.py -k bulk -x` | ⚠️ 扩展既有 test_api.py |
| VAL-02 | 单节点 create（`WorkflowNodeCreateSerializer`）补 config 校验 | integration | `uv run pytest tests/workflows/test_api.py -k node -x` | ⚠️ 扩展 |
| VAL-03 | `useWorkflowValidationStore` 扩展类型；`IssuesPanel` 渲染 errors+warnings；saveWorkflow 接 dry-run/解析 400 | unit（vitest） | `pnpm -C web test` | ❌ Wave 0（新 .test.ts）|
| TPL-01 | daily_summary 修复后变量解析到真实字段；code_review_pipeline 终态可执行 | unit + 人工/执行级 | `uv run pytest tests/workflows/test_template_loader.py -x` | ⚠️ 扩展（注意 Pitfall 3：纯 validator 抓不到语义错）|
| TPL-02 | 每模板经 validator 零 error；注入坏 node_type/缺必填/坏变量路径(schema 可判)/坏 handle → 失败 | unit/integration | `uv run pytest tests/workflows/test_template_loader.py -k validator -x` | ⚠️ 扩展 |
| TPL-03 | `acreate_workflow_from_template` 对非法模板建库前拒绝并返回结构化错误 | integration（django_db async） | `uv run pytest tests/workflows/test_template_loader.py -k from_template -x` | ⚠️ 扩展 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/workflows/test_graph_validator.py -x -q`（+ 改前端时 `pnpm -C web test --run` 相关文件）
- **Per wave merge:** `uv run pytest tests/workflows -q`（全 397+ 例零回归）
- **Phase gate:** 后端全绿 + `pnpm -C web test` 全绿，再进 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `server/tests/workflows/test_graph_validator.py` —— 覆盖 VAL-01 全部规则（含 Pitfall 1/2 的"不误伤"用例：default 边、无 schema 字段、condition 动态输出）
- [ ] 扩展 `server/tests/workflows/test_template_loader.py` —— TPL-01/02/03（每模板零 error + schema-可判定的断裂注入）
- [ ] 扩展 `server/tests/workflows/test_api.py` —— VAL-02 bulk-update / 单节点 create 400 路径
- [ ] 前端 `web/src/stores/__tests__/useWorkflowValidationStore.test.ts` + `IssuesPanel` 渲染测试（VAL-03）
- [ ] 无需新框架——既有 pytest/vitest 基线齐备

## Security Domain

> `security_enforcement: true`，`security_asvs_level: 1`。本阶段是**输入校验强化**（编辑态契约），与安全目标天然对齐。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | **yes** | validator 本体即结构化输入校验；config 走 `jsonschema`；变量引用扫描复用 Phase 17 已转义正则（`rewrite_template_refs` 用 `re.escape`，loader.py L84）——本阶段变量校验**只读不重写**，不引入正则注入面 |
| V4/V11 Access Control & Business Logic | yes | validator 在既有 `WorkflowPermission` 之后执行（views.py L329），不放宽鉴权；越权改写防护沿用 bulk-update 的 `workflow=workflow` 作用域过滤（views.py L258、L291）|
| V7 Error Handling | yes | 错误信息只含拓扑/字段名（node_id/short_id/field_path/reason），**绝不含上游输出值**——延续 `TemplateResolutionError` 的 T-17-01 信息泄露防线（template_resolver.py L54-55、L157）|
| V6 Cryptography | no | 不涉及加密 |
| V2/V3 Auth/Session | no | 不改鉴权/会话 |

### Known Threat Patterns for {Django/DRF + 纯函数校验}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 校验错误消息回显上游输出值 → 信息泄露 | Information Disclosure | `ValidationIssue` 只放键名/路径/reason，不放 config/输出值（沿用 T-17-01）|
| dry-run 端点越权读他人 workflow 校验 | Elevation of Privilege | detail=True 走 `WorkflowPermission` + 作用域；detail=False 仅校验请求体自带 nodes/edges（不读库），无越权面 |
| 变量校验正则被恶意 short_id 注入 | Tampering | 本阶段变量校验**不构造动态正则**（只用固定 `_TEMPLATE_VAR_RE` 扫描 + 字典查 short_id）；如需比对重写路径，`rewrite_template_refs` 已 `re.escape`（loader.py L84）|
| 非法图绕过校验直接执行 | Tampering | 五条写入路径**全部**接入同一 validator（D-01），无旁路；执行期 `DAG.validate`（scheduler）作为第二道防线保留 |

## Sources

### Primary (HIGH confidence) —— 仓库源码逐行核对
- `server/workflows/engine/dag.py` L44-236 —— DAG 构图/validate/has_cycle/get_entry_nodes
- `server/workflows/engine/routing.py` L204-240 —— collect_inputs default 扁平合并语义（Pitfall 1 决定性证据）
- `server/workflows/engine/template_resolver.py` L25-237 —— `_TEMPLATE_VAR_RE`/reason 枚举/`_resolve_nodes_path`/严格语义
- `server/workflows/nodes/base.py` L48-60, L519-642 —— `NodePort.schema`/`validate_config`/`get_schema`
- `server/workflows/nodes/registry.py` —— NodeRegistry API（注意无 `list_types`，Pitfall 7）
- `server/workflows/nodes/control/condition.py` L84-103 —— `get_dynamic_outputs`
- `server/workflows/nodes/integrations/http.py` L83-138 —— http 输出 `{status_code,headers,body,ok}`、无 schema
- `server/workflows/nodes/ai/prompt.py` L262-325, L385-401 —— ai_prompt 输出字段 + schema（`text`/`response`/`output`...）
- `server/workflows/nodes/ai/code_review.py` L215-266, L307-328, L538-554 —— ai_code_review 输入端口 coding_result/plan、输出 review_report 等、merge_requests 依赖
- `server/workflows/nodes/ai/coding.py` L169-181, L1320-1357 —— ai_coding 输出 coding_result/merge_requests/plan
- `server/workflows/nodes/ai/plan_approval.py` L42-86 —— approved/rejected 输出端口
- `server/workflows/api/views.py` L162-316, L460-682 —— 写入路径全景（bulk-update/CRUD/import/from-template）
- `server/workflows/api/serializers.py` L184-265, L454-477 —— serializer 半校验现状 + `list_types` 误用
- `server/workflows/templates/loader.py` L63-283 —— rewrite_template_refs / acreate_workflow_from_template
- `server/workflows/templates/{daily_summary,code_review_pipeline,code_generation,feishu_full_pipeline}.json` —— 模板断裂证据
- `server/workflows/urls.py` —— DRF 路由（dry-run action 注册依据）
- `web/src/stores/useWorkflowValidationStore.ts` / `components/workflow/validation/IssuesPanel.vue` / `stores/useWorkflowsStore.ts` L373-404 —— 前端死代码 + saveWorkflow
- `server/tests/workflows/test_template_loader.py` —— 既有测试基线（TPL-02 扩展基础）
- `.planning/phases/18-engine/18-01-SUMMARY.md` / `19-ssot/19-01-SUMMARY.md` —— routing/SSOT 依赖契约

### Secondary / Tertiary
- 无外部 web 来源（纯仓库内研究）；无 LOW-confidence 待验证项。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH —— 全部既有依赖/资产，逐行核对，零版本不确定
- Architecture（validator 设计/接入点）: HIGH —— 写入路径与复用资产已精确定位到行号
- Pitfalls: HIGH —— Pitfall 1/2/3/4 均有源码级决定性证据（collect_inputs、NodePort.schema、节点输出契约）
- code_review_pipeline 终态语义: MEDIUM —— 技术约束已查清，但"业务预期"的产品定义需 planner/用户确认（OQ#1）

**Research date:** 2026-06-13
**Valid until:** 2026-07-13（稳定领域，30 天；除非节点输出契约或 routing 语义变更）
