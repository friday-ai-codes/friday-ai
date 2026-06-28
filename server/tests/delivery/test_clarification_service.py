"""ClarificationService 单一写入入口测试（CLARIFY-01；P3 process-agnostic 收口）。

P3 起 ClarificationService 移除 legacy 双写（create_clarification / answer_clarification +
affected_partials stale 重跑），统一到结构化轮次三方法。本文件覆盖：

- create_round 建容器 + 多子题 / answer_round 按题作答 + 采纳信号（single/multi/None 三态）/
  采纳率 SQL 聚合 / ahas_pending（结构化子题 + 无子题容器兜底）/ 按题幂等 / 整轮答毕推进容器 +
  emit clarification.answered / 空轮守护 / INV-6 grep 守护（含 ClarificationQuestion 子模型）。
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from django.db.models import Count, Q

from delivery.models import (
    Clarification,
    ClarificationQuestion,
    ConvergenceSession,
    ConvergenceSessionEntrypoint,
    ConvergenceSessionStatus,
)
from delivery.services import ClarificationService

_SERVER_ROOT = Path(__file__).resolve().parents[2]

# transaction=True：本文件 async 用例经 acreate 在独立线程连接写库，普通
# @pytest.mark.django_db（rollback）无法回滚跨线程连接的提交。TransactionTestCase 在
# teardown TRUNCATE 全表，确保跨连接提交也被清理。
pytestmark = pytest.mark.django_db(transaction=True)


def test_inv6_clarification_single_write_entry() -> None:
    """INV-6 grep 守护：Clarification.objects.create 仅出现在 clarification_service.py。"""
    _SKIP_DIRS = (".venv", "node_modules", ".git", "__pycache__", "site-packages")
    offenders: list[str] = []
    for path in _SERVER_ROOT.rglob("*.py"):
        rel = path.relative_to(_SERVER_ROOT).as_posix()
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if rel.startswith("tests/") or "/migrations/" in rel:
            continue
        if path.name == "clarification_service.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "Clarification.objects.create" in line:
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, f"Clarification 旁路写入（应只经 ClarificationService）：{offenders}"


# INV-6 子模型守护：ClarificationQuestion 旁路写入正则（.objects.create / .bulk_create /
# 实例 .save）。本守护用例自身在 tests/ 下被扫描跳过，故字面正则不会自我误判。
_INV6_QUESTION_BYPASS = (
    re.compile(r"ClarificationQuestion\.objects\.(create|bulk_create)\b"),
    re.compile(r"ClarificationQuestion\([^)]*\)\.save\b"),
)


def test_inv6_clarification_question_single_write_entry() -> None:
    """INV-6 grep 守护扩展：ClarificationQuestion 旁路写入只允许出现在 clarification_service.py。"""
    _SKIP_DIRS = (".venv", "node_modules", ".git", "__pycache__", "site-packages")
    offenders: list[str] = []
    for path in _SERVER_ROOT.rglob("*.py"):
        rel = path.relative_to(_SERVER_ROOT).as_posix()
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if rel.startswith("tests/") or "/migrations/" in rel:
            continue
        if path.name == "clarification_service.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            if any(pat.search(line) for pat in _INV6_QUESTION_BYPASS):
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, (
        f"ClarificationQuestion 旁路写入（应只经 ClarificationService）：{offenders}"
    )


# ── 90-02 结构化澄清：create_round / answer_round / 采纳信号 / 采纳率 / 兼容 / 幂等 ──


def _round_questions() -> list[dict]:
    return [
        {"question": "用哪个仓？", "type": "single", "options": ["A", "B"], "recommended": "A"},
        {
            "question": "涉及哪些层？",
            "type": "multi",
            "options": ["X", "Y", "Z"],
            "recommended": ["X", "Y"],
        },
    ]


async def _clarifying_session() -> ConvergenceSession:
    return await ConvergenceSession.objects.acreate(
        process_type="technical_plan", entrypoint=ConvergenceSessionEntrypoint.WORKFLOW,
        current_stage="clarify", status=ConvergenceSessionStatus.WAITING_CLARIFICATION
    )


@pytest.mark.asyncio
async def test_create_round_builds_container_and_questions() -> None:
    """create_round → 1 容器（question=""）+ N 子题，order/qtype/options/recommended 落库正确。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(session, _round_questions(), origin_repo="repo-a")

    reloaded = await Clarification.objects.aget(id=clar.id)
    assert reloaded.question == ""
    assert reloaded.origin_repo == "repo-a"
    assert reloaded.container_status == "pending"

    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]
    assert len(rows) == 2
    assert [r.order for r in rows] == [0, 1]
    assert rows[0].qtype == "single"
    assert rows[0].options == ["A", "B"]
    assert rows[0].recommended == "A"
    assert rows[0].origin_repo == "repo-a"
    assert rows[1].qtype == "multi"
    assert rows[1].recommended == ["X", "Y"]


