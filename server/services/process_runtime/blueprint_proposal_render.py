"""分仓 OpenSpec Proposal 渲染：把合并蓝图按仓投影成 openspec `proposal.md` 结构。

**用途**：技术方案主文档一直「看不到分仓方案」——各仓的 RepoPlan 在 merge 阶段已被
投影进蓝图六段（`implementation_overview.items` / `api_contracts` /
`impact_analysis.affected_features` 按 `repository_id` 组织，`requirement_spec.
feature_points` 经 items 的 `feature_point_id` 归属到仓），但主 markdown 是「一份合并
方案」的视角，分仓内容被打散。本模块把散落各段的**仓级**内容重新**按仓聚合**，渲染成
OpenSpec 的 proposal 结构（Why / What Changes / Impact / Spec Deltas），由
:mod:`blueprint_render` 拼进主 markdown（飞书导出与时间线视图共用）。

四条契约（模块级不变量，改动前先读）：

1. **纯函数**：无 IO / 无 ORM / 无 LLM，只读传入的 `blueprint/v1` content。不查
   `Repository` 表——仓名的权威位置就在 `repo_associations[].repository_name`。
2. **数据同源，绝不新引真相源**：Why ← `repo_associations`（rationale / responsibility /
   planned_change_summary）；What Changes ← `implementation_overview.items` +
   `api_contracts`；Impact ← `impact_analysis`；Spec Deltas ←
   `requirement_spec.feature_points`（经 items 的 `feature_point_id` 归属到本仓）。
3. **版式 ≤3 级 heading**（与 :mod:`blueprint_render` 同约束，飞书 `markdown_to_blocks`
   表达力上界）：Why / What Changes / Impact / Spec Deltas 用**加粗标签**而非 `####`
   标题，场景（Scenario）用嵌套列表表达。
4. **best-effort**：半可信 content 逐字段 `.get` 防御，缺料落占位符，绝不外抛。
"""

from __future__ import annotations

import json
from typing import Any

from delivery.services.blueprint_anchor import _block_text as _anchor_block_text

__all__ = ["render_repo_proposals_markdown", "render_single_repo_proposal_markdown"]

# 缺料一律降级为该占位符（与 blueprint_render 同口径，⛔ 不留白）。
_EMPTY = "—"

_ROLE_LABELS = {"direct": "直接改动", "indirect": "间接依赖"}
_CHANGE_LABELS = {
    "create": "新建",
    "modify": "改动",
    "remove": "删除",
    "indirect_refine": "间接完善",
}
# 功能点意图 → OpenSpec spec delta 类别。openspec 只有 ADDED / MODIFIED / REMOVED /
# RENAMED；缺陷修复归入 MODIFIED（改行为），未知意图兜底 MODIFIED。
_INTENT_DELTA = {"greenfield": "ADDED", "brownfield": "MODIFIED", "fix": "MODIFIED"}


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return _EMPTY
    rendered = str(value).strip()
    return rendered or _EMPTY


def _blocks_text(blocks: Any) -> str:
    """block_list → 段落文本（逐块一段，空列表返回空串，⛔ 不落占位符）。

    取文本委托锚点坐标系同一实现（`text` → `code.source` → `rows` 字段优先级）。
    """
    paragraphs = [
        _anchor_block_text(block).strip() for block in _list(blocks) if isinstance(block, dict)
    ]
    paragraphs = [text for text in paragraphs if text]
    return "\n\n".join(paragraphs)


def _json_text(value: Any) -> str:
    """结构化字段 → 稳定、可读的单行 JSON；空对象不渲染。"""
    if not isinstance(value, (dict, list)) or not value:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _join_nonempty(value: Any) -> str:
    return "、".join(str(item).strip() for item in _list(value) if str(item).strip())


def _repo_names(associations: list) -> dict[str, str]:
    """`repo_associations` → `{repository_id: 仓名}`，缺名回落 id（⛔ 不留白）。"""
    names: dict[str, str] = {}
    for item in associations:
        item = _dict(item)
        repository_id = str(item.get("repository_id") or "").strip()
        if not repository_id:
            continue
        name = str(item.get("repository_name") or "").strip()
        names[repository_id] = name or repository_id
    return names


