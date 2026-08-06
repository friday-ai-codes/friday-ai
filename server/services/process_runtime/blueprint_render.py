"""blueprint/v1 → markdown 渲染器（Phase 116-05，VIEW-05）。

**用途**：``blueprint/v1`` content 转 markdown 的**唯一**渲染器。飞书导出物与
``ArtifactTimelineView.current_version_markdown`` **共用它**——⛔ 不在导出器里就地拼
markdown：那会让时间线面的结构性空壳问题留着，两处口径立刻分叉（导出物有六段、界面
仍是 v0 空壳），而这两个面呈现的应当是同一份方案。

⭐ **不可关闭的标注契约（三条不变量，⛔ 任何人不得放宽）**：

1. ``blueprint_status`` **必填 keyword-only、无默认值** ⇒ 调用方在物理上无法省略它；
2. 抑制集合 :data:`_SUPPRESS_WATERMARK_STATUSES` 是**闭合白名单**（三个已确认态），
   其余一切取值——含空串、含未知字符串、含 ``None`` 归一后的空串——**都渲染标注**；
3. ⛔ **不存在任何布尔开关参数**（「要不要加水印」之流一个都没有——给了早晚有人传
   ``False``）。

⭐ **关键不变量是「没有任何取值能关掉标注」，而不是「只有一个调用点」**：注册表契约
``ContentRenderer = Callable[[dict], str]`` 拿不到 ``Artifact.blueprint_status``（它不在
content 里），所以注册表分支只能传 ``""``——而 ``"" ∉ 白名单`` ⇒ **fail-safe 当作未确认**。
唯一可机器验的形式是一条 ``inspect.signature`` 断言：参数名集合恰为
``{content, blueprint_status}``，任何人加开关参数即转红。

**块取文本口径**：按字段优先级 ``text`` → ``code.source`` → ``rows``，**完全不看块的
类型字段**——直接委托 :func:`delivery.services.blueprint_anchor._block_text`（⛔ 零副本）。
按类型分派会与批注的锚点坐标系分叉，导出物与批注位置对不上。

⛔ **批注不导出是天然满足的**：``BlueprintThread`` 本就不在 content 里（DESIGN §6.2），
本模块只读 content ⇒ **不写任何过滤代码**。写了既是死码，又会让读者误以为 content 里
藏着批注。

**版式保守**（``markdown_to_blocks`` 的表达力上界未逐行核过）：heading ≤3 级、表格不
嵌套、脚注用**普通列表**而非 ``[^n]`` 语法。
"""

from __future__ import annotations

from typing import Any

from delivery.services.blueprint_anchor import _block_text as _anchor_block_text

__all__ = ["blueprint_status_of", "render_blueprint_markdown"]

_COMPONENT = "blueprint_render"

# ⭐ 抑制标注的**闭合白名单**：三个字面量逐字取自 ``delivery.models.BlueprintStatus``
# 的 CONFIRMED / IMPLEMENTING / IMPLEMENTED（用例断言两者成员相同；此处刻意写字面量
# 而非 import 模型层，避免 process_runtime 在 import 期反向依赖 delivery 模型）。
# ⛔ 这是白名单不是黑名单：**白名单之外的一切取值都渲染标注**，方向不可倒过来。
# 前端 ``BlueprintViewerHeader.vue`` 的 ``CONFIRMED_STATUSES`` 与本集合逐字对齐，
# 两侧各有一条变异用例。
_SUPPRESS_WATERMARK_STATUSES: frozenset[str] = frozenset(
    {
        "confirmed",
        "implementing",
        "implemented",
    }
)

# 缺料一律降级为该占位符，⛔ 不留白（读者要能分清「没有这项」与「渲染漏了」）。
_EMPTY = "—"

# 引用摘录快照上界：取不到链接时落原文摘录，过长会把脚注刷成正文。
_QUOTE_SNAPSHOT_CHARS = 120

_REPO_ROLE_LABELS = {"direct": "直接改动", "indirect": "间接依赖"}


# ── 基础工具（形状与 feishu/coding_plan_exporter 的组装范式同形）─────────────


