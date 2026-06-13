# Phase 20: 保存即合法与模板修复 - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 15（新建 4 / 修改 11）
**Analogs found:** 15 / 15（全部有强 analog——本阶段为"收敛与接线"，几乎不引入新范式）

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `server/workflows/validation/graph_validator.py` 🆕 | service（纯函数校验核心） | transform（dict→结构化结果） | `server/workflows/engine/template_resolver.py` | exact（同"零 ORM plain-dict"范式 + reason 枚举 + dataclass error） |
| `server/workflows/validation/__init__.py` 🆕 | config（包导出） | — | `server/workflows/engine/__init__.py`（barrel re-export） | role-match |
| `server/workflows/engine/dag.py` ✏️ | utility（内存构图） | transform | `DAG.from_workflow`（dag.py L54-80） | exact（照搬 incoming/outgoing/incoming_edges 构图） |
| `server/workflows/api/views.py` ✏️ | controller（DRF action + 写入接入） | request-response | 既有 `@action` `from_template`/`import_workflow`/`bulk_update`（views.py L460-682） | exact |
| `server/workflows/api/serializers.py` ✏️ | serializer（config schema 校验闭合） | request-response | `WorkflowNodeSerializer.validate`（serializers.py L226-238） | exact（同一 `validate_config` 调用，复制到 Create 路径） |
| `server/workflows/templates/loader.py` ✏️ | service（模板实例化） | batch | `acreate_workflow_from_template`（loader.py L198-283，建库前插入校验） | exact |
| `server/workflows/templates/daily_summary.json` ✏️ | config（模板 JSON） | — | 自身字段重命名（对照 prompt.py 输出 schema L268-281、http.py 输出） | exact |
| `server/workflows/templates/code_review_pipeline.json` ✏️ | config（模板 JSON） | — | `code_generation.json`（健康范式）+ code_review.py 输入契约 L215-326 | role-match（结构性重构，非字段重命名） |
| `server/tests/workflows/test_graph_validator.py` 🆕 | test（单元，零 DB） | — | `test_dag.py::TestDAGValidation`（L377-410） | exact |
| `server/tests/workflows/test_template_loader.py` ✏️ | test（集成 + 参数化） | — | 自身既有 `TestListTemplates`/`TestLoadTemplate`（L23-60，参数化模板遍历） | exact |
| `server/tests/workflows/test_api.py` ✏️ | test（集成，django_db） | request-response | 自身既有 bulk-update / node create 用例 | role-match |
| `web/src/stores/useWorkflowValidationStore.ts` ✏️ | store（Pinia） | event-driven | 自身现状（扩展 `ValidationWarning`→多 severity/reason） | exact |
| `web/src/stores/useWorkflowsStore.ts` ✏️ | store（saveWorkflow 接 dry-run） | request-response | `saveWorkflow`（useWorkflowsStore.ts L373-404） | exact |
| `web/src/components/workflow/validation/IssuesPanel.vue` ✏️ | component（展示） | — | 自身现状（`v-if=hasWarnings` 接通真实数据） | exact |
| `web/src/stores/__tests__/useWorkflowValidationStore.test.ts` 🆕 | test（vitest） | — | 既有前端 store 测试栈（vitest + setActivePinia） | role-match |

---

## Pattern Assignments

### `server/workflows/validation/graph_validator.py` 🆕 (service, transform)

**Analog:** `server/workflows/engine/template_resolver.py`（Phase 17 纯函数零 DB 范式 + reason 枚举）

**Imports / 模块头范式**（template_resolver.py L25-41）——纯函数模块，**不 import Django ORM**，仅 `re` + `dataclass` + 复用既有正则/校验源：

