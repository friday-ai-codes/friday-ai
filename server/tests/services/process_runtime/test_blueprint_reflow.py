"""澄清答案回灌 + 人工块保护测试（Phase 114-04 Task 3，CLAR-02 / CLAR-03 / B1 / B3）。

守十一件事（断言一律**从 DB 重读**，不信返回体）：

1. **三步顺序（先落版本再收尾）**：``add_version`` 的调用早于 ``resolve_thread``，且
   ``resolve_thread`` 发生时 ``artifact.current_version`` **已是新版本**；本模块自己
   **不调 ``transition``**（状态转移归调用方，顺序由「返回 applied 才转」保证）。
2. ⭐ **``decision_log`` 物化保 ``answer`` 键**：条目键集 ⊇
   ``{thread_id, question, answer, decided_at, decided_by}``，``answer`` 非空。
3. ⭐ **同一问题不再重复问**：把回灌后的 content 喂 ``BlueprintSpecGateAdapter.
   _collect_prior_answers``（**复用读侧同一函数**，不自写指纹逻辑），断言问题指纹与问答
   文本都在。**配会失败的对照**：把 ``answer`` 键改名成 ``decision`` 后，重判 prompt 的
   ``text`` 里再也读不到该答案 ⇒ 模型会重复问（证明「必须保 answer 键」不是恒真装饰）。
4. ⭐ **``decided_at`` 稳定 ⇒ 同 hash 不翻版本**：同一批线程连续回灌两次，第二次
   ``unchanged``、版本行数不变（若 ``decided_at`` 用了 ``timezone.now()`` 这条必红）。
5. **线程收尾 + ``applied_in_version`` 口径**：线程 ``resolved``、``resolution`` 含新版本号、
   ``resolve_thread`` 幂等；条目 ``applied_in_version == str(base.id)``（基线版本 id）；
   产出版本可经 ``produced_by_ref == f"ai_review_reflow:{thread_id}"`` 反查到恰好一行。
6. ⭐ **AI 不覆盖人工（正反并列）**：AI 要改人工改过的块 ⇒ ``conflict`` + **版本行数不变**
   + 新开一条 ``ai_clarification / blocking / return_stage=ai_reviewing`` 线程，且 question
   **不含两侧正文**；AI 改别的块 ⇒ ``applied`` 且版本 +1（判据非恒真）。
7. **非法 content fail-closed**：桩 writer 产非法 content ⇒ ``invalid``、版本行数不变、无异常外泄。
8. **恒不抛 + 空输入**：``threads=[]`` / 无版本 / writer 抛异常 ⇒ 均返回合法 ``status``。
9. **零 ORM 写源码扫描**（去注释去 docstring 后的**可执行代码**层）：两模块不含蓝图模型
   写调用，也不含 ``record_answer``（留痕通道纪律，114-01）。
10. ⭐ **``section_writer`` 默认走生产实现（B1，正反并列）**：不传 ``section_writer`` 时
    ``ablock_section_writer`` **被调用一次**且入参含 answers；即便它把 content 原样返回，
    ``decision_log`` 仍被物化、线程仍 ``resolved``（**答案不因段落未改写而丢失**）。
    另直测它本体：LLM 不可得 ⇒ 返回 content 与入参逐字相等；可解析 ⇒ 目标块正文已更新且
    ``block_id`` 逐字不变；超 ``_MAX_REWRITE_BLOCKS`` 只改写前 5 块。
11. ⭐ **人工块保护三态（B3）**：等价 ⇒ ``unchanged`` 不翻版本；实质冲突 ⇒ ``conflict`` 且
    **新版本的该块与人工版本逐字相等**（头号断言）+ 有阻塞线程；无人工版本 ⇒ ``noop``。

``async`` + ``sync_to_async`` 跨线程写库 → ``transaction=True``。
"""

from __future__ import annotations

