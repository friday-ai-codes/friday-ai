"""工作流图静态校验核心（Phase 20 实现契约）。

本模块是"保存即合法"的唯一校验事实源（D-01）：纯函数式、不 import Django ORM、
输入全部为 plain dict（节点集 + 边集），pytest 零 DB 可测。被 bulk-update、
单节点/边 CRUD、import、template loader、dry-run 接口共用。

五类规则（按序执行，收集到 errors/warnings）：
1. node_type 存在性（NodeRegistry.get）；
2. config jsonschema（复用 BaseNode.validate_config）；
3. DAG 结构（环/入口/孤立，复用 DAG.from_node_edge_dicts + validate，保留回退边语义）；
4. edge 节点归属 + handle 合法性（default/空串恒合法白名单，Pitfall 1；condition
   动态输出经 get_dynamic_outputs 并入）；
5. nodes.* 变量静态可解析性（复用 template_resolver 正则与 reason 枚举；上游输出端口
   无 schema 时只校验节点存在性、字段层跳过，Pitfall 2 / D-03）。

安全约束（T-20-01，延续 T-17-01）：ValidationIssue 的 message/available 只含
node_id / edge_id / field_path / reason 与键名候选，**绝不回显 config 取值或上游输出值**。
"""

from dataclasses import asdict, dataclass
from typing import Any

from workflows.engine.dag import DAG
from workflows.engine.template_resolver import _INDEX_SUFFIX_RE, _TEMPLATE_VAR_RE
from workflows.nodes.registry import NodeRegistry


@dataclass
class ValidationIssue:
    """单条结构化校验问题。

    Attributes:
        reason: 失败原因分类（复用并扩展 TemplateResolutionError 枚举风格）：
            unknown_node_type | config_schema_invalid | cycle | no_entry |
            orphan_node | edge_node_missing | invalid_source_handle |
            invalid_target_handle | node_not_found | field_not_found
        severity: "error"（阻断保存）| "warning"（仅提示，不阻断）
        field_path: 问题定位（如 "config.user_prompt" / "edges[2].source_handle"）
        node_id: 涉及的节点 ID（UUID 形态）
        edge_id: 涉及的边 ID
        message: 人类可读描述，只含拓扑/键名/reason，绝不含 config 取值或上游输出值
    """

    reason: str
    severity: str
    field_path: str = ""
    node_id: str | None = None
    edge_id: str | None = None
    message: str = ""


