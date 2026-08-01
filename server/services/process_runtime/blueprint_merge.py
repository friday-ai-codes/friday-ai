"""BlueprintMergeAdapter —— 阶段 3 融合装配（Phase 113-05，FLOW-06 / SCHEMA-02~05）。

六条契约（模块级不变量，改动前先读）：

1. **新文件，绝不修改冻结的 ``architect_merge_adapter.py``**（DESIGN §13.2）。它只是
   范式来源（Protocol 合成器 / 可空串 section / 类属性上界 / merge 七步骨架 / graceful
   降级），其私有 helper（文本归一、健壮 JSON 解析）一律**复制**到本文件，不 import。
2. **确定性投影优先，模型只写需要推理的四段**：``repo_associations`` 与
   ``current_state_analysis`` 由 :func:`project_repo_associations` /
   :func:`project_current_state` 从上游产物逐字段搬，**mock 掉全部推理能力后这两段仍
   完整产出**且与上游一致（113-CONTEXT 的可断言要求）。只有
   ``implementation_overview`` / ``api_contracts`` / ``interaction_flows`` /
   ``impact_analysis`` 需要起草。
3. **分节多次调用而非单次巨 prompt**：降幻觉、便于按节归因重试；单段失败只降级该段
   （降级值是**过 schema 的最小合法结构**，见 :data:`SECTION_FALLBACKS`），四段全挂才
   判整轮 failed。
4. 「跨仓 API 对账走 ``blueprint_reconcile`` 纯函数」——判定必须可复现、可单测、
   可解释，绝不让推理过程自查（113-CONTEXT 锁定）；矛盾一律开阻塞澄清线程，绝不静默拍板。
5. **INV-6**：蓝图版本落库只经 ``ArtifactService.add_version``（自带 ``content_hash``
   幂等）；澄清线程只经 ``BlueprintLifecycleService.open_thread``（``return_stage="merge"``
   必填，否则阶段 3 的澄清恢复会退回阶段 1）。本文件零 ORM 写。
6. **best-effort 不反噬主链**：事件 / 埋点 / 后置 hook 一律 ``except Exception`` 吞掉 +
   warning；异常文本经 ``redact_secrets_in_text`` 截断后才进日志。

**质量门（113-06 补齐）**：装配后依次过 ``validate_blueprint``（不过就不落版本）与
**引用覆盖率门**（阈值走 ``SettingKeys.BLUEPRINT_MERGE_CONFIG``，缺配置回落
:data:`_DEFAULT_CITATION_COVERAGE_MIN`）。覆盖率不达标时按 :func:`decide_back_target`
归因两档回退（单仓缺口回该仓 ``repo_plan``、融合层缺口重融合），合计上界
:data:`MAX_MERGE_ROUNDS` 轮；**超界一律 ``validation_status="exhausted"``：仍落版本 +
带 ``unresolved`` 未决项清单 + 开阻塞澄清线程**，绝不落 failed 类动作（OQ-3——「未达
覆盖率待人审」不是「流程失败」，蓝图成果不许被丢弃）。stage 注册与出边映射归
``builtin_processes``。
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import structlog
from asgiref.sync import sync_to_async

from common.logging import redact_secrets_in_text
from services.process_runtime.blueprint_quality import citation_coverage
from services.process_runtime.blueprint_reconcile import coverage_gaps, reconcile_cross_repo_apis
from services.process_runtime.blueprint_repo_waves import build_api_waves
from services.process_runtime.blueprint_schema import BLUEPRINT_SCHEMA_VERSION, validate_blueprint

logger = structlog.get_logger(__name__)

__all__ = [
    "BlueprintMergeAdapter",
    "BlueprintSectionSynthesizer",
    "LLMBlueprintSectionSynthesizer",
    "MAX_MERGE_ROUNDS",
    "STAGE_STATE_KEY",
    "SECTION_FALLBACKS",
    "MERGE_SECTIONS",
    "CITATION_ID_PREFIX",
    "build_citation_pool",
    "project_repo_associations",
    "project_current_state",
    "derive_must_haves",
    "decide_back_target",
]

# 合计重试上界 2 轮（113-CONTEXT）。运行时可经
# `SettingKeys.BLUEPRINT_MERGE_CONFIG` 的 `max_merge_rounds` 覆盖；此处是兜底默认。
MAX_MERGE_ROUNDS = 2

# 引用覆盖率门阈值的兜底默认（同上，键 `citation_coverage_min`）。
_DEFAULT_CITATION_COVERAGE_MIN = 0.8

# 未决项清单的上界：它进 `stage_state`（< 2KB 约定）与澄清问题文本，无界会刷爆 HITL 面板。
_MAX_UNRESOLVED = 30

# distill 沉淀只收「有长期价值」的三类总线条目（BUS-03）；`finding` / `question` /
# `dependency_claim` 是会话内过程态，进项目级记忆只会污染它（打包预算 30 条）。
_DISTILL_KINDS = ("decision", "contract", "api_surface")
_DISTILL_READ_LIMIT = 200
_MAX_DISTILL_CHARS = 6000

# `session.stage_state` 内融合阶段的键（handler 单点持久化，回调路径永不触碰计数）。
STAGE_STATE_KEY = "merge"

# 四个需要起草的段名（**确定性投影的两段不在此列**）。
SECTION_IMPLEMENTATION_OVERVIEW = "implementation_overview"
SECTION_API_CONTRACTS = "api_contracts"
SECTION_INTERACTION_FLOWS = "interaction_flows"
SECTION_IMPACT_ANALYSIS = "impact_analysis"
MERGE_SECTIONS = (
    SECTION_IMPLEMENTATION_OVERVIEW,
    SECTION_API_CONTRACTS,
    SECTION_INTERACTION_FLOWS,
    SECTION_IMPACT_ANALYSIS,
)

# 单段失败的降级值：**必须是过 schema 的最小合法结构**，不是 `{}`、不是 `None`、不是缺键。
# 依据（blueprint_schema.py 实测）：`implementation_overview` required 两键（`:381`）、
# `impact_analysis` required `["business_impact","affected_features"]`（`:586`），
# 两个 array 段空数组本身合法（items 的 required 只在有元素时生效）。
# 缺 required 键会把「只挂一段」放大成「整份非法」——明明六段有五段完好却整轮 failed。
SECTION_FALLBACKS: dict[str, Any] = {
    SECTION_IMPLEMENTATION_OVERVIEW: {"requirement_narrative": [], "items": []},
    SECTION_API_CONTRACTS: [],
    SECTION_INTERACTION_FLOWS: [],
    SECTION_IMPACT_ANALYSIS: {"business_impact": [], "affected_features": []},
}

# 引用池 id 前缀（`cit_` + sha1(raw)[:12]，稳定可复现：同一裸路径恒得同一 id）。
CITATION_ID_PREFIX = "cit_"

_NEEDS_SUPPORT = "needs_support"
_VALID_ROLES = ("direct", "indirect")
_VALID_DECIDED_BY = ("ai", "human")
_VALID_CHANGE_TYPES = ("create", "modify", "remove", "indirect_refine")
_VALID_FILE_ACTIONS = ("create", "modify", "remove")
_VALID_FINDING_KINDS = ("capability", "gap", "risk", "convention")
_VALID_IMPACT_KINDS = ("behavior_change", "perf", "compat", "data", "none")
_VALID_BLOCK_TYPES = ("paragraph", "pseudocode", "table", "list", "mermaid")
_VALID_API_KINDS = ("http", "rpc", "event", "mq")

# `change_type` → `files_touched[].action`（RepoPlan 侧 files_touched 是裸路径字符串，
# 蓝图侧要求 `{path, action}`；`indirect_refine` 归 modify）。
_CHANGE_TYPE_ACTION = {
    "create": "create",
    "modify": "modify",
    "remove": "remove",
    "indirect_refine": "modify",
}

# 正文类字段的截断上界（融合产物会进 DRF 响应体与澄清问题文本）。
_MAX_TEXT_CHARS = 4000
_MAX_TITLE_CHARS = 300
_MAX_PROMPT_JSON_CHARS = 12000
_MAX_LIST_ITEMS = 200
_MAX_ERROR_CHARS = 500


# ══════════════════════════════════════════════════════════════════════════
# 分节合成器（照 analog 的 Protocol + 五步骨架，复制不 import）
# ══════════════════════════════════════════════════════════════════════════


@runtime_checkable
class BlueprintSectionSynthesizer(Protocol):
    """分节起草器协议（可注入）：一次调用只产**一段**，便于按节归因重试。"""

    async def draft(self, *, section: str, prompt_parts: dict) -> dict: ...


class LLMBlueprintSectionSynthesizer:
    """默认分节起草器：provider_config 解析 + chat model + 健壮 JSON 解析。

    ``prompt_parts`` 由调用方（adapter 的 ``_adraft_*``）构造好 ``system`` / ``human``
    两串 —— prompt 组装留在 adapter 侧的模块级纯函数里，可零依赖单测。
    解析不出 dict 就抛，由 adapter 的单段 ``except`` 接住降级（绝不返回半截产物）。
    """

    async def draft(self, *, section: str, prompt_parts: dict) -> dict:
        from langchain_core.messages import HumanMessage, SystemMessage

        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService

        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            raise RuntimeError("no_default_model")
        model = build_chat_model(resolved, model_name, streaming=False)
        system = SystemMessage(content=str((prompt_parts or {}).get("system") or ""))
        human = HumanMessage(content=str((prompt_parts or {}).get("human") or ""))
        # 111 已注册的枚举值，不新增（外层 `_adraft_*` 也各自声明一次，嵌套安全）。
        with use_call_source(CallSource.BLUEPRINT_MERGE):
            response = await model.ainvoke([system, human])
        parsed = _parse_json(_content_to_text(response.content))
        if parsed is None:
            raise ValueError(f"blueprint_section_parse_failed:{section}")
        return parsed


def _content_to_text(content: Any) -> str:
    """把 response.content（str / list[block]）归一化为文本（复制自 analog，不 import）。"""
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
    return str(content)


def _parse_json(text: str) -> dict | None:
    """健壮解析：取首 ``{`` 到末 ``}``，不 eval；非 dict 返 ``None``（复制自 analog）。"""
    candidate = (text or "").strip()
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = candidate[start : end + 1]
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _extract_section(payload: Any, section: str) -> Any:
    """从起草产物里取该段：优先同名键，其次 ``items``（array 段），最后整份 payload。"""
    if not isinstance(payload, dict):
        return None
    if section in payload:
        return payload[section]
    if section in (SECTION_API_CONTRACTS, SECTION_INTERACTION_FLOWS):
        return payload.get("items")
    return payload


# ══════════════════════════════════════════════════════════════════════════
# 基元 helper（block / 引用映射 / 摘要，全部纯函数）
# ══════════════════════════════════════════════════════════════════════════


def _short(value: Any) -> str:
    return str(value or "").replace("-", "")[:8]


def _digest(*parts: Any) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _block(block_id: str, text: Any, *, block_type: str = "paragraph") -> dict:
    return {"block_id": block_id, "type": block_type, "text": text}


def _sanitize_block(raw: dict, fallback_id: str) -> dict:
    """外来 block 归一：只留 schema 已知键、``type`` 越界回落 paragraph。

    **block 级 ``citations`` 一律丢弃**：它必须是引用池 id，而外来 block 里通常是裸串，
    留着会让 ``validate_blueprint`` 的引用完整性后置检查判整份非法。证据由**外层条目**
    （finding / item / contract / feature）的 ``citations`` 承载，那是覆盖率指标的口径。
    """
    block: dict[str, Any] = {}
    for key in ("text", "code", "rows"):
        if key in raw:
            block[key] = raw[key]
    block["block_id"] = str(raw.get("block_id") or fallback_id)
    block_type = str(raw.get("type") or "")
    block["type"] = block_type if block_type in _VALID_BLOCK_TYPES else "paragraph"
    return block


def _as_block_list(value: Any, *, block_id: str) -> list[dict]:
    """任意输入 → ``$defs/block_list``；空内容产空数组（**绝不产缺键或 None**）。"""
    if isinstance(value, list):
        blocks: list[dict] = []
        for index, entry in enumerate(value[:_MAX_LIST_ITEMS]):
            if isinstance(entry, dict):
                blocks.append(_sanitize_block(entry, f"{block_id}_{index}"))
            elif str(entry or "").strip():
                blocks.append(_block(f"{block_id}_{index}", str(entry).strip()[:_MAX_TEXT_CHARS]))
        return blocks
    if isinstance(value, dict):
        return [_sanitize_block(value, block_id)]
    text = str(value or "").strip()
    if not text:
        return []
    return [_block(block_id, text[:_MAX_TEXT_CHARS])]


def _blocks_to_text(blocks: Any) -> str:
    """Block[] / 字符串 / 字符串数组 → 纯文本（只用于 prompt 与摘要，不落产物）。"""
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, list):
            parts.extend(str(entry) for entry in text if str(entry or "").strip())
        elif str(text or "").strip():
            parts.append(str(text))
    return "\n".join(parts)


def _map_citations(values: Any, cite_map: dict, dropped: list | None = None) -> list[str]:
    """裸引用串 → 引用池 id（映射不到的**丢弃并计数**，绝不让整份蓝图非法，P-5）。"""
    ids: list[str] = []
    seen: set[str] = set()
    for value in values if isinstance(values, list) else []:
        raw = str(value or "").strip()
        if not raw:
            continue
        mapped = (cite_map or {}).get(raw)
        if not mapped:
            if dropped is not None:
                dropped.append(raw)
            continue
        if mapped in seen:
            continue
        seen.add(mapped)
        ids.append(mapped)
    return ids[:_MAX_LIST_ITEMS]


def _json(value: Any, *, limit: int = _MAX_PROMPT_JSON_CHARS) -> str:
    """prompt 用的 JSON 序列化（有界截断：prompt 体积必须可控）。"""
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "…（已截断）"


# ══════════════════════════════════════════════════════════════════════════
# 引用池（P-5：本 plan 显式选「先建引用池」而非白名单丢弃）
# ══════════════════════════════════════════════════════════════════════════


def build_citation_pool(repo_plans: dict, associations: list) -> tuple[list[dict], dict[str, str]]:
    """收集各仓证据里的裸引用串，归一为文档级引用池条目 + ``raw → id`` 映射（**纯函数**）。

    走查面：确认门锁定条目的 ``fitness.citations`` / ``rationale.citations``，以及各仓
    ``repo_plan`` 的 ``current_state[].findings[].citations`` / ``impl_items[].citations``
    / ``apis_provided|apis_consumed[].citations`` / ``local_impact.affected_features[].citations``
    / ``fitness.citations``。

    Returns:
        ``(entries, cite_map)``——``entries`` 是 ``$defs/citation`` 形状的条目列表
        （``citation_id`` = ``cit_`` + ``sha1(raw)[:12]``，同一裸串恒得同一 id，
        重复调用逐字节一致）；``cite_map`` 是 ``{raw: citation_id}``。

        走查顺序固定（associations 原序 → 仓 id 升序），故输出确定。**只有来自上游产物
        的真实引用才进池**：各段填充时一律经 :func:`_map_citations` 换成池内 id，池外裸串
        丢弃计数（T-113-27）。
    """
    raws: list[str] = []
    seen: set[str] = set()

    def _add(values: Any) -> None:
        for value in values if isinstance(values, list) else []:
            raw = str(value or "").strip()
            # 已是引用池 id 的值**不再入池**：融合基线本身就是上一轮的产物，重新走查它会把
            # `cit_xxx` 当成新裸串再造一条 `cit_sha1("cit_xxx")` 条目 —— 引用池每轮膨胀一层，
            # 同输入两次融合的 content_hash 不再相等，幂等直接失效。
            if raw and raw not in seen and not raw.startswith(CITATION_ID_PREFIX):
                seen.add(raw)
                raws.append(raw)

    for assoc in associations if isinstance(associations, list) else []:
        if not isinstance(assoc, dict):
            continue
        for key in ("fitness", "rationale"):
            nested = assoc.get(key)
            if isinstance(nested, dict):
                _add(nested.get("citations"))

    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        fitness = section.get("fitness")
        if isinstance(fitness, dict):
            _add(fitness.get("citations"))
        for state in section.get("current_state") or []:
            if not isinstance(state, dict):
                continue
            for finding in state.get("findings") or []:
                if isinstance(finding, dict):
                    _add(finding.get("citations"))
        for item in section.get("impl_items") or []:
            if isinstance(item, dict):
                _add(item.get("citations"))
        for api_key in ("apis_provided", "apis_consumed"):
            for api in section.get(api_key) or []:
                if isinstance(api, dict):
                    _add(api.get("citations"))
        local_impact = section.get("local_impact")
        if isinstance(local_impact, dict):
            for feature in local_impact.get("affected_features") or []:
                if isinstance(feature, dict):
                    _add(feature.get("citations"))

    entries: list[dict] = []
    cite_map: dict[str, str] = {}
    for raw in raws:
        citation_id = f"{CITATION_ID_PREFIX}{_digest(raw)[:12]}"
        cite_map[raw] = citation_id
        entries.append(
            {
                "citation_id": citation_id,
                "source_type": "repo_file",
                "source_id": raw[:_MAX_TITLE_CHARS],
                "locator": {"path": raw[:_MAX_TITLE_CHARS]},
                "title": raw[:_MAX_TITLE_CHARS],
            }
        )
    return entries, cite_map


# ══════════════════════════════════════════════════════════════════════════
# 确定性投影（不经推理，可断言：mock 掉起草器后这两段仍完整产出）
# ══════════════════════════════════════════════════════════════════════════


def project_repo_associations(locked_associations: list, cite_map: dict) -> list:
    """确认门锁定产物 → ``repo_associations``（**纯函数、逐字段搬**）。

    ⚠️ **P-8 的唯一防线**：``citation_coverage`` 读的是 ``rationale.citations``，
    **不是** ``fitness.citations``（``blueprint_quality._iter_key_conclusion_citations``
    第二类口径），而 112 确认门 ``build_locked_associations`` 落的恰恰是
    ``fitness.citations``。只搬 fitness 会让 ``repo_associations`` 这一类条目的分子恒 0，
    覆盖率被系统性拉低。故本函数**同时填 ``rationale``**（text + citations）。

    Args:
        locked_associations: 融合基线的 ``repo_associations``（半可信，逐层 `.get` 防御）。
        cite_map: ``raw → citation_id`` 映射（应已并入基线引用池 id 的恒等映射，
            否则 112 落的池内 id 会被当成池外裸串丢掉）。

    Returns:
        ``repo_associations`` 条目列表；``removed is True`` 与无 ``repository_id`` 的条目跳过。
    """
    projected: list[dict] = []
    seen: set[str] = set()
    for assoc in locked_associations if isinstance(locked_associations, list) else []:
        if not isinstance(assoc, dict):
            continue
        repository_id = str(assoc.get("repository_id") or "")
        if not repository_id or repository_id in seen or assoc.get("removed") is True:
            continue
        seen.add(repository_id)
        role = str(assoc.get("role") or assoc.get("role_suggestion") or "").strip()
        entry: dict[str, Any] = {
            "repository_id": repository_id,
            # schema `minLength 1`：无名回落 id（绝不产非法版本）
            "repository_name": str(assoc.get("repository_name") or "") or repository_id,
            "role": role if role in _VALID_ROLES else "direct",
        }
        responsibility = _as_block_list(
            assoc.get("responsibility"), block_id=f"blk_bp_resp_{_short(repository_id)}"
        )
        if responsibility:
            entry["responsibility"] = responsibility
        for key in ("planned_change_summary", "support_needed"):
            blocks = _as_block_list(
                assoc.get(key), block_id=f"blk_bp_{key}_{_short(repository_id)}"
            )
            if blocks:
                entry[key] = blocks
        if isinstance(assoc.get("routing_evidence"), dict):
            entry["routing_evidence"] = assoc["routing_evidence"]
        if isinstance(assoc.get("capabilities_used"), list):
            entry["capabilities_used"] = assoc["capabilities_used"][:_MAX_LIST_ITEMS]
        decided_by = str(assoc.get("decided_by") or "")
        if decided_by in _VALID_DECIDED_BY:
            entry["decided_by"] = decided_by
        if isinstance(assoc.get("confirmed_at_gate"), bool):
            entry["confirmed_at_gate"] = assoc["confirmed_at_gate"]
        fitness = _project_fitness(assoc.get("fitness"), repository_id, cite_map)
        if fitness:
            entry["fitness"] = fitness
        entry["rationale"] = _project_rationale(assoc, repository_id, cite_map, fitness)
        projected.append(entry)
    return projected


def _project_fitness(raw: Any, repository_id: str, cite_map: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    fitness: dict[str, Any] = {}
    verdict = str(raw.get("verdict") or "").strip().lower()
    if verdict in ("suitable", "partial", "unsuitable"):
        fitness["verdict"] = verdict
    reasons = _as_block_list(raw.get("reasons"), block_id=f"blk_bp_fit_{_short(repository_id)}")
    if reasons:
        fitness["reasons"] = reasons
    citations = _map_citations(raw.get("citations"), cite_map)
    if citations:
        fitness["citations"] = citations
    return fitness


def _project_rationale(assoc: dict, repository_id: str, cite_map: dict, fitness: dict) -> dict:
    """``rationale`` = 选仓理由叙述 + **覆盖率口径读的那份 citations**（P-8）。

    citations 取「源条目 ``rationale.citations`` ∪ ``fitness.citations``」并集：确认门只
    落了后者，不并进来这类条目就永远不被算作「有据」。
    """
    source = assoc.get("rationale") if isinstance(assoc.get("rationale"), dict) else {}
    citations = _map_citations(source.get("citations"), cite_map)
    for citation_id in fitness.get("citations") or []:
        if citation_id not in citations:
            citations.append(citation_id)
    text = _as_block_list(
        source.get("text") or assoc.get("responsibility") or (fitness.get("reasons") or []),
        block_id=f"blk_bp_rationale_{_short(repository_id)}",
    )
    rationale: dict[str, Any] = {"text": text, "citations": citations}
    if isinstance(source.get("constraint_refs"), list):
        rationale["constraint_refs"] = [
            str(ref) for ref in source["constraint_refs"][:_MAX_LIST_ITEMS]
        ]
    return rationale


def project_current_state(repo_plans: dict, cite_map: dict) -> list:
    """各仓 ``repo_plan.current_state`` → ``current_state_analysis``（**纯函数、逐字段搬**）。

    保留源侧的 ``title`` / ``detail`` 原键（schema 允许附加属性）**并**补齐 schema 要求的
    ``id`` / ``text`` / ``kind`` / ``citations`` —— 这样「投影与上游逐字段一致」可以被直接
    断言，而不是靠「大致包含」。仓 id 升序遍历，输出确定。

    ⚠️ 调用方须按 ``repo_associations`` 的仓集过滤本函数结果：``validate_blueprint``
    后置检查 (c) 要求 ``current_state_analysis[].repository_id`` 必须出现在
    ``repo_associations``，否则整份判非法。
    """
    projected: list[dict] = []
    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        states = [
            state for state in (section.get("current_state") or []) if isinstance(state, dict)
        ]
        if not states:
            continue
        summary: list[dict] = []
        findings: list[dict] = []
        for s_index, state in enumerate(states):
            summary.extend(
                _as_block_list(
                    state.get("summary"),
                    block_id=f"blk_bp_cs_{_short(repository_id)}_{s_index}",
                )
            )
            for f_index, finding in enumerate(state.get("findings") or []):
                if not isinstance(finding, dict):
                    continue
                entry = _project_finding(finding, repository_id, f"{s_index}{f_index}", cite_map)
                if entry is not None:
                    findings.append(entry)
        analysis: dict[str, Any] = {"repository_id": repository_id, "findings": findings}
        if summary:
            analysis["summary"] = summary
        projected.append(analysis)
    return projected


def _project_finding(finding: dict, repository_id: str, index: str, cite_map: dict) -> dict | None:
    title = str(finding.get("title") or "").strip()
    detail = str(finding.get("detail") or "").strip()
    if not title and not detail:
        return None
    kind = str(finding.get("kind") or "").strip()
    return {
        "id": f"cs_{_short(repository_id)}_{index}",
        "topic": title[:_MAX_TITLE_CHARS],
        # 源键原样保留：投影一致性可被逐字段断言（schema 允许附加属性）
        "title": title,
        "detail": detail,
        "text": _as_block_list(
            detail or title, block_id=f"blk_bp_finding_{_short(repository_id)}_{index}"
        ),
        "kind": kind if kind in _VALID_FINDING_KINDS else "capability",
        "citations": _map_citations(finding.get("citations"), cite_map),
    }


# ══════════════════════════════════════════════════════════════════════════
# must_haves 确定性派生（111 只有 jsonschema 无派生代码，本 plan 新写）
# ══════════════════════════════════════════════════════════════════════════


def derive_must_haves(
    *,
    requirement_spec: dict,
    implementation_overview: dict,
    api_contracts: list | None = None,
) -> dict:
    """由需求规格与实现项**确定性派生** goal-backward 验收锚点（**零推理参与**）。

    形态照 ``blueprint_execution.derive_execution_plan``（同输入重复调用输出逐字节一致，
    排序全部显式化）。三键口径与边界：

    - ``truths`` ← ``requirement_spec.feature_points[]`` 逐条模板化成可观察行为断言
      （有 ``acceptance_criteria`` 就用它，否则退回标题）。无功能点 → ``[]``。
    - ``artifacts`` ← ``implementation_overview.items[].files_touched`` 按 ``path``
      去重聚合，每项 ``{path, provides: <该 item 的 title>}``。**无 items 时是 ``[]``
      而不是缺键**——缺键会让整份蓝图 schema 失败（``must_haves`` required 三键）。
    - ``key_links`` ← ``items[].depends_on`` 的实现项依赖边 + ``api_contracts`` 的
      provider→consumer 边，每项 ``{from, to, via}``。两类都取不到 → ``[]``。

    Args:
        api_contracts: 装配好的 ``api_contracts`` 段（PLAN 的 ``key_links`` 口径需要它；
            缺省 ``None`` 时只派生实现项依赖边）。
    """
    spec = requirement_spec if isinstance(requirement_spec, dict) else {}
    overview = implementation_overview if isinstance(implementation_overview, dict) else {}
    items = [item for item in (overview.get("items") or []) if isinstance(item, dict)]

    truths: list[str] = []
    for point in spec.get("feature_points") or []:
        if not isinstance(point, dict):
            continue
        title = str(point.get("title") or "").strip()
        point_id = str(point.get("id") or "").strip()
        if not title and not point_id:
            continue
        criteria = [
            str(entry).strip()
            for entry in (point.get("acceptance_criteria") or [])
            if str(entry or "").strip()
        ]
        observable = "；".join(criteria) if criteria else f"{title or point_id} 的行为可被观察到"
        prefix = f"[{point_id}] " if point_id else ""
        truths.append(f"{prefix}{title or point_id}：{observable}"[:_MAX_TEXT_CHARS])

    artifacts: dict[str, dict] = {}
    for item in items:
        provides = str(item.get("title") or item.get("id") or "")[:_MAX_TITLE_CHARS]
        for entry in item.get("files_touched") or []:
            # MN-04：`or ""` 必须在条件表达式**外面** —— 写在里面时 dict 缺 `path` 键会得到
            # `str(None) == "None"`，非空且过不了 `if not path`，于是产出字面量路径 "None"
            # 这个垃圾锚点（本函数是 `__all__` 导出的公开纯函数，不能只靠调用方先归一）。
            path = str((entry.get("path") if isinstance(entry, dict) else entry) or "").strip()
            if not path or path in artifacts:
                continue
            artifacts[path] = {"path": path, "provides": provides}

    key_links: list[dict] = []
    known_items = {str(item.get("id") or "") for item in items if item.get("id")}
    for item in sorted(items, key=lambda i: str(i.get("id") or "")):
        item_id = str(item.get("id") or "")
        for dependency in sorted(str(dep) for dep in (item.get("depends_on") or [])):
            if dependency in known_items:
                key_links.append({"from": item_id, "to": dependency, "via": "depends_on"})
    key_links.extend(_api_key_links(api_contracts))

    return {
        "truths": truths[:_MAX_LIST_ITEMS],
        "artifacts": [artifacts[path] for path in sorted(artifacts)],
        "key_links": key_links[:_MAX_LIST_ITEMS],
    }


# ══════════════════════════════════════════════════════════════════════════
# 覆盖率门的归因（纯函数：单仓缺口 vs 融合层缺口）
# ══════════════════════════════════════════════════════════════════════════


def decide_back_target(gaps: list[dict]) -> dict:
    """引用覆盖率缺口 → **回退目标归因**（纯函数，零 ORM，可直接单测）。

    输入是 :func:`blueprint_reconcile.coverage_gaps` 的定位清单。两档判定：

    - 有缺口能解析出 ``repository_id`` → 按仓聚合，取**缺口最多**的仓回该仓
      ``repo_plan``（证据是单仓调研没写够，重融合一万次也补不出来）；同数时按仓 id
      升序取定（**确定性**：同输入恒得同一归因，可写成断言）。
    - 全部解析不出仓 → 回 ``merge`` 重融合（缺口在融合层的装配/投影环节）。
    - 无缺口 → 三键全空（调用方据此知道「没有可归因的缺口」）。

    Returns:
        恒定三键 ``{"back_target": "repo_plan"|"merge"|"", "back_repository_id": str,
        "gap_count": int}``。``gap_count`` 是**该归因对应的**缺口数（单仓档是该仓的
        缺口数，融合档是全部缺口数）。
    """
    entries = [gap for gap in (gaps or []) if isinstance(gap, dict)]
    if not entries:
        return {"back_target": "", "back_repository_id": "", "gap_count": 0}
    by_repo: dict[str, int] = {}
    for gap in entries:
        repository_id = str(gap.get("repository_id") or "").strip()
        if repository_id:
            by_repo[repository_id] = by_repo.get(repository_id, 0) + 1
    if not by_repo:
        return {"back_target": "merge", "back_repository_id": "", "gap_count": len(entries)}
    # 排序键显式化：先按缺口数降序，再按仓 id 升序（同数时结果确定，不随 dict 序漂移）。
    repository_id, gap_count = sorted(by_repo.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return {
        "back_target": "repo_plan",
        "back_repository_id": repository_id,
        "gap_count": gap_count,
    }


def _api_key_links(api_contracts: Any) -> list[dict]:
    """``api_contracts`` 的 provider→consumer 边（按契约名配对，确定性排序）。"""
    contracts = [item for item in (api_contracts or []) if isinstance(item, dict)]
    providers: dict[str, str] = {}
    for contract in contracts:
        if str(contract.get("direction") or "") != "provided":
            continue
        name = str(contract.get("name") or "").strip()
        if name:
            providers.setdefault(name, str(contract.get("repository_id") or ""))
    links: list[dict] = []
    for contract in sorted(contracts, key=lambda c: str(c.get("id") or "")):
        if str(contract.get("direction") or "") != "consumed":
            continue
        name = str(contract.get("name") or "").strip()
        provider = providers.get(name)
        if not provider:
            continue
        links.append(
            {"from": provider, "to": str(contract.get("repository_id") or ""), "via": name}
        )
    return links


# ══════════════════════════════════════════════════════════════════════════
# 分节 prompt（system / human 分离 + ⭐可空串 section 插槽，照 analog L50-58）
# ══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class _MergeInputs:
    """四段起草与装配共用的只读输入（服务端权威状态，不含外部原文指令）。"""

    repo_plans: dict
    waves: dict
    associations: list
    current_state: list
    requirement_spec: dict
    cite_map: dict
    assoc_ids: frozenset


def _cross_repo_section(waves: dict) -> str:
    """跨仓依赖边说明段——**无跨仓边时为空串**，prompt 与基础形态逐字一致（零扰动）。"""
    edges = [edge for edge in (waves or {}).get("edges") or [] if isinstance(edge, dict)]
    if not edges:
        return ""
    lines = [
        f"- {edge.get('from')} 提供 → {edge.get('to')} 消费：{edge.get('api')}"
        for edge in edges[:50]
    ]
    return (
        "已探明的跨仓接口依赖（provider 仓先行，实现项波次据此排）：\n" + "\n".join(lines) + "\n\n"
    )


def _unresolved_section(waves: dict) -> str:
    """找不到 provider 的消费项——空时为空串（`needs_support` 的前置信号，113-04）。"""
    unresolved = [
        item for item in (waves or {}).get("unresolved_consumed") or [] if isinstance(item, dict)
    ]
    if not unresolved:
        return ""
    lines = [f"- {item.get('repository_id')} 消费 {item.get('api')}" for item in unresolved[:50]]
    return (
        "以下消费项在本次仓集内找不到提供方，必须在 data_source 里标注 "
        f'availability="{_NEEDS_SUPPORT}" 并给出 support_repository_id：\n'
        + "\n".join(lines)
        + "\n\n"
    )


def _feature_point_digest(requirement_spec: Any) -> list[dict]:
    spec = requirement_spec if isinstance(requirement_spec, dict) else {}
    digest: list[dict] = []
    for point in spec.get("feature_points") or []:
        if not isinstance(point, dict):
            continue
        digest.append(
            {
                "id": str(point.get("id") or ""),
                "title": str(point.get("title") or "")[:_MAX_TITLE_CHARS],
                "intent": str(point.get("intent") or ""),
            }
        )
    return digest[:_MAX_LIST_ITEMS]


def _impl_items_digest(repo_plans: dict) -> list[dict]:
    """各仓实现项摘要（起草只需分组与叙事，结构字段由服务端搬，不交给推理改写）。"""
    digest: list[dict] = []
    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        for item in section.get("impl_items") or []:
            if not isinstance(item, dict):
                continue
            digest.append(
                {
                    "repository_id": repository_id,
                    "item_id": str(item.get("item_id") or ""),
                    "title": str(item.get("title") or "")[:_MAX_TITLE_CHARS],
                    "change_type": str(item.get("change_type") or ""),
                    "how": _blocks_to_text(item.get("how"))[:1000],
                }
            )
    return digest[:_MAX_LIST_ITEMS]


def _api_digest(repo_plans: dict) -> list[dict]:
    digest: list[dict] = []
    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        for api_key, direction in (("apis_provided", "provided"), ("apis_consumed", "consumed")):
            for api in section.get(api_key) or []:
                if not isinstance(api, dict):
                    continue
                digest.append(
                    {
                        "repository_id": repository_id,
                        "direction": direction,
                        "name": str(api.get("name") or ""),
                        "method": str(api.get("method") or ""),
                        "path": str(api.get("path") or ""),
                        "description": _blocks_to_text(api.get("description"))[:600],
                    }
                )
    return digest[:_MAX_LIST_ITEMS]


def _impact_digest(repo_plans: dict) -> list[dict]:
    digest: list[dict] = []
    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        local_impact = (
            section.get("local_impact") if isinstance(section.get("local_impact"), dict) else {}
        )
        digest.append(
            {
                "repository_id": repository_id,
                "local_impact": {
                    "affected_modules": local_impact.get("affected_modules") or [],
                    "affected_features": local_impact.get("affected_features") or [],
                    "migration_required": bool(local_impact.get("migration_required")),
                },
                "risks": _blocks_to_text(section.get("risks"))[:1000],
            }
        )
    return digest[:_MAX_LIST_ITEMS]


_SYSTEM_BASE = (
    "你是软件架构师，正在把多个单仓分仓方案融合成一份跨仓技术蓝图的**某一段**。"
    "只输出 JSON，不要任何解释；不要编造证据、接口或文件路径。"
)


def _implementation_overview_prompt(inputs: _MergeInputs) -> tuple[str, str]:
    """实现概述段（SCHEMA-03）：只要模块分组与跨仓叙事，结构字段由服务端搬。"""
    human = (
        f"需求功能点：\n{_json(_feature_point_digest(inputs.requirement_spec))}\n\n"
        f"各仓实现项（change_type / files_touched / depends_on 由服务端权威搬，"
        f"你不要改写它们）：\n{_json(_impl_items_digest(inputs.repo_plans))}\n\n"
        f"{_cross_repo_section(inputs.waves)}"
        '请输出 {"implementation_overview": {"requirement_narrative": [Block], '
        '"modules": [{"id","name","feature_point_ids","repository_ids","narrative"}], '
        '"items": [{"repository_id","item_id","feature_point_id","module_id"}]}}。\n'
        "其中 items 只用于把各仓实现项**映射**到功能点与模块（feature_point_id 必须取自上面"
        "的功能点 id 列表），不要新增实现项。Block 形如 "
        '{"block_id","type":"paragraph","text"}。\n'
    )
    return _SYSTEM_BASE, human


def _api_contracts_prompt(inputs: _MergeInputs) -> tuple[str, str]:
    """API 段（SCHEMA-05）：接口描述 + 请求响应示例 + 数据来源说明。"""
    human = (
        f"各仓接口契约（结构字段由服务端权威搬，你只补描述与示例）：\n"
        f"{_json(_api_digest(inputs.repo_plans))}\n\n"
        f"{_unresolved_section(inputs.waves)}"
        '请输出 {"api_contracts": [{"name","method","path","description":[Block],'
        '"request_example":{},"response_example":{},'
        '"data_source":{"from_service","from_api","fields_needed":[str],'
        f'"availability":"existing"|"{_NEEDS_SUPPORT}","support_repository_id","notes":[Block]}}}}]}}。\n'
        "硬约束：消费类契约的数据可用性**只能**写在 data_source 内部（键名 availability，"
        f"两值枚举 existing / {_NEEDS_SUPPORT}）；**不得**产出顶层同名键。"
        f"标 {_NEEDS_SUPPORT} 时必须给出 support_repository_id（哪个仓要配合产出这份数据）。\n"
    )
    return _SYSTEM_BASE, human


def _interaction_flows_prompt(inputs: _MergeInputs) -> tuple[str, str]:
    """交互流程段（SCHEMA-04）：六要素完整叙事。"""
    human = (
        f"需求功能点：\n{_json(_feature_point_digest(inputs.requirement_spec))}\n\n"
        f"可用接口：\n{_json(_api_digest(inputs.repo_plans))}\n\n"
        f"{_cross_repo_section(inputs.waves)}"
        '请输出 {"interaction_flows": [{"id","name","trigger",'
        '"steps":[{"seq","actor","action","component","api_ref","data_in","data_out"}],'
        '"alternative_paths":[{"condition","steps":[...]}]}]}。\n'
        "每条流程必须讲全六要素：**在哪个页面（component）→ 经哪个接口（api_ref/action）→ "
        "传什么参数（data_in）→ 拿到什么数据（data_out）→ 数据流向哪里（后续 step 的 actor）"
        "→ 有哪几条行为路径（alternative_paths）**。steps 的 seq 从 1 递增。\n"
    )
    return _SYSTEM_BASE, human


def _impact_analysis_prompt(inputs: _MergeInputs) -> tuple[str, str]:
    """影响范围段：业务语言优先，每条受影响功能带引用。"""
    citation_section = _citation_section(inputs.cite_map)
    human = (
        f"各仓本地影响与风险：\n{_json(_impact_digest(inputs.repo_plans))}\n\n"
        f"{citation_section}"
        '请输出 {"impact_analysis": {"business_impact": [Block], '
        '"affected_features": [{"feature","repository_ids":[str],'
        '"kind":"behavior_change"|"perf"|"compat"|"data"|"none",'
        '"description":[Block],"citations":[str]}], '
        '"regression_scope":[{"area","level":"full"|"smoke"|"none","reason"}]}}。\n'
        "citations 只能取自上面列出的证据串，取不到就留空数组——**不要编造引用**。\n"
    )
    return _SYSTEM_BASE, human


def _prompt_parts(prompt: tuple[str, str]) -> dict:
    """``(system, human)`` → 起草器入参（system 与 human 分离，照 analog L119-164）。"""
    system, human = prompt
    return {"system": system, "human": human}


def _citation_section(cite_map: dict) -> str:
    """可引用证据清单——**引用池为空时为空串**（prompt 与基础形态逐字一致）。"""
    raws = [raw for raw in sorted(cite_map or {}) if not str(raw).startswith(CITATION_ID_PREFIX)]
    if not raws:
        return ""
    return (
        "可引用的证据（各仓调研产出的真实文件/符号）：\n"
        + "\n".join(f"- {raw}" for raw in raws[:100])
        + "\n\n"
    )


# ══════════════════════════════════════════════════════════════════════════
# 四段归一（起草产物 → 过 schema 的段；结构字段一律从 RepoPlan 搬）
# ══════════════════════════════════════════════════════════════════════════


def _normalize_implementation_overview(raw: Any, inputs: _MergeInputs) -> dict:
    """实现概述归一：``items`` **从 RepoPlan 权威搬**，起草产物只贡献分组与叙事。

    T-113-28：``change_type`` / ``files_touched`` / ``depends_on`` 若交给推理改写会造成
    实现项失真，故这三个字段一律取自 ``repo_plan.impl_items``；``wave`` 取自波次预排结果。
    """
    drafted = raw if isinstance(raw, dict) else {}
    mapping = _item_mapping(drafted.get("items"))
    feature_point_ids = [
        str(point.get("id") or "")
        for point in (inputs.requirement_spec.get("feature_points") or [])
        if isinstance(point, dict) and point.get("id")
    ]
    wave_of = _wave_index(inputs.waves)

    items: list[dict] = []
    for repository_id in sorted(str(rid) for rid in (inputs.repo_plans or {})):
        if repository_id not in inputs.assoc_ids:
            continue  # 后置检查 (c)：仓 id 必须出现在 repo_associations
        section = (inputs.repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        local_ids = {
            str(item.get("item_id") or "")
            for item in (section.get("impl_items") or [])
            if isinstance(item, dict) and item.get("item_id")
        }
        for item in section.get("impl_items") or []:
            if not isinstance(item, dict):
                continue
            entry = _project_impl_item(
                item,
                repository_id=repository_id,
                local_ids=local_ids,
                mapping=mapping,
                feature_point_ids=feature_point_ids,
                wave=wave_of.get(repository_id, 1),
                cite_map=inputs.cite_map,
            )
            if entry is not None:
                items.append(entry)

    overview: dict[str, Any] = {
        "requirement_narrative": _as_block_list(
            drafted.get("requirement_narrative"), block_id="blk_bp_narrative"
        ),
        "items": items[:_MAX_LIST_ITEMS],
    }
    modules = _normalize_modules(drafted.get("modules"), inputs)
    if modules:
        overview["modules"] = modules
    return overview


def _item_mapping(drafted_items: Any) -> dict[tuple[str, str], dict]:
    """起草产物的「实现项 → 功能点/模块」映射层（唯一被采纳的贡献）。"""
    mapping: dict[tuple[str, str], dict] = {}
    for item in drafted_items if isinstance(drafted_items, list) else []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("repository_id") or ""), str(item.get("item_id") or ""))
        if key[1]:
            mapping[key] = item
    return mapping


def _wave_index(waves: Any) -> dict[str, int]:
    index: dict[str, int] = {}
    for wave, repository_ids in ((waves or {}).get("waves") or {}).items():
        try:
            wave_no = max(1, int(wave))
        except (TypeError, ValueError):
            continue
        for repository_id in repository_ids or []:
            index[str(repository_id)] = wave_no
    return index


def _project_impl_item(
    item: dict,
    *,
    repository_id: str,
    local_ids: set[str],
    mapping: dict,
    feature_point_ids: list[str],
    wave: int,
    cite_map: dict,
) -> dict | None:
    item_id = str(item.get("item_id") or "").strip()
    title = str(item.get("title") or "").strip()
    if not item_id or not title:
        return None
    if not feature_point_ids:
        # 后置检查 (b)：feature_point_id 必须可解析到 requirement_spec，无功能点则不产实现项
        return None
    drafted = mapping.get((repository_id, item_id)) or {}
    feature_point_id = str(drafted.get("feature_point_id") or "")
    if feature_point_id not in feature_point_ids:
        feature_point_id = feature_point_ids[0]
    change_type = str(item.get("change_type") or "")
    change_type = change_type if change_type in _VALID_CHANGE_TYPES else "modify"
    entry: dict[str, Any] = {
        "id": _impl_item_id(repository_id, item_id),
        "feature_point_id": feature_point_id,
        "repository_id": repository_id,
        "change_type": change_type,
        "title": title[:_MAX_TITLE_CHARS],
        "wave": wave,
        "how": _as_block_list(
            item.get("how"), block_id=f"blk_bp_how_{_short(repository_id)}_{item_id}"
        ),
        "files_touched": _project_files_touched(item.get("files_touched"), change_type),
        "depends_on": sorted(
            _impl_item_id(repository_id, str(dep))
            for dep in (item.get("depends_on") or [])
            if str(dep) in local_ids
        ),
        "citations": _map_citations(item.get("citations"), cite_map),
    }
    module_id = str(drafted.get("module_id") or "")
    if module_id:
        entry["module_id"] = module_id
    test_strategy = _as_block_list(
        item.get("test_strategy"), block_id=f"blk_bp_test_{_short(repository_id)}_{item_id}"
    )
    if test_strategy:
        entry["test_strategy"] = test_strategy
    return entry


def _impl_item_id(repository_id: str, item_id: str) -> str:
    return f"impl_{_short(repository_id)}_{item_id}"[:120]


def _project_files_touched(raw: Any, change_type: str) -> list[dict]:
    """RepoPlan 的裸路径列表 → 蓝图 ``{path, action}``（action 由 change_type 映射）。"""
    action = _CHANGE_TYPE_ACTION.get(change_type, "modify")
    files: list[dict] = []
    seen: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if isinstance(entry, dict):
            path = str(entry.get("path") or "").strip()
            entry_action = str(entry.get("action") or "")
            entry_action = entry_action if entry_action in _VALID_FILE_ACTIONS else action
        else:
            path = str(entry or "").strip()
            entry_action = action
        if not path or path in seen:
            continue
        seen.add(path)
        files.append({"path": path[:_MAX_TITLE_CHARS], "action": entry_action})
    return files[:_MAX_LIST_ITEMS]


def _normalize_modules(raw: Any, inputs: _MergeInputs) -> list[dict]:
    modules: list[dict] = []
    for index, module in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(module, dict):
            continue
        entry: dict[str, Any] = {
            "id": str(module.get("id") or f"mod_{index}"),
            "name": str(module.get("name") or "")[:_MAX_TITLE_CHARS],
            "narrative": _as_block_list(module.get("narrative"), block_id=f"blk_bp_module_{index}"),
        }
        entry["feature_point_ids"] = [
            str(value) for value in (module.get("feature_point_ids") or []) if str(value or "")
        ][:_MAX_LIST_ITEMS]
        entry["repository_ids"] = [
            str(value)
            for value in (module.get("repository_ids") or [])
            if str(value or "") in inputs.assoc_ids
        ][:_MAX_LIST_ITEMS]
        modules.append(entry)
    return modules[:_MAX_LIST_ITEMS]


def _normalize_api_contracts(raw: Any, inputs: _MergeInputs) -> list[dict]:
    """API 段归一：契约骨架从 RepoPlan 权威搬，起草产物按契约名补描述与示例。

    绝不采纳起草产物里 RepoPlan 没有的契约条目（那是最容易被编造出来的东西，T-113-27）；
    ``from_repository_id`` 是 RepoPlan 中间产物专属键，**不落蓝图顶层**，只映射进
    ``data_source``（``from_service`` / ``support_repository_id``）。
    """
    enrichment = _api_enrichment(raw)
    contracts: list[dict] = []
    used_ids: set[str] = set()
    for repository_id in sorted(str(rid) for rid in (inputs.repo_plans or {})):
        # MN-03：与 `_normalize_implementation_overview` / `current_state` 两段对齐 ——
        # 确认门之后被移除的仓（`_normalize_locked_repos` 会剔它，但它的旧 `PartialPlan.repo_plan`
        # 仍在）否则会留下带**悬空 repository_id** 的契约过门落版本，并经 `_api_key_links`
        # 进 `must_haves.key_links`（`blueprint_schema` 的后置检查不覆盖 `api_contracts`）。
        if repository_id not in inputs.assoc_ids:
            continue
        section = (inputs.repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        for api_key, direction in (("apis_provided", "provided"), ("apis_consumed", "consumed")):
            for api in section.get(api_key) or []:
                if not isinstance(api, dict):
                    continue
                contract = _project_contract(
                    api,
                    repository_id=repository_id,
                    direction=direction,
                    drafted=enrichment.get(_api_key(api)) or {},
                    cite_map=inputs.cite_map,
                    used_ids=used_ids,
                )
                if contract is not None:
                    contracts.append(contract)
    return contracts[:_MAX_LIST_ITEMS]


def _api_key(api: dict) -> tuple[str, str, str]:
    return (
        str(api.get("name") or "").strip(),
        str(api.get("method") or "").strip().upper(),
        str(api.get("path") or "").strip(),
    )


def _api_enrichment(raw: Any) -> dict[tuple[str, str, str], dict]:
    """起草产物按 ``(name, method, path)`` 建索引（只贡献描述 / 示例 / data_source 补充）。"""
    enrichment: dict[tuple[str, str, str], dict] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        enrichment.setdefault(_api_key(item), item)
        name = str(item.get("name") or "").strip()
        if name:
            enrichment.setdefault((name, "", ""), item)
    return enrichment


def _project_contract(
    api: dict,
    *,
    repository_id: str,
    direction: str,
    drafted: dict,
    cite_map: dict,
    used_ids: set[str],
) -> dict | None:
    name = str(api.get("name") or "").strip() or str(api.get("path") or "").strip()
    if not name:
        return None
    if not drafted:
        drafted = {}
    method = str(api.get("method") or "").strip()
    path = str(api.get("path") or "").strip()
    contract_id = f"api_{direction[0]}_{_short(repository_id)}_{_digest(name, method, path)[:8]}"
    while contract_id in used_ids:
        contract_id = f"{contract_id}x"
    used_ids.add(contract_id)
    kind = str(drafted.get("kind") or api.get("kind") or "").strip()
    contract: dict[str, Any] = {
        "id": contract_id,
        "name": name[:_MAX_TITLE_CHARS],
        "kind": kind if kind in _VALID_API_KINDS else "http",
        "direction": direction,
        "repository_id": repository_id,
        "description": _as_block_list(
            drafted.get("description") or api.get("description"),
            block_id=f"blk_bp_api_{contract_id}",
        ),
        "citations": _map_citations(api.get("citations"), cite_map),
    }
    if method:
        contract["method"] = method
    if path:
        contract["path"] = path
    for key in ("request_schema", "response_schema"):
        if isinstance(api.get(key), dict) and api[key]:
            contract[key] = api[key]
    for key in ("request_example", "response_example"):
        if isinstance(drafted.get(key), dict):
            contract[key] = drafted[key]
    data_source = _project_data_source(api, drafted, contract_id)
    if data_source:
        contract["data_source"] = data_source
    return contract


def _project_data_source(api: dict, drafted: dict, contract_id: str) -> dict:
    """``data_source`` 装配（B4 的落位面）。

    可用性与协作仓**只写在这里**：``availability`` 枚举只有 ``existing`` /
    ``needs_support``，``support_repository_id`` 指出配合仓。RepoPlan 的
    ``from_repository_id`` 在此换算成 ``from_service`` / ``support_repository_id``，
    **绝不**随契约落到蓝图顶层（111 schema 无该键）。
    """
    plan_ds = api.get("data_source") if isinstance(api.get("data_source"), dict) else {}
    drafted_ds = drafted.get("data_source") if isinstance(drafted.get("data_source"), dict) else {}
    from_repository_id = str(api.get("from_repository_id") or "").strip()
    data_source: dict[str, Any] = {}
    for key in ("from_service", "from_api"):
        value = str(plan_ds.get(key) or drafted_ds.get(key) or "").strip()
        if value:
            data_source[key] = value
    if from_repository_id and not data_source.get("from_service"):
        data_source["from_service"] = from_repository_id
    fields_needed = plan_ds.get("fields_needed") or drafted_ds.get("fields_needed") or []
    fields = [str(field) for field in fields_needed if str(field or "").strip()]
    if fields:
        data_source["fields_needed"] = fields[:_MAX_LIST_ITEMS]
    availability = _pick_availability(plan_ds, drafted_ds)
    if availability:
        data_source["availability"] = availability
    support_repository_id = str(
        plan_ds.get("support_repository_id") or drafted_ds.get("support_repository_id") or ""
    ).strip()
    if not support_repository_id and availability == _NEEDS_SUPPORT:
        support_repository_id = from_repository_id
    if support_repository_id:
        data_source["support_repository_id"] = support_repository_id
    notes = _as_block_list(
        plan_ds.get("notes") or drafted_ds.get("notes"), block_id=f"blk_bp_ds_{contract_id}"
    )
    if notes:
        data_source["notes"] = notes
    return data_source


def _link_api_refs(flows: Any, contracts: Any) -> int:
    """把流程步骤里的 ``api_ref`` 从契约名/路径**改写成真实契约 id**（就地修改）。

    起草侧只知道接口名（契约 id 是服务端装配时才生成的），不改写则 SCHEMA-04 的
    「经哪个接口」这一环无法从蓝图里跳转过去。解析不到的 ``api_ref`` **删键**——留一个
    悬空引用比没有更糟（115 渲染会指向不存在的契约）。
    """
    index: dict[str, str] = {}
    for contract in contracts if isinstance(contracts, list) else []:
        if not isinstance(contract, dict):
            continue
        contract_id = str(contract.get("id") or "")
        if not contract_id:
            continue
        index.setdefault(contract_id, contract_id)
        for key in ("name", "path"):
            label = str(contract.get(key) or "").strip()
            if label:
                index.setdefault(label, contract_id)
    linked = 0
    for flow in flows if isinstance(flows, list) else []:
        if not isinstance(flow, dict):
            continue
        for step in flow.get("steps") or []:
            if not isinstance(step, dict) or "api_ref" not in step:
                continue
            resolved = index.get(str(step.get("api_ref") or ""))
            if resolved:
                step["api_ref"] = resolved
                linked += 1
            else:
                step.pop("api_ref", None)
    return linked


def _pick_availability(*candidates: dict) -> str:
    """取数据可用性枚举——**只从 ``data_source`` 层取**（B4：顶层同名键一概不读）。

    111 schema 的 ``api_contracts[]`` 没有顶层可用性字段；读顶层等于把结论建在幻觉字段上，
    而 114/115 会按 schema 路径读不到（SC-4 表面通过实际失效）。
    """
    for data_source in candidates:
        value = str((data_source or {}).get("availability") or "").strip()
        if value in ("existing", _NEEDS_SUPPORT):
            return value
    return ""


def _normalize_interaction_flows(raw: Any, inputs: _MergeInputs) -> list[dict]:
    """交互流程段归一（SCHEMA-04）：保留六要素字段，非法 step 丢弃。"""
    flows: list[dict] = []
    for index, flow in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(flow, dict):
            continue
        steps = _normalize_flow_steps(flow.get("steps"), prefix=f"{index}")
        name = str(flow.get("name") or "").strip()
        if not steps or not name:
            continue
        entry: dict[str, Any] = {
            "id": str(flow.get("id") or f"flow_{index}"),
            "name": name[:_MAX_TITLE_CHARS],
            "steps": steps,
            "citations": _map_citations(flow.get("citations"), inputs.cite_map),
        }
        trigger = str(flow.get("trigger") or "").strip()
        if trigger:
            entry["trigger"] = trigger[:_MAX_TITLE_CHARS]
        alternatives = _normalize_alternative_paths(
            flow.get("alternative_paths"), prefix=f"{index}"
        )
        if alternatives:
            entry["alternative_paths"] = alternatives
        flows.append(entry)
    return flows[:_MAX_LIST_ITEMS]


def _normalize_flow_steps(raw: Any, *, prefix: str) -> list[dict]:
    steps: list[dict] = []
    for index, step in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(step, dict):
            continue
        action = str(step.get("action") or "").strip()
        actor = str(step.get("actor") or "").strip()
        if not action or not actor:
            continue
        try:
            seq = int(step.get("seq"))
        except (TypeError, ValueError):
            seq = index + 1
        entry: dict[str, Any] = {"seq": seq, "actor": actor, "action": action[:_MAX_TITLE_CHARS]}
        for key in ("component", "api_ref", "data_in", "data_out"):
            value = str(step.get(key) or "").strip()
            if value:
                entry[key] = value[:_MAX_TITLE_CHARS]
        note = _as_block_list(step.get("note"), block_id=f"blk_bp_step_{prefix}_{index}")
        if note:
            entry["note"] = note
        steps.append(entry)
    return steps[:_MAX_LIST_ITEMS]


def _normalize_alternative_paths(raw: Any, *, prefix: str) -> list[dict]:
    paths: list[dict] = []
    for index, path in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(path, dict):
            continue
        condition = str(path.get("condition") or "").strip()
        steps = _normalize_flow_steps(path.get("steps"), prefix=f"{prefix}alt{index}")
        if not condition and not steps:
            continue
        paths.append({"condition": condition[:_MAX_TITLE_CHARS], "steps": steps})
    return paths[:_MAX_LIST_ITEMS]


def _normalize_impact_analysis(raw: Any, inputs: _MergeInputs) -> dict:
    """影响范围段归一：两键恒在（``business_impact`` / ``affected_features``）。"""
    drafted = raw if isinstance(raw, dict) else {}
    features: list[dict] = []
    for index, feature in enumerate(drafted.get("affected_features") or []):
        if not isinstance(feature, dict):
            continue
        name = str(feature.get("feature") or "").strip()
        if not name:
            continue
        kind = str(feature.get("kind") or "").strip()
        entry: dict[str, Any] = {
            "feature": name[:_MAX_TITLE_CHARS],
            "kind": kind if kind in _VALID_IMPACT_KINDS else "behavior_change",
            "citations": _map_citations(feature.get("citations"), inputs.cite_map),
            "description": _as_block_list(
                feature.get("description"), block_id=f"blk_bp_impact_{index}"
            ),
        }
        entry["repository_ids"] = [
            str(value)
            for value in (feature.get("repository_ids") or [])
            if str(value or "") in inputs.assoc_ids
        ][:_MAX_LIST_ITEMS]
        features.append(entry)

    impact: dict[str, Any] = {
        "business_impact": _as_block_list(
            drafted.get("business_impact"), block_id="blk_bp_business_impact"
        ),
        "affected_features": features[:_MAX_LIST_ITEMS],
    }
    regression = _normalize_regression_scope(drafted.get("regression_scope"))
    if regression:
        impact["regression_scope"] = regression
    for key in ("compat_risks", "rollback_plan"):
        blocks = _as_block_list(drafted.get(key), block_id=f"blk_bp_{key}")
        if blocks:
            impact[key] = blocks
    return impact


def _normalize_regression_scope(raw: Any) -> list[dict]:
    scope: list[dict] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        area = str(entry.get("area") or "").strip()
        if not area:
            continue
        level = str(entry.get("level") or "").strip()
        scope.append(
            {
                "area": area[:_MAX_TITLE_CHARS],
                "level": level if level in ("full", "smoke", "none") else "smoke",
                "reason": str(entry.get("reason") or "")[:_MAX_TITLE_CHARS],
            }
        )
    return scope[:_MAX_LIST_ITEMS]


# ══════════════════════════════════════════════════════════════════════════
# needs_support 落位（B4）
# ══════════════════════════════════════════════════════════════════════════


def _support_hints(repo_plans: dict) -> dict[tuple[str, str], str]:
    """``(仓 id, 契约标签) → from_repository_id``：对账发现无 provider 时的协作仓线索。"""
    hints: dict[tuple[str, str], str] = {}
    for repository_id in sorted(str(rid) for rid in (repo_plans or {})):
        section = (repo_plans or {}).get(repository_id)
        if not isinstance(section, dict):
            continue
        for api in section.get("apis_consumed") or []:
            if not isinstance(api, dict):
                continue
            label = str(api.get("name") or "").strip() or str(api.get("path") or "").strip()
            hint = str(api.get("from_repository_id") or "").strip()
            source = api.get("data_source") if isinstance(api.get("data_source"), dict) else {}
            hint = str(source.get("support_repository_id") or "").strip() or hint
            if label and hint:
                hints[(repository_id, label)] = hint
    return hints


def _apply_needs_support(contracts: list, gaps: list, hints: dict) -> int:
    """``gaps`` 逐条把对应契约标成需要对方配合（**B4：只写 ``data_source`` 两键**）。

    ``data_source`` 不存在时先建 ``{}`` 再写；顶层同名键一概不产 —— 111 schema 里没有
    那个键，写它会让 114/115 按 schema 路径读不到（SC-4 表面通过实际失效）。
    """
    index: dict[tuple[str, str], dict] = {}
    for contract in contracts if isinstance(contracts, list) else []:
        if not isinstance(contract, dict):
            continue
        repository_id = str(contract.get("repository_id") or "")
        for key in ("name", "path", "id"):
            label = str(contract.get(key) or "").strip()
            if label:
                index.setdefault((repository_id, label), contract)
    applied = 0
    for gap in gaps if isinstance(gaps, list) else []:
        if not isinstance(gap, dict):
            continue
        contract = index.get((str(gap.get("repository_id") or ""), str(gap.get("api") or "")))
        if contract is None:
            continue
        data_source = contract.get("data_source")
        if not isinstance(data_source, dict):
            data_source = {}
            contract["data_source"] = data_source
        data_source["availability"] = _NEEDS_SUPPORT
        if not str(data_source.get("support_repository_id") or "").strip():
            hint = hints.get((str(gap.get("repository_id") or ""), str(gap.get("api") or "")), "")
            if hint:
                data_source["support_repository_id"] = hint
        applied += 1
    return applied


# ══════════════════════════════════════════════════════════════════════════
# 融合 adapter
# ══════════════════════════════════════════════════════════════════════════


class BlueprintMergeAdapter:
    """阶段 3 融合装配：确定性投影 + 分节起草 + 派生锚点 + 对账 + 落幂等版本。

    依赖全 keyword-only 可注入（测试注替身，生产零参构造）。
    """

    # 类属性上界（照 analog 的 `MAX_MERGE_RETRIES` 形态）；113-06 会接到 SystemSetting。
    MAX_MERGE_ROUNDS = MAX_MERGE_ROUNDS

    def __init__(
        self,
        *,
        synthesizer: Any = None,
        artifact_service: Any = None,
        lifecycle_service: Any = None,
        repo_plan_adapter: Any = None,
        node_execution_id: str = "",
    ) -> None:
        self.synthesizer = synthesizer or LLMBlueprintSectionSynthesizer()
        self._artifact_service = artifact_service
        self._lifecycle_service = lifecycle_service
        self._repo_plan_adapter = repo_plan_adapter
        self.node_execution_id = node_execution_id or ""

    # ── 主入口 ────────────────────────────────────────────────────────────

    async def merge(self, session: Any) -> dict:
        """融合一次，返回**恒定七键**结果 dict（handler 只据 ``validation_status`` 决定出边）。

        七步：读基线（**取最新 ``version_no``**）→ 收各仓方案 + 波次 → 取轮次 → 建引用池
        + 两段确定性投影 + 四段分节起草 + 派生 ``must_haves`` → 纯函数对账（矛盾开澄清）
        → ``validate_blueprint`` → ``add_version``。

        Returns:
            ``{"validation_status": "passed"|"failed"|"needs_clarification"|"retry"
            |"exhausted", "artifact_version_id": str, "attempt": int,
            "back_target": str, "report": dict, "reconcile": dict, "stage_state": dict}``。
            ``passed`` 路径的 ``artifact_version_id`` 必非空 —— ``_h_bp_merge`` 要用它回填
            ``StageOutcome.current_artifact_version``。

            覆盖率门新增的两条出口（113-06）在上述七键之外**各追加归因键**：

            - ``{"validation_status": "retry", ...}``：覆盖率未达标且回退轮次未用尽。
              额外键 ``back_repository_id`` / ``gap_count``；``back_target`` ∈
              ``repo_plan``（单仓证据缺口）/ ``merge``（融合层缺口）。**不落版本**。
            - ``{"validation_status": "exhausted", ...}``：轮次用尽。**仍落版本**并额外带
              ``unresolved``（未决项定位清单）/ ``back_repository_id`` / ``gap_count``，
              同时开一条 blocking 澄清线程。``_h_bp_merge`` 把它映射到 ``merged``
              ⇒ stage 终态 done，**绝不**落 failed 终态（OQ-3）。
        """
        started = time.monotonic()
        state = await self._aload_stage_state(session)
        attempt = _attempt_of(state)
        artifact, version = await self._aload_baseline(session)
        if artifact is None:
            return self._result(
                "failed",
                attempt=attempt,
                report={"reason": "no_baseline_version"},
                back_target=STAGE_STATE_KEY,
                stage_state=_build_stage_state(state, attempt=attempt, status="failed"),
            )
        baseline = version.content if isinstance(getattr(version, "content", None), dict) else {}
        self._emit("blueprint_merge_started", session, attempt=attempt)

        repo_plans = await self._acollect_repo_plans(session)
        waves = build_api_waves(repo_plans)
        locked = baseline.get("repo_associations")
        # `requirement_spec` / `meta` / `citations` 三条一律**从融合基线承接**（W2）：
        # 重造会丢 112 写入的非 required 键（summary / requirement_refs / language /
        # revision_round / feature_points[].intent），而缺 required 键会让整份判非法。
        requirement_spec = (
            baseline.get("requirement_spec")
            if isinstance(baseline.get("requirement_spec"), dict)
            else {"goal": [], "feature_points": []}
        )
        baseline_pool = (
            baseline.get("citations") if isinstance(baseline.get("citations"), dict) else {}
        )

        pool_entries, cite_map = build_citation_pool(repo_plans, locked or [])
        citations = {**baseline_pool, **{entry["citation_id"]: entry for entry in pool_entries}}
        # 基线池内已有的 id 追加恒等映射：112 落的 `fitness.citations` 已是池内 id，
        # 不加这层会被当成池外裸串丢掉（覆盖率归零）。
        cite_map = {**cite_map, **{citation_id: citation_id for citation_id in citations}}

        associations = project_repo_associations(locked or [], cite_map)
        assoc_ids = frozenset(entry["repository_id"] for entry in associations)
        current_state = [
            analysis
            for analysis in project_current_state(repo_plans, cite_map)
            if analysis["repository_id"] in assoc_ids
        ]
        inputs = _MergeInputs(
            repo_plans=repo_plans,
            waves=waves,
            associations=associations,
            current_state=current_state,
            requirement_spec=requirement_spec,
            cite_map=cite_map,
            assoc_ids=assoc_ids,
        )
        sections, degraded = await self._adraft_sections(session, inputs)
        if len(degraded) == len(MERGE_SECTIONS):
            return self._result(
                "failed",
                attempt=attempt,
                report={"reason": "all_sections_failed", "sections": sorted(degraded)},
                back_target=STAGE_STATE_KEY,
                stage_state=_build_stage_state(
                    state, attempt=attempt, status="failed", degraded=degraded
                ),
            )

        # 流程步骤的 api_ref 由服务端换算成真实契约 id（起草侧只知道接口名）。
        _link_api_refs(sections[SECTION_INTERACTION_FLOWS], sections[SECTION_API_CONTRACTS])
        must_haves = derive_must_haves(
            requirement_spec=requirement_spec,
            implementation_overview=sections[SECTION_IMPLEMENTATION_OVERVIEW],
            api_contracts=sections[SECTION_API_CONTRACTS],
        )
        assembled: dict[str, Any] = {
            # import 常量而非字面量：schema 里是 const，写错即整份非法；写成缺失则会被
            # 当成隐式 v0 pass-through（那是「假通过」，六段再完美也不落蓝图版本）。
            "schema_version": BLUEPRINT_SCHEMA_VERSION,
            "meta": self._project_meta(session, baseline, requirement_spec),
            "requirement_spec": requirement_spec,
            "repo_associations": associations,
            "current_state_analysis": current_state,
            "implementation_overview": sections[SECTION_IMPLEMENTATION_OVERVIEW],
            "api_contracts": sections[SECTION_API_CONTRACTS],
            "impact_analysis": sections[SECTION_IMPACT_ANALYSIS],
            "interaction_flows": sections[SECTION_INTERACTION_FLOWS],
            "must_haves": must_haves,
            "citations": citations,
        }
        for key in ("decision_log", "deferred_ideas"):
            if isinstance(baseline.get(key), list):
                assembled[key] = baseline[key]

        report = reconcile_cross_repo_apis(assembled)
        applied = _apply_needs_support(
            assembled[SECTION_API_CONTRACTS], report["gaps"], _support_hints(repo_plans)
        )
        if applied:
            # 重跑一次：刚标上的 needs_support 还要过「协作仓在关联清单里」那道检查。
            report = reconcile_cross_repo_apis(assembled)
        counts = {key: len(value) for key, value in report.items()}
        if report["conflicts"] or report["missing_support_repos"]:
            thread_id = await self._aopen_clarification(session, artifact, version, report)
            self._log(
                "blueprint_merge_needs_clarification",
                session,
                attempt=attempt,
                thread_id=thread_id,
                **counts,
            )
            return self._result(
                "needs_clarification",
                attempt=attempt,
                report={**report, "thread_id": thread_id},
                reconcile=counts,
                back_target=STAGE_STATE_KEY,
                stage_state=_build_stage_state(
                    state,
                    attempt=attempt,
                    status="needs_clarification",
                    degraded=degraded,
                    counts=counts,
                ),
            )

        ok, error = validate_blueprint(assembled)
        if not ok:
            self._log("blueprint_merge_schema_invalid", session, attempt=attempt, error=error)
            return self._result(
                "failed",
                attempt=attempt,
                report={"schema_error": (error or "")[:_MAX_ERROR_CHARS]},
                reconcile=counts,
                back_target=STAGE_STATE_KEY,
                stage_state=_build_stage_state(
                    state, attempt=attempt, status="failed", degraded=degraded, counts=counts
                ),
            )

        # ── 引用覆盖率门（FLOW-06 后半，阈值可配）───────────────────────────
        # 位置严格在 `validate_blueprint` 之后、`add_version` 之前：schema 非法的产物连
        # 归因都不该做（缺口清单会指向一份本就非法的文档）。
        min_ratio, max_rounds = await self._aload_merge_config()
        coverage = citation_coverage(assembled)
        exhausted = False
        gate_gaps: list[dict] = []
        decision = {"back_target": "", "back_repository_id": "", "gap_count": 0}
        if coverage < min_ratio:
            gate_gaps = coverage_gaps(assembled)
            decision = decide_back_target(gate_gaps)
            if attempt + 1 <= max_rounds:
                # 有界回退：**不落版本**（未达覆盖率的中间产物不该进版本历史），
                # 轮次由本单点递增后整体回写 stage_state。
                self._log(
                    "blueprint_merge_coverage_gate_retry",
                    session,
                    attempt=attempt + 1,
                    coverage=round(coverage, 4),
                    min_ratio=min_ratio,
                    gap_count=len(gate_gaps),
                    back_target=decision["back_target"],
                    level="warning",
                )
                return self._result(
                    "retry",
                    attempt=attempt + 1,
                    report={
                        "coverage": round(coverage, 4),
                        "min": min_ratio,
                        # 只带计数与前 N 条**定位**，绝不带结论正文（T-113-42）。
                        "gaps": len(gate_gaps),
                        "gap_locations": gate_gaps[:_MAX_UNRESOLVED],
                    },
                    reconcile=counts,
                    back_target=decision["back_target"],
                    stage_state=_build_stage_state(
                        state,
                        attempt=attempt,
                        status="retry",
                        degraded=degraded,
                        counts=counts,
                        attribution=decision,
                    ),
                    extra={
                        "back_repository_id": decision["back_repository_id"],
                        "gap_count": decision["gap_count"],
                    },
                )
            exhausted = True

        new_version = await self._aadd_version(session, artifact, assembled, attempt)
        if new_version is None:
            return self._result(
                "failed",
                attempt=attempt,
                report={"reason": "artifact_content_invalid"},
                reconcile=counts,
                back_target=STAGE_STATE_KEY,
                stage_state=_build_stage_state(
                    state, attempt=attempt, status="failed", degraded=degraded, counts=counts
                ),
            )

        if exhausted:
            # ⚠️ 超界出口是 **STAGE_DONE 带未决项**，绝不 failed（OQ-3 / T-113-37）：
            # 蓝图已成形，只是引用覆盖率没达标 —— 那是「待人审」，不是「流程失败」。
            # 版本照落（成果不许丢），未决项进 stage_state 快照供 114 接手。
            unresolved = [dict(gap) for gap in gate_gaps[:_MAX_UNRESOLVED]]
            thread_id = await self._aopen_coverage_clarification(
                session,
                artifact,
                new_version,
                coverage=coverage,
                min_ratio=min_ratio,
                unresolved=unresolved,
            )
            await self._adistill_context_entries(session)
            self._log(
                "blueprint_merge_coverage_gate_exhausted",
                session,
                attempt=attempt,
                artifact_version_id=str(new_version.id),
                coverage=round(coverage, 4),
                min_ratio=min_ratio,
                unresolved_count=len(unresolved),
                thread_id=thread_id,
                back_target=decision["back_target"],
                level="warning",
            )
            return self._result(
                "exhausted",
                attempt=attempt,
                artifact_version_id=str(new_version.id),
                report={
                    "coverage": round(coverage, 4),
                    "min": min_ratio,
                    "gaps": len(gate_gaps),
                    "thread_id": thread_id,
                },
                reconcile=counts,
                back_target=decision["back_target"],
                stage_state=_build_stage_state(
                    state,
                    attempt=attempt,
                    status="exhausted",
                    degraded=degraded,
                    counts=counts,
                    unresolved=unresolved,
                    attribution=decision,
                ),
                extra={
                    "unresolved": unresolved,
                    "back_repository_id": decision["back_repository_id"],
                    "gap_count": decision["gap_count"],
                },
            )

        await self._adistill_context_entries(session)
        self._log(
            "blueprint_merge_completed",
            session,
            attempt=attempt,
            artifact_version_id=str(new_version.id),
            repo_count=len(associations),
            degraded_sections=sorted(degraded),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            **counts,
        )
        return self._result(
            "passed",
            attempt=attempt,
            artifact_version_id=str(new_version.id),
            reconcile=counts,
            stage_state=_build_stage_state(
                state, attempt=attempt, status="passed", degraded=degraded, counts=counts
            ),
        )

    # ── 分节起草（每段独立 except 降级，四段全挂才判 failed） ───────────────

    async def _adraft_sections(self, session: Any, inputs: _MergeInputs) -> tuple[dict, list[str]]:
        drafters = {
            SECTION_IMPLEMENTATION_OVERVIEW: self._adraft_implementation_overview,
            SECTION_API_CONTRACTS: self._adraft_api_contracts,
            SECTION_INTERACTION_FLOWS: self._adraft_interaction_flows,
            SECTION_IMPACT_ANALYSIS: self._adraft_impact_analysis,
        }
        sections: dict[str, Any] = {}
        degraded: list[str] = []
        for section in MERGE_SECTIONS:
            try:
                sections[section] = await drafters[section](session, inputs)
            except Exception as exc:  # noqa: BLE001 — 单段失败只降级该段，绝不上抛
                # ⚠️ 降级值取 `SECTION_FALLBACKS`（过 schema 的最小合法结构），
                # **不是** `{}` / `None` / 缺键：缺 required 键会把「一段挂」放大成
                # 「整份非法」，明明五段完好却整轮 failed。
                sections[section] = copy.deepcopy(SECTION_FALLBACKS[section])
                degraded.append(section)
                self._log(
                    "blueprint_merge_section_degraded",
                    session,
                    section=section,
                    error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                    level="warning",
                )
        return sections, degraded

    async def _adraft_implementation_overview(self, session: Any, inputs: _MergeInputs) -> dict:
        """实现概述段（SCHEMA-03）：一次调用只产这一段。"""
        from agents.call_source import CallSource, use_call_source

        parts = _prompt_parts(_implementation_overview_prompt(inputs))
        with use_call_source(CallSource.BLUEPRINT_MERGE):
            payload = await self.synthesizer.draft(
                section=SECTION_IMPLEMENTATION_OVERVIEW, prompt_parts=parts
            )
        return _normalize_implementation_overview(
            _extract_section(payload, SECTION_IMPLEMENTATION_OVERVIEW), inputs
        )

    async def _adraft_api_contracts(self, session: Any, inputs: _MergeInputs) -> list:
        """API 段（SCHEMA-05）：一次调用只产这一段。"""
        from agents.call_source import CallSource, use_call_source

        parts = _prompt_parts(_api_contracts_prompt(inputs))
        with use_call_source(CallSource.BLUEPRINT_MERGE):
            payload = await self.synthesizer.draft(
                section=SECTION_API_CONTRACTS, prompt_parts=parts
            )
        return _normalize_api_contracts(_extract_section(payload, SECTION_API_CONTRACTS), inputs)

    async def _adraft_interaction_flows(self, session: Any, inputs: _MergeInputs) -> list:
        """交互流程段（SCHEMA-04）：一次调用只产这一段。"""
        from agents.call_source import CallSource, use_call_source

        parts = _prompt_parts(_interaction_flows_prompt(inputs))
        with use_call_source(CallSource.BLUEPRINT_MERGE):
            payload = await self.synthesizer.draft(
                section=SECTION_INTERACTION_FLOWS, prompt_parts=parts
            )
        return _normalize_interaction_flows(
            _extract_section(payload, SECTION_INTERACTION_FLOWS), inputs
        )

    async def _adraft_impact_analysis(self, session: Any, inputs: _MergeInputs) -> dict:
        """影响范围段：一次调用只产这一段。"""
        from agents.call_source import CallSource, use_call_source

        parts = _prompt_parts(_impact_analysis_prompt(inputs))
        with use_call_source(CallSource.BLUEPRINT_MERGE):
            payload = await self.synthesizer.draft(
                section=SECTION_IMPACT_ANALYSIS, prompt_parts=parts
            )
        return _normalize_impact_analysis(
            _extract_section(payload, SECTION_IMPACT_ANALYSIS), inputs
        )

    # ── 澄清线程（矛盾绝不静默拍板） ────────────────────────────────────────

    async def _aopen_clarification(
        self, session: Any, artifact: Any, version: Any, report: dict
    ) -> str:
        """跨仓矛盾 / 缺协作仓 → 开一条 blocking 澄清线程交人裁决。

        ``return_stage="merge"`` 必填（B3）：漏传会让阶段 3 的澄清恢复退回阶段 1。
        问题文本只列契约名与双方取值 / 缺的协作仓，**绝不夹带方案正文**（T-113-33）。
        幂等：该 artifact 上已有 OPEN 的 blocking 澄清线程时不叠开（会话本就停着）。
        """
        try:
            if await self._acount_open_blocking(artifact.id):
                return ""
            thread = await self._get_lifecycle_service().open_thread(
                artifact,
                kind="ai_clarification",
                blocking=True,
                question=_clarification_question(report),
                initiated_by_user_id=_initiated_by(session),
                created_on_version=version,
                # B3：必填且必须是 merge（== STAGE_STATE_KEY）——漏传或写错会让阶段 3 的
                # 澄清恢复退回阶段 1（`blueprint_resume` 的 stage→status 映射依赖它）。
                return_stage="merge",
            )
            return str(thread.id)
        except Exception as exc:  # noqa: BLE001 — 开不出线程也不上抛（返回 needs_clarification 仍成立）
            self._log(
                "blueprint_merge_clarification_open_failed",
                session,
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                level="warning",
            )
            return ""

    async def _aopen_coverage_clarification(
        self,
        session: Any,
        artifact: Any,
        version: Any,
        *,
        coverage: float,
        min_ratio: float,
        unresolved: list[dict],
    ) -> str:
        """超界（引用覆盖率未达标且回退轮次用尽）→ 开一条 blocking 澄清线程带未决项。

        ``return_stage="merge"`` 必填（B3）：漏传会让人审恢复后退回阶段 1，已产出的
        RepoPlan 与本版蓝图被当成「还没调研」。问题文本只列**段名 + 序号 + 仓 id**
        （T-113-42：未决项清单绝不夹带结论正文或凭证）。幂等：该 artifact 已有 OPEN
        blocking 澄清线程时不叠开。
        """
        try:
            if await self._acount_open_blocking(artifact.id):
                return ""
            thread = await self._get_lifecycle_service().open_thread(
                artifact,
                kind="ai_clarification",
                blocking=True,
                question=_coverage_question(coverage, min_ratio, unresolved),
                initiated_by_user_id=_initiated_by(session),
                created_on_version=version,
                return_stage="merge",
            )
            return str(thread.id)
        except Exception as exc:  # noqa: BLE001 — 开不出线程也不上抛（exhausted 出口仍成立）
            self._log(
                "blueprint_merge_coverage_clarification_open_failed",
                session,
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                level="warning",
            )
            return ""

    # ── 运行时阈值（只调既有 getter，settings_service 一行不改）─────────────

    async def _aload_merge_config(self) -> tuple[float, int]:
        """读 ``SettingKeys.BLUEPRINT_MERGE_CONFIG`` → ``(覆盖率下限, 回退轮次上界)``。

        缺配置 / 非 JSON / 缺键 / 值类型错 → **整段回落模块常量**（配置坏了绝不能卡死
        流水线：覆盖率门是质量门不是可用性门）。读取一律经既有
        ``settings_service.aget_json_setting``，本 plan 不改 settings_service 一行。
        """
        try:
            from system.models import SettingKeys
            from system.settings_service import aget_json_setting

            cfg = await aget_json_setting(SettingKeys.BLUEPRINT_MERGE_CONFIG, {}) or {}
            min_ratio = float(cfg.get("citation_coverage_min", _DEFAULT_CITATION_COVERAGE_MIN))
            max_rounds = int(cfg.get("max_merge_rounds", MAX_MERGE_ROUNDS))
            return min_ratio, max_rounds
        except Exception as exc:  # noqa: BLE001 — 配置坏了回默认，绝不阻断融合
            self._log(
                "blueprint_merge_config_load_failed",
                None,
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                level="warning",
            )
            return _DEFAULT_CITATION_COVERAGE_MIN, MAX_MERGE_ROUNDS

    # ── distill 沉淀 hook（BUS-03，best-effort，绝不反噬主链）───────────────

    async def _adistill_context_entries(self, session: Any) -> None:
        """会话总线里有长期价值的条目 → ``ProjectMemory`` **草案**（人工 confirm 才生效）。

        三条硬纪律：

        1. **只调** ``MemoryDistiller.distill_to_draft``（产 pending 草案）。绝不调
           ``MemoryService`` 的 active 直写入口（会覆盖人工内容）、人工确认入口
           （那是人工动作的专属出口）或 IDE hook 精炼入口（它压根不产草案）——
           三者的反向「零调用」断言见 ``test_blueprint_distill.py``。
        2. ``proposed_by`` **只取真实 User**（``session.created_by``）；解析不到就
           **跳过沉淀**，绝不伪造 actor 去绕过 ``distill_to_draft`` 的成员校验。
           项目归属同理取自总线条目上的 ``project_id``（``ConvergenceSession`` 无
           project FK），解析不到亦跳过。
        3. 整段 ``except`` 吞掉：沉淀失败绝不反噬 merge 主链（蓝图已落版本）。
        """
        try:
            from delivery.services.blueprint_context_service import BlueprintContextService
            from initiatives.services.memory_distill import MemoryDistiller

            service = BlueprintContextService()
            entries: list[dict] = []
            for kind in _DISTILL_KINDS:
                rows = await service.read_entries(
                    session=session, kind=kind, status="active", limit=_DISTILL_READ_LIMIT
                )
                entries.extend(row for row in (rows or []) if isinstance(row, dict))
            if not entries:
                return
            user = await self._aresolve_session_user(session)
            if user is None:
                return
            project_id = await self._aresolve_bus_project_id(session)
            if not project_id:
                return
            text = _distill_text(entries)
            if not text:
                return
            await MemoryDistiller().distill_to_draft(
                project_id=project_id,
                conversation_text=text,
                proposed_by=user,
                initiated_by_user_id=str(getattr(user, "id", "") or ""),
            )
            self._log(
                "blueprint_context_distill_completed",
                session,
                entry_count=len(entries),
            )
        except Exception as exc:  # noqa: BLE001 — 沉淀 best-effort，绝不反噬 merge 主链
            logger.warning(
                "blueprint_context_distill_failed",
                category="sampling",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
            )

    @staticmethod
    @sync_to_async
    def _aresolve_session_user(session: Any) -> Any:
        """取 ``session.created_by`` 真实 ``User`` 实例（lazy-FK 必须在 sync 上下文取）。

        与 ``blueprint_research_adapter._resolve_dispatch_user`` 同款（**不 import 私有名**）。
        为空即返回 ``None``，调用方跳过沉淀 —— 绝不伪造 actor。
        """
        return getattr(session, "created_by", None)

    @staticmethod
    async def _aresolve_bus_project_id(session: Any) -> str:
        """项目归属取自本会话总线条目上的 ``project_id``（``ConvergenceSession`` 无该列）。

        解析不到返回空串（调用方跳过沉淀，不伪造归属）。
        """
        from delivery.models import BlueprintContextEntry

        project_id = await (
            BlueprintContextEntry.objects.filter(
                convergence_session_id=getattr(session, "id", None),
                project_id__isnull=False,
            )
            .values_list("project_id", flat=True)
            .afirst()
        )
        return str(project_id or "")

    # ── 只读边界与依赖装配（本文件零 ORM 写，INV-6） ────────────────────────

    async def _aadd_version(
        self, session: Any, artifact: Any, assembled: dict, attempt: int
    ) -> Any:
        """落幂等版本；内容非法时返回 ``None``（转 failed，绝不上抛，graceful）。"""
        try:
            return await self._get_artifact_service().add_version(
                artifact,
                assembled,
                produced_by_session_id=str(getattr(session, "id", "")),
                # 轮次进 produced_by_ref：同 content_hash 不翻版本（幂等），但哪一轮产出的
                # 仍可归因（P-6 残留口 1）。
                produced_by_ref=f"blueprint_merge#attempt={attempt}",
            )
        except Exception as exc:  # noqa: BLE001 — 内容非法转 failed，绝不上抛（graceful）
            self._log(
                "blueprint_merge_add_version_failed",
                session,
                attempt=attempt,
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
            )
            return None

    def _get_artifact_service(self) -> Any:
        if self._artifact_service is None:
            from delivery.services import ArtifactService

            self._artifact_service = ArtifactService()
        return self._artifact_service

    def _get_lifecycle_service(self) -> Any:
        if self._lifecycle_service is None:
            from delivery.services.blueprint_lifecycle_service import BlueprintLifecycleService

            self._lifecycle_service = BlueprintLifecycleService()
        return self._lifecycle_service

    def _get_repo_plan_adapter(self) -> Any:
        if self._repo_plan_adapter is None:
            from services.process_runtime.blueprint_repo_plan import BlueprintRepoPlanAdapter

            self._repo_plan_adapter = BlueprintRepoPlanAdapter(
                node_execution_id=self.node_execution_id
            )
        return self._repo_plan_adapter

    async def _acollect_repo_plans(self, session: Any) -> dict:
        try:
            plans = await self._get_repo_plan_adapter().acollect_repo_plans(session)
        except Exception as exc:  # noqa: BLE001 — 读失败按「无方案」处理（装配仍产投影两段）
            self._log(
                "blueprint_merge_repo_plans_collect_failed",
                session,
                error=redact_secrets_in_text(str(exc))[:_MAX_ERROR_CHARS],
                level="warning",
            )
            return {}
        return plans if isinstance(plans, dict) else {}

    @staticmethod
    async def _aload_stage_state(session: Any) -> dict:
        """重读会话新实例的 ``stage_state``（轮次递增点单点串行，减少 lost-update 窗口）。"""
        from delivery.models import ConvergenceSession

        try:
            row = await (
                ConvergenceSession.objects.filter(id=getattr(session, "id", None))
                .values("stage_state")
                .afirst()
            )
            state = (row or {}).get("stage_state")
            if isinstance(state, dict):
                return state
        except Exception:  # noqa: BLE001 — 读失败回落内存态（绝不因观测面阻断融合）
            pass
        state = getattr(session, "stage_state", None)
        return state if isinstance(state, dict) else {}

    @staticmethod
    async def _aload_baseline(session: Any) -> tuple[Any, Any]:
        """融合基线 = artifact 的**最新** ``ArtifactVersion``（``order_by("-version_no")``）。

        ⚠️ 绝不把会话钉住的那一版当基线（P-6 残留口 2）：它只在 handler 显式回填
        ``StageOutcome`` 时才推进，读它会把确认门 / 规格门刚落的成果覆盖回旧内容。
        会话指针在此**只用于定位 artifact**，不用于取内容。
        """
        from delivery.models import Artifact, ArtifactVersion, ConvergenceSession

        artifact_id = await (
            ConvergenceSession.objects.filter(id=getattr(session, "id", None))
            .values_list("current_artifact_version__artifact_id", flat=True)
            .afirst()
        )
        if not artifact_id:
            return None, None
        artifact = await Artifact.objects.filter(id=artifact_id).afirst()
        version = await (
            ArtifactVersion.objects.filter(artifact_id=artifact_id).order_by("-version_no").afirst()
        )
        if artifact is None or version is None:
            return None, None
        return artifact, version

    @staticmethod
    async def _acount_open_blocking(artifact_id: Any) -> int:
        from delivery.models import BlueprintThread, ThreadKind, ThreadStatus

        return await BlueprintThread.objects.filter(
            artifact_id=artifact_id,
            kind=ThreadKind.AI_CLARIFICATION,
            blocking=True,
            status=ThreadStatus.OPEN,
        ).acount()

    # ── meta 承接（W2：缺 title / project_id 时整份非法或假通过成 v0） ───────

    def _project_meta(self, session: Any, baseline: dict, requirement_spec: dict) -> dict:
        """``meta`` **从融合基线整段承接**（浅合并），只在缺 required 两键时兜底补。

        绝不重造：重造会丢 112 写入的 ``summary`` / ``requirement_refs`` / ``language``
        / ``revision_round`` 等非 required 键。
        """
        source = baseline.get("meta") if isinstance(baseline.get("meta"), dict) else {}
        meta = {**source}
        if not str(meta.get("title") or "").strip():
            meta["title"] = _default_title(requirement_spec, session)
        if not str(meta.get("project_id") or "").strip():
            meta["project_id"] = _resolve_project_id(session)
        return meta

    # ── 结果形状与观测 ────────────────────────────────────────────────────

    @staticmethod
    def _result(
        status: str,
        *,
        attempt: int,
        artifact_version_id: str = "",
        report: dict | None = None,
        reconcile: dict | None = None,
        stage_state: dict | None = None,
        back_target: str = "",
        extra: dict | None = None,
    ) -> dict:
        """**恒定七键**返回（下游 handler 无需判空分支）。

        ``extra`` 只在**覆盖率门的两条出口**（``retry`` / ``exhausted``）追加归因键
        （``back_repository_id`` / ``gap_count`` / ``unresolved``）—— ``passed`` /
        ``failed`` / ``needs_clarification`` 三条既有出口的键集**逐字未变**（113-05 有一条
        `set(result) == 七键` 的形状断言守着它）。
        """
        result = {
            "validation_status": status,
            "artifact_version_id": artifact_version_id,
            "attempt": attempt,
            "back_target": back_target,
            "report": report or {},
            "reconcile": reconcile or {"gaps": 0, "conflicts": 0, "missing_support_repos": 0},
            "stage_state": stage_state or {},
        }
        if extra:
            result.update(extra)
        return result

    def _emit(self, event: str, session: Any, **payload: Any) -> None:
        """生命周期事件（本 plan 只走 structlog：``event_taxonomy`` 是冻结面，
        ``ConvergenceSessionEvent`` 类型的补齐随 stage 注册归 113-06）。"""
        self._log(event, session, **payload)

    @staticmethod
    def _log(event: str, session: Any, *, level: str = "info", **payload: Any) -> None:
        """结构化事件 best-effort（payload 只含计数与关联键，绝不含方案正文）。"""
        try:
            emit = logger.warning if level == "warning" else logger.info
            emit(
                event,
                category="caller",
                component="process_runtime",
                session_id=str(getattr(session, "id", "")),
                initiated_by_user_id=_initiated_by(session),
                **payload,
            )
        except Exception:  # noqa: BLE001 — 观测绝不反噬融合主链
            pass


# ══════════════════════════════════════════════════════════════════════════
# 模块级 helper（轮次 / stage_state / 澄清文本 / meta 兜底）
# ══════════════════════════════════════════════════════════════════════════


def _attempt_of(state: Any) -> int:
    bucket = (state or {}).get(STAGE_STATE_KEY) if isinstance(state, dict) else None
    try:
        return max(0, int((bucket or {}).get("count", 0)))
    except (TypeError, ValueError):
        return 0


def _build_stage_state(
    state: dict,
    *,
    attempt: int,
    status: str,
    degraded: list[str] | None = None,
    counts: dict | None = None,
    unresolved: list[dict] | None = None,
    attribution: dict | None = None,
) -> dict:
    """``{**state, "merge": {...}}`` 浅合并整体回写（只存计数与定位，序列化后 < 2KB）。

    ⚠️ ``stage_state`` 是**整字典替换**（handler 把本返回值原样落盘）：只写增量会把
    ``routing`` / ``decomposition`` / ``repo_plan`` 等既有键一起清空。故这里必须
    ``{**state, ...}`` 浅合并整体产出，形态照 ``aadvance_reroute``。

    **adapter 不自己落库**：由 ``builtin_processes._h_bp_merge`` 单点持久化（并行路径写
    单行 JSON 就是 lost-update 场景，113-04 已确立该约定；回调路径永不触碰轮次计数）。

    ``unresolved`` / ``last_attribution`` 只在覆盖率门的出口写：前者是超界带给 114 的
    未决项快照（**只含 section/index/repository_id 标量**，零结论正文），后者是本轮
    归因结论（回哪个仓 / 重融合）。
    """
    bucket: dict[str, Any] = {
        "count": attempt + 1,
        "status": status,
        "degraded_sections": sorted(degraded or []),
    }
    bucket.update({key: int(value) for key, value in (counts or {}).items()})
    if unresolved is not None:
        bucket["unresolved"] = unresolved[:_MAX_UNRESOLVED]
    if attribution:
        bucket["last_attribution"] = dict(attribution)
    return {**(state if isinstance(state, dict) else {}), STAGE_STATE_KEY: bucket}


def _clarification_question(report: dict) -> str:
    """澄清问题文本：只列契约名与双方取值 / 缺的协作仓（有界截断，零方案正文）。"""
    lines: list[str] = []
    for conflict in (report.get("conflicts") or [])[:20]:
        if not isinstance(conflict, dict):
            continue
        lines.append(
            f"- 契约 {conflict.get('api')} 的 {conflict.get('field')} 两侧不一致："
            f"提供方 {conflict.get('provider_repository_id')} = "
            f"{_short_value(conflict.get('provider_value'))}，"
            f"消费方 {conflict.get('consumer_repository_id')} = "
            f"{_short_value(conflict.get('consumer_value'))}"
        )
    for missing in (report.get("missing_support_repos") or [])[:20]:
        if not isinstance(missing, dict):
            continue
        support = str(missing.get("support_repository_id") or "") or "（未指明）"
        lines.append(
            f"- {missing.get('repository_id')} 消费的 {missing.get('api')} 需要其他仓配合，"
            f"但协作仓 {support} 不在本次锁定的仓库集里"
        )
    return (
        "跨仓接口对账发现以下问题，需要你裁决（自动融合不会替你拍板）：\n"
        + "\n".join(lines)
        + "\n请确认以哪一侧的契约为准，或补充需要一并纳入的协作仓。"
    )


def _coverage_question(coverage: float, min_ratio: float, unresolved: list[dict]) -> str:
    """超界澄清文本：只列**段名 + 序号 + 仓 id**（零结论正文，T-113-42）。"""
    lines = [
        f"- {gap.get('section')} 第 {gap.get('index')} 条"
        + (f"（仓 {gap.get('repository_id')}）" if gap.get("repository_id") else "（未标仓）")
        for gap in unresolved[:_MAX_UNRESOLVED]
        if isinstance(gap, dict)
    ]
    return (
        f"蓝图已装配完成并落版本，但引用覆盖率 {coverage:.2f} 未达基线 {min_ratio:.2f}，"
        "自动补证已用尽回退轮次。以下关键结论仍缺引用证据，需要你确认是补证据还是接受现状：\n"
        + "\n".join(lines)
        + "\n（未决项已随本版蓝图记录，后续 AI 审查会一并带上。）"
    )


def _distill_text(entries: list[dict]) -> str:
    """总线条目 → 供 distill 的会话文本（**有界截断**，只取 key 与结论字段）。

    条目 ``content`` 是半可信 JSON（service 入库时已递归脱敏），这里只取几个结论型字段
    的字符串化摘要，避免把整份契约 schema 灌进 LLM prompt。
    """
    lines: list[str] = []
    for entry in entries:
        key = str(entry.get("key") or "").strip()
        kind = str(entry.get("kind") or "").strip()
        content = entry.get("content") if isinstance(entry.get("content"), dict) else {}
        detail = ""
        for field in ("conclusion", "decision", "summary", "description", "text", "name"):
            value = content.get(field)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
        if not detail:
            detail = _json(content, limit=500)
        lines.append(f"[{kind}] {key}：{detail}")
    return "\n".join(lines)[:_MAX_DISTILL_CHARS]


def _short_value(value: Any) -> str:
    text = value if isinstance(value, str) else _json(value, limit=200)
    return str(text)[:200]


def _default_title(requirement_spec: Any, session: Any) -> str:
    """``meta.title`` 兜底（``minLength 1``）：规格目标首句，取不到用会话 id 兜。"""
    goal = _blocks_to_text((requirement_spec or {}).get("goal")).strip()
    if goal:
        first = goal.splitlines()[0].strip()
        if first:
            return first[:_MAX_TITLE_CHARS]
    return f"技术蓝图 {str(getattr(session, 'id', '') or 'unknown')}"[:_MAX_TITLE_CHARS]


def _resolve_project_id(session: Any) -> str:
    """``meta.project_id`` 兜底（``minLength 1``）。

    ``ConvergenceSession`` 没有 ``project_id`` 列（项目归属只在 ``content.meta.project_id``，
    见 ``blueprint_lifecycle_service`` 模块 docstring P10），故按「feature list 入口的取数
    溯源元信息 → 会话 id」的顺序兜底。正常路径根本走不到这里：基线 ``meta`` 已带该键。
    """
    decomposition = getattr(session, "decomposition", None)
    if isinstance(decomposition, dict):
        feature_meta = decomposition.get("feature_meta")
        if isinstance(feature_meta, dict):
            project_id = str(feature_meta.get("project_id") or "").strip()
            if project_id:
                return project_id
    return str(getattr(session, "id", "") or "unknown")


def _initiated_by(session: Any) -> str:
    return (
        str(getattr(session, "initiated_by_user_id", "") or "")
        or str(getattr(session, "created_by_id", "") or "")
        or "system"
    )