import ast
import copy
import io
import json
import re
import tokenize
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from delivery.models import (
    Artifact,
    ArtifactVersion,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.artifact_service import ArtifactService
from delivery.services.blueprint_block_edit import aapply_block_edit
from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService
from services.process_runtime.blueprint_reflow import (
    _MAX_REWRITE_BLOCKS,
    AI_REVIEW_REFLOW_PREFIX,
    DECISION_LOG_KEYS,
    HUMAN_BLOCK_RESTORE_PREFIX,
    aapply_thread_answers,
    ablock_section_writer,
    acollect_human_block_ids,
    arestore_human_blocks,
    build_decision_entries,
    detect_human_conflicts,
    merge_decision_log,
)
from services.process_runtime.blueprint_spec_gate import BlueprintSpecGateAdapter
from tests.helpers.blueprint_samples import make_blueprint

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

_ARESOLVE = "services.provider_config.ProviderConfigService.aresolve"
_BUILD = "agents.llm_factory.build_chat_model"
_WRITER_TARGET = "services.process_runtime.blueprint_reflow.ablock_section_writer"

_BLOCK_X = "blk_impl01_how"
_BLOCK_Y = "blk_impl02_how"
_QUESTION = "生成失败时应该回落到静态题库还是直接报错？"
_ANSWER = "回落到静态题库，并在响应里标记 degraded=true。"

_SERVER_DIR = Path(__file__).resolve().parents[3]
_SCANNED_MODULES = (
    "services/process_runtime/blueprint_reflow.py",
    "delivery/services/blueprint_block_edit.py",
)


# ══════════════════════════════════════════════════════════════════════════
# fixture 工厂
# ══════════════════════════════════════════════════════════════════════════


async def _make_artifact(content: dict | None = None) -> Artifact:
    return await ArtifactService().create("technical_plan", content or make_blueprint())


async def _make_user() -> Any:
    from django.contrib.auth import get_user_model

    return await get_user_model().objects.acreate(username=f"u-{uuid.uuid4().hex[:6]}")


async def _answered_thread(
    artifact: Artifact, *, block_id: str = _BLOCK_X, question: str = _QUESTION
) -> BlueprintThread:
    """开一条澄清线程并由人类作答 ⇒ 线程进 ``answered``（回灌的输入前提）。

    ``record_answer`` 在此是**人类回答澄清线程**的正当用途（它会把 open 推到 answered）；
    AI 侧留痕一律走 ``append_note``，见守 9 的源码扫描。
    """
    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_CLARIFICATION,
        blocking=True,
        question=question,
        anchor={"section_path": "implementation_overview", "block_id": block_id},
    )
    await lifecycle.record_answer(thread, body=_ANSWER)
    return thread


def _writer_touching(block_id: str, text: str = "回灌后的新正文。") -> Any:
    """桩 section_writer：只改指定块的正文（其余原样）。"""

    async def _writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        from services.process_runtime.blueprint_schema import iter_blocks

        for _path, block in iter_blocks(content):
            if block.get("block_id") == block_id:
                block["text"] = text
        return content

    return _writer


async def _noop_writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
    """桩 section_writer：正文原样返回（用于「答案不因段落未改写而丢失」）。"""
    return content


def _version_count(artifact: Artifact) -> Any:
    return ArtifactVersion.objects.filter(artifact=artifact).acount()


async def _message_bodies(thread_id: Any) -> list[str]:
    """线程消息正文（按 ``created_at``，与 ``BlueprintThreadMessage.ordering`` 同序）。"""
    return [
        str(row["body"])
        async for row in BlueprintThreadMessage.objects.filter(thread_id=thread_id)
        .order_by("created_at")
        .values("body")
    ]


def _resolved(default_model: str = "test-model") -> SimpleNamespace:
    return SimpleNamespace(extra={"default_model": default_model})


def _model_returning(content: object) -> MagicMock:
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content=content))
    return model


def _code_only(rel: str) -> str:
    """去掉全部注释与 docstring，只留**可执行代码**。

    源码扫描必须扫代码而不是扫全文：两个模块的 docstring 里**故意**写着
    「⛔ 绝不用 ``record_answer``」这类纪律说明，扫全文会把纪律说明本身判成违规。
    """
    src = (_SERVER_DIR / rel).read_text(encoding="utf-8")
    kept = [
        token
        for token in tokenize.generate_tokens(io.StringIO(src).readline)
        if token.type != tokenize.COMMENT
    ]
    tree = ast.parse(tokenize.untokenize(kept))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                first.value.value = ""
    return ast.unparse(tree)


# ══════════════════════════════════════════════════════════════════════════
# 守 1：三步顺序
# ══════════════════════════════════════════════════════════════════════════