@pytest.mark.asyncio
async def test_recommendation_adopted_single() -> None:
    """单选采纳信号：选中==推荐→True；不命中→False。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [{"question": "Q", "type": "single", "options": ["A", "B"], "recommended": "A"}],
    )
    q = await ClarificationQuestion.objects.aget(clarification=clar)

    await svc.answer_round(clar, [{"question_id": q.id, "selected": "A"}])
    q_hit = await ClarificationQuestion.objects.aget(id=q.id)
    assert q_hit.recommendation_adopted is True
    assert q_hit.selected == "A"
    assert q_hit.answered_at is not None

    # 另起一轮验证不命中
    clar2 = await svc.create_round(
        session,
        [{"question": "Q", "type": "single", "options": ["A", "B"], "recommended": "A"}],
    )
    q2 = await ClarificationQuestion.objects.aget(clarification=clar2)
    await svc.answer_round(clar2, [{"question_id": q2.id, "selected": "B"}])
    q_miss = await ClarificationQuestion.objects.aget(id=q2.id)
    assert q_miss.recommendation_adopted is False


@pytest.mark.asyncio
async def test_recommendation_adopted_multi() -> None:
    """多选采纳信号：set 全等→True；部分命中→False。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [{"question": "Q", "type": "multi", "options": ["X", "Y", "Z"], "recommended": ["X", "Y"]}],
    )
    q = await ClarificationQuestion.objects.aget(clarification=clar)
    await svc.answer_round(clar, [{"question_id": q.id, "selected": ["Y", "X"]}])
    q_hit = await ClarificationQuestion.objects.aget(id=q.id)
    assert q_hit.recommendation_adopted is True  # set 全等（顺序无关）

    clar2 = await svc.create_round(
        session,
        [{"question": "Q", "type": "multi", "options": ["X", "Y", "Z"], "recommended": ["X", "Y"]}],
    )
    q2 = await ClarificationQuestion.objects.aget(clarification=clar2)
    await svc.answer_round(clar2, [{"question_id": q2.id, "selected": ["X"]}])
    q_partial = await ClarificationQuestion.objects.aget(id=q2.id)
    assert q_partial.recommendation_adopted is False


@pytest.mark.asyncio
async def test_recommendation_adopted_none() -> None:
    """无推荐项 或 纯 freeform（无 selected）→ recommendation_adopted=None（不计入分母）。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [
            {"question": "无推荐", "type": "single", "options": ["A", "B"], "recommended": ""},
            {"question": "纯文本", "type": "single", "options": ["A", "B"], "recommended": "A"},
        ],
    )
    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]
    no_rec, freeform = rows[0], rows[1]

    await svc.answer_round(
        clar,
        [
            {"question_id": no_rec.id, "selected": "A"},
            {"question_id": freeform.id, "selected": None, "freeform_text": "我要自定义"},
        ],
    )
    no_rec_reloaded = await ClarificationQuestion.objects.aget(id=no_rec.id)
    freeform_reloaded = await ClarificationQuestion.objects.aget(id=freeform.id)
    assert no_rec_reloaded.recommendation_adopted is None  # 无推荐项
    assert no_rec_reloaded.answered_at is not None
    assert freeform_reloaded.recommendation_adopted is None  # 纯 freeform 无 selected
    assert freeform_reloaded.freeform_text == "我要自定义"


@pytest.mark.asyncio
async def test_adoption_rate_aggregation() -> None:
    """采纳率可经 SQL 聚合：recommendation_adopted__isnull=False 为分母，adopted/total。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [
            {"question": "Q1", "type": "single", "options": ["A", "B"], "recommended": "A"},
            {"question": "Q2", "type": "single", "options": ["A", "B"], "recommended": "A"},
            {"question": "Q3", "type": "single", "options": ["A", "B"], "recommended": ""},
        ],
    )
    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]
    await svc.answer_round(
        clar,
        [
            {"question_id": rows[0].id, "selected": "A"},  # adopted True
            {"question_id": rows[1].id, "selected": "B"},  # adopted False
            {"question_id": rows[2].id, "selected": "A"},  # adopted None（无推荐，不入分母）
        ],
    )
    stats = await ClarificationQuestion.objects.filter(
        recommendation_adopted__isnull=False
    ).aaggregate(total=Count("id"), adopted=Count("id", filter=Q(recommendation_adopted=True)))
    assert stats["total"] == 2  # 仅两题计入分母
    assert stats["adopted"] == 1