```1:41:server/workflows/engine/template_resolver.py
"""模板变量解析核心（Phase 17 实现契约）。

本模块是 `render_template` / `get_template_value` 两个 API 共享的纯函数解析核心：
不 import Django ORM、不依赖 ExecutionContext，输入全部为 plain dict，
pytest 零 DB 可测。
...
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# 合法前缀列表（unknown_prefix 错误的 available 候选）
VALID_PREFIXES = ["input", "context", "config", "nodes", "global", "trigger", "$"]
...
# {{...}} 变量占位符
_TEMPLATE_VAR_RE = re.compile(r"\{\{(.+?)\}\}")
# [n] / [-n] 数组索引后缀（get_template_value 现状保留）
_INDEX_SUFFIX_RE = re.compile(r"(.+?)\[(-?\d+)\]$")
```

> **复用而非重写**：`graph_validator.py` 直接 `from workflows.engine.template_resolver import _TEMPLATE_VAR_RE, _INDEX_SUFFIX_RE, VALID_PREFIXES`，扫描 config 字符串字段。**不要自写 `{{}}` 正则**（Don't Hand-Roll）。

**结构化错误 dataclass + reason 枚举**（参照 `TemplateResolutionError` L43-70）——`ValidationIssue` 复用同款 reason 命名（`node_not_found`/`field_not_found`/`missing_field_path`），并扩展图级 reason：

```43:71:server/workflows/engine/template_resolver.py
class TemplateResolutionError(ValueError):
    """模板解析失败。
    ...
        reason: 失败原因分类，取值
            node_not_found | field_not_found | unknown_prefix | missing_field_path
        available: 可用候选（节点 ID 列表 / 字段 keys / 合法前缀），
            只含键名，绝不包含上游输出值（T-17-01 缓解）
    """
    def __init__(self, *, template, reference, reason, available, message):
        super().__init__(message)
        self.template = template
        self.reference = reference
        self.reason = reason
        self.available = available
```

> **安全约束（T-17-01 延续，V7 错误处理）**：`ValidationIssue` 只放 `node_id/edge_id/field_path/reason/message`，**绝不含 config 值或上游输出值**。`message` 里的 available 只列键名（见 L157「available 只列该节点输出的顶层字段 keys（绝不含输出值）」）。

**nodes.* 严格语义参照**（`_resolve_nodes_path` L113-189）——静态校验照此分支但只判存在性，不取值；`node_id not in nodes_data → node_not_found`，字段层断路 `→ field_not_found`：

```130:158:server/workflows/engine/template_resolver.py
    node_id = parts[1]
    field_parts = parts[2:]
    nodes_data = sources.previous_outputs or {}

    if node_id not in nodes_data:
        available = _node_id_candidates(nodes_data)
        ...
        raise TemplateResolutionError(
            ..., reason="node_not_found", available=available, message=message,
        )

    output = nodes_data[node_id]
    field_path = ".".join(field_parts)
    top_level_keys = list(output.keys()) if isinstance(output, dict) else []
```

> **关键差异（D-03 / Pitfall 2）**：运行态 resolver 用真实 `previous_outputs` 值下钻；静态校验**没有值**，只有 `NodePort.schema`。因此字段层校验改为「**仅当上游输出端口 `schema` 非空时**，校验首段字段 ∈ `schema["properties"]`；schema 为 `None` 则只校验节点存在性、字段层跳过」。建议口径：取该上游节点**所有输出端口 schema 的 properties 并集**（A2，宽松少误报）。剥 `[n]` 后缀用 `_INDEX_SUFFIX_RE`。仅处理 `nodes.` 前缀，`input./trigger./global./context./config./$` 跳过。

**建议入口签名**（RESEARCH Pattern 1）——`validate(nodes, edges) -> {"errors":[...], "warnings":[...]}`，每条 `asdict(ValidationIssue)`。

---

### `server/workflows/engine/dag.py` ✏️ (utility, transform)

**Analog:** `DAG.from_workflow`（dag.py L54-80）——新增 `DAG.from_node_edge_dicts(nodes, edges)`，**逐字符照搬** incoming/outgoing/incoming_edges/`_detect_back_edges` 逻辑，仅把 `DAGNode.node` 换成 duck-typed `SimpleNamespace`（`DAG.validate` 只读 `.id/.node_type/.name`，见下）：

