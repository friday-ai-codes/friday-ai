"""execution_plan 确定性派生器（Phase 111-01，SCHEMA-06）。

从 blueprint/v1 的 ``implementation_overview.items`` 按 ``repository_id`` 聚合派生
technical_plan 形状的 ``execution_plan``（DESIGN §3.14）：

- 每仓一个 task，补齐 ``validate_technical_plan`` 的必填字段（id/name/repository_id/
  repository_name/branch_strategy——蓝图无 branch_strategy 概念，派生给默认值）；
- ``coding_instruction`` 由 item 的 how/existing_integration/test_strategy Block[]
  文本确定性拼装；
- ``files`` 合并 ``files_touched`` 并做 **action 映射 remove→delete**（蓝图侧枚举是
  create/modify/remove，technical_plan 侧是 create/modify/delete）；
- item 跨仓 ``depends_on`` 投影为仓级 task ``dependencies`` 边。

**纯函数**（无 IO / 无 ORM / 无 LLM），顶层仅 import ``validate_technical_plan``
与 stdlib。同输入重复调用输出逐字节一致（排序全部显式化），派生文档必须通过既有
``validate_technical_plan`` 验收——保证下游 coding dispatcher 零改动可消费。
"""

from __future__ import annotations

from typing import Any

from workflows.schemas.technical_plan import validate_technical_plan

__all__ = [
    "derive_execution_plan",
    "derive_technical_plan_document",
    "DEFAULT_BRANCH_STRATEGY",
]

# 蓝图无分支策略概念；派生时统一默认值（technical_plan enum 只认 feature/hotfix/release）。
DEFAULT_BRANCH_STRATEGY = "feature"

# 蓝图 files_touched.action（create/modify/remove）→ technical_plan files.action
# （create/modify/delete）的映射；不映射会被 validate_technical_plan 拒绝。
_ACTION_MAP = {"remove": "delete"}


def _blocks_to_text(blocks: Any) -> str:
    """Block[] → 纯文本：paragraph/list 取 text、pseudocode 围栏渲染、table 按行拼接。"""
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type == "pseudocode":
            code = block.get("code") if isinstance(block.get("code"), dict) else {}
            language = str(code.get("language") or "")
            source = str(code.get("source") or "")
            if source:
                parts.append(f"```{language}\n{source}\n```")
        elif block_type == "table":
            rows = block.get("rows")
            if isinstance(rows, list):
                lines = [
                    " | ".join(str(cell) for cell in row) for row in rows if isinstance(row, list)
                ]
                if lines:
                    parts.append("\n".join(lines))
        else:  # paragraph / list / mermaid：尽力从 text 取
            text = block.get("text")
            if isinstance(text, list):
                entries = [f"- {entry}" for entry in text if isinstance(entry, str) and entry]
                if entries:
                    parts.append("\n".join(entries))
            elif isinstance(text, str) and text:
                parts.append(text)
    return "\n\n".join(parts)


def _build_coding_instruction(items: list[dict]) -> str:
    """按 item id 排序拼装该仓的编码指令（确定性输出）。"""
    sections: list[str] = []
    for item in sorted(items, key=lambda i: str(i.get("id", ""))):
        title = str(item.get("title") or item.get("id") or "")
        change_type = str(item.get("change_type") or "")
        lines = [f"## {title}（{change_type}）"]
        how_text = _blocks_to_text(item.get("how"))
        if how_text:
            lines.append(how_text)
        integration = _blocks_to_text(item.get("existing_integration"))
        if integration:
            lines.append(f"与既有功能配合：{integration}")
        test_strategy = _blocks_to_text(item.get("test_strategy"))
        if test_strategy:
            lines.append(f"测试策略：{test_strategy}")
        sections.append("\n\n".join(lines))
    return "\n\n".join(sections)


def _merge_files(items: list[dict]) -> list[dict]:
    """合并该仓全部 files_touched：remove→delete 映射、(path, action) 去重、按 path 排序。"""
    merged: dict[tuple[str, str], dict] = {}
    for item in items:
        for entry in item.get("files_touched") or []:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            action_raw = entry.get("action")
            if not isinstance(path, str) or not path or not isinstance(action_raw, str):
                continue
            action = _ACTION_MAP.get(action_raw, action_raw)
            key = (path, action)
            if key in merged:
                continue
            file_entry: dict[str, Any] = {"path": path, "action": action}
            note = entry.get("note")
            if isinstance(note, str) and note:
                file_entry["note"] = note
            merged[key] = file_entry
    return [merged[key] for key in sorted(merged)]


