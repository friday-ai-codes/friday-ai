"""implementation 数据迁移命令测试。

验证 `migrate_coding_sessions_to_plans` 管理命令的以下行为：

- dry-run 不写 DB
- 基础回填 + 去重 (sha256(tech_plan) 同字符串共享一个 CodingPlan)
- 跨 conversation 不去重
- 空 tech_plan 走占位 plan
- 已 linked 的 session 被 skip
- idempotent
- --report 写 JSON 报告
"""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command

from chat.models import CodingPlan, CodingSession, Conversation

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _make_session(conversation, repository, tech_plan: str, **extra):
    return CodingSession.objects.create(
        conversation=conversation,
        repository=repository,
        tech_plan=tech_plan,
        affected_files=extra.pop(
            "affected_files",
            [{"file_path": "x.py", "change_type": "modify"}],
        ),
        **extra,
    )


@pytest.fixture
def conversation(db, project):
    return Conversation.objects.create(space=project, title="迁移测试对话")


@pytest.fixture
def second_conversation(db, project):
    return Conversation.objects.create(space=project, title="第二对话")


# ---------------------------------------------------------------------------
# 用例
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_command_dry_run_no_writes(conversation, repository):
    """dry-run 不写 DB：CodingPlan 计数 0、session.coding_plan_id 仍为 None。"""
    for i in range(3):
        _make_session(conversation, repository, f"## 方案 {i}")
    call_command("migrate_coding_sessions_to_plans", "--dry-run")
    assert CodingPlan.objects.count() == 0
    assert all(
        s.coding_plan_id is None for s in CodingSession.objects.all()
    )


@pytest.mark.django_db(transaction=True)
def test_command_basic_creates_plans(conversation, repository):
    """3 个不同 tech_plan 创建 3 个 CodingPlan 并全部回填关联。"""
    sessions = [
        _make_session(conversation, repository, f"## 方案 {i}") for i in range(3)
    ]
    call_command("migrate_coding_sessions_to_plans")
    assert CodingPlan.objects.count() == 3
    for s in sessions:
        s.refresh_from_db()
        assert s.coding_plan_id is not None


@pytest.mark.django_db(transaction=True)
def test_command_dedupes_same_tech_plan(conversation, repository):
    """同一 conversation 下两个 session 共享同一 tech_plan → 1 个 plan。

    implementation 新增 partial unique 约束后，同 (plan, repo) 不允许 2 个
    active session。本用例下两个 session 默认都是 draft，迁移命令检测到第二个
    会触发约束，于是按 "conflicted" 分支跳过链接（不污染 DB）。第一个 session
    仍正常关联到同一 plan。
    """
    s1 = _make_session(conversation, repository, "## 同样的方案")
    s2 = _make_session(conversation, repository, "## 同样的方案")
    call_command("migrate_coding_sessions_to_plans")
    assert CodingPlan.objects.count() == 1
    s1.refresh_from_db()
    s2.refresh_from_db()
    # 第一个 session 关联成功
    assert s1.coding_plan_id is not None
    # 第二个 session 因 unique_active_plan_repo 冲突被跳过，未被覆盖
    assert s2.coding_plan_id is None


@pytest.mark.django_db(transaction=True)
def test_command_isolates_per_conversation(conversation, second_conversation, repository):
    """两个 conversation 各 1 个 session 但 tech_plan 完全相同 → 2 个独立 plan。"""
    s1 = _make_session(conversation, repository, "## 相同方案文本")
    s2 = _make_session(second_conversation, repository, "## 相同方案文本")
    call_command("migrate_coding_sessions_to_plans")
    assert CodingPlan.objects.count() == 2
    s1.refresh_from_db()
    s2.refresh_from_db()
    assert s1.coding_plan_id != s2.coding_plan_id


@pytest.mark.django_db(transaction=True)
def test_command_placeholder_for_empty_tech_plan(conversation, repository):
    """空 tech_plan 走占位路径并复用同一占位 plan。

    同 (placeholder_plan, repo) 上同时只能 1 个 active
    session。第一个 session 链接成功，第二个走 "conflicted" 分支跳过。
    """
    s1 = _make_session(conversation, repository, "")
    s2 = _make_session(conversation, repository, "")
    call_command("migrate_coding_sessions_to_plans")
    plans = list(CodingPlan.objects.all())
    assert len(plans) == 1
    placeholder = plans[0]
    assert placeholder.title == "占位方案（无技术方案文本）"
    s1.refresh_from_db()
    s2.refresh_from_db()
    assert s1.coding_plan_id == placeholder.id
    # work item 冲突跳过：s2 未被链接
    assert s2.coding_plan_id is None


@pytest.mark.django_db(transaction=True)
def test_command_skips_already_linked_sessions(conversation, repository, capsys):
    """已 coding_plan_id 的 session 不被覆盖，统计为 skipped。"""
    pre_plan = CodingPlan.objects.create(
        conversation=conversation,
        tech_plan="pre",
        affected_files=[],
    )
    s = _make_session(conversation, repository, "## 不会用到")
    s.coding_plan = pre_plan
    s.save(update_fields=["coding_plan"])

    call_command("migrate_coding_sessions_to_plans")
    s.refresh_from_db()
    assert s.coding_plan_id == pre_plan.id
    # 没有新建 plan（pre 已存在）
    assert CodingPlan.objects.count() == 1
    captured = capsys.readouterr()
    assert "跳过" in captured.out


@pytest.mark.django_db(transaction=True)
def test_command_is_idempotent(conversation, repository):
    """连续运行两次：第二次不再新建 / 不再 linked，全部 skipped。"""
    for i in range(2):
        _make_session(conversation, repository, f"## 方案 {i}")
    call_command("migrate_coding_sessions_to_plans")
    after_first = CodingPlan.objects.count()
    assert after_first == 2

    call_command("migrate_coding_sessions_to_plans")
    after_second = CodingPlan.objects.count()
    assert after_second == 2


@pytest.mark.django_db(transaction=True)
def test_command_writes_report_file(conversation, repository, tmp_path):
    """--report 路径写出可解析 JSON 含 session_id / plan_id / action。"""
    _make_session(conversation, repository, "## 方案 R1")
    report_path = tmp_path / "report.json"
    call_command(
        "migrate_coding_sessions_to_plans",
        f"--report={report_path}",
    )
    assert report_path.exists()
    parsed = json.loads(report_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    entry = parsed[0]
    assert {"session_id", "plan_id", "action"} <= set(entry.keys())
    assert entry["action"] in {"linked", "created"}
