"""blueprint_reflow —— 澄清答案回灌 + 人工块保护（Phase 114-04，CLAR-02/CLAR-03）。

四段契约（改动前先读）：

1. **本模块把已作答的澄清/审查线程消费成新版本**：改 content → ``add_version`` →
   ``transition``，**顺序固定为「先落版本再转状态」**。反了会出现「状态已 ``drafting``
   而内容仍是旧版」的窗口，AI 在这个窗口里会拿旧内容重跑，答案等于没回灌。
   （本模块只负责前两步与线程收尾；``transition`` 由调用方 114-03/114-05 在拿到
   ``status == "applied"`` 后发起，故本模块**不碰状态机**。）
2. **INV-6：本模块零 ORM 写**。线程（开/收尾/留痕）一律经 ``BlueprintLifecycleService``，
   版本一律经 ``ArtifactService``；本模块只做**只读**查询装配。留痕通道只有
   ``append_note``/``resolve_thread``——⛔ **绝不用** ``record_answer``（它会把 ``open``
   推到 ``answered``，让 confirm 守卫与续驱 pause 判据失真，见 114-01）。
3. **AI 不覆盖人工**（镜像 ``ProjectContextLink`` 的「AI 不覆盖人工」原则），两条链路：

   - **回灌侧**（:func:`aapply_thread_answers`）：落版本前用
     :func:`detect_human_conflicts` 算「人工改过的 block」与「本轮 AI 将改写的 block」
     的交集，非空 ⇒ **不写版本**，改开阻塞线程询问；
   - **重装侧**（:func:`arestore_human_blocks`，B3）：打回后 ``repo_rework``/``remerge``
     重跑 merge 是**主要产版本路径**，回灌侧的检测挡不住它 ⇒ 以
     :func:`acollect_human_block_ids` 求保护集，逐块 canonical JSON 比对，等价则保留、
     实质冲突则**把人工块写回并开阻塞线程**，绝不静默覆盖。

4. **幂等**：``decided_at`` 取**线程作答消息的 ``created_at``** 而非 ``timezone.now()``。
   回灌是**可重放路径**，时间戳每次变会改 ``content_hash``（``sort_keys=True`` 只消除
   key 顺序的影响，不消除值的影响）⇒ 每次回灌都翻一版新版本，「同 hash 不翻版本」的
   幂等意图被破坏、版本历史被刷成噪声、diff 视图不可用（T-114-25）。

``produced_by_ref`` 三前缀对照（本相位的全部归属通道，115/116 消费面按此反查）：

======================  ====================================================
前缀                    产出方
======================  ====================================================
``human_edit:``         :func:`blueprint_block_edit.aapply_block_edit`（人工编辑）
``ai_review_reflow:``   :func:`aapply_thread_answers`（澄清答案回灌）
``human_block_restore:``:func:`arestore_human_blocks`（重装后人工块保护）
======================  ====================================================
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text
from delivery.models import (
    ArtifactVersion,
    BlueprintThread,
    BlueprintThreadMessage,
    ThreadAuthorType,
    ThreadKind,
    ThreadStatus,
)
from delivery.services.blueprint_anchor import _block_text
from services.process_runtime.blueprint_schema import diff_blueprint_blocks, iter_blocks

logger = structlog.get_logger(__name__)

__all__ = [
    "HUMAN_EDIT_PREFIX",
    "AI_REVIEW_REFLOW_PREFIX",
    "HUMAN_BLOCK_RESTORE_PREFIX",
    "DECISION_LOG_KEYS",
    "REFLOW_KINDS",
    "build_decision_entries",
    "merge_decision_log",
    "detect_human_conflicts",
    "ablock_section_writer",
    "aapply_thread_answers",
    "acollect_human_block_ids",
    "arestore_human_blocks",
]

# produced_by_ref 三前缀（见模块 docstring 对照表）
HUMAN_EDIT_PREFIX = "human_edit:"
AI_REVIEW_REFLOW_PREFIX = "ai_review_reflow:"
HUMAN_BLOCK_RESTORE_PREFIX = "human_block_restore:"

# 冲突线程的恢复目标（`BlueprintThread.return_stage` max_length=16，本值 12 字符）
RETURN_STAGE_AI_REVIEWING = "ai_reviewing"

# ⭐ 回灌链**唯一**允许消费的线程 kind（114-CR-01 收口）。
#
# `ai_review_finding` **刻意不在内**：回灌链落版本成功后会对全部被消费线程无条件
# `resolve_thread`，那是终态、离开 confirm 守卫判据集合。让 finding 进来即等于「在
# finding 上回一句任意文本」就能解开 confirm 门——而 finding 的处置在设计上必须经
# `blueprint_review_action._adispose_finding`（强制 `reason`、写 `[已修复]` /
# `[误报忽略]` 标签与「处置人：{uid}」、`first_action=finding_resolve/dismiss`）。
# 更根本的一条：回答一条「关键结论缺 citations」的 finding 并不等于补上了 citations。
REFLOW_KINDS: tuple[str, ...] = (ThreadKind.AI_CLARIFICATION,)

# decision_log 条目键集：规格门形状 `{thread_id, question, answer, decided_at,
# decided_by}`（`blueprint_spec_gate._merge_decision_log:497-510`）的**超集**，多一个
# `applied_in_version`。⚠️ 必须保 `answer` 键——读侧 `_collect_prior_answers:587` 读的
# 是 `item.get("answer")`，只写 `decision` 会让「同一问题不再重复问」在审查阶段断链。
DECISION_LOG_KEYS: tuple[str, ...] = (
    "thread_id",
    "question",
    "answer",
    "decided_at",
    "decided_by",
    "applied_in_version",
)

# 段落重产上界（B1）：一轮最多改写几块 / prompt 裁剪 / 回写截断
_MAX_REWRITE_BLOCKS = 5
_MAX_BLOCK_PROMPT_CHARS = 4000
_MAX_REWRITTEN_TEXT_CHARS = 4000
_MAX_QA_PROMPT_CHARS = 2000
_MAX_DETAIL_CHARS = 500
# 冲突线程 question 里最多列几个 block_id（正文一律不贴，T-114-27）
_MAX_CONFLICT_IDS = 20


# ══════════════════════════════════════════════════════════════════════════
# 纯函数节（无 IO / 无 ORM / 无 LLM）
# ══════════════════════════════════════════════════════════════════════════


def _canonical(node: Any) -> str:
    """canonical JSON 口径与 ``artifact_service._content_hash`` 同源（sha256 之前那步）。

    人工块「是否仍在」的判据用它而不是 ``==``：dict 的 ``==`` 对键顺序不敏感但对
    数值类型敏感（``1`` vs ``1.0``），而 JSON 往返后类型可能变；canonical 串比对与
    「同 hash 不翻版本」的判据同源，两处不会各说各话。
    """
    return json.dumps(node, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def build_decision_entries(threads_payload: list[dict]) -> list[dict]:
    """把线程消息流投影成 ``decision_log`` 条目 + 段落重产所需的 ``anchor``。

    每个 payload 形状 ``{thread_id, anchor, applied_in_version, decided_by?, messages}``，
    ``messages`` 为 ``{author_type, body, author_id, created_at}`` 的有序列表
    （``BlueprintThreadMessage.ordering = ["created_at"]``）。

    投影口径（逐条对齐 ``blueprint_spec_gate._collect_prior_answers:544-577``）：

    - ``question``：**首条** ``author_type == "ai"`` 的消息 body（线程首条即 AI 提问，
      ``_open_thread_sync`` 保证）；
    - ``answer``：**全部** ``author_type == "human"`` 消息 body 的 ``"；".join``；
    - ``decided_at``：**最后一条 human 消息的 ``created_at``**（不是 ``timezone.now()``
      —— 见模块 docstring 第 4 段的幂等推论）；
    - ``decided_by``：默认 ``"human"``；有 ``author_id`` 取其 str；AI 侧作答由调用方在
      payload 里传 ``decided_by="ai"``；
    - ``applied_in_version``：由调用方给**基线版本 id**（见
      :func:`aapply_thread_answers` docstring 的落地口径）。

    ``answer`` 为空的线程整条丢弃（无答案不成决策）。``anchor`` 只随条目传给段落重产
    writer，**不进 ``decision_log``**（:func:`merge_decision_log` 会投影掉它）。
    """
    entries: list[dict] = []
    for payload in threads_payload or []:
        if not isinstance(payload, dict):
            continue
        thread_id = str(payload.get("thread_id") or "")
        if not thread_id:
            continue
        question = ""
        answers: list[str] = []
        decided_by = str(payload.get("decided_by") or "human")
        decided_at = ""
        for message in payload.get("messages") or []:
            if not isinstance(message, dict):
                continue
            body = str(message.get("body") or "").strip()
            if not body:
                continue
            if str(message.get("author_type") or "") == ThreadAuthorType.AI:
                if not question:
                    question = body
                continue
            answers.append(body)
            if message.get("author_id"):
                decided_by = str(message["author_id"])
            created_at = message.get("created_at")
            stamp = (
                created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else str(created_at or "")
            )
            if stamp:
                decided_at = stamp
        answer = "；".join(answers)
        if not answer:
            continue
        anchor = payload.get("anchor")
        entries.append(
            {
                "thread_id": thread_id,
                "question": question,
                "answer": answer,
                "decided_at": decided_at,
                "decided_by": decided_by,
                "applied_in_version": str(payload.get("applied_in_version") or ""),
                "anchor": anchor if isinstance(anchor, dict) else None,
            }
        )
    return entries


def merge_decision_log(existing: Any, entries: list[dict]) -> list[Any]:
    """按 ``thread_id`` 去重追加决策条目（幂等重跑不重复堆积）。

    去重逻辑口径同源 ``blueprint_spec_gate._merge_decision_log:497-510`` —— 两处漂移会
    让同一线程在导出时出现两条互相矛盾的决策。

    追加时按 :data:`DECISION_LOG_KEYS` 投影：``anchor`` 等版本相关的定位信息**不入
    文档**（它随重锚定漂移，写进 content 会让同一决策在不同版本下 hash 不同，破坏
    「同 hash 不翻版本」）。
    """
    merged = list(existing) if isinstance(existing, list) else []
    seen = {
        str(item.get("thread_id"))
        for item in merged
        if isinstance(item, dict) and item.get("thread_id")
    }
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        thread_id = str(entry.get("thread_id") or "")
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        merged.append({key: entry.get(key, "") for key in DECISION_LOG_KEYS})
    return merged


def detect_human_conflicts(
    *,
    human_version_content: Any,
    human_base_content: Any,
    ai_new_content: Any,
) -> list[str]:
    """AI 不覆盖人工的判据：返回「人工改过 ∩ AI 将改写」的 block_id 升序列表。

    - ``human_changed`` = ``diff_blueprint_blocks(human_base_content, human_version_content)``
      的 ``added ∪ removed ∪ modified``——人工版本相对它 ``supersedes`` 的那一版改过什么。
      人工版本的「前一版」经 ``ArtifactVersion.supersedes`` 取，``produced_by_ref`` 以
      :data:`HUMAN_EDIT_PREFIX` 开头才算人工版本（``ArtifactVersion`` **无**
      ``created_by_user_id``，前缀是全仓唯一的人工归属通道）。
    - ``ai_changed`` = 同上 of ``diff_blueprint_blocks(human_version_content, ai_new_content)``。

    交集非空 ⇒ AI 要改的正是人手动改过的块 ⇒ 调用方**不写版本**，改开阻塞线程询问。
    交集为空 ⇒ 两边改的是不同块，正常合并（判据非恒真，Task 3 第 6 条配了对照用例）。
    """
    human_diff = diff_blueprint_blocks(human_base_content, human_version_content)
    ai_diff = diff_blueprint_blocks(human_version_content, ai_new_content)
    human_changed = (
        set(human_diff["added"]) | set(human_diff["removed"]) | set(human_diff["modified"])
    )
    ai_changed = set(ai_diff["added"]) | set(ai_diff["removed"]) | set(ai_diff["modified"])
    return sorted(human_changed & ai_changed)


def _conflict_question(block_ids: list[str], *, scene: str) -> str:
    """冲突线程的提问文案：**只列 block_id 与裁决提示，绝不贴两侧正文**（T-114-27）。"""
    listed = "、".join(block_ids[:_MAX_CONFLICT_IDS])
    more = "…" if len(block_ids) > _MAX_CONFLICT_IDS else ""
    return (
        f"{scene}与人工编辑存在冲突，涉及内容块：{listed}{more}。"
        "已保留人工版本，请裁决是否采纳 AI 的修订。"
    )


def _content_to_text(content: Any) -> str:
    """LangChain ``message.content`` 归一为文本（口径同源 ``blueprint_review``）。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "".join(parts)
    return str(content or "")