@pytest.mark.asyncio
async def test_answer_round_emits_clarification_answered_on_completion() -> None:
    """整轮答毕（容器推进 answered）→ emit clarification.answered（仅标量 payload，process-agnostic）。"""
    session = await _clarifying_session()
    emit_spy = AsyncMock()
    svc = ClarificationService(session_service=type("S", (), {"_emit_event": emit_spy})())
    clar = await svc.create_round(
        session,
        [
            {"question": "Q1", "type": "single", "options": ["A", "B"], "recommended": "A"},
            {"question": "Q2", "type": "single", "options": ["A", "B"], "recommended": "A"},
        ],
    )
    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]

    # 部分作答（仅一题）→ 容器未推进 → 不 emit
    await svc.answer_round(clar, [{"question_id": rows[0].id, "selected": "A"}])
    assert emit_spy.await_count == 0

    # 答完剩余题 → 容器推进 answered → emit clarification.answered（标量 payload）
    await svc.answer_round(clar, [{"question_id": rows[1].id, "selected": "A"}])
    answered = [
        c for c in emit_spy.call_args_list if c.args and c.args[0] == "clarification.answered"
    ]
    assert len(answered) == 1
    payload = answered[0].args[2]
    assert payload["clarification_id"] == str(clar.id)
    # process-agnostic：payload 不含任何 process 专属重跑面（如 affected_partials）
    assert "affected_partials" not in payload


@pytest.mark.asyncio
async def test_ahas_pending_structured_round() -> None:
    """ahas_pending 新结构化：有未答子题→True；全部作答后→False。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [{"question": "Q", "type": "single", "options": ["A", "B"], "recommended": "A"}],
    )
    assert await svc.ahas_pending(session.id) is True

    q = await ClarificationQuestion.objects.aget(clarification=clar)
    await svc.answer_round(clar, [{"question_id": q.id, "selected": "A"}])
    assert await svc.ahas_pending(session.id) is False


@pytest.mark.asyncio
async def test_answer_round_idempotent() -> None:
    """重复作答同题幂等 no-op：首答不被二次覆盖。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [{"question": "Q", "type": "single", "options": ["A", "B"], "recommended": "A"}],
    )
    q = await ClarificationQuestion.objects.aget(clarification=clar)

    await svc.answer_round(clar, [{"question_id": q.id, "selected": "A"}])
    first = await ClarificationQuestion.objects.aget(id=q.id)
    first_answered_at = first.answered_at

    await svc.answer_round(clar, [{"question_id": q.id, "selected": "B"}])
    second = await ClarificationQuestion.objects.aget(id=q.id)
    assert second.selected == "A"  # 首答未被覆盖
    assert second.recommendation_adopted is True
    assert second.answered_at == first_answered_at


@pytest.mark.asyncio
async def test_answer_round_advances_container_when_all_answered() -> None:
    """WR-01：轮内全部子题作答后，容器 container_status 从 pending 推进到 answered。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    clar = await svc.create_round(
        session,
        [
            {"question": "Q1", "type": "single", "options": ["A", "B"], "recommended": "A"},
            {"question": "Q2", "type": "single", "options": ["A", "B"], "recommended": "A"},
        ],
    )
    rows = [
        q async for q in ClarificationQuestion.objects.filter(clarification=clar).order_by("order")
    ]

    # 只答一题 → 容器仍 pending
    await svc.answer_round(clar, [{"question_id": rows[0].id, "selected": "A"}])
    mid = await Clarification.objects.aget(id=clar.id)
    assert mid.container_status == "pending"
    assert mid.answered_at is None

    # 答完剩余题 → 容器推进 answered + answered_at 落定
    await svc.answer_round(clar, [{"question_id": rows[1].id, "selected": "A"}])
    done = await Clarification.objects.aget(id=clar.id)
    assert done.container_status == "answered"
    assert done.answered_at is not None
    assert await svc.ahas_pending(session.id) is False


@pytest.mark.asyncio
async def test_create_round_empty_questions_returns_none() -> None:
    """WR-02：空问题列表不创建轮次（返回 None），避免永久不可作答的 pending 容器。"""
    session = await _clarifying_session()
    svc = ClarificationService()
    result = await svc.create_round(session, [])
    assert result is None
    # 未建任何容器 → 会话不挂起
    assert await Clarification.objects.filter(session_id=session.id).acount() == 0
    assert await svc.ahas_pending(session.id) is False