async def test_version_lands_before_thread_is_resolved_and_state_is_untouched() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    calls: list[tuple[str, Any]] = []

    class _RecordingArtifacts(ArtifactService):
        async def add_version(self, artifact_: Any, content: Any, **kwargs: Any) -> Any:
            version = await super().add_version(artifact_, content, **kwargs)
            calls.append(("add_version", version.id))
            return version

    class _RecordingLifecycle(BlueprintLifecycleService):
        async def resolve_thread(self, thread_: Any, **kwargs: Any) -> Any:
            fresh = await Artifact.objects.aget(id=thread_.artifact_id)
            calls.append(("resolve_thread", fresh.current_version_id))
            return await super().resolve_thread(thread_, **kwargs)

        async def transition(self, *args: Any, **kwargs: Any) -> Any:
            calls.append(("transition", None))
            return await super().transition(*args, **kwargs)

    result = await aapply_thread_answers(
        artifact,
        threads=[thread],
        section_writer=_writer_touching(_BLOCK_X),
        artifact_service=_RecordingArtifacts(),
        lifecycle_service=_RecordingLifecycle(),
    )

    assert result["status"] == "applied"
    names = [name for name, _ in calls]
    assert names.count("add_version") == 1
    assert names.index("add_version") < names.index("resolve_thread")
    # resolve_thread 发生时 current_version 已经是新版本（版本先落地）
    assert str(dict(calls)["resolve_thread"]) == result["version_id"]
    # 本模块不碰状态机：transition 归调用方（拿到 applied 之后才转）
    assert "transition" not in names


# ══════════════════════════════════════════════════════════════════════════
# 守 2-3：decision_log 物化 + 同一问题不重复问（含会失败的对照）
# ══════════════════════════════════════════════════════════════════════════


async def test_decision_log_entry_keeps_the_answer_key() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)

    result = await aapply_thread_answers(artifact, threads=[thread], section_writer=_noop_writer)

    assert result["status"] == "applied"
    version = await ArtifactVersion.objects.aget(id=result["version_id"])
    entries = [
        item for item in version.content["decision_log"] if item["thread_id"] == str(thread.id)
    ]
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) >= {"thread_id", "question", "answer", "decided_at", "decided_by"}
    assert set(entry) == set(DECISION_LOG_KEYS)
    assert entry["answer"] == _ANSWER
    assert entry["question"] == _QUESTION
    assert entry["decided_at"]  # 取作答消息 created_at，非空


async def test_the_same_question_is_not_asked_twice() -> None:
    """复用读侧同一函数 ``_collect_prior_answers`` 断言指纹与问答文本都在。"""
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    result = await aapply_thread_answers(artifact, threads=[thread], section_writer=_noop_writer)
    version = await ArtifactVersion.objects.aget(id=result["version_id"])

    # 用**无线程**的干净 artifact 喂 content：指纹只能来自 decision_log 这一条路径
    clean = await _make_artifact()
    prior = await BlueprintSpecGateAdapter()._collect_prior_answers(clean, version.content)

    assert _QUESTION in prior["text"]
    assert _ANSWER in prior["text"]
    assert prior["fingerprints"]


async def test_renaming_answer_key_breaks_the_dedupe_chain() -> None:
    """⭐ 会失败的对照：``answer`` 改名成 ``decision`` ⇒ 重判 prompt 里读不到答案。"""
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    result = await aapply_thread_answers(artifact, threads=[thread], section_writer=_noop_writer)
    version = await ArtifactVersion.objects.aget(id=result["version_id"])

    broken = copy.deepcopy(version.content)
    for item in broken["decision_log"]:
        item["decision"] = item.pop("answer")

    clean = await _make_artifact()
    prior = await BlueprintSpecGateAdapter()._collect_prior_answers(clean, broken)

    assert _ANSWER not in prior["text"], "只写 decision 不写 answer 时答案不该还能被读到"


# ══════════════════════════════════════════════════════════════════════════
# 守 4-5：幂等 + 线程收尾与 applied_in_version
# ══════════════════════════════════════════════════════════════════════════


async def test_repeated_reflow_is_idempotent_and_does_not_bump_version() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    writer = _writer_touching(_BLOCK_X)

    first = await aapply_thread_answers(artifact, threads=[thread], section_writer=writer)
    after_first = await _version_count(artifact)
    second = await aapply_thread_answers(artifact, threads=[thread], section_writer=writer)

    assert first["status"] == "applied"
    assert second["status"] == "unchanged"
    assert second["version_id"] == first["version_id"]
    assert await _version_count(artifact) == after_first