def _md_escape(text: str) -> str:
    """对 markdown 表格 cell 做最小转义，避免 | 截断列。

    ⚠️ **复制自** ``feishu.coding_plan_exporter._md_escape``：``services/process_runtime``
    ⛔ 不反向依赖 ``feishu/``（导出器依赖渲染器，反过来会成环）。
    """
    return text.replace("|", "\\|").replace("\n", " ")


def _block_text(block: Any) -> str:
    """取块的可比对文本：委托锚点坐标系的同一实现，⛔ 零副本。

    字段优先级 ``text`` → ``code.source`` → ``rows``，完全不看块自身的类别字段。
    """
    return _anchor_block_text(block)


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    """标量降级：``None`` / 空串 / 非标量一律落占位符。"""
    if value is None:
        return _EMPTY
    rendered = str(value).strip()
    return rendered or _EMPTY


def _cell(value: Any) -> str:
    return _md_escape(_text(value))


def _join_ids(value: Any) -> str:
    items = [str(item).strip() for item in _list(value) if str(item).strip()]
    return "、".join(items) if items else _EMPTY


# ── 仓名解析（⛔ 零 DB：映射从 content 自身派生）────────────────────────────


def _repo_names(associations: list) -> dict[str, str]:
    """``repo_associations`` → ``{repository_id: 仓名}``。

    ⭐ **仓名的权威位置就在 content 里**（``repo_associations[].repository_name`` 是 schema
    必填项），所以渲染器无需查 ``Repository`` 表就能把散落各段的 ``repository_id`` 渲染成
    人读的仓名 —— 这一点很要紧：渲染器是**纯函数**，注册表契约
    ``ContentRenderer = Callable[[dict], str]`` 也不给它 DB 会话。

    ⛔ **不为仓名给** :func:`render_blueprint_markdown` **加参数**：签名断言（用例 §1）要求
    参数名集合恰为 ``{content, blueprint_status}``，那是「未经确认」标注不可关闭的唯一机器
    验形式。映射从 content 派生既守住该不变量，又不引入第二个真相源。

    空仓名**不入表** ⇒ :func:`_repo_label` 自然回落 id（融合期 ``repository_name`` 缺失会被
    回落成 id 写进快照，两条路径落点一致）。
    """
    names: dict[str, str] = {}
    for item in associations:
        item = _dict(item)
        repository_id = str(item.get("repository_id") or "").strip()
        name = str(item.get("repository_name") or "").strip()
        if repository_id and name:
            names[repository_id] = name
    return names


def _repo_label(value: Any, names: dict[str, str]) -> str:
    """仓库 id → 仓名；解析不到**回落 id**，⛔ 不留白也⛔ 不吞掉这一维信息。

    回落方向与前端各 section 的 ``repoNames[id] || id`` 逐字同口径（`[id].vue:418`）——
    两侧分叉会让同一份方案在页面与导出物上指向不同的仓。
    """
    repository_id = str(value or "").strip()
    if not repository_id:
        return _EMPTY
    return names.get(repository_id) or repository_id


def _join_repos(value: Any, names: dict[str, str]) -> str:
    """仓库 id 列表 → 顿号连接的仓名（`_join_ids` 的解析版）。"""
    labels = [_repo_label(item, names) for item in _list(value) if str(item or "").strip()]
    return "、".join(labels) if labels else _EMPTY


def _render_blocks(blocks: Any) -> str:
    """block_list → 段落文本（逐块一段，空列表落占位符）。"""
    paragraphs = [_block_text(block).strip() for block in _list(blocks) if isinstance(block, dict)]
    paragraphs = [text for text in paragraphs if text]
    if not paragraphs:
        return _EMPTY
    return "\n\n".join(paragraphs)


def _build_table(headers: list[str], rows: list[list[str]]) -> str:
    """渲染 markdown 表格；**零行补一行占位**（analog `_build_affected_files_table`）。"""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    if not rows:
        lines.append("| " + " | ".join(_EMPTY for _ in headers) + " |")
    return "\n".join(lines) + "\n"


# ── 引用脚注（每段末尾以普通列表给出，取不到链接落 title / quote 快照）────────