```54:80:server/workflows/engine/dag.py
    @classmethod
    def from_workflow(cls, workflow: "Workflow") -> "DAG":
        """从工作流模型构建 DAG"""
        dag = cls()
        for node in workflow.nodes.all():
            dag.nodes[str(node.id)] = DAGNode(node=node)
        for edge in workflow.edges.all():
            source_id = str(edge.source_node_id)
            target_id = str(edge.target_node_id)
            handle = edge.source_handle
            if source_id in dag.nodes and target_id in dag.nodes:
                dag.nodes[target_id].incoming.add(source_id)
                dag.nodes[target_id].incoming_edges.append(
                    (source_id, edge.source_handle or "default", edge.target_handle or "default")
                )
                if handle not in dag.nodes[source_id].outgoing:
                    dag.nodes[source_id].outgoing[handle] = set()
                dag.nodes[source_id].outgoing[handle].add(target_id)
                dag.edges.append(edge)
        dag._detect_back_edges()
        return dag
```

**`DAGNode.node` 只需三属性**（用 `SimpleNamespace` 承载，RESEARCH Pattern 2）：

```python
from types import SimpleNamespace
node_obj = SimpleNamespace(id=nid, node_type=nd["node_type"], name=nd.get("name", nid))
```

**复用 `validate()` 而非重写**（dag.py L138-160）——把返回的中文字符串映射成 `ValidationIssue(reason="cycle"/"no_entry"/"orphan_node")`。**注意孤立豁免只含 `manual_trigger`/`webhook_trigger`，不含 `feishu_event_trigger`（Pitfall 8）**——孤立建议降为 warning severity：

```138:160:server/workflows/engine/dag.py
    def validate(self) -> list[str]:
        """验证 DAG 是否有效"""
        errors = []
        if self.has_cycle():
            errors.append("工作流存在循环依赖")
        entry_nodes = self.get_entry_nodes()
        if not entry_nodes:
            errors.append("工作流没有入口节点（触发器）")
        for node_id, dag_node in self.nodes.items():
            if dag_node.in_degree == 0 and not dag_node.outgoing:
                if dag_node.node.node_type not in ("manual_trigger", "webhook_trigger"):
                    errors.append(f"节点 '{dag_node.node.name}' 是孤立的")
        return errors
```

> **Anti-pattern（强制）**：**不要**自写 DFS 环检测。`has_cycle`（L162-193）含「非 default handle 回退边不算环」精细语义（审批驳回回环），重写必丢失。`from_node_edge_dicts` 必须调 `_detect_back_edges()` 保留该语义。

---

### `server/workflows/api/serializers.py` ✏️ (serializer, request-response)

**Analog:** `WorkflowNodeSerializer.validate`（serializers.py L226-238）——把同一 `validate_config` 调用复制到 `WorkflowNodeCreateSerializer`（现仅校 node_type，L262-265），闭合 VAL-02 config 缺口：

```226:238:server/workflows/api/serializers.py
    def validate(self, attrs: dict) -> dict:
        """Validate node configuration against schema."""
        node_type = attrs.get("node_type") or (self.instance.node_type if self.instance else None)
        config = attrs.get("config", {})

        if node_type:
            node_class = NodeRegistry.get(node_type)
            if node_class:
                errors = node_class.validate_config(config)
                if errors:
                    raise serializers.ValidationError({"config": errors})

        return attrs
```

**当前缺口**（serializers.py L241-265，Create 路径只校 node_type）：

```241:265:server/workflows/api/serializers.py
class WorkflowNodeCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating WorkflowNode."""
    class Meta:
        model = WorkflowNode
        fields = [ "node_type", "name", ... "config", ... ]

    def validate_node_type(self, value: str) -> str:
        if not NodeRegistry.get(value):
            raise serializers.ValidationError(f"Unknown node type: {value}")
        return value
```

> **Pitfall 7（顺手修）**：`serializers.py` L213、L467 调用了**不存在**的 `NodeRegistry.list_types()`（registry 只有 `get`/`get_all`/`get_by_category`/`get_all_schemas`/`get_ui_schema`，见 registry.py L92-113）。补 `list_types()` 或改用 `list(NodeRegistry.get_all().keys())`。validator 列举类型也用后者。