async def test_thread_is_resolved_and_applied_in_version_is_the_baseline() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    base = await ArtifactVersion.objects.filter(artifact=artifact).order_by("-version_no").afirst()

    result = await aapply_thread_answers(
        artifact, threads=[thread], section_writer=_writer_touching(_BLOCK_X)
    )

    fresh = await BlueprintThread.objects.aget(id=thread.id)
    assert fresh.status == ThreadStatus.RESOLVED
    messages = await _message_bodies(thread.id)
    assert any(f"v{result['version_no']}" in body for body in messages)

    version = await ArtifactVersion.objects.aget(id=result["version_id"])
    entry = next(
        item for item in version.content["decision_log"] if item["thread_id"] == str(thread.id)
    )
    assert entry["applied_in_version"] == str(base.id)  # 基线版本 id（写入前已知、可重放稳定）
    # 产出版本的反查方式（115 消费面依赖）
    assert (
        await ArtifactVersion.objects.filter(
            artifact=artifact, produced_by_ref=f"{AI_REVIEW_REFLOW_PREFIX}{thread.id}"
        ).acount()
        == 1
    )

    # resolve_thread 幂等：再回灌一次不覆盖首次结论
    await aapply_thread_answers(
        artifact, threads=[fresh], section_writer=_writer_touching(_BLOCK_X)
    )
    assert await _message_bodies(thread.id) == messages


# ══════════════════════════════════════════════════════════════════════════
# 守 6：AI 不覆盖人工（正反并列）
# ══════════════════════════════════════════════════════════════════════════


async def _human_edit_block_x(artifact: Artifact) -> dict:
    user = await _make_user()
    return await aapply_block_edit(
        artifact,
        [
            {
                "op": "replace",
                "block_id": _BLOCK_X,
                "block": {
                    "block_id": _BLOCK_X,
                    "type": "paragraph",
                    "text": "人手写的实现说明：先查缓存再落库。",
                },
            }
        ],
        user=user,
    )


async def test_ai_never_overwrites_a_human_edited_block() -> None:
    artifact = await _make_artifact()
    edit = await _human_edit_block_x(artifact)
    assert edit["status"] == "applied"
    thread = await _answered_thread(artifact)
    before = await _version_count(artifact)
    threads_before = await BlueprintThread.objects.filter(artifact=artifact).acount()

    result = await aapply_thread_answers(
        artifact, threads=[thread], section_writer=_writer_touching(_BLOCK_X)
    )

    assert result["status"] == "conflict"
    assert result["conflict_block_ids"] == [_BLOCK_X]
    assert await _version_count(artifact) == before  # 冲突时零版本增长
    assert await BlueprintThread.objects.filter(artifact=artifact).acount() == threads_before + 1

    opened = await BlueprintThread.objects.aget(id=result["thread_id"])
    assert opened.kind == ThreadKind.AI_CLARIFICATION
    assert opened.blocking is True
    assert opened.return_stage == "ai_reviewing"
    body = await opened.messages.afirst()  # type: ignore[attr-defined]
    assert _BLOCK_X in body.body
    # question 只列 block_id 与裁决提示，**不贴两侧正文**（T-114-27）
    assert "人手写的实现说明" not in body.body
    assert "回灌后的新正文" not in body.body


async def test_ai_editing_an_untouched_block_is_applied() -> None:
    """对照：AI 改的是人工没碰过的块 ⇒ 正常落版本（证明冲突判据非恒真）。"""
    artifact = await _make_artifact()
    await _human_edit_block_x(artifact)
    thread = await _answered_thread(artifact)
    before = await _version_count(artifact)

    result = await aapply_thread_answers(
        artifact, threads=[thread], section_writer=_writer_touching(_BLOCK_Y)
    )

    assert result["status"] == "applied"
    assert result["conflict_block_ids"] == []
    assert await _version_count(artifact) == before + 1


# ══════════════════════════════════════════════════════════════════════════
# 守 7-8：fail-closed 与恒不抛
# ══════════════════════════════════════════════════════════════════════════