def derive_execution_plan(blueprint: dict) -> list[dict]:
    """从 blueprint/v1 派生 technical_plan 形状的 execution_plan（确定性）。

    Args:
        blueprint: 半可信 blueprint dict（逐字段 ``.get`` 防御，缺 id/repository_id
            的 item 跳过；无效 depends_on 引用过滤）。

    Returns:
        每仓一个 task 的列表，按 ``(min(item.wave, default=1), repository_id)``
        升序；同输入重复调用输出逐字节一致。
    """
    if not isinstance(blueprint, dict):
        return []
    overview = blueprint.get("implementation_overview")
    raw_items = overview.get("items") if isinstance(overview, dict) else None
    items = [
        item
        for item in (raw_items if isinstance(raw_items, list) else [])
        if isinstance(item, dict) and item.get("id") and item.get("repository_id")
    ]
    if not items:
        return []

    # repository_name 快照：从 repo_associations 查表，查不到回退 repository_id 字符串
    # （漏 repository_name 会被 validate_technical_plan 拒，RESEARCH P9）。
    repo_names: dict[str, str] = {}
    for assoc in blueprint.get("repo_associations") or []:
        if (
            isinstance(assoc, dict)
            and assoc.get("repository_id")
            and isinstance(assoc.get("repository_name"), str)
            and assoc["repository_name"]
        ):
            repo_names.setdefault(assoc["repository_id"], assoc["repository_name"])

    item_repo = {item["id"]: item["repository_id"] for item in items}

    repo_items: dict[str, list[dict]] = {}
    for item in items:
        repo_items.setdefault(item["repository_id"], []).append(item)

    # 仓间依赖：item.depends_on 指向他仓 item → 本仓任务依赖目标仓任务；
    # 无效引用过滤、同仓内部依赖不成边（wave_layering 范式）。
    repo_deps: dict[str, set[str]] = {rid: set() for rid in repo_items}
    for item in items:
        rid = item["repository_id"]
        for dep in item.get("depends_on") or []:
            target_repo = item_repo.get(dep, "")
            if target_repo and target_repo != rid:
                repo_deps[rid].add(target_repo)

    def _repo_sort_key(rid: str) -> tuple[int, str]:
        waves = [item["wave"] for item in repo_items[rid] if isinstance(item.get("wave"), int)]
        return (min(waves) if waves else 1, rid)

    tasks: list[dict] = []
    for rid in sorted(repo_items, key=_repo_sort_key):
        repository_name = repo_names.get(rid) or rid
        tasks.append(
            {
                "id": f"task_{rid}",
                "name": f"{repository_name} 蓝图变更集",
                "repository_id": rid,
                "repository_name": repository_name,
                "branch_strategy": DEFAULT_BRANCH_STRATEGY,
                "coding_instruction": _build_coding_instruction(repo_items[rid]),
                "files": _merge_files(repo_items[rid]),
                "dependencies": sorted(f"task_{dep}" for dep in repo_deps[rid]),
            }
        )
    return tasks


def derive_technical_plan_document(blueprint: dict) -> tuple[dict | None, str | None]:
    """派生完整 technical_plan 文档并用既有 ``validate_technical_plan`` 验收。

    Returns:
        ``(doc, None)``——派生文档通过校验；``(None, error)``——未通过（字段补齐
        义务未满足即在此暴露，RESEARCH P9）。
    """
    if not isinstance(blueprint, dict):
        return None, "blueprint 必须是 JSON 对象"
    meta = blueprint.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    title = str(meta.get("title") or "")
    summary = _blocks_to_text(meta.get("summary")) or title
    doc = {
        "title": title,
        "summary": summary,
        "execution_plan": derive_execution_plan(blueprint),
    }
    ok, err = validate_technical_plan(doc)
    if not ok:
        return None, err
    return doc, None