**config schema 校验直接复用**（base.py L567-575，jsonschema，**不要手写字段必填检查**）：

```567:575:server/workflows/nodes/base.py
    @classmethod
    def validate_config(cls, config: dict) -> list[str]:
        """验证节点配置"""
        errors = []
        try:
            jsonschema.validate(config, cls.config_schema)
        except jsonschema.ValidationError as e:
            errors.append(str(e.message))
        return errors
```

---

### `server/workflows/api/views.py` ✏️ (controller, request-response)

**Analog A — dry-run `@action`（detail=True/False 双形态，D-04 / Pattern 5）:** 照搬 `import_workflow`（detail=False，L460）与 `from_template`（detail=False，L645）的 `@action(detail=..., methods=["post"], url_path=...)` 范式。dry-run 直接调 validator、**不写库**、返回 200 + `{errors, warnings}`：

```460:464:server/workflows/api/views.py
    @action(detail=False, methods=["post"], url_path="import")
    async def import_workflow(self, request: Request) -> Response:
        """Import workflow from JSON."""
        serializer = WorkflowImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
```

> 路由不冲突：detail=False 的 `workflows/validate/` 注册在 `{pk}` detail-route 前，不会被吞（urls.py `DefaultRouter`）。

**Analog B — bulk-update 接入（Pattern 4 / Pitfall 6）:** validator 必须在 `_bulk_update_nodes_and_edges` 内、`_resolve_short_ids` + 引用重写**之后**、commit 之前调用，用最终 short_id 空间；error 即 `raise ValidationError(...)` → `transaction.atomic()` 自动回滚 → DRF 400。**变量校验用 short_id，edge 归属/handle 校验用 UUID**——节点 dict 须同时带 `id` 与 `short_id`：

```251:316:server/workflows/api/views.py
    with transaction.atomic():
        final_short_ids, rewrite_candidates = _resolve_short_ids(workflow, nodes_data)
        ...
        # 引用重写：仅当客户端值在最终分配后不再属于该工作流任何节点时才纳入 id_map
        if rewrite_candidates:
            final_owned = set(workflow.nodes.values_list("short_id", flat=True))
            id_map = {old: new for old, new in rewrite_candidates.items() if old not in final_owned}
            if id_map:
                for node in workflow.nodes.all():
                    rewritten = rewrite_template_refs(node.config, id_map)
                    ...
        if edges_data:
            workflow.edges.all().delete()
            for edge_data in edges_data:
                serializer = WorkflowEdgeCreateSerializer(data=edge_data)
                serializer.is_valid(raise_exception=True)
                ...
```

**async/sync 边界**：validator 纯 CPU 无 DB；bulk-update 已整体走 `sync_to_async(_bulk_update_nodes_and_edges)`（views.py L620），在其同步函数体内**同步调用** validator 最自然。

**handle 合法性校验（Pitfall 1 强制——`"default"` 恒合法白名单）:** 边节点归属 + handle 校验事实源 `NodeRegistry` + 动态输出。`target_handle="default"`（及空串）**恒合法**（靠 `collect_inputs` 扁平合并），只对非 default 校验 ∈ inputs；source 同理；condition 用 `get_dynamic_outputs`（见下分配）。

---

### `server/workflows/templates/loader.py` ✏️ (service, batch)

**Analog:** `acreate_workflow_from_template`（loader.py L198-283）——在 `load_template(template_id)` 之后、`Workflow.objects.acreate` **之前**插入 validator（D-09 / TPL-03）。校验输入用模板 `nodes`（`type`→`node_type`、`config`）+ `edges`（`source`/`target`），id 空间用模板 ID（与 `rewrite_template_refs(template_to_short)` 同源，loader.py L84/L246-252）。非法 `raise ValueError(...)`，view 层 `from_template` 已捕获 `ValueError → 400`（views.py L675-676）：

```211:224:server/workflows/templates/loader.py
    template = load_template(template_id)

    # Create workflow
    workflow = await Workflow.objects.acreate(
        name=name or template.get("name", template_id),
        ...
    )
```

