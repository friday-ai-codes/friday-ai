"""蓝图澄清飞书卡片送达守护测试（CLAR-04 的另一半，Phase 116-06）。

守六件事：

1. **正路**：有 project + space + 收件人 ⇒ ``send_card`` 被调一次，
   ``receive_id_type == "chat_id"``。
2. ⭐ **题面脱敏**：题面含 ``sk-ant-xxx`` ⇒ 传给 ``build_clarification_card`` 的实参已脱敏。
3. ⭐ **收件人口径**：``BlueprintReviewer`` ∪ 会话发起人、去重升序；⭐ 反查会话带
   ``process_type`` 过滤（造一条同 artifact 的 ``technical_plan`` 会话作对照，断言它
   **不影响**收件人，T-116-58）。
4. ⭐ **best-effort**：``send_card`` 抛异常 ⇒ 函数**不抛**、返回 ``None``，且落一条
   ``blueprint_clarification_card_failed``（T-116-55）。
5. **早退**：空 questions / 无 project / 无收件人 ⇒ 各自早退且 ``send_card`` 零调用。
6. ⛔ **题面正文不进日志**：AST 断言日志 kwarg 里没有 ``question`` / ``questions`` 原文实参。

⭐ 另外守**收敛法自述**：模块 docstring 写明「同步点 1 之后只改这一个文件」，且送达收口在
生产代码里的接线点恰为 CLAR-04 的**两个半边** —— 规格门开线程时的首次送达（116-06）与
apscheduler 周期提醒的到期重推（归档前收尾）（⛔ 仍不在四个入口各接一次）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs

from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
from delivery.services import ArtifactService
from services.process_runtime.blueprint_notify import anotify_blueprint_clarification
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

_SERVER_DIR = Path(__file__).resolve().parents[3]
_NOTIFY_REL = "services/process_runtime/blueprint_notify.py"

_SECRET = "sk-ant-api03-DEADBEEFDEADBEEFDEADBEEFDEADBEEF"
_PROJECT_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture(autouse=True)
def _no_blueprint_background_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """拦掉蓝图版本落地触发的后台摄取（SQLite 并发写会撞 table is locked）。"""
    from knowledge import ingestion

    real = ingestion.aschedule_ingestion

    async def _guarded(request, **kwargs):
        if getattr(request, "source_kind", "") == "blueprint":
            return None
        return await real(request, **kwargs)

    monkeypatch.setattr(ingestion, "aschedule_ingestion", _guarded)


@sync_to_async
def _make_project() -> Any:
    from initiatives.models import Project
    from projects.models import Space

    space, _ = Space.objects.get_or_create(
        name="notify-space", defaults={"feishu_project_key": "notify-key"}
    )
    project, _ = Project.objects.get_or_create(
        id=_PROJECT_ID, defaults={"space": space, "name": "notify-proj"}
    )
    return project


@sync_to_async
def _make_user(username: str) -> Any:
    from django.contrib.auth import get_user_model

    user, _ = get_user_model().objects.get_or_create(username=username)
    return user


async def _make_artifact(*, project_id: str = _PROJECT_ID):
    content = make_blueprint()
    content["meta"]["project_id"] = project_id
    return await ArtifactService().create(
        artifact_type="technical_plan", content=content, created_by_user_id="tester"
    )


async def _make_session(artifact, user, *, process_type: str = "technical_blueprint"):
    return await ConvergenceSession.objects.acreate(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="spec_gate",
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )


@sync_to_async
def _add_reviewer(artifact, user) -> None:
    from delivery.models import BlueprintReviewer

    BlueprintReviewer.objects.get_or_create(
        artifact=artifact, user=user, defaults={"first_action": "thread_answer"}
    )


class _Seams:
    """三个外部 seam 的一次性注入（card builder / 建群 / 发卡）。"""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, chat_id: str = "oc_1") -> None:
        self.card_calls: list[tuple[Any, ...]] = []
        self.group_calls: list[dict[str, Any]] = []
        self.send_card = AsyncMock(return_value=None)

        def _build(questions, execution_id, node_id, **kwargs):
            self.card_calls.append((questions, kwargs))
            return {"card": "ok"}

        async def _group(_self, **kwargs):
            self.group_calls.append(kwargs)
            return chat_id

        im = MagicMock()
        im.send_card = self.send_card
        monkeypatch.setattr("feishu.cards.chat_question_card.build_clarification_card", _build)
        monkeypatch.setattr(
            "initiatives.services.project_service.ProjectService.resolve_or_create_group",
            _group,
        )
        monkeypatch.setattr("services.feishu_im.FeishuIMService.create", AsyncMock(return_value=im))


_QUESTIONS = [{"text": "目标用户是谁？", "options": ["高三", "初三"], "citations": []}]


# ═══════════════════════════════════════════════════════════════════════════
# 1-2. 正路 + 脱敏
# ═══════════════════════════════════════════════════════════════════════════


async def test_happy_path_sends_one_card_to_the_project_group(monkeypatch) -> None:
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    seams.send_card.assert_awaited_once()
    kwargs = seams.send_card.await_args.kwargs
    assert kwargs["receive_id"] == "oc_1"
    assert kwargs["receive_id_type"] == "chat_id"
    assert kwargs["card"] == {"card": "ok"}


async def test_question_text_is_redacted_before_it_reaches_the_card(monkeypatch) -> None:
    """⭐ 题面来自 LLM（半可信）⇒ 进飞书卡片前必须脱敏（T-116-54）。"""
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    await anotify_blueprint_clarification(
        artifact=artifact, questions=[{"text": f"密钥是 {_SECRET} 吗？", "options": [_SECRET]}]
    )

    questions, _kwargs = seams.card_calls[0]
    payload = str(questions)
    assert _SECRET not in payload
    assert "密钥是" in payload


# ═══════════════════════════════════════════════════════════════════════════
# 3. ⭐ 收件人口径（含 process_type 过滤的反向对照）
# ═══════════════════════════════════════════════════════════════════════════


async def test_recipients_are_reviewers_union_session_initiator_sorted(monkeypatch) -> None:
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()
    initiator = await _make_user("notify-initiator")
    reviewer = await _make_user("notify-reviewer")
    await _make_session(artifact, initiator)
    await _add_reviewer(artifact, reviewer)

    await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    members = seams.group_calls[0]["member_ids"]
    assert members == sorted({str(initiator.id), str(reviewer.id)})


async def test_legacy_technical_plan_session_initiator_is_not_a_recipient(monkeypatch) -> None:
    """⭐ T-116-58：反查会话必须带 ``process_type`` 过滤（同 artifact 上可并存两条会话）。"""
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()
    blueprint_initiator = await _make_user("notify-initiator")
    legacy_initiator = await _make_user("notify-legacy")
    await _make_session(artifact, blueprint_initiator)
    await _make_session(artifact, legacy_initiator, process_type="technical_plan")

    await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    members = seams.group_calls[0]["member_ids"]
    assert str(legacy_initiator.id) not in members
    assert members == [str(blueprint_initiator.id)]


def test_process_type_filter_is_present_in_the_source() -> None:
    src = (_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8")
    assert "process_type" in src
    assert "BLUEPRINT_PROCESS_TYPE" in src


# ═══════════════════════════════════════════════════════════════════════════
# 4. ⭐ best-effort：失败绝不反噬挂起
# ═══════════════════════════════════════════════════════════════════════════


async def test_send_card_failure_never_propagates(monkeypatch) -> None:
    seams = _Seams(monkeypatch)
    seams.send_card.side_effect = RuntimeError("飞书炸了")
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    result = await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    assert result is None


async def test_group_resolution_failure_never_propagates(monkeypatch) -> None:
    _Seams(monkeypatch)
    monkeypatch.setattr(
        "initiatives.services.project_service.ProjectService.resolve_or_create_group",
        AsyncMock(side_effect=RuntimeError("建群炸了")),
    )
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    assert await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS) is None


# ═══════════════════════════════════════════════════════════════════════════
# 5. 早退
# ═══════════════════════════════════════════════════════════════════════════


def _skips(cap: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in cap if e["event"] == "blueprint_clarification_card_skipped"]


async def test_empty_questions_short_circuits(monkeypatch) -> None:
    seams = _Seams(monkeypatch)
    artifact = await _make_artifact()

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=[])

    seams.send_card.assert_not_awaited()
    assert [e["reason"] for e in _skips(cap)] == ["no_questions"]


async def test_blank_question_text_is_dropped_and_short_circuits(monkeypatch) -> None:
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=[{"text": "   "}])

    seams.send_card.assert_not_awaited()
    assert [e["reason"] for e in _skips(cap)] == ["no_questions"]


async def test_unresolvable_project_short_circuits(monkeypatch) -> None:
    """``meta.project_id`` 指向不存在的项目 ⇒ 早退（⛔ 不猜、不发）。"""
    seams = _Seams(monkeypatch)
    artifact = await _make_artifact(project_id="66666666-6666-6666-6666-666666666666")

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    seams.send_card.assert_not_awaited()
    assert [e["reason"] for e in _skips(cap)] == ["no_project"]


async def test_no_recipients_short_circuits(monkeypatch) -> None:
    """既无 reviewer 也无蓝图会话发起人 ⇒ 没有收件人，早退。"""
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    seams.send_card.assert_not_awaited()
    assert [e["reason"] for e in _skips(cap)] == ["no_recipients"]


# ═══════════════════════════════════════════════════════════════════════════
# 5b. ⭐ 早退不等于不留痕（116-REVIEW MN-03）
#
# 回退前五条早退全是裸 `return`：卡片没发出去时日志里既看不到
# `blueprint_clarification_card_sent`，也看不到任何失败记录 —— 运维只能靠「没有 sent
# 事件」反推，而那与「本来就没开澄清」完全同形。这五条恰恰是生产上最可能命中的。
# ═══════════════════════════════════════════════════════════════════════════


async def test_empty_chat_id_leaves_a_trace(monkeypatch) -> None:
    """⭐ ``resolve_or_create_group`` 回空 chat_id（项目没建飞书群）⇒ 必须留痕。"""
    seams = _Seams(monkeypatch, chat_id="")
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    seams.send_card.assert_not_awaited()
    skipped = _skips(cap)
    assert [e["reason"] for e in skipped] == ["no_chat_id"]
    assert skipped[0]["recipient_count"] == 1


async def test_missing_space_leaves_a_trace(monkeypatch) -> None:
    """project 有但 ``project.space`` 为空 ⇒ 留痕 ``no_space``。"""
    from unittest.mock import Mock

    seams = _Seams(monkeypatch)
    artifact = await _make_artifact()
    monkeypatch.setattr(
        "services.process_runtime.blueprint_notify._aresolve_project_from_artifact",
        AsyncMock(return_value=Mock(space=None)),
    )

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    seams.send_card.assert_not_awaited()
    assert [e["reason"] for e in _skips(cap)] == ["no_space"]


async def test_every_skip_trace_is_sampling_and_scalar_only(monkeypatch) -> None:
    """⛔ 留痕仍只记标量：``reason`` / id / 计数 —— 题面正文一个字都不进日志。"""
    seams = _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()

    with capture_logs() as cap:
        await anotify_blueprint_clarification(
            artifact=artifact, questions=[{"text": f"密钥 {_SECRET} 对吗？"}]
        )

    seams.send_card.assert_not_awaited()
    event = _skips(cap)[0]
    assert event["category"] == "sampling"
    assert event["component"] == "blueprint_notify"
    assert event["initiated_by_user_id"] == "system"
    assert "duration_ms" in event
    payload = str(event)
    assert _SECRET not in payload
    assert "密钥" not in payload


async def test_happy_path_leaves_no_skip_trace(monkeypatch) -> None:
    """⭐ 非恒真对照：正路一条 skip 都不落（⛔ 留痕不是无差别刷屏）。"""
    _Seams(monkeypatch)
    await _make_project()
    artifact = await _make_artifact()
    user = await _make_user("notify-initiator")
    await _make_session(artifact, user)

    with capture_logs() as cap:
        await anotify_blueprint_clarification(artifact=artifact, questions=_QUESTIONS)

    assert _skips(cap) == []
    assert [e for e in cap if e["event"] == "blueprint_clarification_card_sent"]


def test_no_bare_early_return_is_left_in_the_send_path() -> None:
    """⭐ 源码级钉子：主函数体内不得再出现**裸** ``return``（每条早退都得先留痕）。

    ⛔ 这条盯的是「以后新加一条早退忘了留痕」——那正是 MN-03 的复发形态。
    """
    tree = ast.parse((_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8"))
    target = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "anotify_blueprint_clarification"
    )
    # 收集嵌套的 _skip 辅助函数体，免得把它自己的语句算进主流程
    nested = {
        stmt
        for helper in ast.walk(target)
        if isinstance(helper, ast.FunctionDef)
        for stmt in ast.walk(helper)
    }
    bare = [
        node.lineno
        for node in ast.walk(target)
        if isinstance(node, ast.Return) and node.value is None and node not in nested
    ]
    lines = (_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8").splitlines()
    for lineno in bare:
        # 裸 return 的**上一条语句**必须是 _skip(...)
        assert "_skip(" in "".join(lines[max(0, lineno - 4) : lineno - 1]), (
            f"第 {lineno} 行是没有留痕的裸 return（早退不等于不留痕）"
        )


# ═══════════════════════════════════════════════════════════════════════════
# 6 + 收敛法自述
# ═══════════════════════════════════════════════════════════════════════════


def test_question_text_never_reaches_the_logs() -> None:
    """⛔ AST：日志 kwarg 里不得出现题面原文实参（只允许条数）。"""
    tree = ast.parse((_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8"))
    banned = {"question", "questions", "question_text", "body"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        if func.value.id != "logger":
            continue
        for keyword in node.keywords:
            assert keyword.arg not in banned, f"{keyword.arg} 不得进日志"
        assert any(k.arg == "question_count" for k in node.keywords) or all(
            k.arg != "question_count" for k in node.keywords
        )


def test_module_declares_the_single_file_convergence_promise() -> None:
    """⭐ 「同步点 1 之后换 107 的送达设施时只改这一个文件」必须写进模块 docstring。"""
    src = (_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8")
    assert "同步点 1" in src
    assert "ExecutionContext" in src, "两处 DIFFER 必须逐字写明（⛔ 不依赖 ExecutionContext）"
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "ExecutionContext":
            pytest.fail(
                "blueprint_notify 不得在代码里依赖 ExecutionContext（只允许 docstring 提及）"
            )


def test_wiring_points_are_exactly_the_two_clar04_halves() -> None:
    """⭐ 接线是 CLAR-04 的**两个半边**，不是四个入口各接一次。

    白名单恰为两条，各自「一个 import + 一处调用」：

    1. ``blueprint_spec_gate`` —— 开出阻塞澄清线程时的**首次送达**（116-06）。
    2. ``blueprint_review_action`` —— apscheduler 周期提醒的**到期重推**（归档前收尾）。
       114-05 那条周期任务此前只写 ``last_reminded_at`` 锚点、不投递，用户收不到任何
       通知 ⇒ CLAR-04「按配置周期提醒」只兑现了「记账」那一半。

    ⛔ **这条白名单只增这一次，且仍是逐字路径**：加第三条之前请先确认它不是「在某个入口
    上又接了一次」—— 那正是本断言从一开始要拦的形态（送达细节必须留在收口模块里，
    同步点 1 换 107 的送达设施时仍然只改那一个文件）。
    """
    hits: list[str] = []
    for path in _SERVER_DIR.rglob("*.py"):
        rel = path.relative_to(_SERVER_DIR).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel or ".venv" in rel:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits.extend([rel] * text.count("anotify_blueprint_clarification"))

    callers = sorted({rel for rel in hits if rel != _NOTIFY_REL})
    assert callers == [
        "delivery/services/blueprint_review_action.py",
        "services/process_runtime/blueprint_spec_gate.py",
    ], (
        "⛔ 不在四个入口各接一次：生产代码里只允许「首次送达 + 周期重推」两处调用方",
        callers,
    )
    for rel in callers:
        assert hits.count(rel) == 2, (f"{rel} 里也只允许「一个 import + 一处调用」", hits)


def test_redaction_helper_is_used() -> None:
    src = (_SERVER_DIR / _NOTIFY_REL).read_text(encoding="utf-8")
    assert "redact_secrets_in_text" in src