def _feature_points_by_id(spec: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for point in _list(spec.get("feature_points")):
        point = _dict(point)
        fid = str(point.get("id") or "").strip()
        if fid:
            result[fid] = point
    return result


def _render_why(assoc: dict) -> list[str]:
    rationale = _dict(assoc.get("rationale"))
    why = _blocks_text(rationale.get("text"))
    responsibility = _blocks_text(assoc.get("responsibility"))
    change_summary = _blocks_text(assoc.get("planned_change_summary"))
    parts = ["**Why**\n"]
    parts.append((why or responsibility or _EMPTY) + "\n")
    if responsibility and responsibility != why:
        parts.append(f"职责：{responsibility}\n")
    if change_summary:
        parts.append(f"计划改动：{change_summary}\n")
    return parts


def _render_what_changes(
    rid: str, role: str, assoc: dict, items: list, contracts: list
) -> list[str]:
    lines: list[str] = []
    for item in (_dict(x) for x in items):
        if str(item.get("repository_id") or "") != rid:
            continue
        change = str(item.get("change_type") or "")
        change_label = _CHANGE_LABELS.get(change, change or _EMPTY)
        title = _text(item.get("title"))
        how = _blocks_text(item.get("how"))
        files = "、".join(
            f"{_text(_dict(f).get('path'))}[{_text(_dict(f).get('action'))}]"
            for f in _list(item.get("files_touched"))
        )
        line = f"- {change_label} `{title}`"
        lines.append(line)
        if how:
            lines.append(f"  - 实现：{how}")
        if files:
            lines.append(f"  - 文件：{files}")
        dependencies = _join_nonempty(item.get("depends_on"))
        if dependencies:
            lines.append(f"  - 依赖实现项：{dependencies}")
        integration = _blocks_text(item.get("existing_integration"))
        if integration:
            lines.append(f"  - 既有集成：{integration}")
        test_strategy = _blocks_text(item.get("test_strategy"))
        if test_strategy:
            lines.append(f"  - 测试策略：{test_strategy}")

    for contract in (_dict(x) for x in contracts):
        if str(contract.get("repository_id") or "") != rid:
            continue
        direction = str(contract.get("direction") or "")
        endpoint = f"{_text(contract.get('method'))} {_text(contract.get('path'))}".strip()
        name = _text(contract.get("name"))
        if direction == "provided":
            lines.append(f"- 提供接口 `{endpoint}`（{name}）")
        elif direction == "consumed":
            data_source = _dict(contract.get("data_source"))
            source = _text(data_source.get("from_service"))
            availability = str(data_source.get("availability") or "").strip()
            suffix = f"（来源：{source}"
            if availability:
                suffix += f"，{availability}"
            suffix += "）"
            lines.append(f"- 消费接口 `{endpoint}`{suffix}")
            fields_needed = _join_nonempty(data_source.get("fields_needed"))
            if fields_needed:
                lines.append(f"  - 所需字段：{fields_needed}")
        else:
            continue
        description = _blocks_text(contract.get("description"))
        if description:
            lines.append(f"  - 说明：{description}")
        request_schema = _json_text(contract.get("request_schema"))
        if request_schema:
            lines.append(f"  - 请求 schema：`{request_schema}`")
        response_schema = _json_text(contract.get("response_schema"))
        if response_schema:
            lines.append(f"  - 响应 schema：`{response_schema}`")

    if role == "indirect":
        for capability in (_dict(x) for x in _list(assoc.get("capabilities_used"))):
            name = _text(capability.get("name"))
            how_used = _text(capability.get("how_used"))
            lines.append(f"- 被引用能力 `{name}`：{how_used}")

    parts = ["**What Changes**\n"]
    if lines:
        parts.append("\n".join(lines) + "\n")
    elif role == "indirect":
        parts.append("- 本方案不改动此仓（作为间接依赖被引用）\n")
    else:
        parts.append(_EMPTY + "\n")
    return parts


def _render_impact(rid: str, affected: list, contracts: list) -> list[str]:
    lines: list[str] = []
    for feature in (_dict(x) for x in affected):
        repo_ids = [str(r) for r in _list(feature.get("repository_ids"))]
        if rid not in repo_ids:
            continue
        kind = _text(feature.get("kind"))
        lines.append(f"- 受影响功能：{_text(feature.get('feature'))}（{kind}）")
        description = _blocks_text(feature.get("description"))
        if description:
            lines.append(f"  - 影响说明：{description}")

    # 本仓被别的仓「点名要配合产出」的消费项（needs_support）——这是该仓的对外承诺。
    for contract in (_dict(x) for x in contracts):
        data_source = _dict(contract.get("data_source"))
        if str(data_source.get("availability") or "") != "needs_support":
            continue
        if str(data_source.get("support_repository_id") or "") != rid:
            continue
        lines.append(
            f"- 需本仓配合产出：{_text(contract.get('name'))}（{_text(contract.get('path'))}）"
        )

    parts = ["**Impact**\n"]
    parts.append(("\n".join(lines) if lines else _EMPTY) + "\n")
    return parts


def _render_scenario_lines(feature_point: dict) -> list[str]:
    """把功能点的 acceptance_criteria + test_cases 渲染成 openspec spec delta 的
    SHALL / Scenario 子列表（heading ≤3 约束下用嵌套列表表达）。"""
    lines: list[str] = []
    for criterion in _list(feature_point.get("acceptance_criteria")):
        text = str(criterion).strip()
        if text:
            lines.append(f"  - SHALL：{text}")
    for case in _list(feature_point.get("test_cases")):
        case = _dict(case)
        name = _text(case.get("name"))
        lines.append(f"  - Scenario 场景「{name}」")
        gwt = case.get("given_when_then")
        if isinstance(gwt, dict):
            for label, key in (("GIVEN", "given"), ("WHEN", "when"), ("THEN", "then")):
                value = str(gwt.get(key) or "").strip()
                if value:
                    lines.append(f"    - {label} {value}")
        elif isinstance(gwt, str) and gwt.strip():
            lines.append(f"    - {gwt.strip()}")
    return lines


def _render_spec_deltas(rid: str, items: list, feature_points: dict) -> list[str]:
    ordered_fp_ids: list[str] = []
    seen: set[str] = set()
    for item in (_dict(x) for x in items):
        if str(item.get("repository_id") or "") != rid:
            continue
        fid = str(item.get("feature_point_id") or "").strip()
        if fid and fid not in seen and fid in feature_points:
            seen.add(fid)
            ordered_fp_ids.append(fid)

    parts = ["**Spec Deltas**\n"]
    if not ordered_fp_ids:
        parts.append(_EMPTY + "\n")
        return parts

    lines: list[str] = []
    for fid in ordered_fp_ids:
        feature_point = feature_points[fid]
        intent = str(feature_point.get("intent") or "")
        delta = _INTENT_DELTA.get(intent, "MODIFIED")
        title = _text(feature_point.get("title"))
        lines.append(f"- {delta} · 需求「{title}」（{fid}）")
        description = _blocks_text(feature_point.get("description"))
        if description:
            lines.append(f"  - 需求说明：{description}")
        lines.extend(_render_scenario_lines(feature_point))
    parts.append("\n".join(lines) + "\n")
    return parts


def _render_repo_proposal(
    rid: str,
    assoc: dict,
    names: dict[str, str],
    feature_points: dict,
    items: list,
    contracts: list,
    affected: list,
) -> list[str]:
    role = str(assoc.get("role") or "")
    role_label = _ROLE_LABELS.get(role, role or _EMPTY)
    heading = names.get(rid, rid)
    parts = [f"### {heading}（{role_label}）\n"]
    parts.extend(_render_why(assoc))
    parts.extend(_render_what_changes(rid, role, assoc, items, contracts))
    parts.extend(_render_impact(rid, affected, contracts))
    parts.extend(_render_spec_deltas(rid, items, feature_points))
    return parts


def render_repo_proposals_markdown(content: Any) -> str:
    """把 `blueprint/v1` content 按仓渲染成「分仓方案（OpenSpec Proposal）」章节。

    Args:
        content: `blueprint/v1` 的 content dict（半可信：逐字段 `.get` 防御）。

    Returns:
        markdown 章节全文（以 `## 分仓方案（OpenSpec Proposal）` 起头）；无
        `repo_associations` 时返回空串（由调用方决定是否并入主文档）。
    """
    data = _dict(content)
    associations = _list(data.get("repo_associations"))
    if not associations:
        return ""

    names = _repo_names(associations)
    feature_points = _feature_points_by_id(_dict(data.get("requirement_spec")))
    items = _list(_dict(data.get("implementation_overview")).get("items"))
    contracts = _list(data.get("api_contracts"))
    affected = _list(_dict(data.get("impact_analysis")).get("affected_features"))

    parts = ["## 分仓方案（OpenSpec Proposal）\n"]
    parts.append(
        "> 每仓一份 OpenSpec 风格提案（Why / What Changes / Impact / Spec Deltas），"
        "由本次需求在该仓的分仓方案（RepoPlan）投影聚合而成。\n"
    )
    for assoc in associations:
        assoc = _dict(assoc)
        rid = str(assoc.get("repository_id") or "").strip()
        if not rid:
            continue
        parts.extend(
            _render_repo_proposal(rid, assoc, names, feature_points, items, contracts, affected)
        )
    return "\n".join(parts)


def render_single_repo_proposal_markdown(content: Any, repository_id: Any) -> str:
    """从 ``blueprint/v1`` 确定性渲染单仓完整 OpenSpec Proposal。

    该输出用于编码 fan-out 的**只读 prompt 上下文**，不会写入目标仓库。无匹配仓库时返回
    空串，调用方据此保持 legacy / 非 blueprint 路径零回归。
    """
    data = _dict(content)
    rid = str(repository_id or "").strip()
    if not rid:
        return ""
    associations = _list(data.get("repo_associations"))
    assoc = next(
        (
            _dict(item)
            for item in associations
            if str(_dict(item).get("repository_id") or "").strip() == rid
        ),
        None,
    )
    if not assoc:
        return ""

    names = _repo_names(associations)
    feature_points = _feature_points_by_id(_dict(data.get("requirement_spec")))
    items = _list(_dict(data.get("implementation_overview")).get("items"))
    contracts = _list(data.get("api_contracts"))
    affected = _list(_dict(data.get("impact_analysis")).get("affected_features"))
    return "\n".join(
        _render_repo_proposal(rid, assoc, names, feature_points, items, contracts, affected)
    )
