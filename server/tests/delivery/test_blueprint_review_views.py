"""阶段 4 人审七端点 REST 测试（Phase 114-05 Task 3，FLOW-07 / CLAR-03 / CLAR-04）。

守十四件事（断言一律**从 DB 重读**，不信响应体）：

1. ⭐ **鉴权第一条**：七端点未认证一律拒（401/403），无一例外（参数化七条）。
2. **只读快照**：无 artifact → 中性 404；有数据 → 200 且含 findings 分级分组（每条带
   ``thread_id``）/ 澄清线程 / **失锚列表** / 未决清单 / ``revision_round``。GET
   **不接续驱**，且 ⭐ **不触发提醒**（伪挂载点已移除）。
3. ⭐ **approve 有未决 BLOCKER → 409**，DB 重读状态仍 ``pending_review``（DB 不写）。
4. ⭐ **approve 清空后 → 200**，DB 重读 ``confirmed``，请求用户进 ``BlueprintReviewer``。
5. ⭐ **approve 无 TOCTOU**：源码扫描断言 View 内无预查询；行为侧在守卫查询发生的
   那一刻插入一条 ``open+blocking`` finding → 仍 409 且状态不变（对照组 200 ⇒ 非恒真）。
6. ⭐ **reject：先版本后状态**——版本 +1、``revision_round`` +1、``produced_by_ref`` 前缀
   正确、DB 重读 ``drafting``；带 ``comment`` 时新增 ``human_comment`` 线程且非阻塞。
7. **reject 幂等**：连续两次各 +1（基于重读的 current content，不会连加两次或不加）。
8. ⭐ **edit-blocks 不合法 → 400 且版本数不变**。
9. ⭐ **edit-blocks 同 hash 不翻版本**；成功版本 ``produced_by_ref == human_edit:{uid}``；
   编辑者进名单且 ``first_action`` 不被重复编辑覆盖。
10. **threads answer + ⭐ 回灌接线（B1）**：不属该 artifact → 404；空 body → 400；正路
    产新版本且 ``decision_log`` 带 ``applied_in_version``、线程 DB 重读 ``resolved``；
    **对照**：回灌返 ``noop`` / 抛异常时端点仍 200 且 ``reflow.status`` 如实上报。
11. ⭐ **B2 死锁解除端到端（不桩 service，经真实 REST 端点）**：``pending_review`` +
    两条未决 BLOCKER → approve **409** → 只处置一条仍 **409**（反向对照）→ 经
    ``reverse("blueprint-review-thread-resolve")`` / ``-thread-dismiss`` 处置完 →
    approve **200** 且 DB 重读 ``confirmed``。含边界：理由空 400、重复处置 noop 不覆盖
    首次结论、澄清线程走处置端点 400、线程不属该 artifact 404。
12. ⭐ **续驱接线正反 + 失败隔离**：六个动作端点各 ``await_count == 1``；GET 为 0；
    续驱抛异常时端点仍 2xx 且动作已持久化（不回滚、不回 5xx）。
13. ⭐ **``process_type`` 过滤证伪**：同 artifact 上另造一条 ``technical_plan`` 会话（且更
    新），断言续驱拿到的仍是蓝图会话 —— 跨 process 污染是 112 已发生过的 CRITICAL。
14. **视图零 ORM 写源码扫描** + 端到端后会话**绝不静默落 FAILED**。

REST client 是同步的 ⇒ 本文件用同步用例 + ``async_to_sync`` 装配（照 112 的
``test_blueprint_gate_api.py``）；async service 跨线程写库 ⇒ ``transaction=True``。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintReviewer,
    BlueprintStatus,
    BlueprintThread,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
    ThreadAnchorStatus,
    ThreadKind,
    ThreadSeverity,
    ThreadStatus,
)
from delivery.services import ArtifactService
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from delivery.services.blueprint_review_action import REJECT_PREFIX
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = pytest.mark.django_db(transaction=True)

SERVER_DIR = Path(__file__).resolve().parents[2]
_VIEWS_REL = "delivery/api/blueprint_review_views.py"

_RESUME_TARGET = "services.process_runtime.blueprint_resume.aresume_after_gate_action"
# 视图内是函数级懒 import ⇒ 必须 patch **来源模块**的属性，patch 视图模块无效
_REFLOW_TARGET = "services.process_runtime.blueprint_reflow.aapply_thread_answers"
_REMIND_TARGET = "delivery.services.blueprint_review_action.aremind_clarification_threads"

_TEXT_BLOCK = "blk_impl01_how"


# ── 工厂 ─────────────────────────────────────────────────────────────────────


def _make_artifact(status: str = BlueprintStatus.PENDING_REVIEW) -> Artifact:
    artifact = async_to_sync(ArtifactService().create)(
        "technical_plan", make_blueprint(), created_by_user_id="tester"
    )
    Artifact.objects.filter(id=artifact.id).update(blueprint_status=status)
    artifact.blueprint_status = status
    return artifact


def _make_session(
    artifact: Artifact,
    user: Any,
    *,
    process_type: str = "technical_blueprint",
    status: str = ConvergenceSessionStatus.RUNNING,
):
    return ConvergenceSession.objects.create(
        process_type=process_type,
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="ai_review",
        status=status,
        stage_state={"ai_review": {"round": 2, "unresolved": [{"rule_id": "R2"}]}},
        current_artifact_version_id=artifact.current_version_id,
        created_by=user,
    )


def _open_finding(
    artifact: Artifact,
    *,
    severity: str = ThreadSeverity.BLOCKER,
    blocking: bool = True,
    question: str = "[R2] 关键结论缺 citations",
) -> BlueprintThread:
    return async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        blocking=blocking,
        question=question,
        severity=severity,
        initiated_by_user_id="reviewer-agent",
    )


def _open_clarification(artifact: Artifact, *, blocking: bool = True) -> BlueprintThread:
    return async_to_sync(BlueprintLifecycleService().open_thread)(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=blocking,
        question="该接口的鉴权走哪套？",
        anchor={"block_id": _TEXT_BLOCK, "section_path": "impl", "quoted_text": "复用既有"},
        initiated_by_user_id="reviewer-agent",
    )


def _url(name: str, artifact: Artifact, thread: Any = None) -> str:
    args = [str(artifact.id)] + ([str(thread.id)] if thread is not None else [])
    return reverse(name, args=args)


def _db_status(artifact: Artifact) -> str:
    return Artifact.objects.get(id=artifact.id).blueprint_status


def _version_count(artifact: Artifact) -> int:
    return ArtifactVersion.objects.filter(artifact=artifact).count()


def _latest_version(artifact: Artifact) -> ArtifactVersion:
    return ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").first()


def _stub_resume(monkeypatch, *, side_effect: Any = None) -> AsyncMock:
    mock = AsyncMock(side_effect=side_effect) if side_effect else AsyncMock(return_value=None)
    monkeypatch.setattr(_RESUME_TARGET, mock)
    return mock


# ═══════════════════════════════════════════════════════════════════════════
# 1. 鉴权（T-114-32：安全边界不降级）
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("name", "with_thread"),
    [
        ("blueprint-review-snapshot", False),
        ("blueprint-review-approve", False),
        ("blueprint-review-reject", False),
        ("blueprint-review-edit-blocks", False),
        ("blueprint-review-thread-answer", True),
        ("blueprint-review-thread-resolve", True),
        ("blueprint-review-thread-dismiss", True),
    ],
)
def test_review_endpoints_reject_unauthenticated(api_client, name: str, with_thread: bool) -> None:
    args = [str(uuid.uuid4())] + ([str(uuid.uuid4())] if with_thread else [])
    url = reverse(name, args=args)
    resp = api_client.get(url) if name.endswith("snapshot") else api_client.post(url)
    assert resp.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# 2. 只读快照
# ═══════════════════════════════════════════════════════════════════════════


def test_snapshot_404_for_unknown_artifact(authenticated_client) -> None:
    resp = authenticated_client.get(reverse("blueprint-review-snapshot", args=[str(uuid.uuid4())]))
    assert resp.status_code == 404


def test_snapshot_groups_findings_and_lists_orphaned(
    authenticated_client, user, monkeypatch
) -> None:
    resume = _stub_resume(monkeypatch)
    remind = AsyncMock(return_value={})
    monkeypatch.setattr(_REMIND_TARGET, remind)

    artifact = _make_artifact()
    _make_session(artifact, user)
    blocker = _open_finding(artifact)
    _open_finding(artifact, severity=ThreadSeverity.WARNING, blocking=False, question="[R5] 警告")
    clarification = _open_clarification(artifact)
    BlueprintThread.objects.filter(id=clarification.id).update(
        anchor_status=ThreadAnchorStatus.ORPHANED
    )

    resp = authenticated_client.get(_url("blueprint-review-snapshot", artifact))

    assert resp.status_code == 200
    body = resp.json()
    assert [row["thread_id"] for row in body["findings"]["blocker"]] == [str(blocker.id)]
    assert len(body["findings"]["warning"]) == 1
    assert [row["thread_id"] for row in body["orphaned_threads"]] == [str(clarification.id)]
    assert body["unresolved"] == [{"rule_id": "R2"}]
    assert body["review_round"] == 2
    assert body["unresolved_blocker_count"] == 1
    assert body["unresolved_blocker_thread_ids"] == [str(blocker.id)]
    assert "revision_round" in body
    # GET 既不接续驱，也不触发提醒（提醒挂 apscheduler，GET 是伪挂载点）
    assert resume.await_count == 0
    assert remind.await_count == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3-5. approve：守卫、放行、无 TOCTOU
# ═══════════════════════════════════════════════════════════════════════════


def test_approve_with_unresolved_blocker_is_409_and_db_unchanged(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    blocker = _open_finding(artifact)

    resp = authenticated_client.post(_url("blueprint-review-approve", artifact))

    assert resp.status_code == 409
    body = resp.json()
    # 409 响应体必须告诉人审「去处置这几条」——那是死锁的解药入口
    assert body["unresolved_blocker_thread_ids"] == [str(blocker.id)]
    assert body["unresolved_blocker_count"] == 1
    assert _db_status(artifact) == BlueprintStatus.PENDING_REVIEW


def test_approve_after_clearing_blockers_confirms_and_registers_reviewer(
    authenticated_client, user, monkeypatch
) -> None:
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    thread = _open_finding(artifact)
    async_to_sync(BlueprintLifecycleService().resolve_thread)(thread, resolution="已修复")

    resp = authenticated_client.post(_url("blueprint-review-approve", artifact))

    assert resp.status_code == 200
    assert _db_status(artifact) == BlueprintStatus.CONFIRMED
    assert BlueprintReviewer.objects.filter(artifact=artifact, user=user).exists()
    assert resume.await_count == 1


def test_approve_view_has_no_out_of_transaction_precheck() -> None:
    """源码扫描：View 内不得出现事务外的 BLOCKER 预查询（TOCTOU 窗口复活）。"""
    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")
    start = src.index("class BlueprintReviewApproveView")
    end = src.find("class Blueprint", start + 1)
    body = src[start : end if end > 0 else len(src)]
    for token in ("aunresolved_blocker_count", "ahas_open_blocking_threads"):
        assert token not in body, f"approve View 内出现事务外预查询：{token}"


def test_approve_is_rejected_when_blocker_appears_inside_guard_window(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ 行为侧无 TOCTOU：守卫查询发生的那一刻插入 finding → 仍 409 且状态不变。

    对照组（不插行）在上一条用例里 200 ⇒ 本断言非恒真。
    """
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)

    original = BlueprintLifecycleService._has_confirm_blockers_sync

    def _racing_guard(target: Artifact) -> bool:
        BlueprintThread.objects.create(
            artifact=target,
            kind=ThreadKind.AI_REVIEW_FINDING,
            severity=ThreadSeverity.BLOCKER,
            blocking=True,
            status=ThreadStatus.OPEN,
            initiated_by_user_id="racer",
        )
        return original(target)

    monkeypatch.setattr(
        BlueprintLifecycleService, "_has_confirm_blockers_sync", staticmethod(_racing_guard)
    )

    resp = authenticated_client.post(_url("blueprint-review-approve", artifact))

    assert resp.status_code == 409
    assert _db_status(artifact) == BlueprintStatus.PENDING_REVIEW


