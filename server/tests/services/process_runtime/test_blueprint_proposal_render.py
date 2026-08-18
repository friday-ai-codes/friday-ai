"""分仓 OpenSpec Proposal 渲染器用例。

守九件事：

1. 每个 ``repo_associations`` 仓都出一个 ``### 仓名（角色）`` 三级块。
2. 四个加粗标签（Why / What Changes / Impact / Spec Deltas）逐仓都在。
3. direct 仓的 What Changes 落该仓的实现项（标题 + 变更类型 + 涉及文件）。
4. indirect 仓无实现项时 What Changes 落「本方案不改动此仓」，⛔ 不留白。
5. Spec Deltas 只吃**经本仓 items 的 feature_point_id 归属到本仓**的功能点。
6. 意图 → delta 类别：greenfield=ADDED / brownfield=MODIFIED。
7. test_cases 的 given_when_then 渲染成 WHEN/THEN 嵌套列表。
8. ⭐ 版式 heading ≤3 级（飞书 markdown_to_blocks 上界）。
9. ⭐ 主渲染器把本章节并入主 markdown（分仓方案不再「看不见」）。
"""

from __future__ import annotations

from services.process_runtime.blueprint_proposal_render import (
    render_repo_proposals_markdown,
    render_single_repo_proposal_markdown,
)
from services.process_runtime.blueprint_render import render_blueprint_markdown
from tests.helpers.blueprint_samples import make_blueprint


def test_every_repo_gets_a_proposal_block_with_role() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    assert "## 分仓方案（OpenSpec Proposal）" in rendered
    assert "### onion-practice（直接改动）" in rendered
    assert "### study-app（直接改动）" in rendered
    assert "### study-course（间接依赖）" in rendered


def test_all_four_openspec_labels_present_per_repo() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    # 三仓 × 四标签，各标签至少出现三次。
    for label in ("**Why**", "**What Changes**", "**Impact**", "**Spec Deltas**"):
        assert rendered.count(label) >= 3, label


def test_direct_repo_what_changes_lists_impl_items() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    assert "新建 `新增习题生成接口`" in rendered
    assert "改动 `练习页接入生成入口`" in rendered
    # 涉及文件带动作标注。
    assert "src/api/generate.py[create]" in rendered
    assert "def generate(chapter_id)" in rendered
    assert "依赖实现项：impl_01" in rendered
    assert "测试策略：接口级用例覆盖生成成功与超时降级" in rendered
    assert "既有集成：与既有练习提交链路共用结果组件" in rendered


def test_direct_repo_what_changes_lists_apis() -> None:
    blueprint = make_blueprint()
    blueprint["api_contracts"][0]["request_schema"] = {
        "type": "object",
        "required": ["chapter_id"],
    }
    rendered = render_repo_proposals_markdown(blueprint)
    assert "提供接口 `POST /api/practice/generate`" in rendered
    assert "消费接口 `GET /api/course/chapters`" in rendered
    assert "说明：按章节与难度生成习题列表" in rendered
    assert '"required":["chapter_id"]' in rendered
    assert "所需字段：chapter_id、knowledge_points" in rendered


def test_indirect_repo_lists_used_capabilities() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    assert "被引用能力 `章节目录接口`" in rendered


def test_indirect_repo_without_anything_notes_no_change() -> None:
    """真正零内容的 indirect 仓（无实现项/契约/能力）落「本方案不改动此仓」，⛔ 不留白。"""
    blueprint = make_blueprint()
    # 去掉该 indirect 仓的能力清单，构造纯占位 indirect。
    blueprint["repo_associations"][2].pop("capabilities_used", None)
    rendered = render_repo_proposals_markdown(blueprint)
    assert "本方案不改动此仓（作为间接依赖被引用）" in rendered


def test_spec_deltas_map_intent_to_delta_kind() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    # fp_01 greenfield（归属 repo-backend）→ ADDED；fp_02 brownfield（归属 repo-frontend）→ MODIFIED。
    assert "ADDED · 需求「习题生成接口」（fp_01）" in rendered
    assert "MODIFIED · 需求「练习页生成入口」（fp_02）" in rendered
    assert "需求说明：后端提供按知识点生成习题的接口" in rendered
    assert "SHALL：POST /api/practice/generate 返回习题列表" in rendered


def test_spec_deltas_render_given_when_then_scenarios() -> None:
    blueprint = make_blueprint()
    blueprint["requirement_spec"]["feature_points"][0]["test_cases"] = [
        {
            "name": "生成成功",
            "given_when_then": {
                "given": "已选章节",
                "when": "点击生成",
                "then": "返回习题列表",
            },
        }
    ]
    rendered = render_repo_proposals_markdown(blueprint)
    assert "Scenario 场景「生成成功」" in rendered
    assert "GIVEN 已选章节" in rendered
    assert "WHEN 点击生成" in rendered
    assert "THEN 返回习题列表" in rendered


def test_headings_never_exceed_level_three() -> None:
    rendered = render_repo_proposals_markdown(make_blueprint())
    for line in rendered.splitlines():
        if line.startswith("#"):
            assert len(line) - len(line.lstrip("#")) <= 3, line


def test_empty_associations_return_empty_string() -> None:
    assert render_repo_proposals_markdown({"repo_associations": []}) == ""
    assert render_repo_proposals_markdown({}) == ""
    assert render_repo_proposals_markdown(None) == ""


def test_single_repo_proposal_contains_only_requested_repository() -> None:
    rendered = render_single_repo_proposal_markdown(make_blueprint(), "repo-backend")
    assert "### onion-practice（直接改动）" in rendered
    assert "新增习题生成接口" in rendered
    assert "练习页接入生成入口" not in rendered
    assert "study-app" not in rendered
    assert "## 分仓方案（OpenSpec Proposal）" not in rendered


def test_single_repo_proposal_missing_repository_returns_empty() -> None:
    blueprint = make_blueprint()
    assert render_single_repo_proposal_markdown(blueprint, "") == ""
    assert render_single_repo_proposal_markdown(blueprint, "missing") == ""


def test_main_renderer_embeds_the_repo_proposals_section() -> None:
    """⭐ 分仓方案并入主技术方案文档：主渲染器输出里带本章节。"""
    rendered = render_blueprint_markdown(make_blueprint(), blueprint_status="confirmed")
    assert "## 分仓方案（OpenSpec Proposal）" in rendered
    assert "### onion-practice（直接改动）" in rendered
    # 版式：全篇 heading 仍 ≤3 级（新章节没有引入 #### 及以上）。
    for line in rendered.splitlines():
        if line.startswith("#"):
            assert len(line) - len(line.lstrip("#")) <= 3, line