> **接入位置**：在 `template = load_template(...)` 与 `acreate` 之间。建库前拒绝 → 不产生半残 workflow。

---

### `server/workflows/templates/daily_summary.json` ✏️ (config) — 低风险字段重命名（TPL-01）

**断裂证据 + 修复**（对照 http.py 输出 `{status_code,headers,body,ok}` 无 schema、prompt.py 输出 schema L268-281 含 `text`/`response`/`output`）：

```text
L37  "数据：\n{{nodes.fetch_data.output}}"  →  "{{nodes.fetch_data.body}}"   # http 实际输出 body（无 schema → validator 字段层跳过）
L50  "content": "{{nodes.summarize.output}}" →  "{{nodes.summarize.text}}"   # ai_prompt 主文本字段（text 在输出 schema 内）
```

当前文件相关行：

```37:50:server/workflows/templates/daily_summary.json
        "user_prompt": "...数据：\n{{nodes.fetch_data.output}}"
        ...
        "content": "{{nodes.summarize.output}}",
```

> **Pitfall 3 警告**：`summarize` 是 ai_prompt，`output` **确实在其 schema**（prompt.py L281），validator 不会报错——但运行时拼出数组字符串而非日报文本。**TPL-01 修复的正确性靠人工核对 + 可选执行级断言**，不能仅靠 validator。`body`（http 无 schema）与 `text`（schema 内）修复后 validator 均零 error 且运行语义正确。

---

### `server/workflows/templates/code_review_pipeline.json` ✏️ (config) — 结构性契约重构（TPL-01，最大不确定点）

**Analog:** `code_generation.json`（健康范式：`ai_coding → code_review`）+ `ai_code_review` 输入契约（code_review.py L215-326）。**这不是字段重命名**（Pitfall 4）：当前 `http_request` 永远产不出 `coding_result.merge_requests`：

```215:230:server/workflows/nodes/ai/code_review.py
            name="coding_result",
            ...
            name="plan",
```

```310:326:server/workflows/nodes/ai/code_review.py
        # coding_result 端口（AICodingNode 包装输出）或扁平的 merge_requests（直连兼容）
        coding_result = context.get_input("coding_result")
        if not coding_result or not isinstance(coding_result, dict):
            if context.input_data and isinstance(context.input_data.get("merge_requests"), list):
                coding_result = context.input_data
            else:
                ... error="缺少编码结果数据（coding_result 输入端口为空）"
        merge_requests = coding_result.get("merge_requests", [])
        if not merge_requests:
            ... error="编码结果中无 merge_requests 数据"
```

**推荐方案 A（最小契约正确，RESEARCH Pitfall 4 / OQ#1）：** 去掉 http 节点，让触发器 payload 携带 `merge_requests: [{mr_id, repository_id, ...}]`，边 `trigger → review` 用 `target_handle="coding_result"`（或 default 靠扁平合并 + L313 兜底分支）；notify 改引真实输出字段 `review_report`（code_review.py L241/L539，**当前 `{{nodes.review.output}}` 不在输出 schema → validator 能抓 field_not_found**）：

```49:49:server/workflows/templates/code_review_pipeline.json
        "content": "PR 审查完成：{{nodes.review.output}}",
```

```56:60:server/workflows/templates/code_review_pipeline.json
  "edges": [
    {"source": "trigger", "target": "fetch_pr"},
    {"source": "fetch_pr", "target": "review"},
    {"source": "review", "target": "notify"}
  ]
```

> **⚠️ planner 必须先定终态语义再排 task**（OQ#1）：「零改配置执行到业务预期」是否接受「模板要求 webhook 提供正确 payload + 预注册仓库 UUID + 凭证」作为文档化前提。`repository_id` 必须是 Friday 已注册仓库 UUID——非 config 默认值能填。建议在模板 `description` 文档化前提。

---

### 测试文件