def test_approve_illegal_transition_is_409_and_db_unchanged(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact(BlueprintStatus.DRAFTING)
    _make_session(artifact, user)

    resp = authenticated_client.post(_url("blueprint-review-approve", artifact))

    assert resp.status_code == 409
    assert _db_status(artifact) == BlueprintStatus.DRAFTING


# ═══════════════════════════════════════════════════════════════════════════
# 6-7. reject：先版本后状态 + 轮次幂等
# ═══════════════════════════════════════════════════════════════════════════


def test_reject_bumps_revision_round_before_transitioning(
    authenticated_client, user, monkeypatch
) -> None:
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    before = _version_count(artifact)

    resp = authenticated_client.post(
        _url("blueprint-review-reject", artifact),
        {"comment": "第 3 节的接口契约与现状不符", "anchor": {"block_id": _TEXT_BLOCK}},
        format="json",
    )

    assert resp.status_code == 200
    assert _version_count(artifact) == before + 1
    version = _latest_version(artifact)
    assert version.content["meta"]["revision_round"] == 1
    assert version.produced_by_ref.startswith(REJECT_PREFIX)
    assert _db_status(artifact) == BlueprintStatus.DRAFTING
    comment = BlueprintThread.objects.get(artifact=artifact, kind=ThreadKind.HUMAN_COMMENT)
    assert comment.blocking is False
    assert resp.json()["thread_id"] == str(comment.id)
    assert resume.await_count == 1


def test_reject_twice_increments_revision_round_exactly_once_each(
    authenticated_client, user, monkeypatch
) -> None:
    """幂等：每次都基于**重读的** current content ⇒ 单调 +1，不会连加两次或不加。"""
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)

    assert authenticated_client.post(_url("blueprint-review-reject", artifact)).status_code == 200
    assert _latest_version(artifact).content["meta"]["revision_round"] == 1

    Artifact.objects.filter(id=artifact.id).update(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    assert authenticated_client.post(_url("blueprint-review-reject", artifact)).status_code == 200
    assert _latest_version(artifact).content["meta"]["revision_round"] == 2


def test_reject_reopens_a_terminal_session_so_the_ai_can_actually_rerun(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ MJ-01 回归：驳回必须把终态会话拉回可运行态，否则驳回是空动作。

    ``pending_review`` 只能由 ``ai_review`` 的 ``review_passed`` / ``review_exhausted``
    到达，而两条出边都落 ``__done__`` ⇒ 人能点驳回的那一刻会话**必定** ``done``，而续驱
    驱动器第一件事就是终态短路、``engine.advance`` 同样对终态直接 return。修前实测：
    reject 返 200 但会话仍 ``done / __done__``（零 advance），融合与审查都不会重跑，
    ``revision_round`` 因此永远只会是 1。
    """
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    session = _make_session(artifact, user, status=ConvergenceSessionStatus.DONE)

    resp = authenticated_client.post(
        _url("blueprint-review-reject", artifact), {"comment": "证据不足"}, format="json"
    )

    assert resp.status_code == 200
    fresh = ConvergenceSession.objects.get(id=session.id)
    assert fresh.status == ConvergenceSessionStatus.RUNNING
    # 回 merge 而非 ai_review：只回审查等于拿同一份内容再审一遍，必然复现同样的 findings
    assert fresh.current_stage == "merge"
    assert resume.await_count == 1
    # stage_state 原样保留给重跑那一轮读（复位只改「能不能被驱动」）
    assert fresh.stage_state["ai_review"]["round"] == 2


def test_reject_reports_the_status_the_db_actually_lands(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ MJ-01 第二点：``current_status`` 必须在续驱**之后**重读。

    service 侧取值发生在续驱之前，而续驱的 ``_amap_blueprint_status`` 会因为还有
    open+blocking 线程把状态推成 ``needs_clarification`` ⇒ 修前前端拿到 ``drafting``、
    刷新一下变 ``needs_clarification``。这里用「续驱把状态改掉」的桩复现那一步。
    """

    artifact = _make_artifact()
    _make_session(artifact, user, status=ConvergenceSessionStatus.DONE)

    async def _resume_maps_status(session: Any, **kwargs: Any) -> None:
        """模拟 ``_amap_blueprint_status``：有阻塞线程 ⇒ 派生 needs_clarification。"""
        fresh = await Artifact.objects.aget(id=artifact.id)
        await BlueprintLifecycleService().transition(
            fresh,
            BlueprintStatus.NEEDS_CLARIFICATION,
            initiated_by_user_id="system",
            return_status=BlueprintStatus.DRAFTING,
        )

    monkeypatch.setattr(_RESUME_TARGET, AsyncMock(side_effect=_resume_maps_status))

    resp = authenticated_client.post(_url("blueprint-review-reject", artifact))

    assert resp.status_code == 200
    assert _db_status(artifact) == BlueprintStatus.NEEDS_CLARIFICATION
    assert resp.json()["current_status"] == _db_status(artifact)


# ═══════════════════════════════════════════════════════════════════════════
# 8-9. edit-blocks
# ═══════════════════════════════════════════════════════════════════════════


def test_edit_blocks_rejects_non_list_ops(authenticated_client, user) -> None:
    artifact = _make_artifact()
    resp = authenticated_client.post(
        _url("blueprint-review-edit-blocks", artifact), {"ops": "坏输入"}, format="json"
    )
    assert resp.status_code == 400


def test_edit_blocks_invalid_op_is_400_and_version_count_unchanged(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    before = _version_count(artifact)

    resp = authenticated_client.post(
        _url("blueprint-review-edit-blocks", artifact),
        {"ops": [{"op": "replace", "block_id": "blk_not_exist", "block": {"type": "paragraph"}}]},
        format="json",
    )

    assert resp.status_code == 400
    assert _version_count(artifact) == before


def test_edit_blocks_applies_then_same_ops_do_not_bump_version(
    authenticated_client, user, monkeypatch
) -> None:
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    before = _version_count(artifact)
    ops = {
        "ops": [
            {
                "op": "replace",
                "block_id": _TEXT_BLOCK,
                "block": {
                    "block_id": _TEXT_BLOCK,
                    "type": "paragraph",
                    "text": "人工改写后的实现说明。",
                },
            }
        ]
    }

    first = authenticated_client.post(
        _url("blueprint-review-edit-blocks", artifact), ops, format="json"
    )
    assert first.status_code == 200
    assert _version_count(artifact) == before + 1
    assert _latest_version(artifact).produced_by_ref == f"human_edit:{user.id}"
    reviewer = BlueprintReviewer.objects.get(artifact=artifact, user=user)
    assert reviewer.first_action == "block_edit"

    second = authenticated_client.post(
        _url("blueprint-review-edit-blocks", artifact), ops, format="json"
    )
    assert second.status_code == 200
    assert second.json()["status"] == "unchanged"
    assert _version_count(artifact) == before + 1
    # 重复编辑不覆盖首次 first_action
    assert BlueprintReviewer.objects.get(artifact=artifact, user=user).first_action == "block_edit"
    assert resume.await_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# 10. threads answer + ⭐ B1 回灌接线
# ═══════════════════════════════════════════════════════════════════════════


def test_answer_404_when_thread_belongs_to_another_artifact(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    other = _make_artifact()
    thread = _open_clarification(other)

    resp = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, thread), {"body": "走 JWT"}, format="json"
    )
    assert resp.status_code == 404


def test_answer_rejects_empty_body(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    thread = _open_clarification(artifact)
    resp = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, thread), {"body": "  "}, format="json"
    )
    assert resp.status_code == 400


def test_answer_is_consumed_into_a_new_version_with_decision_log(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ B1 正路：作答后**同一请求内**回灌产新版本，线程被回灌链收尾为 resolved。"""
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    thread = _open_clarification(artifact)
    before = _version_count(artifact)

    async def _writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        """桩掉段落重产（不打 LLM）。答案的物化由 ``decision_log`` 承担——即便 writer 原样
        返回 content，答案也绝不该丢失，这正是 114-04 的块级降级语义。"""
        assert answers, "生产 writer 必须收到答案条目"
        return content

    monkeypatch.setattr("services.process_runtime.blueprint_reflow.ablock_section_writer", _writer)

    resp = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, thread),
        {"body": "统一走 JWT，网关侧校验"},
        format="json",
    )

    assert resp.status_code == 200
    assert _version_count(artifact) == before + 1
    entries = _latest_version(artifact).content["decision_log"]
    entry = next(item for item in entries if item["thread_id"] == str(thread.id))
    assert set(entry) >= {
        "thread_id",
        "question",
        "answer",
        "decided_at",
        "decided_by",
        "applied_in_version",
    }
    assert entry["applied_in_version"]
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.RESOLVED
    assert resp.json()["reflow"]["status"] == "applied"
    assert (
        BlueprintReviewer.objects.get(artifact=artifact, user=user).first_action == "thread_answer"
    )
    assert resume.await_count == 1


def test_answer_still_200_when_reflow_noops_and_reports_it_truthfully(
    authenticated_client, user, monkeypatch
) -> None:
    """对照：回灌未消费时端点仍 200、版本不变、线程停在 answered，且 ``reflow`` 如实上报。"""
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    thread = _open_clarification(artifact)
    before = _version_count(artifact)
    monkeypatch.setattr(_REFLOW_TARGET, AsyncMock(return_value={"status": "noop"}))

    resp = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, thread), {"body": "走 JWT"}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["reflow"]["status"] == "noop"
    assert _version_count(artifact) == before
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.ANSWERED


def test_answer_still_200_when_reflow_raises(authenticated_client, user, monkeypatch) -> None:
    """作答已持久化 ⇒ 回灌异常绝不回滚、绝不回 5xx，但必须如实标记失败（不静默）。"""
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    thread = _open_clarification(artifact)
    monkeypatch.setattr(_REFLOW_TARGET, AsyncMock(side_effect=RuntimeError("回灌炸了")))

    resp = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, thread), {"body": "走 JWT"}, format="json"
    )

    assert resp.status_code == 200
    assert resp.json()["reflow"]["status"] == "failed"
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.ANSWERED


# ═══════════════════════════════════════════════════════════════════════════
# 11. ⭐ B2 死锁解除端到端（本 plan 头号靶子；不桩 service，经真实 REST 端点）
# ═══════════════════════════════════════════════════════════════════════════


def test_over_bound_deadlock_is_released_only_after_all_blockers_are_disposed(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ 超界出口的死锁与解药，全链经真实 REST 端点。

    ``review_exhausted`` 的等价终局：蓝图 ``pending_review`` + 两条未决 BLOCKER finding。
    此时 approve 恒 409（人审只能驳回 = 死锁）。**只处置一条仍 409**（反向对照：放行确
    由「全部清空」驱动，不是端点副作用）；两条都处置完 approve 才 200。
    """
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    session = _make_session(artifact, user)
    t1 = _open_finding(artifact, question="[R2] 关键结论缺 citations")
    t2 = _open_finding(artifact, question="[R7] 目标仓与章程边界冲突")

    # ① 死锁：approve 被守卫拒绝，DB 状态不变，响应体带未决清单
    first = authenticated_client.post(_url("blueprint-review-approve", artifact))
    assert first.status_code == 409
    assert set(first.json()["unresolved_blocker_thread_ids"]) == {str(t1.id), str(t2.id)}
    assert _db_status(artifact) == BlueprintStatus.PENDING_REVIEW

    # ② 经真实端点处置第一条（已修复）
    resolved = authenticated_client.post(
        reverse("blueprint-review-thread-resolve", args=[str(artifact.id), str(t1.id)]),
        {"reason": "已在 v3 修复"},
        format="json",
    )
    assert resolved.status_code == 200
    t1_db = BlueprintThread.objects.get(id=t1.id)
    assert t1_db.status == ThreadStatus.RESOLVED
    conclusion = t1_db.messages.order_by("created_at").last().body
    assert "已在 v3 修复" in conclusion and str(user.id) in conclusion

    # ③ 反向对照：还剩一条未决 ⇒ approve 仍 409
    still = authenticated_client.post(_url("blueprint-review-approve", artifact))
    assert still.status_code == 409
    assert _db_status(artifact) == BlueprintStatus.PENDING_REVIEW

    # ④ 经真实端点处置第二条（误报忽略）
    dismissed = authenticated_client.post(
        reverse("blueprint-review-thread-dismiss", args=[str(artifact.id), str(t2.id)]),
        {"reason": "规则误报，章程已授权"},
        format="json",
    )
    assert dismissed.status_code == 200
    assert BlueprintThread.objects.get(id=t2.id).status == ThreadStatus.DISMISSED

    # ⑤ 死锁解除：approve 放行且 DB 重读 confirmed
    final = authenticated_client.post(_url("blueprint-review-approve", artifact))
    assert final.status_code == 200
    assert _db_status(artifact) == BlueprintStatus.CONFIRMED

    actions = set(
        BlueprintReviewer.objects.filter(artifact=artifact).values_list("first_action", flat=True)
    )
    assert actions & {"finding_resolve", "finding_dismiss"}
    assert ConvergenceSession.objects.get(id=session.id).status != ConvergenceSessionStatus.FAILED
    assert resume.await_count >= 2


def test_finding_dispose_requires_a_reason(authenticated_client, user, monkeypatch) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    thread = _open_finding(artifact)

    resp = authenticated_client.post(
        reverse("blueprint-review-thread-resolve", args=[str(artifact.id), str(thread.id)]),
        {"reason": "   "},
        format="json",
    )

    assert resp.status_code == 400
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.OPEN


def test_repeated_dispose_is_noop_and_never_overwrites_the_first_conclusion(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    thread = _open_finding(artifact)
    url = reverse("blueprint-review-thread-resolve", args=[str(artifact.id), str(thread.id)])

    assert authenticated_client.post(url, {"reason": "首次结论"}, format="json").status_code == 200
    first_conclusion = (
        BlueprintThread.objects.get(id=thread.id).messages.order_by("created_at").last().body
    )

    second = authenticated_client.post(url, {"reason": "第二次结论"}, format="json")

    assert second.status_code == 200
    assert second.json()["status"] == "noop"
    latest = BlueprintThread.objects.get(id=thread.id).messages.order_by("created_at").last().body
    assert latest == first_conclusion
    assert "第二次结论" not in latest


def test_dispose_endpoint_rejects_non_finding_threads(
    authenticated_client, user, monkeypatch
) -> None:
    """该通道只处置审查发现；澄清线程走 answer 端点。"""
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    thread = _open_clarification(artifact)

    resp = authenticated_client.post(
        reverse("blueprint-review-thread-dismiss", args=[str(artifact.id), str(thread.id)]),
        {"reason": "不该走这条通道"},
        format="json",
    )

    assert resp.status_code == 400
    assert BlueprintThread.objects.get(id=thread.id).status == ThreadStatus.OPEN


def test_dispose_404_when_thread_belongs_to_another_artifact(
    authenticated_client, user, monkeypatch
) -> None:
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    thread = _open_finding(_make_artifact())

    resp = authenticated_client.post(
        reverse("blueprint-review-thread-resolve", args=[str(artifact.id), str(thread.id)]),
        {"reason": "越权处置"},
        format="json",
    )
    assert resp.status_code == 404


def test_answer_endpoint_refuses_finding_threads_and_the_confirm_guard_holds(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ CR-01 回归：作答通道不得成为 finding 的处置通道。

    修前的实测链路是 approve **409** → 对同一条 BLOCKER finding 调 answer 端点答一句
    「知道了」→ 回灌链落版本后无条件收尾 ⇒ 线程 DB 重读 ``resolved`` → approve **200**。
    那条路径同时绕开了 ``reason`` 必填、``[已修复]`` / ``[误报忽略]`` 的语义区分、以及
    「处置人：{uid}」的归因留痕——**AI 的一句「答案已回灌」冒充了人的裁决**。

    ⛔ 处置只走 resolve / dismiss；answer 通道对 finding 一律 400 且不改线程状态。
    **对照**：同一 artifact 上的澄清线程走 answer 端点仍 200（证明分流非恒真）。
    """
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    _make_session(artifact, user)
    finding = _open_finding(artifact)
    before = _version_count(artifact)

    assert authenticated_client.post(_url("blueprint-review-approve", artifact)).status_code == 409

    refused = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, finding),
        {"body": "知道了"},
        format="json",
    )

    assert refused.status_code == 400
    assert BlueprintThread.objects.get(id=finding.id).status == ThreadStatus.OPEN
    assert _version_count(artifact) == before
    # 守卫仍满弦：绕不开处置通道
    assert authenticated_client.post(_url("blueprint-review-approve", artifact)).status_code == 409
    assert _db_status(artifact) == BlueprintStatus.PENDING_REVIEW

    # 对照：澄清线程仍可正常作答（分流不是「一律 400」）
    clarification = _open_clarification(artifact)
    monkeypatch.setattr(_REFLOW_TARGET, AsyncMock(return_value={"status": "noop"}))
    ok = authenticated_client.post(
        _url("blueprint-review-thread-answer", artifact, clarification),
        {"body": "走 JWT"},
        format="json",
    )
    assert ok.status_code == 200
    assert BlueprintThread.objects.get(id=clarification.id).status == ThreadStatus.ANSWERED


# ═══════════════════════════════════════════════════════════════════════════
# 12-13. 续驱接线正反 / 失败隔离 / process_type 过滤
# ═══════════════════════════════════════════════════════════════════════════


def test_resume_failure_never_rolls_back_a_persisted_action(
    authenticated_client, user, monkeypatch
) -> None:
    """续驱抛异常 → 端点仍 2xx 且动作已持久化（失败隔离在 helper 内，视图不重复包 try）。"""
    monkeypatch.setattr(
        "services.process_runtime.blueprint_resume.adrive_blueprint_session_to_pause_or_terminal",
        AsyncMock(side_effect=RuntimeError("续驱炸了")),
    )
    artifact = _make_artifact()
    _make_session(artifact, user)

    resp = authenticated_client.post(_url("blueprint-review-reject", artifact))

    assert resp.status_code == 200
    assert _db_status(artifact) == BlueprintStatus.DRAFTING


def test_resume_receives_the_blueprint_session_not_the_legacy_one(
    authenticated_client, user, monkeypatch
) -> None:
    """⭐ ``process_type`` 过滤证伪：同 artifact 上另有一条**更新的** ``technical_plan``
    会话；不过滤就会拿它去续驱（112 已发生过的 CRITICAL：旧链 handler 取不到 deps →
    engine 把那条无关会话落 FAILED，而 REST 仍回 2xx）。"""
    resume = _stub_resume(monkeypatch)
    artifact = _make_artifact()
    blueprint_session = _make_session(artifact, user)
    legacy = _make_session(artifact, user, process_type="technical_plan")

    resp = authenticated_client.post(_url("blueprint-review-reject", artifact))

    assert resp.status_code == 200
    passed = resume.await_args.args[0]
    assert str(passed.id) == str(blueprint_session.id)
    assert passed.process_type == "technical_blueprint"
    assert str(passed.id) != str(legacy.id)


def test_aload_session_source_carries_the_process_type_filter() -> None:
    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")
    start = src.index("async def _aload_session")
    body = src[start : src.index("async def _aload_thread")]
    assert "BLUEPRINT_PROCESS_TYPE" in body, "_aload_session 缺 process_type 过滤"


# ═══════════════════════════════════════════════════════════════════════════
# 14. 视图零 ORM 写 + 端到端不静默落 FAILED
# ═══════════════════════════════════════════════════════════════════════════


def test_views_never_write_orm_directly() -> None:
    """INV-6 源码扫描：写入全部委托 service，视图只读。"""
    import re

    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")
    hits = re.findall(r"objects\.(create|acreate|bulk_create|update|bulk_update|delete)\(", src)
    assert not hits, f"视图出现直接 ORM 写：{hits}"


def test_seven_views_follow_the_112_conventions() -> None:
    import re

    src = (SERVER_DIR / _VIEWS_REL).read_text(encoding="utf-8")
    assert len(re.findall(r"^class Blueprint", src, re.M)) == 7
    assert src.count("permission_classes = [IsAuthenticated]") == 7
    assert "from adrf.views import APIView" in src
    assert "from rest_framework.views import APIView" not in src


def test_end_to_end_edit_reject_approve_never_silently_fails_the_session(
    authenticated_client, user, monkeypatch
) -> None:
    """端到端：edit-blocks → reject → （清干净后）approve，会话绝不静默落 FAILED。"""
    _stub_resume(monkeypatch)
    artifact = _make_artifact()
    session = _make_session(artifact, user)

    authenticated_client.post(
        _url("blueprint-review-edit-blocks", artifact),
        {
            "ops": [
                {
                    "op": "replace",
                    "block_id": _TEXT_BLOCK,
                    "block": {"block_id": _TEXT_BLOCK, "type": "paragraph", "text": "人工修订。"},
                }
            ]
        },
        format="json",
    )
    assert authenticated_client.post(_url("blueprint-review-reject", artifact)).status_code == 200
    assert _db_status(artifact) == BlueprintStatus.DRAFTING

    Artifact.objects.filter(id=artifact.id).update(blueprint_status=BlueprintStatus.PENDING_REVIEW)
    assert authenticated_client.post(_url("blueprint-review-approve", artifact)).status_code == 200
    assert _db_status(artifact) == BlueprintStatus.CONFIRMED
    assert ConvergenceSession.objects.get(id=session.id).status != ConvergenceSessionStatus.FAILED