async def test_invalid_content_from_writer_is_fail_closed() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    before = await _version_count(artifact)

    async def _bad_writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        # 抹掉块的必填 `type` ⇒ jsonschema 失败
        content["implementation_overview"]["items"][0]["how"][0].pop("type", None)
        return content

    result = await aapply_thread_answers(artifact, threads=[thread], section_writer=_bad_writer)

    assert result["status"] == "invalid"
    assert result["detail"]
    assert await _version_count(artifact) == before  # 不落半合法版本、不落 failed


async def test_reflow_never_raises_on_empty_or_failing_inputs() -> None:
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)

    empty = await aapply_thread_answers(artifact, threads=[])
    assert empty["status"] == "noop"

    bare = await Artifact.objects.acreate(artifact_type="technical_plan")
    assert (await aapply_thread_answers(bare))["status"] == "noop"

    async def _raising_writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        raise RuntimeError("writer 崩了")

    # writer 抛异常 ⇒ 正文回落未改写，但答案照常物化并落版本（答案永不丢失）
    result = await aapply_thread_answers(artifact, threads=[thread], section_writer=_raising_writer)
    assert result["status"] == "applied"
    version = await ArtifactVersion.objects.aget(id=result["version_id"])
    assert any(item["thread_id"] == str(thread.id) for item in version.content["decision_log"])


# ══════════════════════════════════════════════════════════════════════════
# 守 12：⭐ 回灌链绝不消费 ai_review_finding（114-CR-01 回归）
# ══════════════════════════════════════════════════════════════════════════


async def _answered_finding(artifact: Artifact) -> BlueprintThread:
    """开一条 BLOCKER finding 线程并把它推到 ``answered``（CR-01 的攻击前提）。

    ``record_answer`` 在此**刻意**被用来复现「有人用作答通道碰了 finding」这一前提；
    被测的不变式是回灌链**即便拿到这样一条线程也绝不消费、绝不 resolve 它**。
    """
    from delivery.models import ThreadSeverity

    lifecycle = BlueprintLifecycleService()
    thread = await lifecycle.open_thread(
        artifact,
        kind=ThreadKind.AI_REVIEW_FINDING,
        severity=ThreadSeverity.BLOCKER,
        blocking=True,
        question="[citation_missing] 关键结论缺 citations",
        anchor={"section_path": "implementation_overview", "block_id": _BLOCK_X},
    )
    await lifecycle.record_answer(thread, body="知道了")
    return thread


async def test_reflow_never_consumes_an_explicitly_passed_finding_thread() -> None:
    """⭐ 显式 ``threads=[finding]`` 也必须被 kind 过滤掉（fail-closed，不靠调用方自觉）。

    这是 CR-01 的核心洞：answer 端点曾把 finding 线程直接交给回灌链，落版本成功后收尾
    分支无条件 ``resolve_thread`` ⇒ 一条 BLOCKER finding 被推到 ``resolved`` 终态，
    confirm 守卫两条判据同时失配，approve 白放行——且没有 ``reason``、没有
    ``[已修复]`` / ``[误报忽略]`` 语义、没有处置人留痕。
    """
    artifact = await _make_artifact()
    finding = await _answered_finding(artifact)
    before = await _version_count(artifact)

    result = await aapply_thread_answers(artifact, threads=[finding], section_writer=_noop_writer)

    assert result["status"] == "noop"
    assert await _version_count(artifact) == before
    # 线程状态逐字不变：既没被消费，也没被冒名处置
    assert (await BlueprintThread.objects.aget(id=finding.id)).status == ThreadStatus.ANSWERED


async def test_reflow_default_queryset_excludes_finding_threads() -> None:
    """第二入口：``threads=None`` 的默认查询集也不得含 ``ai_review_finding``。

    ai_review 入口 0-a 走的正是这条默认查询集——不堵它，任何以任何方式落到
    ``answered`` 的 finding 都会在下一轮审查入口被自动 ``resolved`` 掉。
    **对照**：同一 artifact 上并存的澄清线程仍被正常消费（证明过滤非恒真）。
    """
    artifact = await _make_artifact()
    finding = await _answered_finding(artifact)
    clarification = await _answered_thread(artifact, block_id=_BLOCK_Y)

    result = await aapply_thread_answers(artifact, section_writer=_noop_writer)

    assert result["status"] == "applied"
    assert result["thread_ids"] == [str(clarification.id)]
    assert (await BlueprintThread.objects.aget(id=finding.id)).status == ThreadStatus.ANSWERED
    assert (await BlueprintThread.objects.aget(id=clarification.id)).status == (
        ThreadStatus.RESOLVED
    )


