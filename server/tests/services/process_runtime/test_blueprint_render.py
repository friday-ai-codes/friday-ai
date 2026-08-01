"""蓝图 markdown 渲染器用例（Phase 116-05，VIEW-05）。

守十件事：

1. ⭐ ``inspect.signature`` 参数名集合**恰为** ``{content, blueprint_status}``，且
   ``blueprint_status`` 是 KEYWORD_ONLY 且无默认值 —— 这是「标注不可关闭」唯一可机器
   验的形式：任何人加 ``include_watermark`` 之流即转红。
2. 抑制白名单三态**不出**标注（字面量取自 ``BlueprintStatus``，两侧成员相同）。
3. ⭐ 其余一切取值（其余八态 + ``""`` + 未知串 + ``None``）**都出**标注。
4. 标注在**第一行**。
5. ⭐ 白名单是闭合集合：去掉任一成员，对应用例即转红（变异实跑记录见 SUMMARY）。
6. ``decision_log`` 缺键渲染占位符且不抛；七键齐全时 ``answer`` 与 ``applied_in_version``
   都出现在输出里。
7. ``citations`` 取不到链接落 ``quote`` 快照，⛔ 不留白。
8. ⭐ 块取文本按 ``text`` → ``code.source`` → ``rows`` 的**字段优先级**，⛔ 不按块类型分派。
9. 批注天然不出现（content 里本就没有），且源码零过滤死码。
10. ⭐ **两个面都带标注**：注册表路径（传 ``""``）出标注；``ArtifactTimelineSerializer``
    传真实状态 —— ``confirmed`` 不出标注且六段结构在（⛔ 不是 v0 空壳）、``pending_review``
    出标注。
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from delivery.models import BlueprintStatus
from services.process_runtime.blueprint_render import (
    _SUPPRESS_WATERMARK_STATUSES,
    render_blueprint_markdown,
)
from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION

_WATERMARK_TOKEN = "未经确认"

_RENDER_MODULE = (
    Path(__file__).resolve().parents[3] / "services/process_runtime/blueprint_render.py"
)


def _block(block_id: str, text: str) -> dict:
    return {"block_id": block_id, "type": "paragraph", "text": text}


def _content(**overrides) -> dict:
    """一份结构完整的 ``blueprint/v1`` content（各段至少一条真实数据）。"""
    content = {
        "schema_version": BLUEPRINT_SCHEMA_VERSION,
        "meta": {"title": "订单导出蓝图", "project_id": "p-1"},
        "requirement_spec": {
            "goal": [_block("b1", "让订单可导出为飞书文档")],
            "background": [_block("b2", "现状是只能截图")],
            "feature_points": [
                {
                    "id": "fp_1",
                    "title": "导出按钮",
                    "intent": "greenfield",
                    "acceptance_criteria": ["点击后生成文档"],
                    "citations": ["c_link"],
                }
            ],
        },
        "repo_associations": [
            {
                "repository_id": "r-1",
                "repository_name": "friday-server",
                "role": "direct",
                "responsibility": [_block("b3", "提供导出端点")],
            }
        ],
        "current_state_analysis": [
            {
                "repository_id": "r-1",
                "summary": [_block("b4", "已有飞书文档 client")],
                "findings": [
                    {
                        "id": "cs_1",
                        "text": [_block("b5", "create_document 可复用")],
                        "kind": "capability",
                        "citations": ["c_quote"],
                    }
                ],
            }
        ],
        "implementation_overview": {
            "requirement_narrative": [_block("b6", "渲染器 + 端点两步")],
            "modules": [{"id": "mod_1", "name": "导出模块", "repository_ids": ["r-1"]}],
            "items": [
                {
                    "id": "impl_1",
                    "feature_point_id": "fp_1",
                    "repository_id": "r-1",
                    "change_type": "create",
                    "title": "新建渲染器",
                    "how": [_block("b7", "十段全量渲染")],
                    "files_touched": [{"path": "blueprint_render.py", "action": "create"}],
                }
            ],
        },
        "api_contracts": [
            {
                "id": "api_1",
                "name": "导出到飞书",
                "kind": "http",
                "direction": "provided",
                "method": "POST",
                "path": "/blueprint/export-feishu/",
                "description": [_block("b8", "返回文档 id 与 url")],
            }
        ],
        "impact_analysis": {
            "business_impact": [_block("b9", "评审可直接分享文档")],
            "affected_features": [{"feature": "时间线摘要", "kind": "behavior_change"}],
        },
        "interaction_flows": [
            {
                "id": "flow_1",
                "name": "用户导出流程",
                "steps": [{"seq": 1, "actor": "user", "action": "点击导出"}],
            }
        ],
        "must_haves": {
            "truths": ["未确认版本导出物首行带标注"],
            "artifacts": [{"path": "blueprint_render.py", "provides": "渲染器"}],
            "key_links": [{"from": "端点", "to": "渲染器", "via": "真实状态"}],
        },
        "citations": {
            "c_link": {
                "citation_id": "c_link",
                "source_type": "url",
                "title": "飞书文档 API",
                "source_id": "https://open.feishu.cn/document",
            },
            "c_quote": {
                "citation_id": "c_quote",
                "source_type": "repo_file",
                "quote": "async def create_document(self, title, folder_token, content)",
            },
        },
    }
    content.update(overrides)
    return content


# ── 1. 签名不变量（标注不可关闭的唯一机器验形式）────────────────────────────


def test_signature_parameter_names_are_exactly_content_and_status() -> None:
    parameters = inspect.signature(render_blueprint_markdown).parameters
    assert set(parameters) == {"content", "blueprint_status"}


def test_blueprint_status_is_required_keyword_only() -> None:
    parameter = inspect.signature(render_blueprint_markdown).parameters["blueprint_status"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty, "必填无默认值：调用方无法省略"


def test_no_boolean_switch_parameter_exists() -> None:
    """⛔ 零布尔开关：给了早晚有人传 False。"""
    source = _RENDER_MODULE.read_text(encoding="utf-8")
    for banned in ("include_watermark", "show_watermark", "with_watermark", "skip_watermark"):
        assert banned not in source, f"⛔ 不得引入开关参数：{banned}"


# ── 2-4. 闭合白名单：白名单内不出、白名单外一律出，且在第一行 ────────────────


def test_whitelist_literals_match_blueprint_status_enum() -> None:
    """前后端与模型三处的白名单必须是同一组字面量。"""
    assert _SUPPRESS_WATERMARK_STATUSES == frozenset(
        {
            BlueprintStatus.CONFIRMED.value,
            BlueprintStatus.IMPLEMENTING.value,
            BlueprintStatus.IMPLEMENTED.value,
        }
    )


@pytest.mark.parametrize(
    "status",
    [
        BlueprintStatus.CONFIRMED.value,
        BlueprintStatus.IMPLEMENTING.value,
        BlueprintStatus.IMPLEMENTED.value,
    ],
)
def test_confirmed_statuses_have_no_watermark(status: str) -> None:
    assert _WATERMARK_TOKEN not in render_blueprint_markdown(_content(), blueprint_status=status)


@pytest.mark.parametrize(
    "status",
    [
        BlueprintStatus.RESEARCHING.value,
        BlueprintStatus.DRAFTING.value,
        BlueprintStatus.AI_REVIEWING.value,
        BlueprintStatus.NEEDS_CLARIFICATION.value,
        BlueprintStatus.PENDING_REVIEW.value,
        BlueprintStatus.ARCHIVED.value,
        BlueprintStatus.FAILED.value,
        BlueprintStatus.SUPERSEDED.value,
        "",
        "totally_unknown",
        None,
    ],
)
def test_every_other_status_renders_the_watermark(status) -> None:
    """⭐ 没有任何取值能关掉标注 —— 含空串与未知串。"""
    rendered = render_blueprint_markdown(_content(), blueprint_status=status)
    assert _WATERMARK_TOKEN in rendered


def test_watermark_is_the_first_line() -> None:
    rendered = render_blueprint_markdown(_content(), blueprint_status="pending_review")
    first_line = rendered.splitlines()[0]
    assert first_line.startswith("> ⚠️ 未经确认")
    assert "pending_review" in first_line


def test_watermark_absent_status_falls_back_to_unknown_label() -> None:
    """空串也要有可读的状态文案，⛔ 不留白。"""
    rendered = render_blueprint_markdown(_content(), blueprint_status="")
    assert "当前状态：未知" in rendered.splitlines()[0]


# ── 5. 十段全量 ──────────────────────────────────────────────────────────────


def test_all_sections_are_rendered() -> None:
    rendered = render_blueprint_markdown(_content(), blueprint_status="confirmed")
    for heading in (
        "# 订单导出蓝图",
        "## 需求规格",
        "## 仓库关联",
        "## 现状分析",
        "## 实现概述",
        "## API 契约",
        "## 影响范围",
        "## 交互流程",
        "## 验收锚点",
        "## 决策记录",
        "## 引用清单",
    ):
        assert heading in rendered, heading
    # 各段的真实数据都在（⛔ 不是只有骨架标题）
    for token in (
        "让订单可导出为飞书文档",
        "friday-server",
        "create_document 可复用",
        "新建渲染器",
        "/blueprint/export-feishu/",
        "时间线摘要",
        "用户导出流程",
        "未确认版本导出物首行带标注",
    ):
        assert token in rendered, token


def test_headings_never_exceed_level_three() -> None:
    """版式保守（§C.4 A2）：heading ≤3 级、脚注用普通列表而非 [^n] 语法。"""
    rendered = render_blueprint_markdown(_content(), blueprint_status="confirmed")
    for line in rendered.splitlines():
        if line.startswith("#"):
            assert len(line) - len(line.lstrip("#")) <= 3, line
    assert "[^" not in rendered


# ── 6. decision_log 是零约束裸 array ────────────────────────────────────────


def test_decision_log_missing_keys_degrade_to_placeholder() -> None:
    rendered = render_blueprint_markdown(
        _content(decision_log=[{"question": "用哪个文件夹？"}]),
        blueprint_status="confirmed",
    )
    assert "用哪个文件夹？" in rendered
    assert "| —" in rendered


def test_decision_log_keeps_answer_and_applied_in_version() -> None:
    """§3.13 的存在意义就是「文档自包含、导出不丢决策」。"""
    entry = {
        "thread_id": "t-1",
        "question": "导出留痕写哪里？",
        "answer": "落 Interaction Ledger",
        "decided_at": "2026-08-01T00:00:00Z",
        "decided_by": "human",
        "applied_in_version": 7,
        "anchor": {"block_id": "b1"},
    }
    rendered = render_blueprint_markdown(
        _content(decision_log=[entry]), blueprint_status="confirmed"
    )
    assert "落 Interaction Ledger" in rendered
    assert "| 7 |" in rendered


# ── 7. 引用脚注 ─────────────────────────────────────────────────────────────


def test_citation_without_link_falls_back_to_quote_snapshot() -> None:
    rendered = render_blueprint_markdown(_content(), blueprint_status="confirmed")
    assert "async def create_document" in rendered
    assert "原文摘录" in rendered


def test_citation_with_link_renders_clickable_markdown_link() -> None:
    rendered = render_blueprint_markdown(_content(), blueprint_status="confirmed")
    assert "[飞书文档 API](https://open.feishu.cn/document)" in rendered


def test_citation_footnotes_use_plain_list_per_section() -> None:
    rendered = render_blueprint_markdown(_content(), blueprint_status="confirmed")
    assert rendered.count("**本段引用**") >= 2


# ── 8. 块取文本的字段优先级（与锚点坐标系同源）──────────────────────────────


def _rendered_goal(block: dict) -> str:
    content = _content()
    content["requirement_spec"]["goal"] = [block]
    return render_blueprint_markdown(content, blueprint_status="confirmed")


def test_block_text_priority_prefers_text_then_code_then_rows() -> None:
    assert "纯文本块" in _rendered_goal({"block_id": "x", "type": "paragraph", "text": "纯文本块"})
    assert "print(1)" in _rendered_goal(
        {"block_id": "x", "type": "pseudocode", "code": {"source": "print(1)"}}
    )
    assert "单元格甲" in _rendered_goal(
        {"block_id": "x", "type": "table", "rows": [["单元格甲", "单元格乙"]]}
    )


def test_block_without_any_text_field_degrades_silently() -> None:
    rendered = _rendered_goal({"block_id": "x", "type": "paragraph"})
    assert "## 需求规格" in rendered  # 不抛、不吞掉后续段落


def test_block_text_does_not_dispatch_on_block_type() -> None:
    """⭐ 证伪点：类别是 pseudocode 但有 text ⇒ **仍按 text 取**。"""
    rendered = _rendered_goal(
        {
            "block_id": "x",
            "type": "pseudocode",
            "text": "按字段优先级取到的文本",
            "code": {"source": "不应被取到"},
        }
    )
    assert "按字段优先级取到的文本" in rendered
    assert "不应被取到" not in rendered


# ── 9. 批注天然不出现，且⛔ 无过滤死码 ──────────────────────────────────────


def test_threads_never_appear_and_there_is_no_filter_dead_code() -> None:
    """``BlueprintThread`` 本就不在 content 里 ⇒ 渲染器只读 content 即天然满足。"""
    source = _RENDER_MODULE.read_text(encoding="utf-8")
    module_docstring = ast.get_docstring(ast.parse(source)) or ""
    code_only = source.replace(module_docstring, "", 1)
    assert "BlueprintThread" not in code_only, "⛔ 不得写过滤批注的死码"

    rendered = render_blueprint_markdown(_content(), blueprint_status="pending_review")
    assert "BlueprintThread" not in rendered


# ── 10. P-4 两个面（注册表 fail-safe / 时间线序列化器传真值）─────────────────


def test_registry_branch_passes_empty_status_and_keeps_the_watermark() -> None:
    """注册表签名拿不到状态 ⇒ 传 ``""`` ⇒ 当作未确认，标注**存在**。"""
    from delivery.artifacts.registry import render_markdown

    rendered = render_markdown("technical_plan", _content())
    assert rendered is not None
    assert rendered.splitlines()[0].startswith("> ⚠️ 未经确认")
    assert "## 需求规格" in rendered


def test_registry_branch_leaves_v0_content_untouched() -> None:
    """反向对照：无 ``schema_version`` 的 v0 content 走原渲染器，行为零变化。"""
    from delivery.artifacts.registry import render_markdown

    rendered = render_markdown("technical_plan", {"title": "旧链方案", "summary": "摘要"})
    assert rendered is not None
    assert _WATERMARK_TOKEN not in rendered
    assert "## 需求规格" not in rendered


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("status", "expects_watermark"),
    [("confirmed", False), ("pending_review", True)],
)
def test_timeline_serializer_passes_the_real_status(status: str, expects_watermark: bool) -> None:
    """⭐ P-4 的第二个面：该字段拿得到真实状态，且空壳被一并修掉。"""
    from delivery.api.artifact_serializers import ArtifactTimelineSerializer
    from delivery.models import Artifact, ArtifactVersion

    artifact = Artifact.objects.create(
        artifact_type="technical_plan", title="订单导出蓝图", blueprint_status=status
    )
    version = ArtifactVersion.objects.create(
        artifact=artifact, version_no=1, content=_content(), content_hash="h1"
    )
    artifact.current_version = version
    artifact.save(update_fields=["current_version"])

    markdown = ArtifactTimelineSerializer(artifact).data["current_version_markdown"]
    assert markdown is not None
    # ⛔ 不是 v0 空壳：六段结构真的在
    assert "## 需求规格" in markdown
    assert "## 交互流程" in markdown
    assert (_WATERMARK_TOKEN in markdown) is expects_watermark