**`server/tests/workflows/test_graph_validator.py` 🆕 (test, 零 DB unit)** — Analog: `test_dag.py::TestDAGValidation`（L377-410）。validator 纯函数 → **无需 `db` fixture**，直接传 plain dict 断言 errors/warnings。必须覆盖 Pitfall 1/2 的「不误伤」用例：

```380:393:server/tests/workflows/test_dag.py
    def test_validate_valid_workflow(self, linear_workflow):
        dag = DAG.from_workflow(linear_workflow)
        errors = dag.validate()
        assert len(errors) == 0

    def test_validate_cyclic_workflow(self, cyclic_workflow):
        dag = DAG.from_workflow(cyclic_workflow)
        errors = dag.validate()
        assert len(errors) > 0
        assert any("循环" in error for error in errors)
```

> 必测「不误伤」：`target_handle="default"` 边放行、无 schema 输出端口字段层跳过（`fetch_data.body` 零 error）、condition 动态 `branch_N`/`else` handle 放行。

**`server/tests/workflows/test_template_loader.py` ✏️ (test)** — Analog: 自身参数化遍历（L26-49）。新增「每内置模板经 validator 零 error」+「注入断裂 → 失败」。**Pitfall 3：注入用例必须 schema-可判定**（`{{nodes.summarize.nonexistent_field}}` → field_not_found / `{{nodes.ghost.x}}` → node_not_found / 坏 node_type / 坏 handle），**不可用 http 节点字段**（无 schema 跳过 → 假绿）：

```26:38:server/tests/workflows/test_template_loader.py
    def test_list_templates_returns_4(self):
        templates = list_templates()
        assert len(templates) == 4
        ids = {t["template_id"] for t in templates}
        expected = {"code_generation", "feishu_full_pipeline", "code_review_pipeline", "daily_summary"}
        assert ids == expected
```

**`server/tests/workflows/test_api.py` ✏️ (test, django_db)** — bulk-update 非法 config/坏 handle → 400 结构化 errors；单节点 create 补 config 校验；**合法保存零变化（不误拒）回归**。

---

### 前端

**`web/src/stores/useWorkflowValidationStore.ts` ✏️ (store)** — 扩展现有 `ValidationWarning`（当前唯一 `type: 'schema_mismatch'`，L8-21）为多 severity/reason。保留 `addWarning/clearAllWarnings/warningsList/hasWarnings/getWarningForEdge` API 形态，新增 `severity`（`'error'|'warning'`）与 reason 字段，并支持 node 级（非仅 edge 级）问题：

```8:21:web/src/stores/useWorkflowValidationStore.ts
export interface ValidationWarning {
  id: string
  edgeId: string
  type: 'schema_mismatch'
  message: string
  sourceNodeId: string
  targetNodeId: string
}
```

> reason 字段与后端 `ValidationIssue.reason` 枚举对齐（`node_not_found`/`field_not_found`/`cycle`/`config_schema_invalid`/`invalid_source_handle`/...，D-06）。建议新增 `addIssues(backendIssues)` action 批量摄入后端 `{errors, warnings}`。

**`web/src/stores/useWorkflowsStore.ts` ✏️ (store, request-response)** — Analog: `saveWorkflow`（L373-404）。保存前 dry-run（或解析 bulk-update 400 body）写入 validation store。**400 catch 分支**解析 `e.body.errors` 灌入 store（ApiError 带 `body`，见 `web/src/api/client.ts`）：

```380:399:web/src/stores/useWorkflowsStore.ts
      const workflow = await client.put<Workflow>(`/workflows/${currentWorkflow.value.id}/bulk-update/`, {
        nodes: toBackendNodes(nodes.value),
        edges: toBackendEdges(edges.value),
        delete_orphans: true,
      })
      currentWorkflow.value = workflow
      ...
    catch (e: unknown) {
      error.value = (e as Error).message
      throw e
    }
```

**`web/src/components/workflow/validation/IssuesPanel.vue` ✏️ (component)** — 已是完整 UI（`v-if="hasWarnings"`、`v-for="warning in warningsList"`），**只需后端数据接通即真实渲染**。`handleWarningClick` 留 TODO（已是，L24-28，D-06 非阻断）。需按 severity 区分 error/warning 视觉（当前全 amber）：