# ══════════════════════════════════════════════════════════════════════════
# 守 9：零 ORM 写 + 零 record_answer 源码扫描
# ══════════════════════════════════════════════════════════════════════════


async def test_modules_have_no_orm_writes_and_no_record_answer() -> None:
    write_patterns = (
        r"BlueprintThread\.objects\.(?:a?create|a?update|bulk_update|bulk_create)",
        r"BlueprintThreadMessage\.objects\.(?:a?create|a?update)",
        r"BlueprintReviewer\.objects\.(?:a?create|a?update)",
        r"ArtifactVersion\.objects\.(?:a?create|a?update)",
        r"\brecord_answer\b",
    )
    for rel in _SCANNED_MODULES:
        code = _code_only(rel)
        for pattern in write_patterns:
            assert not re.search(pattern, code), f"{rel} 命中禁止写法 {pattern}"

    # 守护的守护：正则真的能命中这些写法（防扫描形同虚设）
    sample = 'BlueprintThread.objects.create(x=1)\nawait lifecycle.record_answer(t, body="")'
    assert any(re.search(pattern, sample) for pattern in write_patterns)


# ══════════════════════════════════════════════════════════════════════════
# 守 10：section_writer 默认走生产实现（B1）
# ══════════════════════════════════════════════════════════════════════════


async def test_default_section_writer_is_the_production_impl() -> None:
    """⭐ 不传 ``section_writer`` ⇒ ``ablock_section_writer`` 被调用（**默认不是 no-op**）。"""
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)
    seen: list[list[dict]] = []

    async def _spy(content: dict, answers: list[dict], *, session: Any = None) -> dict:
        seen.append(answers)
        return content

    with patch(_WRITER_TARGET, _spy):
        result = await aapply_thread_answers(artifact, threads=[thread])

    assert len(seen) == 1
    assert seen[0] and seen[0][0]["answer"] == _ANSWER
    assert seen[0][0]["anchor"]["block_id"] == _BLOCK_X
    assert result["status"] == "applied"


async def test_answers_survive_a_no_op_section_writer() -> None:
    """段落未被改写也不丢答案：``decision_log`` 照常物化、线程照常 ``resolved``。"""
    artifact = await _make_artifact()
    thread = await _answered_thread(artifact)

    with patch(_WRITER_TARGET, _noop_writer):
        result = await aapply_thread_answers(artifact, threads=[thread])

    assert result["status"] == "applied"
    version = await ArtifactVersion.objects.aget(id=result["version_id"])
    assert any(item["thread_id"] == str(thread.id) for item in version.content["decision_log"])
    assert (await BlueprintThread.objects.aget(id=thread.id)).status == ThreadStatus.RESOLVED


async def test_block_section_writer_keeps_content_verbatim_without_default_model() -> None:
    """LLM 不可得 ⇒ 该块原样保留：返回 content 与入参逐字相等（不抛、不清空）。"""
    content = make_blueprint()
    snapshot = copy.deepcopy(content)
    answers = [
        {
            "thread_id": "t1",
            "question": _QUESTION,
            "answer": _ANSWER,
            "anchor": {"block_id": _BLOCK_X},
        }
    ]

    with patch(_ARESOLVE, AsyncMock(return_value=_resolved(""))):
        result = await ablock_section_writer(content, answers)

    assert result == snapshot
    assert content == snapshot  # 入参也不被原地修改


async def test_block_section_writer_rewrites_target_block_keeping_block_id() -> None:
    content = make_blueprint()
    snapshot = copy.deepcopy(content)
    answers = [
        {
            "thread_id": "t1",
            "question": _QUESTION,
            "answer": _ANSWER,
            "anchor": {"block_id": _BLOCK_X},
        }
    ]
    model = _model_returning(json.dumps({"text": "改写后的正文：失败即回落静态题库。"}))

    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        result = await ablock_section_writer(content, answers)

    target = next(
        block
        for block in result["implementation_overview"]["items"][0]["how"]
        if block["block_id"] == _BLOCK_X
    )
    assert target["text"] == "改写后的正文：失败即回落静态题库。"
    assert target["block_id"] == _BLOCK_X  # 逐字不变（改 id 会打散该块上的线程 anchor）
    assert target["type"] == "paragraph"
    assert content == snapshot


