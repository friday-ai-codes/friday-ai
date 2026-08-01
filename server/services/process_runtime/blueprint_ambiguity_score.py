"""需求歧义四维打分 helper（Phase 112-02，FLOW-01 规格门的判定输入）。

契约四段：

- **谁调用**：``blueprint_spec_gate`` stage adapter（阶段 0 规格门）。本模块是入口无关
  的纯 helper——只接收原语、不碰 ORM、不写线程，打分结果由 adapter 决定怎么用。
- **fail-closed 方向**：LLM 不可得、响应不可解析、某维缺失或畸形，一律取**保守值 1.0**
  （最歧义）而非 0；``ascore_ambiguity`` 整体不可用时返回 ``None``，上游按「需澄清」
  处理。规格门是全链路唯一 fail-closed 点，任何降级都不得变成静默放行。
- **阈值与权重来自 SystemSetting**（``blueprint.spec_gate.config``，运行时可调）；本模块
  的 ``DEFAULT_SPEC_GATE_CONFIG`` 只作配置缺失/畸形时的兜底默认，不是硬编码判定。
- **判定是纯函数**：``normalize_ambiguity_scores`` / ``weighted_total`` / ``is_ambiguous``
  三个纯函数无 IO，可被 golden set 直接评估与回归。

LLM 调用赋 ``call_source=blueprint_spec_gate``（可观测性规范，category=sampling /
component=process_runtime），观测三事件只记标量分数与计数——**需求正文与澄清问题正文
绝不进日志**（T-112-08）。
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

__all__ = [
    "ascore_ambiguity",
    "normalize_ambiguity_scores",
    "weighted_total",
    "is_ambiguous",
    "aload_spec_gate_config",
    "DEFAULT_SPEC_GATE_CONFIG",
    "DEFAULT_ASSUMPTIONS_TIERS",
    "ASSUMPTIONS_TIERS",
]

# 歧义四维（DESIGN §5.4）：目标 / 边界 / 约束 / 验收。
_DIMENSIONS: tuple[str, ...] = ("goal", "boundary", "constraint", "acceptance")

# 兜底默认（与 SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG 注释逐字一致，112-01）。
#
# ⭐ ``max_rounds`` 是 **116-06 新增**、且是这个值的**单一事实源**：它原本是
# ``blueprint_spec_gate._MAX_SPEC_GATE_ROUNDS = 3`` 这个模块级常量（配置里根本没有该键），
# 档位要能运行时调轮数上界就必须把它配置化。116-06 已**删除**那个常量。
# ⛔ **绝不反过来写成** ``"max_rounds": blueprint_spec_gate._MAX_SPEC_GATE_ROUNDS`` ——
# ``blueprint_spec_gate`` 已经从本模块 import，反向取值即**循环 import**，而这里是模块级
# dict 字面量、没有懒 import 的落点。默认值 ``3`` 与改动前逐字相等 ⇒ 不配置时行为不变。
DEFAULT_SPEC_GATE_CONFIG: dict[str, Any] = {
    "threshold": 0.20,
    "weights": {"goal": 0.30, "boundary": 0.25, "constraint": 0.20, "acceptance": 0.25},
    "max_rounds": 3,
}

# 三档 assumptions 预设（GATE-01，116-06）：配置缺失/畸形时的内置默认。
#
# ⭐ **档位只管「问不问」，不管「问了等不等」**：它只覆盖 ``threshold`` 与 ``max_rounds``
# 两个判定参数，⛔ **绝不跳过 spec_gate stage** —— 那等于原地复活 GATE-01 要消灭的那条
# 「跳过交互澄清」旧策略。``assume_more`` 档下四维打分**仍然执行**、超阈值**仍然开阻塞
# 线程**，只是阈值更高、轮数更少（问得更少 ≠ 不问）。超时语义永远是显式 pending 不自动
# 作答（§12 决策 4，本里程碑不可动）。
#
# ⚠️ ``balanced`` 必须与 :data:`DEFAULT_SPEC_GATE_CONFIG` **逐字相等**（默认档零回归）。
DEFAULT_ASSUMPTIONS_TIERS: dict[str, dict[str, Any]] = {
    # 更低阈值 = 更爱问，更多轮
    "strict": {"threshold": 0.10, "max_rounds": 5},
    # = 现状（默认档）
    "balanced": {"threshold": 0.20, "max_rounds": 3},
    # 更高阈值 = 更少问，轮数更少
    "assume_more": {"threshold": 0.45, "max_rounds": 2},
}
ASSUMPTIONS_TIERS: tuple[str, ...] = tuple(DEFAULT_ASSUMPTIONS_TIERS)

# 轮数上界的下界（``max_rounds <= 0`` 会让规格门第 0 轮即 capped 放行 = 恒不澄清，
# 那正是档位不该能表达的语义 ⇒ 强转后一律 ``max(1, ...)``）。
_MIN_MAX_ROUNDS = 1

# 缺维/畸形/无依据时的保守分（1.0 = 最歧义 = 必澄清，fail-closed 方向）。
_CONSERVATIVE_SCORE = 1.0
# 单维理由长度上界（半可信 LLM 文本，进蓝图 ambiguity_report 前先截断）。
_MAX_REASON_CHARS = 300
# 澄清问题条数上界（防 LLM 失控刷题淹没用户）。
_MAX_QUESTIONS = 5
# 单条问题/选项/引用的长度与条数上界。
_MAX_QUESTION_CHARS = 300
_MAX_OPTIONS_PER_QUESTION = 8
_MAX_CITATIONS_PER_QUESTION = 8
# prompt 各分节字符上界（控体积；需求正文可能很长）。
_MAX_PROMPT_CHARS = 6000
# 无理由时补的占位（让 ambiguity_report 里「为什么判歧义」不留空白）。
_NO_REASON_PLACEHOLDER = "（模型未给出判定依据，按保守值处理）"


def _clamp01(value: float) -> float:
    """把任意数值夹到 ``[0, 1]``。"""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _to_score(value: Any) -> float | None:
    """强转为 ``[0,1]`` 分数；不可转换返回 ``None``（由调用方落保守值）。"""
    if isinstance(value, bool):
        return None
    try:
        return _clamp01(float(value))
    except (TypeError, ValueError):
        return None


def _content_to_text(content: Any) -> str:
    """LangChain message.content 归一为文本（兼容 str / 分块 list）。

    reasoning 模型（经兼容代理的 deepseek/glm 等）content 为 content_blocks 列表，
    直接 ``str()`` 会得到 Python repr（单引号）致下游 ``json.loads`` 失败——只拼接
    含 text 的 block。
    """
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
    """从 LLM 文本中健壮提取顶层 JSON 对象（``` 围栏 + 裸 JSON 双路）。

    非 JSON / 非对象 → ``None``（调用方按 fail-closed 处理），本函数不外抛。
    """
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


def _normalize_questions(raw: Any) -> list[dict[str, Any]]:
    """澄清问题白名单归一：只留 ``{text, options, citations}``，空 text 整项丢弃。"""
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, Any]] = []
    for item in raw:
        if len(questions) >= _MAX_QUESTIONS:
            break
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()[:_MAX_QUESTION_CHARS]
        if not text:
            continue
        raw_options = item.get("options")
        options = [
            str(opt).strip()[:_MAX_QUESTION_CHARS]
            for opt in (raw_options if isinstance(raw_options, list) else [])
            if str(opt).strip()
        ][:_MAX_OPTIONS_PER_QUESTION]
        raw_citations = item.get("citations")
        citations = [
            str(cid).strip()
            for cid in (raw_citations if isinstance(raw_citations, list) else [])
            if str(cid).strip()
        ][:_MAX_CITATIONS_PER_QUESTION]
        questions.append({"text": text, "options": options, "citations": citations})
    return questions


def normalize_ambiguity_scores(data: Any) -> dict[str, Any]:
    """把 LLM 打分响应归一为稳定结构（防御畸形输出与幻觉，T-112-05）。

    输出恒为 ``{"dimensions": {dim: {"score": float, "reason": str}}, "questions": [...]}``，
    四维齐全。归一规则：

    - 每维 ``score`` 强转 ``float`` 并 clamp ``[0,1]``；缺维/非数/非法 → 保守值 1.0。
    - ``reason`` 截断 300 字符；**理由为空的维一律落保守值 1.0 + 占位理由**——判定
      失去依据就降级（镜像 ``feature_classify`` 的 modify 无证据回落 unclear），
      降级方向朝「需澄清」而非「放行」。
    - ``questions`` 按白名单 ``{text, options, citations}`` 归一，空 ``text`` 整项丢弃、
      条数截断到 5。
    - 输入非 dict（含 ``None``）→ 全维保守值 + 空问题清单。
    """
    payload = data if isinstance(data, dict) else {}
    raw_dimensions = payload.get("dimensions")
    if not isinstance(raw_dimensions, dict):
        raw_dimensions = {}

    dimensions: dict[str, dict[str, Any]] = {}
    for dim in _DIMENSIONS:
        entry = raw_dimensions.get(dim)
        if not isinstance(entry, dict):
            dimensions[dim] = {
                "score": _CONSERVATIVE_SCORE,
                "reason": _NO_REASON_PLACEHOLDER,
            }
            continue
        score = _to_score(entry.get("score"))
        reason = str(entry.get("reason", "") or "").strip()[:_MAX_REASON_CHARS]
        if score is None:
            score = _CONSERVATIVE_SCORE
        if not reason:
            # 结论失去依据 → 降级到保守值（fail-closed 方向），并补占位理由。
            score = _CONSERVATIVE_SCORE
            reason = _NO_REASON_PLACEHOLDER
        dimensions[dim] = {"score": score, "reason": reason}

    return {"dimensions": dimensions, "questions": _normalize_questions(payload.get("questions"))}


def weighted_total(dimensions: dict, weights: dict) -> float:
    """四维加权总分（纯函数，clamp ``[0,1]``）。

    - 权重缺失/非数/为负 → 该维取 ``DEFAULT_SPEC_GATE_CONFIG`` 同维权重（配置写坏了
      不得让某一维静默失重）。
    - 权重全为 0 → 回退等权（否则总分恒 0 = 规格门形同虚设，T-112-07）。
    - 分数缺失/畸形 → 该维取保守值 1.0。
    """
    dims = dimensions if isinstance(dimensions, dict) else {}
    raw_weights = weights if isinstance(weights, dict) else {}
    default_weights = DEFAULT_SPEC_GATE_CONFIG["weights"]

    effective: dict[str, float] = {}
    for dim in _DIMENSIONS:
        candidate = raw_weights.get(dim)
        try:
            weight = float(candidate)
        except (TypeError, ValueError):
            weight = float(default_weights[dim])
        if isinstance(candidate, bool) or weight < 0:
            weight = float(default_weights[dim])
        effective[dim] = weight

    if sum(effective.values()) <= 0:
        equal = 1.0 / len(_DIMENSIONS)
        effective = {dim: equal for dim in _DIMENSIONS}

    total = 0.0
    for dim in _DIMENSIONS:
        entry = dims.get(dim)
        score = _to_score(entry.get("score")) if isinstance(entry, dict) else None
        if score is None:
            score = _CONSERVATIVE_SCORE
        total += score * effective[dim]
    return _clamp01(total)


def is_ambiguous(total: float, threshold: float) -> bool:
    """加权总分是否达到澄清阈值（``>=``：等于阈值即判需澄清，边界朝 fail-closed）。"""
    try:
        return float(total) >= float(threshold)
    except (TypeError, ValueError):
        return True


def _to_max_rounds(value: Any) -> int | None:
    """强转轮数上界（``int()`` + 下界 :data:`_MIN_MAX_ROUNDS`）；不可转换返回 ``None``。"""
    if isinstance(value, bool):
        return None
    try:
        return max(int(value), _MIN_MAX_ROUNDS)
    except (TypeError, ValueError):
        return None


async def _aload_tier_overrides(tier: str) -> dict[str, Any]:
    """读某一档的 ``{threshold, max_rounds}`` 覆盖项（畸形/未配置一律回内置预设）。

    ⭐ ``tier`` 是**字符串**而不是 session：本函数与 :func:`aload_spec_gate_config` 都要
    保持**无 ORM 依赖**（纯配置读取），档位由调用方从 ``stage_state`` 里取好再传进来。

    三层 fail-soft（形状照 ``blueprint_entry_switch.aresolve_entry_process_type``）：
    档名不在三档内 ⇒ ``{}``（不覆盖）；整段异常 ⇒ 回内置预设 + 一条 warning；
    ``aget_json_setting`` 只保证外层是 dict ⇒ 逐键强转，不可转换的项**不覆盖**。
    """
    preset = copy.deepcopy(DEFAULT_ASSUMPTIONS_TIERS.get(tier) or {})
    if not preset:
        logger.warning(
            "blueprint_assumptions_tier_unknown",
            category="sampling",
            component="process_runtime",
            tier=tier,
        )
        return {}
    try:
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting

        raw = await aget_json_setting(
            SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS, copy.deepcopy(DEFAULT_ASSUMPTIONS_TIERS)
        )
    except Exception:  # noqa: BLE001 — 配置读取绝不反噬编排主流程（⛔ 不带异常文本）
        logger.warning(
            "blueprint_assumptions_tiers_load_failed",
            category="sampling",
            component="process_runtime",
            tier=tier,
            reason="load_failed",
        )
        return preset

    entry = raw.get(tier) if isinstance(raw, dict) else None
    if not isinstance(entry, dict):
        return preset

    overrides = dict(preset)
    threshold = _to_score(entry.get("threshold"))
    if threshold is not None:
        overrides["threshold"] = threshold
    max_rounds = _to_max_rounds(entry.get("max_rounds"))
    if max_rounds is not None:
        overrides["max_rounds"] = max_rounds
    return overrides


async def aload_spec_gate_config(tier: str = "") -> dict[str, Any]:
    """读运行时阈值 / 四维权重 / 轮数上界（``blueprint.spec_gate.config``），强转 + 兜底。

    任何异常/畸形一律回 :data:`DEFAULT_SPEC_GATE_CONFIG`（绝不外抛、绝不 eval，
    T-112-07）：``threshold`` 经 ``float()`` + clamp ``[0,1]``，``weights`` 非 dict
    回默认、逐维 ``float()`` 且负值取 0，``max_rounds`` 经 ``int()`` + 下界 1。

    Args:
        tier: assumptions 档位（``strict`` / ``balanced`` / ``assume_more``，116-06）。
            ⭐ **传档位字符串而不是 session** —— 本函数保持无 ORM 依赖。非空时读
            ``SettingKeys.BLUEPRINT_ASSUMPTIONS_TIERS`` 覆盖 ``threshold`` 与
            ``max_rounds``；空串 / 未配置 / 畸形 / 档名不在三档内一律**回落 base**
            ⇒ 不传档位时行为与改动前逐字相同。
            ⛔ 档位只覆盖这两个判定参数，**绝不跳过 stage**（见
            :data:`DEFAULT_ASSUMPTIONS_TIERS` 的纪律段）。
    """
    fallback = copy.deepcopy(DEFAULT_SPEC_GATE_CONFIG)
    try:
        from system.models import SettingKeys
        from system.settings_service import aget_json_setting

        raw = await aget_json_setting(
            SettingKeys.BLUEPRINT_SPEC_GATE_CONFIG, copy.deepcopy(DEFAULT_SPEC_GATE_CONFIG)
        )
        if not isinstance(raw, dict):
            raw = {}

        threshold = _to_score(raw.get("threshold"))
        if threshold is None:
            threshold = float(DEFAULT_SPEC_GATE_CONFIG["threshold"])

        max_rounds = _to_max_rounds(raw.get("max_rounds"))
        if max_rounds is None:
            max_rounds = int(DEFAULT_SPEC_GATE_CONFIG["max_rounds"])

        raw_weights = raw.get("weights")
        weights: dict[str, float] = {}
        for dim in _DIMENSIONS:
            candidate = (raw_weights or {}).get(dim) if isinstance(raw_weights, dict) else None
            try:
                weight = float(candidate)
            except (TypeError, ValueError):
                weight = float(DEFAULT_SPEC_GATE_CONFIG["weights"][dim])
            if isinstance(candidate, bool):
                weight = float(DEFAULT_SPEC_GATE_CONFIG["weights"][dim])
            weights[dim] = max(weight, 0.0)

        config = {"threshold": threshold, "weights": weights, "max_rounds": max_rounds}
        if str(tier or ""):
            config.update(await _aload_tier_overrides(str(tier)))
        return config
    except Exception as exc:  # noqa: BLE001 — 配置读取绝不反噬编排主流程
        logger.warning(
            "blueprint_spec_gate_config_load_failed",
            category="sampling",
            component="process_runtime",
            error=redact_secrets_in_text(str(exc)),
        )
        return fallback


def _system_prompt() -> str:
    return (
        "你是资深需求分析师。给定一份需求的目标、功能点与已知约束，从四个维度评估它的"
        "**歧义程度**（0=完全清晰可直接进技术调研，1=严重歧义无法开工），并给出需要向"
        "提出者澄清的问题。\n"
        "四个维度：\n"
        "- goal：目标是否唯一、可证伪（做成什么样算成功）。\n"
        "- boundary：范围边界是否清楚（做什么 / 明确不做什么）。\n"
        "- constraint：技术/业务/合规约束是否明确（性能、兼容、时间、依赖方）。\n"
        "- acceptance：验收标准是否可机械验证。\n"
        "要求：\n"
        '- 只输出 JSON，形如 {"dimensions": {"goal": {"score": 0.0, "reason": ".."},'
        '"boundary": {...}, "constraint": {...}, "acceptance": {...}},'
        '"questions": [{"text": "..", "options": ["候选A", "候选B"], "citations": ["cit_x"]}]}。\n'
        "- 每个维度都必须给 score 与 reason；**reason 必须说明缺什么，不得留空**"
        "（留空的维度会被按最高歧义处理）。\n"
        "- **判不出就给高分并说明缺什么，不要猜**——猜错的代价比多问一句大。\n"
        "- questions 只针对真正挡住开工的歧义，每题尽量给 2-4 个候选选项（options）"
        "让人一键选；citations 逐字取自输入中出现过的引用 id，没有就给空数组，"
        "严禁编造。\n"
        f"- questions 最多 {_MAX_QUESTIONS} 条，按阻塞程度降序。\n"
        "- 不要输出 JSON 以外的解释性文字。"
    )


def _section(title: str, body: str) -> str:
    return f"### {title}\n{body.strip()[:_MAX_PROMPT_CHARS] or '（未提供）'}"


def _build_prompt(
    *,
    goal: str,
    feature_points: list[dict[str, Any]],
    constraints: list | None,
    prior_context: str,
) -> str:
    """按分节拼装打分输入（各节独立截断，防单节撑爆 prompt）。"""
    fp_lines: list[str] = []
    for point in feature_points or []:
        if not isinstance(point, dict):
            continue
        title = str(point.get("title", "") or "").strip()
        if not title:
            continue
        fp_id = str(point.get("id", "") or "").strip()
        criteria = point.get("acceptance_criteria")
        criteria_text = (
            "；".join(str(c).strip() for c in criteria if str(c).strip())
            if isinstance(criteria, list)
            else ""
        )
        line = f"- [{fp_id or '-'}] {title}"
        if criteria_text:
            line += f"（验收：{criteria_text}）"
        fp_lines.append(line)

    constraint_lines: list[str] = []
    for item in constraints or []:
        if isinstance(item, dict):
            text = str(item.get("text", "") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            constraint_lines.append(f"- {text}")

    sections = [
        _section("需求目标", goal),
        _section("功能点", "\n".join(fp_lines)),
        _section("已知约束", "\n".join(constraint_lines)),
    ]
    if prior_context.strip():
        # 已澄清结论必须进重判输入，否则同一问题会被反复问（clarify_adapter 先例）。
        sections.append(_section("已澄清结论（请勿重复追问，据此判断是否仍需补充）", prior_context))
    return "\n\n".join(sections) + "\n\n请输出四维歧义评分与澄清问题 JSON。"


async def ascore_ambiguity(
    *,
    goal: str,
    feature_points: list[dict[str, Any]],
    constraints: list | None = None,
    prior_context: str = "",
    session_id: str = "",
    tier: str = "",
) -> dict[str, Any] | None:
    """LLM 单调用产出四维歧义分数 + 理由 + 澄清问题；不可用时返回 ``None``。

    ``None`` 是「打分不可得」信号——上游规格门据此**判需澄清**（fail-closed），
    绝不当作「不歧义」放行。成功时返回经 :func:`normalize_ambiguity_scores` 归一的
    ``{"dimensions": ..., "questions": [...]}``。本函数 best-effort，不外抛。

    Args:
        tier: ⭐ **assumptions 档位必须传到这里**（116-06）。本函数体内**自己也读一次**
            ``aload_spec_gate_config``，紧接着把 ``config["threshold"]`` 打进
            ``blueprint_ambiguity_score_completed`` 的 ``threshold=`` / ``above_threshold=``
            —— 那条 sampling 日志正是运维回答「这轮为什么问 / 为什么不问」的依据。
            不透传档位 ⇒ **日志报的阈值与规格门真正判定用的分叉**，静默且永不报错
            （留痕撒谎，T-116-53）。⚠️ 本函数**没有** ``session`` 可用（签名里只有原语），
            所以只能由调用方传 ``tier``——这正是它必须加这个形参的原因。
    """
    started = time.monotonic()
    try:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        logger.info(
            "blueprint_ambiguity_score_started",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            feature_point_count=len(feature_points or []),
            constraint_count=len(constraints or []),
            has_prior_context=bool(prior_context.strip()),
        )

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning(
                "blueprint_ambiguity_score_no_default_model",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            return None

        model = build_chat_model(resolved, model_name, streaming=False)
        messages = [
            SystemMessage(content=_system_prompt()),
            HumanMessage(
                content=_build_prompt(
                    goal=goal,
                    feature_points=feature_points,
                    constraints=constraints,
                    prior_context=prior_context,
                )
            ),
        ]
        with use_call_source(CallSource.BLUEPRINT_SPEC_GATE):
            response = await model.ainvoke(messages)

        parsed = _parse_object_json(_content_to_text(response.content))
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if parsed is None:
            logger.warning(
                "blueprint_ambiguity_score_failed",
                category="sampling",
                component="process_runtime",
                session_id=session_id,
                reason="unparsable_response",
                duration_ms=duration_ms,
            )
            return None

        scores = normalize_ambiguity_scores(parsed)
        dimension_scores = {dim: entry["score"] for dim, entry in scores["dimensions"].items()}
        # ⭐ 必须带 tier：否则下面这条日志报的阈值与规格门判定用的分叉（见 docstring）。
        config = await aload_spec_gate_config(tier=tier)
        total = weighted_total(scores["dimensions"], config["weights"])
        logger.info(
            "blueprint_ambiguity_score_completed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            dimension_scores=dimension_scores,
            weighted_total=total,
            assumptions_tier=str(tier or ""),
            threshold=config["threshold"],
            above_threshold=is_ambiguous(total, config["threshold"]),
            question_count=len(scores["questions"]),
            duration_ms=duration_ms,
        )
        return scores
    except Exception as exc:  # noqa: BLE001 — best-effort：上游按 fail-closed 处理 None
        logger.warning(
            "blueprint_ambiguity_score_failed",
            category="sampling",
            component="process_runtime",
            session_id=session_id,
            error=redact_secrets_in_text(str(exc)),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return None