def _parse_object_json(text: str) -> dict[str, Any] | None:
    """从 LLM 文本中健壮提取顶层 JSON 对象（``` 围栏 + 裸 JSON 双路），失败返 ``None``。"""
    candidates: list[str] = re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    candidates.append(text)
    for block in candidates:
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return None


def _write_block_text(block: dict, text: str) -> bool:
    """把改写后的正文写回块，返回是否写成功；``block_id`` / ``type`` **逐字不变**。

    落位口径与 ``blueprint_anchor._block_text`` 的**读侧**镜像：``text`` 为 str 直写、
    为 list 按行重建、``code.source`` 直写。table 型（``rows``）**不由 LLM 改写**——
    行列语义容易被打乱成不可对齐的表格，宁可原样保留。

    ⚠️ 绝不改 ``block_id``：改 id 会把该块上的全部线程 anchor 打散（重锚定退化成
    quoted_text 模糊匹配甚至失锚）。
    """
    raw = block.get("text")
    if isinstance(raw, str):
        block["text"] = text
        return True
    if isinstance(raw, list):
        lines = [line for line in text.splitlines() if line.strip()]
        block["text"] = lines or [text]
        return True
    code = block.get("code")
    if isinstance(code, dict) and isinstance(code.get("source"), str):
        code["source"] = text
        return True
    return False