async def test_block_section_writer_respects_the_rewrite_upper_bound() -> None:
    from services.process_runtime.blueprint_schema import iter_blocks

    content = make_blueprint()
    paragraph_ids = [
        block["block_id"]
        for _path, block in iter_blocks(content)
        if isinstance(block.get("text"), str)
    ][: _MAX_REWRITE_BLOCKS + 2]
    assert len(paragraph_ids) == _MAX_REWRITE_BLOCKS + 2
    answers = [
        {
            "thread_id": f"t{i}",
            "question": _QUESTION,
            "answer": _ANSWER,
            "anchor": {"block_id": bid},
        }
        for i, bid in enumerate(paragraph_ids)
    ]
    model = _model_returning(json.dumps({"text": "统一改写正文。"}))

    with (
        patch(_ARESOLVE, AsyncMock(return_value=_resolved())),
        patch(_BUILD, return_value=model),
    ):
        result = await ablock_section_writer(content, answers)

    rewritten = {
        block["block_id"]
        for _path, block in iter_blocks(result)
        if block.get("text") == "统一改写正文。"
    }
    assert rewritten == set(paragraph_ids[:_MAX_REWRITE_BLOCKS])


# ══════════════════════════════════════════════════════════════════════════
# 守 11：人工块保护三态（B3）
# ══════════════════════════════════════════════════════════════════════════


async def test_restore_human_blocks_keeps_equivalent_blocks_without_new_version() -> None:
    """等价 ⇒ ``unchanged``、无冲突、版本行数不变。"""
    artifact = await _make_artifact()
    await _human_edit_block_x(artifact)
    before = await _version_count(artifact)

    result = await arestore_human_blocks(artifact)

    assert result["status"] == "unchanged"
    assert result["conflicted"] == []
    assert result["thread_id"] == ""
    assert await _version_count(artifact) == before


async def test_restore_human_blocks_writes_back_conflicting_block_and_opens_thread() -> None:
    """⭐ B3 头号断言：重装抹掉人工块后，新版本的该块与人工版本**逐字相等**且有阻塞线程。"""
    artifact = await _make_artifact()
    edit = await _human_edit_block_x(artifact)
    human_version = await ArtifactVersion.objects.aget(id=edit["version_id"])
    human_block = next(
        block
        for block in human_version.content["implementation_overview"]["items"][0]["how"]
        if block["block_id"] == _BLOCK_X
    )

    # 模拟打回后 repo_rework / remerge 重装：块 X 被 AI 写成了别的内容
    remerged = copy.deepcopy(human_version.content)
    for block in remerged["implementation_overview"]["items"][0]["how"]:
        if block["block_id"] == _BLOCK_X:
            block["text"] = "AI 重装后的实现说明：直接落库。"
    await ArtifactService().add_version(artifact, remerged, produced_by_ref="blueprint_merge")
    before = await _version_count(artifact)

    result = await arestore_human_blocks(artifact)

    assert result["status"] == "conflict"
    assert result["conflicted"] == [_BLOCK_X]
    assert result["preserved"] == [_BLOCK_X]
    assert await _version_count(artifact) == before + 1

    restored = await ArtifactVersion.objects.aget(id=result["version_id"])
    # 归属可审计：第三个前缀 + 被保护时的基线版本号（v1 建 / v2 人工编辑 / v3 重装）
    assert restored.produced_by_ref == "human_block_restore:3"
    assert restored.produced_by_ref.startswith(HUMAN_BLOCK_RESTORE_PREFIX)
    restored_block = next(
        block
        for block in restored.content["implementation_overview"]["items"][0]["how"]
        if block["block_id"] == _BLOCK_X
    )
    assert restored_block == human_block  # 人工编辑未被抹掉

    opened = await BlueprintThread.objects.aget(id=result["thread_id"])
    assert opened.kind == ThreadKind.AI_CLARIFICATION
    assert opened.blocking is True
    assert opened.return_stage == "ai_reviewing"
    body = await opened.messages.afirst()  # type: ignore[attr-defined]
    assert _BLOCK_X in body.body
    assert "人手写的实现说明" not in body.body  # 不贴两侧正文
    assert "AI 重装后的实现说明" not in body.body