```34:49:web/src/components/workflow/validation/IssuesPanel.vue
  <Collapsible
    v-if="hasWarnings"
    ...
          <span class="text-sm font-medium">问题</span>
          <Badge variant="warning">
            {{ warningCount }}
          </Badge>
```

---

## Shared Patterns

### 校验事实源单例查询（所有 handle/config/类型校验）
**Source:** `server/workflows/nodes/registry.py` L92-113（`get`/`get_all`/`get_all_schemas`）
**Apply to:** `graph_validator.py` 全部规则、serializers config 校验
```92:113:server/workflows/nodes/registry.py
    @classmethod
    def get(cls, node_type: str) -> Type[BaseNode] | None:
        cls._ensure_initialized()
        return cls._nodes.get(node_type)
    @classmethod
    def get_all(cls) -> dict[str, Type[BaseNode]]:
        cls._ensure_initialized()
        return cls._nodes.copy()
```
> **注意**：无 `list_types()`（Pitfall 7）。列举类型用 `list(NodeRegistry.get_all().keys())`。

### 动态输出 handle（condition）
**Source:** `server/workflows/nodes/control/condition.py` L84-103（`get_dynamic_outputs`）
**Apply to:** `graph_validator.py` source_handle 校验（**不要硬编码分支名**）
```84:103:server/workflows/nodes/control/condition.py
    @classmethod
    def get_dynamic_outputs(cls, config: dict) -> list[NodePort]:
        """根据配置动态生成输出端口"""
        outputs = []
        for i, condition in enumerate(config.get("conditions", [])):
            outputs.append(NodePort(name=f"branch_{i}", ...))
        outputs.append(NodePort(name=config.get("default_branch", "else"), ...))
        return outputs
```
> 校验时 `out_names = {p.name for p in src_cls.outputs}`；若 `hasattr(src_cls, "get_dynamic_outputs")` 则并入 `get_dynamic_outputs(config)` 的 names。

### NodePort.schema 字段层校验依据
**Source:** `server/workflows/nodes/base.py` L48-60（`NodePort.schema: dict | None`）
**Apply to:** `graph_validator.py` 变量字段层校验
```48:60:server/workflows/nodes/base.py
@dataclass
class NodePort:
    name: str
    label: str
    port_type: PortType = PortType.ANY
    required: bool = True
    default: Any = None
    description: str = ""
    schema: dict | None = None
```
> `schema is None` → 字段层跳过（Pitfall 2）；非空 → 校验首段字段 ∈ `schema["properties"]`。

### handle 校验防误伤（default 恒合法 + 动态输出）
**Source:** RESEARCH Code Examples（基于 routing.py L227-238 扁平合并语义）
**Apply to:** `graph_validator.py._validate_handles`
```python
sh = edge.get("source_handle") or "default"
th = edge.get("target_handle") or "default"
# source_handle / target_handle == "default" → 恒合法，跳过
if sh != "default":  # 校验 ∈ outputs (+ 动态)
if th != "default":  # 校验 ∈ inputs
```

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| （无） | — | — | 本阶段所有文件均有强 analog；无需回退 RESEARCH 通用范式 |

> 唯一「半新」逻辑：变量「schema 模式」静态校验（Pattern 3）——它**复用** `template_resolver` 的正则与 reason 枚举，但下钻逻辑（只判存在性、无值、schema 非空才校验字段）是新写。这是本阶段唯一无法直接复制的代码段，其余全为既有范式组合。

---

## Metadata

**Analog search scope:** `server/workflows/{validation,engine,api,nodes,templates}/`、`server/tests/workflows/`、`web/src/{stores,components/workflow/validation}/`
**Files scanned:** 16（template_resolver、dag、base、condition、registry、views、serializers、loader、daily_summary.json、code_review_pipeline.json、prompt.py、code_review.py、useWorkflowValidationStore、IssuesPanel、useWorkflowsStore、test_dag、test_template_loader）
**Pattern extraction date:** 2026-06-13