class WorkflowGraphValidator:
    """工作流图静态校验器（纯函数核心，零 ORM / 零 DB）。"""

    def validate(self, nodes: list[dict], edges: list[dict]) -> dict:
        """对节点集 + 边集做五类静态校验，返回结构化结果。

        Args:
            nodes: 节点 dict 列表，每项至少含 ``id`` / ``node_type``，可选
                ``short_id`` / ``name`` / ``config``。
            edges: 边 dict 列表，每项含 ``source_node_id`` / ``target_node_id``，
                可选 ``id`` / ``source_handle`` / ``target_handle``。

        Returns:
            ``{"errors": [asdict(issue), ...], "warnings": [...]}``。
        """
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []

        # (a) node_type 存在性 + (b) config jsonschema
        for nd in nodes:
            node_type = nd.get("node_type")
            node_class = NodeRegistry.get(node_type) if node_type else None
            if node_class is None:
                errors.append(
                    ValidationIssue(
                        reason="unknown_node_type",
                        severity="error",
                        node_id=nd.get("id"),
                        field_path="node_type",
                        message=f"未知节点类型 '{node_type}'",
                    )
                )
                continue
            for msg in node_class.validate_config(nd.get("config", {})):
                errors.append(
                    ValidationIssue(
                        reason="config_schema_invalid",
                        severity="error",
                        node_id=nd.get("id"),
                        field_path="config",
                        message=msg,
                    )
                )

        # (c) DAG 结构：复用 DAG.validate()，映射中文字符串到 reason
        self._validate_dag_structure(nodes, edges, errors, warnings)

        # (d) edge 节点归属 + handle 合法性
        self._validate_edges(nodes, edges, errors)

        # (e) nodes.* 变量静态校验
        self._validate_variables(nodes, errors)

        return {
            "errors": [asdict(i) for i in errors],
            "warnings": [asdict(i) for i in warnings],
        }

    def _validate_dag_structure(
        self,
        nodes: list[dict],
        edges: list[dict],
        errors: list[ValidationIssue],
        warnings: list[ValidationIssue],
    ) -> None:
        """DAG 环/入口/孤立校验。复用 DAG.validate()，孤立降为 warning（Pitfall 8）。"""
        dag = DAG.from_node_edge_dicts(nodes, edges)
        for msg in dag.validate():
            if "循环依赖" in msg:
                errors.append(ValidationIssue(reason="cycle", severity="error", message=msg))
            elif "入口" in msg:
                errors.append(ValidationIssue(reason="no_entry", severity="error", message=msg))
            elif "孤立" in msg:
                # 孤立节点降为 warning，避免编辑中途草图误报（D-05 warnings 不阻断）
                warnings.append(
                    ValidationIssue(reason="orphan_node", severity="warning", message=msg)
                )

    def _validate_edges(
        self,
        nodes: list[dict],
        edges: list[dict],
        errors: list[ValidationIssue],
    ) -> None:
        """edge 节点归属（UUID 空间）+ handle 合法性。default/空串恒合法（Pitfall 1）。"""
        node_by_id = {str(nd["id"]): nd for nd in nodes if nd.get("id") is not None}

        for idx, edge in enumerate(edges):
            src = node_by_id.get(str(edge.get("source_node_id")))
            tgt = node_by_id.get(str(edge.get("target_node_id")))
            if src is None or tgt is None:
                errors.append(
                    ValidationIssue(
                        reason="edge_node_missing",
                        severity="error",
                        edge_id=edge.get("id"),
                        field_path=f"edges[{idx}]",
                        message="边的源节点或目标节点不在节点集中",
                    )
                )
                continue

            sh = edge.get("source_handle") or "default"
            th = edge.get("target_handle") or "default"

            # source_handle：default（及空串）恒合法；非 default 校验 ∈ outputs（+ 动态）
            src_class = NodeRegistry.get(src["node_type"])
            if sh != "default" and src_class is not None:
                out_names = {p.name for p in src_class.outputs}
                if hasattr(src_class, "get_dynamic_outputs"):
                    out_names |= {
                        p.name for p in src_class.get_dynamic_outputs(src.get("config", {}))
                    }
                if sh not in out_names:
                    errors.append(
                        ValidationIssue(
                            reason="invalid_source_handle",
                            severity="error",
                            edge_id=edge.get("id"),
                            field_path=f"edges[{idx}].source_handle",
                            message=(
                                f"source_handle '{sh}' 不在 {src['node_type']} "
                                f"输出端口 {sorted(out_names)} 中"
                            ),
                        )
                    )

            # target_handle：default（扁平合并路径）恒合法；非 default 校验 ∈ inputs
            tgt_class = NodeRegistry.get(tgt["node_type"])
            if th != "default" and tgt_class is not None:
                in_names = {p.name for p in tgt_class.inputs}
                if th not in in_names:
                    errors.append(
                        ValidationIssue(
                            reason="invalid_target_handle",
                            severity="error",
                            edge_id=edge.get("id"),
                            field_path=f"edges[{idx}].target_handle",
                            message=(
                                f"target_handle '{th}' 不在 {tgt['node_type']} "
                                f"输入端口 {sorted(in_names)} 中"
                            ),
                        )
                    )

    def _validate_variables(
        self,
        nodes: list[dict],
        errors: list[ValidationIssue],
    ) -> None:
        """nodes.* 变量静态校验（short_id 空间）。

        D-03 / Pitfall 2：仅处理 ``nodes.`` 前缀（input/trigger/global/context/config/$
        跳过）；short_id 不存在 → node_not_found；上游输出端口 schema 全为 None 时只校验
        节点存在性、字段层跳过；首段字段不在所有输出端口 schema properties 并集 → field_not_found。
        """
        short_by_id = {str(nd["short_id"]): nd for nd in nodes if nd.get("short_id")}

        for nd in nodes:
            config = nd.get("config", {})
            for field_path, text in self._iter_config_strings(config, "config"):
                for raw_ref in _TEMPLATE_VAR_RE.findall(text):
                    ref = raw_ref.strip()
                    parts = ref.split(".")
                    # 仅 nodes.* 严格；其余前缀（input/trigger/global/context/config/$）跳过
                    if parts[0] != "nodes":
                        continue
                    if len(parts) < 3:
                        # 缺字段路径（仅两段），本阶段维持宽松不报
                        continue

                    short_id = parts[1]
                    target_nd = short_by_id.get(short_id)
                    if target_nd is None:
                        errors.append(
                            ValidationIssue(
                                reason="node_not_found",
                                severity="error",
                                node_id=nd.get("id"),
                                field_path=field_path,
                                message=f"变量引用的节点 '{short_id}' 不存在",
                            )
                        )
                        continue

                    self._validate_variable_field(
                        target_nd, short_id, parts[2], nd, field_path, errors
                    )

    def _validate_variable_field(
        self,
        target_nd: dict,
        short_id: str,
        first_segment: str,
        referencing_node: dict,
        field_path: str,
        errors: list[ValidationIssue],
    ) -> None:
        """字段层校验：上游输出端口 schema properties 并集（A2）。无 schema 跳过。"""
        target_class = NodeRegistry.get(target_nd.get("node_type"))
        if target_class is None:
            return

        # 取所有输出端口 NodePort.schema 非空者的 properties 并集
        props: set[str] = set()
        for port in target_class.outputs:
            if port.schema and isinstance(port.schema, dict):
                props |= set(port.schema.get("properties", {}).keys())

        # 并集为空（全 None）→ 字段层跳过（Pitfall 2 / D-03）
        if not props:
            return

        # 剥离 [n]/[-n] 下标后缀后取首段字段名
        first_field = first_segment
        index_match = _INDEX_SUFFIX_RE.match(first_field)
        if index_match:
            first_field = index_match.group(1)

        if first_field not in props:
            errors.append(
                ValidationIssue(
                    reason="field_not_found",
                    severity="error",
                    node_id=referencing_node.get("id"),
                    field_path=field_path,
                    message=(
                        f"节点 '{short_id}' 输出中不存在字段 '{first_field}'，"
                        f"可用字段: {sorted(props)}"
                    ),
                )
            )

    def _iter_config_strings(self, value: Any, path: str):
        """递归遍历 config，产出 (field_path, 字符串值) 二元组。"""
        if isinstance(value, str):
            yield path, value
        elif isinstance(value, dict):
            for key, sub_value in value.items():
                sub_path = f"{path}.{key}" if path else str(key)
                yield from self._iter_config_strings(sub_value, sub_path)
        elif isinstance(value, list):
            for index, sub_value in enumerate(value):
                yield from self._iter_config_strings(sub_value, f"{path}[{index}]")