def _collect_citation_ids(node: Any) -> list[str]:
    """递归收集该段内出现过的 ``citations`` id（去重保序）。

    ⚠️ 只走**段落子树**：文档级引用池 ``content["citations"]`` 是 dict，不从这里进来。
    """
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "citations" and isinstance(item, list):
                    found.extend(str(cid) for cid in item if isinstance(cid, str) and cid)
                    continue
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    seen: set[str] = set()
    ordered: list[str] = []
    for cid in found:
        if cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def _citation_link(citation: dict) -> str:
    """取可点链接（拿不到返空串）。"""
    locator = _dict(citation.get("locator"))
    candidates = (
        citation.get("url"),
        locator.get("url"),
        locator.get("link"),
        citation.get("source_id"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
    return ""


def _citation_line(citation_id: str, pool: dict) -> str:
    """单条引用脚注：title + 来源类型 + 可点链接；⛔ 取不到链接不留白，落 quote 快照。"""
    citation = _dict(pool.get(citation_id))
    if not citation:
        # 引用池里没有这条（半可信 content 允许块引到不存在的 id）——仍如实列出 id。
        return f"- {_md_escape(citation_id)} —— 来源：{_EMPTY}｜链接：{_EMPTY}"
    title = str(citation.get("title") or "").strip()
    source_type = str(citation.get("source_type") or "").strip() or _EMPTY
    quote = str(citation.get("quote") or "").strip()
    link = _citation_link(citation)
    label = _md_escape(title or citation_id)
    display = f"[{label}]({link})" if link else label
    line = f"- {display} —— 来源：{_md_escape(source_type)}"
    if link:
        return line
    if quote:
        snapshot = quote[:_QUOTE_SNAPSHOT_CHARS]
        return line + f"｜原文摘录：{_md_escape(snapshot)}"
    return line + f"｜链接：{_EMPTY}"


def _citation_footnotes(node: Any, pool: dict) -> list[str]:
    """段末脚注块（该段无引用时返回空列表，⛔ 不塞空标题）。"""
    citation_ids = _collect_citation_ids(node)
    if not citation_ids:
        return []
    lines = [_citation_line(citation_id, pool) for citation_id in citation_ids]
    return ["**本段引用**\n", "\n".join(lines) + "\n"]


# ── 十段渲染 ────────────────────────────────────────────────────────────────


def _build_watermark(meta: dict, status: str) -> str:
    """⭐ 未确认标注：**文档第一行、无条件**（``> `` blockquote 形态，飞书可承载）。

    ⚠️ ``version_no`` **不在 blueprint/v1 的 meta 段内** ⇒ 取不到时**整段省略版本片段**，
    ⛔ 不编造、⛔ 不为它改 schema。标注本身与版本片段无关：白名单外一律有标注。
    """
    label = status or "未知"
    version_no = meta.get("version_no")
    fragment = ""
    if version_no not in (None, ""):
        fragment = f" · 版本 v{_text(version_no)}"
    return f"> ⚠️ 未经确认 —— 本方案尚未经人工终审（当前状态：{label}{fragment}）\n"


def _section_requirement_spec(spec: dict, pool: dict) -> list[str]:
    parts = ["## 需求规格\n", "### 目标\n", _render_blocks(spec.get("goal")) + "\n"]
    parts.append("### 背景\n")
    parts.append(_render_blocks(spec.get("background")) + "\n")
    parts.append("### 功能点\n")
    rows = []
    for point in _list(spec.get("feature_points")):
        point = _dict(point)
        rows.append(
            [
                _cell(point.get("id")),
                _cell(point.get("title")),
                _cell(point.get("intent")),
                _cell("；".join(str(item) for item in _list(point.get("acceptance_criteria")))),
            ]
        )
    parts.append(_build_table(["功能点 id", "标题", "意图", "验收标准"], rows))
    parts.extend(_citation_footnotes(spec, pool))
    return parts


def _section_repo_associations(associations: list, pool: dict) -> list[str]:
    parts = ["## 仓库关联\n"]
    rows = []
    for item in associations:
        item = _dict(item)
        role = str(item.get("role") or "")
        rationale = _dict(item.get("rationale"))
        rows.append(
            [
                _cell(item.get("repository_name")),
                _cell(_REPO_ROLE_LABELS.get(role, role)),
                _cell(_render_blocks(item.get("responsibility"))),
                _cell(_render_blocks(rationale.get("text"))),
            ]
        )
    parts.append(_build_table(["仓库", "角色", "职责", "选仓理由"], rows))
    parts.extend(_citation_footnotes(associations, pool))
    return parts


def _section_current_state(analysis: list, pool: dict, names: dict[str, str]) -> list[str]:
    parts = ["## 现状分析\n"]
    if not analysis:
        parts.append(_EMPTY + "\n")
    for entry in analysis:
        entry = _dict(entry)
        parts.append(f"### 仓库 {_repo_label(entry.get('repository_id'), names)}\n")
        parts.append(_render_blocks(entry.get("summary")) + "\n")
        rows = []
        for finding in _list(entry.get("findings")):
            finding = _dict(finding)
            rows.append(
                [
                    _cell(finding.get("id")),
                    _cell(finding.get("kind")),
                    _cell(finding.get("topic")),
                    _cell(_render_blocks(finding.get("text"))),
                ]
            )
        parts.append(_build_table(["结论 id", "类型", "主题", "结论"], rows))
    parts.extend(_citation_footnotes(analysis, pool))
    return parts


def _section_implementation(overview: dict, pool: dict, names: dict[str, str]) -> list[str]:
    parts = ["## 实现概述\n", "### 需求叙事\n"]
    parts.append(_render_blocks(overview.get("requirement_narrative")) + "\n")
    parts.append("### 功能模块\n")
    module_rows = []
    for module in _list(overview.get("modules")):
        module = _dict(module)
        module_rows.append(
            [
                _cell(module.get("id")),
                _cell(module.get("name")),
                _cell(_join_ids(module.get("feature_point_ids"))),
                _cell(_join_repos(module.get("repository_ids"), names)),
            ]
        )
    parts.append(_build_table(["模块 id", "模块名", "覆盖功能点", "涉及仓库"], module_rows))
    parts.append("### 实现项\n")
    item_rows = []
    details: list[str] = []
    for item in _list(overview.get("items")):
        item = _dict(item)
        item_rows.append(
            [
                _cell(item.get("id")),
                _cell(item.get("title")),
                _cell(item.get("feature_point_id")),
                _cell(_repo_label(item.get("repository_id"), names)),
                _cell(item.get("change_type")),
                _cell(item.get("wave")),
            ]
        )
        files = "；".join(
            f"{_text(_dict(entry).get('path'))}({_text(_dict(entry).get('action'))})"
            for entry in _list(item.get("files_touched"))
        )
        details.append(
            f"**{_text(item.get('id'))} {_text(item.get('title'))}**\n\n"
            f"{_render_blocks(item.get('how'))}\n\n"
            f"涉及文件：{files or _EMPTY}\n"
        )
    parts.append(
        _build_table(["实现项 id", "标题", "功能点", "仓库", "变更类型", "波次"], item_rows)
    )
    if details:
        parts.append("### 实现项详情\n")
        parts.extend(details)
    parts.extend(_citation_footnotes(overview, pool))
    return parts


def _section_api_contracts(contracts: list, pool: dict, names: dict[str, str]) -> list[str]:
    parts = ["## API 契约\n"]
    rows = []
    details: list[str] = []
    for contract in contracts:
        contract = _dict(contract)
        rows.append(
            [
                _cell(contract.get("id")),
                _cell(contract.get("name")),
                _cell(contract.get("kind")),
                _cell(contract.get("direction")),
                _cell(contract.get("method")),
                _cell(contract.get("path")),
                _cell(_repo_label(contract.get("repository_id"), names)),
            ]
        )
        description = _render_blocks(contract.get("description"))
        if description != _EMPTY:
            details.append(
                f"**{_text(contract.get('id'))} {_text(contract.get('name'))}**\n\n{description}\n"
            )
    parts.append(
        _build_table(["契约 id", "名称", "接口类型", "方向", "方法", "路径", "归属仓库"], rows)
    )
    if details:
        parts.append("### 契约说明\n")
        parts.extend(details)
    parts.extend(_citation_footnotes(contracts, pool))
    return parts


def _section_impact(impact: dict, pool: dict, names: dict[str, str]) -> list[str]:
    parts = ["## 影响范围\n", "### 业务影响\n"]
    parts.append(_render_blocks(impact.get("business_impact")) + "\n")
    parts.append("### 受影响功能\n")
    feature_rows = []
    for feature in _list(impact.get("affected_features")):
        feature = _dict(feature)
        feature_rows.append(
            [
                _cell(feature.get("feature")),
                _cell(feature.get("kind")),
                _cell(_join_repos(feature.get("repository_ids"), names)),
                _cell(_render_blocks(feature.get("description"))),
            ]
        )
    parts.append(_build_table(["既有功能", "影响类型", "涉及仓库", "影响描述"], feature_rows))
    parts.append("### 回归范围\n")
    regression_rows = []
    for scope in _list(impact.get("regression_scope")):
        scope = _dict(scope)
        regression_rows.append(
            [_cell(scope.get("area")), _cell(scope.get("level")), _cell(scope.get("reason"))]
        )
    parts.append(_build_table(["回归区域", "回归级别", "理由"], regression_rows))
    parts.append("### 兼容风险与回滚\n")
    parts.append(f"兼容风险：{_render_blocks(impact.get('compat_risks'))}\n")
    parts.append(f"回滚方案：{_render_blocks(impact.get('rollback_plan'))}\n")
    parts.extend(_citation_footnotes(impact, pool))
    return parts


def _section_interaction_flows(flows: list, pool: dict) -> list[str]:
    parts = ["## 交互流程\n"]
    if not flows:
        parts.append(_EMPTY + "\n")
    for flow in flows:
        flow = _dict(flow)
        parts.append(f"### {_text(flow.get('name'))}（{_text(flow.get('id'))}）\n")
        parts.append(f"触发条件：{_text(flow.get('trigger'))}\n")
        rows = []
        for step in _list(flow.get("steps")):
            step = _dict(step)
            rows.append(
                [
                    _cell(step.get("seq")),
                    _cell(step.get("actor")),
                    _cell(step.get("action")),
                    _cell(step.get("component")),
                    _cell(step.get("api_ref")),
                    _cell(step.get("data_in")),
                    _cell(step.get("data_out")),
                ]
            )
        parts.append(
            _build_table(["序号", "执行方", "动作", "组件", "接口", "输入数据", "输出数据"], rows)
        )
    parts.extend(_citation_footnotes(flows, pool))
    return parts


def _section_must_haves(must_haves: dict, pool: dict) -> list[str]:
    parts = ["## 验收锚点\n", "### 可观察行为断言\n"]
    truths = [str(item).strip() for item in _list(must_haves.get("truths")) if str(item).strip()]
    parts.append(("\n".join(f"- {truth}" for truth in truths) if truths else _EMPTY) + "\n")
    parts.append("### 必须存在的产物\n")
    artifact_rows = []
    for artifact in _list(must_haves.get("artifacts")):
        artifact = _dict(artifact)
        artifact_rows.append([_cell(artifact.get("path")), _cell(artifact.get("provides"))])
    parts.append(_build_table(["产物路径", "提供什么"], artifact_rows))
    parts.append("### 关键链接\n")
    link_rows = []
    for link in _list(must_haves.get("key_links")):
        link = _dict(link)
        link_rows.append([_cell(link.get("from")), _cell(link.get("to")), _cell(link.get("via"))])
    parts.append(_build_table(["从", "到", "经由"], link_rows))
    parts.extend(_citation_footnotes(must_haves, pool))
    return parts


def _section_decision_log(decision_log: list) -> list[str]:
    """⭐ 决策记录附录。

    ``decision_log`` 是**零约束裸 array**（schema `:733-736` 既不在顶层 required、也不进
    ``iter_blocks``）⇒ 114-04 写入的那组键是**约定不是契约**：逐项 ``.get`` 防御、缺键
    渲染占位符。**特别保 ``answer`` 与 ``applied_in_version``**——§3.13 的存在意义就是
    「文档自包含、导出不丢决策」，丢了这两个键等于把结论和它生效的版本一起丢了。
    """
    parts = ["## 决策记录\n"]
    rows = []
    for entry in decision_log:
        entry = _dict(entry)
        rows.append(
            [
                _cell(entry.get("question")),
                _cell(entry.get("answer")),
                _cell(entry.get("decided_by")),
                _cell(entry.get("applied_in_version")),
            ]
        )
    parts.append(_build_table(["问题", "结论", "决策人", "生效版本"], rows))
    return parts


def _section_citation_pool(pool: dict) -> list[str]:
    """引用清单：文档级引用池全量（含未被任何块引用的条目，⛔ 不丢）。"""
    parts = ["## 引用清单\n"]
    if not pool:
        parts.append(_EMPTY + "\n")
        return parts
    lines = [_citation_line(citation_id, pool) for citation_id in pool]
    parts.append("\n".join(lines) + "\n")
    return parts


# ── 唯一公开入口 ────────────────────────────────────────────────────────────


def blueprint_status_of(artifact: Any) -> str:
    """从 ``Artifact`` **读**出渲染用状态（缺失/空一律归一为空串）。

    两个权威面（导出端点 / ``ArtifactTimelineSerializer``）共用这一处读法，⛔ 不各写
    一份 ``getattr`` 归一——两份迟早会在「``None`` 算不算未确认」上分叉。

    ⚠️ 纯读、零写：状态的唯一写口仍是 ``BlueprintLifecycleService`` 的 CAS（INV-6）。
    """
    return str(getattr(artifact, "blueprint_status", "") or "")


def render_blueprint_markdown(content: dict, *, blueprint_status: str) -> str:
    """把 ``blueprint/v1`` content 渲染成一篇 markdown。

    Args:
        content: ``blueprint/v1`` 的 content dict（半可信：逐字段 ``.get`` 防御）。
        blueprint_status: ⭐ **必填 keyword-only、无默认值** —— 蓝图状态的真实取值。
            ``str(blueprint_status or "") ∉`` :data:`_SUPPRESS_WATERMARK_STATUSES` 时
            **无条件**在第一行渲染「未经确认」标注。⛔ **没有任何取值能关掉它**：白名单
            是闭合集合，空串与未知串都落在集合外。注册表分支拿不到状态只能传 ``""``，
            方向恰好是 fail-safe（当作未确认）。

    Returns:
        markdown 全文（未确认时首行为 ``> ⚠️ 未经确认 …``）。
    """
    data = _dict(content)
    meta = _dict(data.get("meta"))
    pool = _dict(data.get("citations"))
    status = str(blueprint_status or "")

    parts: list[str] = []
    # ⭐ 标注必须是 parts[0]：验收断言的是 ``rendered.splitlines()[0]``。
    if status not in _SUPPRESS_WATERMARK_STATUSES:
        parts.append(_build_watermark(meta, status))

    parts.append(f"# {_md_escape(_text(meta.get('title')))}\n")
    summary = _render_blocks(meta.get("summary"))
    if summary != _EMPTY:
        parts.append("## 执行摘要\n")
        parts.append(summary + "\n")

    associations = _list(data.get("repo_associations"))
    # 仓名映射先于四个引用仓库的段落建好：它们各自只有 `repository_id`，没有这张表就只能
    # 把 UUID 直接印进导出物（现状分析的三级标题、实现项/功能模块/API 契约/影响范围四张表）。
    names = _repo_names(associations)

    parts.extend(_section_requirement_spec(_dict(data.get("requirement_spec")), pool))
    parts.extend(_section_repo_associations(associations, pool))
    parts.extend(_section_current_state(_list(data.get("current_state_analysis")), pool, names))
    parts.extend(_section_implementation(_dict(data.get("implementation_overview")), pool, names))
    parts.extend(_section_api_contracts(_list(data.get("api_contracts")), pool, names))
    parts.extend(_section_impact(_dict(data.get("impact_analysis")), pool, names))
    parts.extend(_section_interaction_flows(_list(data.get("interaction_flows")), pool))
    parts.extend(_section_must_haves(_dict(data.get("must_haves")), pool))
    parts.extend(_section_decision_log(_list(data.get("decision_log"))))
    parts.extend(_section_citation_pool(pool))

    return "\n".join(parts)