async def test_restore_human_blocks_is_noop_without_any_human_version() -> None:
    """无 ``human_edit:`` 版本 ⇒ ``noop``、零副作用（证明前两条断言非恒真）。"""
    artifact = await _make_artifact()
    before = await _version_count(artifact)
    threads_before = await BlueprintThread.objects.filter(artifact=artifact).acount()

    result = await arestore_human_blocks(artifact)

    assert result["status"] == "noop"
    assert result["preserved"] == [] and result["conflicted"] == []
    assert await _version_count(artifact) == before
    assert await BlueprintThread.objects.filter(artifact=artifact).acount() == threads_before


async def test_collect_human_block_ids_is_sorted_and_deterministic() -> None:
    artifact = await _make_artifact()
    user = await _make_user()
    await _human_edit_block_x(artifact)
    await aapply_block_edit(
        artifact,
        [
            {
                "op": "replace",
                "block_id": _BLOCK_Y,
                "block": {"block_id": _BLOCK_Y, "type": "paragraph", "text": "人手写的前端说明。"},
            }
        ],
        user=user,
    )

    assert await acollect_human_block_ids(artifact) == sorted([_BLOCK_X, _BLOCK_Y])
    assert await acollect_human_block_ids(await _make_artifact()) == []


async def test_collect_human_block_ids_tolerates_a_null_supersedes() -> None:
    """首版即人工编辑（``supersedes is None``）不抛，保护集回落成全文。"""
    artifact = await ArtifactService().create(
        "technical_plan", make_blueprint(), produced_by_ref="human_edit:u-first"
    )

    protected = await acollect_human_block_ids(artifact)

    assert _BLOCK_X in protected
    assert protected == sorted(protected)


# ══════════════════════════════════════════════════════════════════════════
# 纯函数节自证（无 DB 依赖）
# ══════════════════════════════════════════════════════════════════════════


async def test_build_decision_entries_projection_and_dedupe() -> None:
    from django.utils import timezone

    stamp = timezone.now()
    payload = [
        {
            "thread_id": "t1",
            "anchor": {"block_id": _BLOCK_X},
            "applied_in_version": "v-base",
            "messages": [
                {"author_type": "ai", "body": _QUESTION, "created_at": stamp},
                {"author_type": "human", "body": "先这样", "created_at": stamp, "author_id": 7},
                {"author_type": "human", "body": "再补一句", "created_at": stamp},
            ],
        },
        {"thread_id": "t2", "messages": [{"author_type": "ai", "body": "无人作答"}]},
        {"thread_id": "", "messages": []},
        "不是 dict",
    ]

    entries = build_decision_entries(payload)  # type: ignore[arg-type]

    assert [entry["thread_id"] for entry in entries] == ["t1"]  # 无答案的线程整条丢弃
    assert entries[0]["answer"] == "先这样；再补一句"
    assert entries[0]["decided_by"] == "7"
    assert entries[0]["decided_at"] == stamp.isoformat()
    assert entries[0]["applied_in_version"] == "v-base"

    merged = merge_decision_log([{"thread_id": "t0", "question": "旧问题"}], entries)
    assert [item["thread_id"] for item in merged] == ["t0", "t1"]
    assert set(merged[1]) == set(DECISION_LOG_KEYS)  # anchor 被投影掉，不入文档
    # 幂等：同 thread_id 再合并不堆积
    assert merge_decision_log(merged, entries) == merged
    assert merge_decision_log(None, []) == []


async def test_detect_human_conflicts_returns_the_intersection_only() -> None:
    base = make_blueprint()

    human = copy.deepcopy(base)
    human["implementation_overview"]["items"][0]["how"][0]["text"] = "人改的 X"
    ai_same = copy.deepcopy(human)
    ai_same["implementation_overview"]["items"][0]["how"][0]["text"] = "AI 也改 X"
    ai_other = copy.deepcopy(human)
    ai_other["implementation_overview"]["items"][1]["how"][0]["text"] = ["AI 改的 Y"]

    assert detect_human_conflicts(
        human_version_content=human, human_base_content=base, ai_new_content=ai_same
    ) == [_BLOCK_X]
    assert (
        detect_human_conflicts(
            human_version_content=human, human_base_content=base, ai_new_content=ai_other
        )
        == []
    )