def _section_writer_system_prompt() -> str:
    return (
        "你是技术蓝图的段落改写助手。用户会给你一个内容块的原文，以及一条已被回答的"
        "澄清问题与答案。请把答案的结论**融进原文**，产出改写后的完整正文。\n"
        "要求：① 只改写这一个块，不要新增小节标题；② 保持原文的语言（中文）与体例；"
        "③ 不要输出解释、不要输出 markdown 围栏之外的多余内容；"
        '④ 严格输出 JSON：{"text": "改写后的完整正文"}。'
    )


def _section_writer_prompt(original: str, entry: dict) -> str:
    question = str(entry.get("question") or "")[:_MAX_QA_PROMPT_CHARS]
    answer = str(entry.get("answer") or "")[:_MAX_QA_PROMPT_CHARS]
    return (
        f"## 原文\n{original}\n\n"
        f"## 已澄清的问题\n{question}\n\n"
        f"## 用户给出的答案\n{answer}\n\n"
        "请输出改写后正文的 JSON。"
    )


# ══════════════════════════════════════════════════════════════════════════
# 段落重产（B1：`aapply_thread_answers` 的默认 section_writer 生产实现）
# ══════════════════════════════════════════════════════════════════════════


async def _arewrite_block_text(model: Any, block: dict, entry: dict) -> str:
    """单块单次 LLM 改写，返回新正文；任何不可用情形返回空串（⇒ 该块原样保留）。"""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source

        original = _block_text(block)[:_MAX_BLOCK_PROMPT_CHARS]
        messages = [
            SystemMessage(content=_section_writer_system_prompt()),
            HumanMessage(content=_section_writer_prompt(original, entry)),
        ]
        with use_call_source(CallSource.BLUEPRINT_AI_REVIEW):
            response = await model.ainvoke(messages)
        parsed = _parse_object_json(_content_to_text(getattr(response, "content", "")))
        if not isinstance(parsed, dict):
            return ""
        text = parsed.get("text")
        if not isinstance(text, str) or not text.strip():
            return ""
        return text.strip()[:_MAX_REWRITTEN_TEXT_CHARS]
    except Exception as exc:  # noqa: BLE001 — 单块失败只影响该块正文，不牵连整轮
        logger.warning(
            "blueprint_reflow_block_rewrite_failed",
            category="sampling",
            component="process_runtime",
            block_id=str(block.get("block_id") or ""),
            error=redact_secrets_in_text(str(exc)),
        )
        return ""


async def ablock_section_writer(content: dict, answers: list[dict], *, session: Any = None) -> dict:
    """按 ``anchor.block_id`` 逐块改写蓝图正文，返回**新的 content dict**（B1 生产实现）。

    这是 :func:`aapply_thread_answers` 的**默认** ``section_writer``：
    ``section_writer=None`` ⇒ 用它。⚠️ 它**不是** no-op —— 若默认为 no-op，答案只进
    ``decision_log`` 而蓝图正文永不更新，「答案回灌产新版本」就只剩一条日志行，等于
    答案不落地（T-114-23c）。测试要 no-op 时**显式注入桩**，不要靠默认值。

    行为：

    - 入参 ``content`` **不被原地修改**（内部先 ``deepcopy``）；
    - 逐条按 ``entry["anchor"]["block_id"]`` 用 ``iter_blocks`` 定位块；**找不到就跳过**
      （只记 warning，**不新建块**——凭 LLM 猜落位是把答案写到错误段落的最快路径）；
    - 单块单次 LLM 改写（``call_source=CallSource.BLUEPRINT_AI_REVIEW``、
      ``streaming=False``），一轮最多改写 :data:`_MAX_REWRITE_BLOCKS` 块，超出的答案
      只进 ``decision_log`` 并记 warning；
    - ``block_id`` / ``type`` 逐字不变（见 :func:`_write_block_text`）。

    **best-effort 但不静默丢答案**：LLM 不可得（无 ``default_model``）/ 响应不可解析 /
    块找不到 / 整体异常 ⇒ 该块（或全部块）**正文原样保留**，而 ``decision_log`` 物化与
    线程收尾照常由 :func:`aapply_thread_answers` 完成 ⇒ 答案永远可追溯。
    """
    started = time.monotonic()
    target: dict = copy.deepcopy(content) if isinstance(content, dict) else {}
    rewritten = 0
    skipped = 0
    try:
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        pending = [entry for entry in (answers or []) if isinstance(entry, dict)]
        if not pending:
            return target
        block_by_id = {
            str(block.get("block_id")): block
            for _path, block in iter_blocks(target)
            if block.get("block_id")
        }

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "blueprint_reflow_section_writer_no_default_model",
                category="sampling",
                component="process_runtime",
                session_id=str(getattr(session, "id", "") or ""),
                answer_count=len(pending),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return target

        model = build_chat_model(resolved, model_name, streaming=False)
        for entry in pending:
            anchor = entry.get("anchor")
            block_id = str(anchor.get("block_id") or "") if isinstance(anchor, dict) else ""
            block = block_by_id.get(block_id)
            if block is None or rewritten >= _MAX_REWRITE_BLOCKS:
                skipped += 1
                continue
            new_text = await _arewrite_block_text(model, block, entry)
            if not new_text or not _write_block_text(block, new_text):
                skipped += 1
                continue
            rewritten += 1

        logger.info(
            "blueprint_reflow_section_rewritten",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "") or ""),
            block_count=len(block_by_id),
            rewritten_count=rewritten,
            skipped_count=skipped,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return target
    except Exception as exc:  # noqa: BLE001 — 段落重产失败只让正文原样，答案照常留痕
        logger.warning(
            "blueprint_reflow_section_rewrite_failed",
            category="sampling",
            component="process_runtime",
            session_id=str(getattr(session, "id", "") or ""),
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return copy.deepcopy(content) if isinstance(content, dict) else {}


# ══════════════════════════════════════════════════════════════════════════
# 只读装配 helper（adapter 允许直查，但零 ORM 写 —— INV-6）
# ══════════════════════════════════════════════════════════════════════════


async def _aload_latest_version(artifact: Any) -> Any:
    """基线一律取**最新** ``version_no``（带 ``supersedes``，防 async 裸 lazy-FK）。

    ⛔ **绝不读** ``session.current_artifact_version``：上游 ``add_version`` 已推进
    ``current_version``，而 session 钉住的那一版只在显式 ``StageOutcome`` 里才更新——
    读 session 那一版会把上游成果覆盖回旧内容（``blueprint_confirm_gate.py:546-550``
    同源坑，T-114-31）。
    """
    return await (
        ArtifactVersion.objects.select_related("supersedes")
        .filter(artifact=artifact)
        .order_by("-version_no")
        .afirst()
    )


async def _alatest_human_version(artifact: Any) -> Any:
    """取最近一条人工编辑版本（``produced_by_ref`` 带 :data:`HUMAN_EDIT_PREFIX`）。"""
    return await (
        ArtifactVersion.objects.select_related("supersedes")
        .filter(artifact=artifact, produced_by_ref__startswith="human_edit:")
        .order_by("-version_no")
        .afirst()
    )


async def _aload_thread_payloads(
    artifact: Any, threads: Any, applied_in_version: str
) -> tuple[list, list[dict]]:
    """装配待消费线程与其消息流（只读）。

    ``threads is None`` ⇒ 查该 artifact 上 ``status=answered`` 且 ``kind`` 落在
    :data:`REFLOW_KINDS` 的线程；显式传入（含 ``[]``）则**同样按 ``kind`` 过滤**——
    ``threads=[]`` 是「本轮没有要消费的线程」的合法表达，不能被回落成全量查询。

    ⭐ **``kind`` 过滤对显式入参也生效（fail-closed，不依赖调用方自觉）**：回灌链落版本
    成功后会对全部被消费线程无条件 ``resolve_thread``，而 ``resolved`` 是终态、离开
    confirm 守卫判据集合。一旦让 ``ai_review_finding`` 进到这里，「在 finding 上回一句
    任意文本」就等于把一条 BLOCKER 推到终态、放开 confirm 门——绕开 ``reason`` 必填、
    绕开 ``[已修复]`` / ``[误报忽略]`` 的语义区分、绕开「处置人：{uid}」的归因留痕
    （114-CR-01）。finding 的处置**只**走 ``aresolve_finding`` / ``adismiss_finding``。
    """
    if threads is None:
        rows = [
            row
            async for row in BlueprintThread.objects.filter(
                artifact=artifact,
                status=ThreadStatus.ANSWERED,
                kind__in=list(REFLOW_KINDS),
            ).order_by("created_at")
        ]
    else:
        rows = [
            row
            for row in threads
            if row is not None and str(getattr(row, "kind", "") or "") in REFLOW_KINDS
        ]
    if not rows:
        return ([], [])

    grouped: dict[str, list[dict]] = {}
    async for message in (
        BlueprintThreadMessage.objects.filter(thread_id__in=[row.id for row in rows])
        .order_by("thread_id", "created_at")
        .values("thread_id", "author_type", "body", "author_id", "created_at")
    ):
        grouped.setdefault(str(message["thread_id"]), []).append(dict(message))

    payloads = [
        {
            "thread_id": str(row.id),
            "anchor": row.anchor if isinstance(row.anchor, dict) else None,
            "applied_in_version": applied_in_version,
            "messages": grouped.get(str(row.id), []),
        }
        for row in rows
    ]
    return (rows, payloads)


def _reflow_result(
    status: str,
    *,
    version_id: str = "",
    version_no: int = 0,
    thread_ids: list[str] | None = None,
    conflict_block_ids: list[str] | None = None,
    thread_id: str = "",
    detail: str = "",
) -> dict:
    """回灌恒定七键返回（下游无需判空分支）。"""
    return {
        "status": status,
        "version_id": version_id,
        "version_no": version_no,
        "thread_ids": list(thread_ids or []),
        "conflict_block_ids": list(conflict_block_ids or []),
        "thread_id": thread_id,
        "detail": str(detail or "")[:_MAX_DETAIL_CHARS],
    }


def _restore_result(
    status: str,
    *,
    preserved: list[str] | None = None,
    conflicted: list[str] | None = None,
    thread_id: str = "",
    version_id: str = "",
    version_no: int = 0,
) -> dict:
    """人工块保护恒定六键返回（下游无需判空分支）。"""
    return {
        "status": status,
        "preserved": list(preserved or []),
        "conflicted": list(conflicted or []),
        "thread_id": thread_id,
        "version_id": version_id,
        "version_no": version_no,
    }


# ══════════════════════════════════════════════════════════════════════════
# 澄清答案回灌三步链
# ══════════════════════════════════════════════════════════════════════════


async def aapply_thread_answers(
    artifact: Any,
    *,
    threads: Any = None,
    session: Any = None,
    initiated_by_user_id: str = "system",
    section_writer: Any = None,
    artifact_service: Any = None,
    lifecycle_service: Any = None,
) -> dict:
    """把已作答线程消费成新版本（CLAR-02），恒定七键返回。

    ``status`` 五值语义：

    ==============  ==========================================================
    status          语义
    ==============  ==========================================================
    ``applied``     已落新版本 + 线程 ``resolved`` + 已重锚定
    ``unchanged``   同 ``content_hash`` 复用 current ⇒ **不翻版本**、不重复 resolve、
                    不重复重锚（重放安全）
    ``conflict``    AI 将改写的块与人工编辑冲突 ⇒ **不落版本**，已开阻塞线程询问，
                    ``conflict_block_ids`` / ``thread_id`` 可回显
    ``invalid``     改写后 content 不过 artifact 校验 ⇒ **不落版本、不落半合法版本、
                    不落 failed**；或整体异常（``detail == "reflow_failed"``）
    ``noop``        无版本 / 无待消费线程 / 无有效答案 ⇒ 什么都没做
    ==============  ==========================================================

    七步（顺序固定，照 ``blueprint_confirm_gate.alock``）：读最新版本作基线 → 装配待消费
    线程与答案条目 → ``deepcopy`` + 段落重产（``section_writer or ablock_section_writer``）
    → 冲突检测（AI 不覆盖人工）→ ``decision_log`` 去重合并 → ``add_version`` →
    成功后才 ``resolve_thread`` + ``areanchor_threads``。

    ⚠️ **``applied_in_version`` 的落地口径**：条目里的 ``applied_in_version`` 取
    **基线版本 id**（``str(base.id)``，即「答案是在哪一版之上被应用的」）。理由：产出
    版本的 id 由 ``add_version`` 在写库时生成，**写入前不可知**；若为了填自身 id 而二次
    ``add_version``，会额外翻一版并破坏「同 hash 不翻版本」的幂等意图。基线 id 写入前
    已知且**可重放稳定**（重放时 :func:`merge_decision_log` 按 ``thread_id`` 去重、条目
    值不变 ⇒ hash 不变 ⇒ 不翻版本）。
    **产出版本的反查方式**（115 消费面依赖）：
    ``ArtifactVersion.objects.filter(artifact=..., produced_by_ref=f"ai_review_reflow:{thread_id}")``，
    或沿 ``supersedes`` 链取 base 的后继。``BlueprintThreadMessage`` 无「结论」字段，
    结构化留痕只能进 ``decision_log``。

    整函数 ``try/except`` 兜底：回灌失败**绝不上抛**（不该把会话打成 FAILED）。
    """
    from delivery.services.artifact_service import ArtifactContentInvalid, ArtifactService
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    started = time.monotonic()
    artifacts = artifact_service or ArtifactService()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    session_id = str(getattr(session, "id", "") or "")

    try:
        base = await _aload_latest_version(artifact)
        if base is None:
            return _reflow_result("noop", detail="蓝图尚无版本")

        rows, payloads = await _aload_thread_payloads(artifact, threads, str(base.id))
        entries = build_decision_entries(payloads)
        if not entries:
            return _reflow_result("noop", detail="无待消费的已作答线程")
        answered_ids = {entry["thread_id"] for entry in entries}
        consumed = [row for row in rows if str(row.id) in answered_ids]
        thread_ids = [entry["thread_id"] for entry in entries]
        primary_thread_id = thread_ids[0]

        content = copy.deepcopy(base.content if isinstance(base.content, dict) else {})
        writer = section_writer or ablock_section_writer
        try:
            rewritten = await writer(content, entries, session=session)
        except Exception as exc:  # noqa: BLE001 — writer 失败只让正文原样，答案照常留痕
            logger.warning(
                "blueprint_reflow_section_writer_failed",
                category="caller",
                component="process_runtime",
                session_id=session_id,
                error=redact_secrets_in_text(str(exc)),
            )
            rewritten = None
        if isinstance(rewritten, dict):
            content = rewritten

        human_version = (
            base
            if str(base.produced_by_ref or "").startswith(HUMAN_EDIT_PREFIX)
            else await _alatest_human_version(artifact)
        )
        if human_version is not None:
            human_base = human_version.supersedes
            conflicts = detect_human_conflicts(
                human_version_content=human_version.content,
                human_base_content=(human_base.content if human_base is not None else {}),
                ai_new_content=content,
            )
            if conflicts:
                thread = await lifecycle.open_thread(
                    artifact,
                    kind=ThreadKind.AI_CLARIFICATION,
                    blocking=True,
                    question=_conflict_question(conflicts, scene="AI 修订"),
                    anchor={"block_id": conflicts[0]},
                    created_on_version=base,
                    return_stage=RETURN_STAGE_AI_REVIEWING,
                    initiated_by_user_id=initiated_by_user_id or "system",
                )
                logger.info(
                    "blueprint_reflow_human_conflict_detected",
                    category="caller",
                    component="process_runtime",
                    session_id=session_id,
                    artifact_id=str(getattr(artifact, "id", "")),
                    thread_id=str(thread.id),
                    conflict_block_count=len(conflicts),
                    initiated_by_user_id=initiated_by_user_id or "system",
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                return _reflow_result(
                    "conflict",
                    thread_ids=thread_ids,
                    conflict_block_ids=conflicts,
                    thread_id=str(thread.id),
                    detail="AI 修订与人工编辑冲突，已开线程等待裁决",
                )

        content["decision_log"] = merge_decision_log(content.get("decision_log"), entries)

        try:
            version = await artifacts.add_version(
                artifact,
                content,
                produced_by_session_id=session_id,
                produced_by_ref=f"{AI_REVIEW_REFLOW_PREFIX}{primary_thread_id}",
            )
        except ArtifactContentInvalid as exc:
            logger.warning(
                "blueprint_reflow_invalid_content",
                category="caller",
                component="process_runtime",
                session_id=session_id,
                artifact_id=str(getattr(artifact, "id", "")),
                error=redact_secrets_in_text(str(exc)),
            )
            return _reflow_result(
                "invalid", thread_ids=thread_ids, detail=redact_secrets_in_text(str(exc))
            )

        if str(version.id) == str(base.id):
            return _reflow_result(
                "unchanged",
                version_id=str(version.id),
                version_no=int(version.version_no),
                thread_ids=thread_ids,
                detail="内容无实质改动，未产生新版本",
            )

        for row in consumed:
            try:
                await lifecycle.resolve_thread(
                    row,
                    resolution=f"答案已回灌，产出版本 v{version.version_no}。",
                    initiated_by_user_id=initiated_by_user_id or "system",
                )
            except Exception as exc:  # noqa: BLE001 — 单条收尾失败不牵连整轮
                logger.warning(
                    "blueprint_reflow_resolve_thread_failed",
                    category="caller",
                    component="process_runtime",
                    session_id=session_id,
                    thread_id=str(row.id),
                    error=redact_secrets_in_text(str(exc)),
                )

        reanchor_counts = await lifecycle.areanchor_threads(
            artifact,
            content,
            old_content=base.content if isinstance(base.content, dict) else None,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        logger.info(
            "blueprint_reflow_applied",
            category="caller",
            component="process_runtime",
            session_id=session_id,
            artifact_id=str(getattr(artifact, "id", "")),
            thread_count=len(thread_ids),
            version_no=int(version.version_no),
            reanchor_checked=reanchor_counts.get("checked", 0),
            reanchor_reanchored=reanchor_counts.get("reanchored", 0),
            reanchor_orphaned=reanchor_counts.get("orphaned", 0),
            reanchor_skipped=reanchor_counts.get("skipped", 0),
            initiated_by_user_id=initiated_by_user_id or "system",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return _reflow_result(
            "applied",
            version_id=str(version.id),
            version_no=int(version.version_no),
            thread_ids=thread_ids,
        )
    except Exception as exc:  # noqa: BLE001 — 回灌失败绝不把会话打成 FAILED
        logger.warning(
            "blueprint_reflow_failed",
            category="caller",
            component="process_runtime",
            session_id=session_id,
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return _reflow_result("invalid", detail="reflow_failed")


# ══════════════════════════════════════════════════════════════════════════
# 人工块保护（B3：114-03 的 ai_review 入口消费；本 plan 只交付与单测，不接线）
# ══════════════════════════════════════════════════════════════════════════


async def acollect_human_block_ids(artifact: Any) -> list[str]:
    """求「哪些 block 是人写的」保护集，返回升序去重的 block_id 列表（**只读**）。

    保护集 = 版本链中 ``produced_by_ref`` 带 :data:`HUMAN_EDIT_PREFIX` 的版本，各自与其
    ``supersedes`` 做 ``diff_blueprint_blocks`` 取 ``added ∪ modified`` 的并集。

    这是「哪些块是人写的」的**唯一判据**：``ArtifactVersion`` 无 ``created_by_user_id``，
    ``produced_by_ref`` 前缀是本仓唯一的人工归属通道。``removed`` **不进**保护集——人工
    删掉的块无内容可保护，硬塞回去等于替用户撤销他自己的删除。

    ``supersedes`` 为 ``None``（首版即人工编辑）时基线取空 dict ⇒ 全文入保护集（保守
    优先）。整体 ``try/except`` → ``[]``：保护集读失败不该阻断审查。
    """
    try:
        protected: set[str] = set()
        async for version in (
            ArtifactVersion.objects.select_related("supersedes")
            .filter(artifact=artifact, produced_by_ref__startswith="human_edit:")
            .order_by("version_no")
        ):
            previous = version.supersedes
            diff = diff_blueprint_blocks(
                previous.content if previous is not None else {}, version.content
            )
            protected |= set(diff["added"]) | set(diff["modified"])
        return sorted(protected)
    except Exception as exc:  # noqa: BLE001 — 保护集读失败不阻断审查
        logger.warning(
            "blueprint_reflow_collect_human_blocks_failed",
            category="sampling",
            component="process_runtime",
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
        )
        return []


async def arestore_human_blocks(
    artifact: Any,
    *,
    initiated_by_user_id: str = "system",
    session: Any = None,
    artifact_service: Any = None,
    lifecycle_service: Any = None,
) -> dict:
    """重装后的人工块保护（B3，T-114-23b），恒定六键返回。

    ``status`` 四值语义：

    ==============  ==========================================================
    status          语义
    ==============  ==========================================================
    ``noop``        无 ``human_edit:`` 版本 / 无版本 / 保护失败 ⇒ 什么都没做
    ``unchanged``   保护集里的人工内容**仍逐字在位** ⇒ 不翻版本、不开线程
    ``restored``    有块被写回但无冲突需裁决（当前实现下不出现，保留给未来的
                    「等价归一」场景）
    ``conflict``    有块实质冲突 ⇒ **人工块已写回**新版本 + **已开阻塞线程**等裁决
    ==============  ==========================================================

    步骤：``acollect_human_block_ids`` 求保护集（空 ⇒ ``noop``，零查询开销路径）→ 读
    **最新**版本作当前态 + 最近一条 ``human_edit:`` 版本作人工基准（⛔ 不读
    ``session.current_artifact_version``）→ 逐块用 **canonical JSON**
    （:func:`_canonical`，与 ``artifact_service`` 的 hash 口径同源）比对：等价则无事，
    **缺失或不等即实质冲突** ⇒ 把人工基准块写回 ``deepcopy`` 后的当前 content →
    冲突非空则 ``open_thread(kind=ai_clarification, blocking=True,
    return_stage="ai_reviewing")``（question **只含 block_id 与裁决提示，不贴两侧正文**）
    → 有实际写回才 ``add_version(produced_by_ref=f"human_block_restore:{base.version_no}")``
    → 落新版本后 ``areanchor_threads``。

    ⛔ **绝不静默覆盖**。整体 ``try/except`` → ``noop`` + warning，**绝不上抛**（保护失败
    不该把 stage 打成异常；114-03 据 ``status`` 决定是否停等）。
    """
    from delivery.services.artifact_service import ArtifactContentInvalid, ArtifactService
    from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

    started = time.monotonic()
    artifacts = artifact_service or ArtifactService()
    lifecycle = lifecycle_service or BlueprintLifecycleService()
    session_id = str(getattr(session, "id", "") or "")

    try:
        protected = await acollect_human_block_ids(artifact)
        if not protected:
            return _restore_result("noop")

        base = await _aload_latest_version(artifact)
        human = await _alatest_human_version(artifact)
        if base is None or human is None:
            return _restore_result("noop")

        content = copy.deepcopy(base.content if isinstance(base.content, dict) else {})
        current_blocks = {
            str(block.get("block_id")): block
            for _path, block in iter_blocks(content)
            if block.get("block_id")
        }
        human_blocks = {
            str(block.get("block_id")): block
            for _path, block in iter_blocks(human.content)
            if block.get("block_id")
        }

        preserved: list[str] = []
        conflicted: list[str] = []
        for block_id in protected:
            human_block = human_blocks.get(block_id)
            if human_block is None:
                # 人工版本里也没有了（后续人工自己删掉）⇒ 无内容可保护。
                continue
            current_block = current_blocks.get(block_id)
            if current_block is not None and _canonical(current_block) == _canonical(human_block):
                continue
            conflicted.append(block_id)
            if current_block is None:
                # 块被重装整体移除：没有落位可写回（**不猜落位**），只开线程请人裁决。
                continue
            current_block.clear()
            current_block.update(copy.deepcopy(human_block))
            preserved.append(block_id)

        thread_id = ""
        if conflicted:
            thread = await lifecycle.open_thread(
                artifact,
                kind=ThreadKind.AI_CLARIFICATION,
                blocking=True,
                question=_conflict_question(conflicted, scene="AI 重装"),
                anchor={"block_id": conflicted[0]},
                created_on_version=base,
                return_stage=RETURN_STAGE_AI_REVIEWING,
                initiated_by_user_id=initiated_by_user_id or "system",
            )
            thread_id = str(thread.id)

        if not preserved:
            # 没有任何块被写回 ⇒ content 与 base 逐字相同，**不落版本**。
            return _restore_result(
                "conflict" if conflicted else "unchanged",
                conflicted=conflicted,
                thread_id=thread_id,
            )

        try:
            version = await artifacts.add_version(
                artifact,
                content,
                produced_by_session_id=session_id,
                produced_by_ref=f"{HUMAN_BLOCK_RESTORE_PREFIX}{base.version_no}",
            )
        except ArtifactContentInvalid as exc:
            logger.warning(
                "blueprint_reflow_restore_invalid_content",
                category="caller",
                component="process_runtime",
                session_id=session_id,
                artifact_id=str(getattr(artifact, "id", "")),
                error=redact_secrets_in_text(str(exc)),
            )
            return _restore_result("noop", conflicted=conflicted, thread_id=thread_id)

        if str(version.id) == str(base.id):
            return _restore_result(
                "unchanged",
                preserved=preserved,
                conflicted=conflicted,
                thread_id=thread_id,
                version_id=str(version.id),
                version_no=int(version.version_no),
            )

        await lifecycle.areanchor_threads(
            artifact,
            content,
            old_content=base.content if isinstance(base.content, dict) else None,
            initiated_by_user_id=initiated_by_user_id or "system",
        )
        logger.info(
            "blueprint_human_blocks_restored",
            category="caller",
            component="process_runtime",
            session_id=session_id,
            artifact_id=str(getattr(artifact, "id", "")),
            protected_count=len(protected),
            preserved_count=len(preserved),
            conflicted_count=len(conflicted),
            version_no=int(version.version_no),
            thread_id=thread_id,
            initiated_by_user_id=initiated_by_user_id or "system",
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return _restore_result(
            "conflict" if conflicted else "restored",
            preserved=preserved,
            conflicted=conflicted,
            thread_id=thread_id,
            version_id=str(version.id),
            version_no=int(version.version_no),
        )
    except Exception as exc:  # noqa: BLE001 — 保护失败绝不把 stage 打成异常
        logger.warning(
            "blueprint_reflow_restore_failed",
            category="caller",
            component="process_runtime",
            session_id=session_id,
            artifact_id=str(getattr(artifact, "id", "")),
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return _restore_result("noop")
