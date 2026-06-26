"""分支名 AI 生成 + 固定格式权威拼装/正则校验/兜底（Phase 89 PLAN-04，BRANCH_NAMING）。

分支名固定格式（用户精确指定，server 权威拼装）::

    {type}/{yymmdd}.m-{项目跟踪id}.{项目名}[-{版本号}]

- ``type``：conventional commits 类型（feat/fix/chore/...），按变更性质取；
- ``yymmdd``：日期（如 ``260610``）；
- ``m-{项目跟踪id}``：飞书项目跟踪 work_item id（server 权威字段）；
- ``{项目名}``：与项目跟踪看板名一致（路径规整后保留中文 UTF-8）；
- ``{版本号}``：项目名/描述里有版本号则填（如 ``v1.0`` → ``-v1.0``），否则省略。

示例：``feat/260610.m-123456770019.高三提分专项-v1.0``。

安全契约（T-89-04-TAMPER）：**绝不**让 LLM 自由拼整名——``id`` / ``项目名`` / ``日期`` 由
server 权威字段拼装，LLM 仅判定 ``change_type`` 与是否带版本号 + 抽版本号值；正则校验兜底，
非法即回退默认 ``type=feat`` 标准名（防格式漂移/注入）。
"""

from __future__ import annotations

import re
from datetime import date
from time import perf_counter
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "CONVENTIONAL_TYPES",
    "build_branch_name",
    "validate_branch_name",
    "generate_branch_name",
]

_COMPONENT = "initiatives"

# conventional commits 受控类型（闭集；LLM 产出经此归一，非法回退 feat）。
CONVENTIONAL_TYPES: tuple[str, ...] = (
    "feat",
    "fix",
    "chore",
    "refactor",
    "docs",
    "style",
    "test",
    "perf",
    "build",
    "ci",
)
_DEFAULT_TYPE = "feat"

# 固定格式校验正则（与 CONTEXT 锁定一致）：
# ^(type)/{6位日期}.m-{tracking}.{项目名}[-v{版本}]$
_BRANCH_RE = re.compile(
    r"^(?:feat|fix|chore|refactor|docs|style|test|perf|build|ci)/"
    r"\d{6}\.m-\w+\.[^/\s]+(?:-v[\d.]+)?$"
)

# 版本号抽取（v1 / v1.0 / V2.3.1 ...，取数字段，去前导 v）。
_VERSION_RE = re.compile(r"[vV](\d+(?:\.\d+)*)")

# git ref 段非法字符（空白 + git 保留符号）；保留中文等 UTF-8（git 允许 UTF-8 ref）。
_ILLEGAL_SEG_RE = re.compile(r"[\s/~^:?*\[\]\\@]+")

_NAMING_SYSTEM_PROMPT = (
    "你是资深软件工程师，负责为一次需求变更选择 Git 分支的 conventional commits 类型，"
    "并判断需求里是否含版本号。只输出 JSON，不要任何解释。"
)


def _normalize_type(change_type: Any) -> str:
    """归一化 conventional commits 类型（非法/空 → 默认 feat）。"""
    raw = str(change_type or "").strip().lower()
    return raw if raw in CONVENTIONAL_TYPES else _DEFAULT_TYPE


def _normalize_version(version: Any) -> str:
    """归一化版本号为 ``vX[.Y...]``（无有效数字段 → 空串，表示省略）。"""
    match = _VERSION_RE.search(str(version or ""))
    return f"v{match.group(1)}" if match else ""


def _sanitize_tracking_id(tracking_id: Any) -> str:
    """规整项目跟踪 id：去前导 ``m-``、仅保留 ``\\w``（防破坏 ``m-\\w+`` 格式）。"""
    raw = str(tracking_id or "").strip()
    if raw.lower().startswith("m-"):
        raw = raw[2:]
    cleaned = re.sub(r"\W+", "", raw)
    return cleaned or "0"


def _sanitize_yymmdd(yymmdd: Any) -> str:
    """规整日期为 6 位数字（非法 → 当天日期，server 权威）。"""
    raw = re.sub(r"\D+", "", str(yymmdd or ""))
    if len(raw) == 6:
        return raw
    return date.today().strftime("%y%m%d")


def _sanitize_segment(value: Any) -> str:
    """规整项目名段为 git ref 合法（去空白/非法符号，保留中文 UTF-8）。"""
    raw = str(value or "").strip()
    cleaned = _ILLEGAL_SEG_RE.sub("-", raw)
    cleaned = cleaned.strip("-.")
    return cleaned or "project"


def build_branch_name(
    *,
    change_type: str,
    yymmdd: str,
    tracking_id: str,
    project_name: str,
    version: str = "",
) -> str:
    """server 权威拼装固定格式分支名（纯函数）。

    各段经规整：``change_type`` 归一 conventional 类型、``yymmdd`` 6 位数字、``tracking_id``
    去前导 ``m-`` 仅 ``\\w``、``project_name`` 去非法路径字符/空白（保留中文）、``version`` 有则
    追加 ``-vX``。
    """
    ctype = _normalize_type(change_type)
    ymd = _sanitize_yymmdd(yymmdd)
    tid = _sanitize_tracking_id(tracking_id)
    pname = _sanitize_segment(project_name)
    name = f"{ctype}/{ymd}.m-{tid}.{pname}"
    ver = _normalize_version(version)
    if ver:
        name = f"{name}-{ver}"
    return name


def validate_branch_name(name: str) -> bool:
    """校验分支名是否符合固定格式正则。"""
    return bool(_BRANCH_RE.match(str(name or "")))


def _extract_tracking_id(work_item: Any) -> str:
    """从 work_item（对象/dict）提取飞书项目跟踪 work_item id（server 权威）。"""
    if work_item is None:
        return ""
    for attr in ("work_item_id", "feishu_work_item_id", "id"):
        val = getattr(work_item, attr, None)
        if val is None and isinstance(work_item, dict):
            val = work_item.get(attr)
        if val:
            return str(val)
    if isinstance(work_item, dict):
        return str(work_item.get("work_item_id") or work_item.get("id") or "")
    return ""


def _extract_board_name(work_item: Any, project: Any) -> str:
    """提取项目跟踪看板名（缺则 project.name 兜底，A6）。"""
    for src in (work_item, project):
        if src is None:
            continue
        name = getattr(src, "name", None)
        if name is None and isinstance(src, dict):
            name = src.get("name")
        if name:
            return str(name)
    return ""


async def generate_branch_name(
    *,
    repo: Any = None,
    project: Any = None,
    work_item: Any = None,
    requirement_text: str = "",
    change_type_override: str = "",
    initiated_by_user_id: str = "system",
) -> dict[str, Any]:
    """生成单仓分支名：LLM 仅定 ``change_type`` + 版本号，server 权威拼装 + 正则兜底。

    ``tracking_id``（飞书 work_item id）/ ``project_name``（看板名）/ ``yymmdd``（当天）一律 server
    权威字段拼装，**不信 LLM 自由拼**（T-89-04-TAMPER）。``change_type_override`` 非空时直接采用
    （用户卡片改 type，无需再问 LLM）。LLM 调用/解析任一失败 → 兜底 ``type=feat`` + server 抽版本号，
    绝不反噬。

    Returns: ``{branch_name, change_type, version, tracking_id, project_name, yymmdd, fallback}``。
    """
    from common.logging import redact_secrets_in_text

    started = perf_counter()
    log = logger.bind(
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(initiated_by_user_id or "system"),
    )

    # server 权威字段（LLM 永不染指）。
    tracking_id = _extract_tracking_id(work_item)
    project_name = _extract_board_name(work_item, project)
    yymmdd = date.today().strftime("%y%m%d")
    version_source = f"{project_name} {requirement_text}"

    change_type = _normalize_type(change_type_override) if change_type_override else ""
    version = ""
    fallback = False

    if change_type_override:
        # 用户已指定 type（卡片改 type），server 抽版本号即可，不调 LLM。
        version = _normalize_version(version_source)
    else:
        try:
            decided = await _ainvoke_naming_llm(
                requirement_text=redact_secrets_in_text(str(requirement_text or "")),
                project_name=project_name,
                initiated_by_user_id=str(initiated_by_user_id or "system"),
            )
            change_type = _normalize_type(decided.get("change_type"))
            if decided.get("include_version"):
                version = _normalize_version(decided.get("version") or version_source)
        except Exception as exc:  # noqa: BLE001 — LLM best-effort，失败兜底 type=feat
            fallback = True
            change_type = _DEFAULT_TYPE
            version = _normalize_version(version_source)
            log.warning(
                "branch_naming_llm_failed",
                error_type=type(exc).__name__,
                reason=redact_secrets_in_text(str(exc)),
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )

    if not change_type:
        change_type = _DEFAULT_TYPE

    branch_name = build_branch_name(
        change_type=change_type,
        yymmdd=yymmdd,
        tracking_id=tracking_id,
        project_name=project_name,
        version=version,
    )
    # 正则兜底：拼装结果异常（不应发生）→ 退回默认 feat 标准名。
    if not validate_branch_name(branch_name):
        fallback = True
        branch_name = build_branch_name(
            change_type=_DEFAULT_TYPE,
            yymmdd=yymmdd,
            tracking_id=tracking_id,
            project_name=project_name,
            version="",
        )

    log.info(
        "branch_naming_generated",
        repo_id=str(getattr(repo, "id", "") or ""),
        change_type=change_type,
        has_version=bool(version),
        fallback=fallback,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
    return {
        "branch_name": branch_name,
        "change_type": change_type,
        "version": version,
        "tracking_id": tracking_id,
        "project_name": project_name,
        "yymmdd": yymmdd,
        "fallback": fallback,
    }


async def _ainvoke_naming_llm(
    *, requirement_text: str, project_name: str, initiated_by_user_id: str
) -> dict[str, Any]:
    """调 branch_naming LLM 判定 ``change_type`` + 版本号（镜像 PlanDeepenService 取模/留痕范式）。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from agents.call_source import CallSource, use_call_source
    from agents.llm_factory import build_chat_model
    from interactions.ledger import arecord_llm_usage
    from services.provider_config import ProviderConfigService

    resolved = await ProviderConfigService.aresolve()
    model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
    if not model_name:
        raise RuntimeError("no_default_model")
    model = build_chat_model(resolved, model_name, streaming=False)
    system = SystemMessage(content=_NAMING_SYSTEM_PROMPT)
    human = HumanMessage(content=_build_naming_prompt(requirement_text, project_name))

    llm_started = perf_counter()
    with use_call_source(CallSource.BRANCH_NAMING):
        response = await model.ainvoke([system, human])
    duration_ms = int((perf_counter() - llm_started) * 1000)

    try:
        await arecord_llm_usage(
            call_source=CallSource.BRANCH_NAMING.value,
            provider=str(getattr(resolved, "provider_type", "") or "unknown"),
            model=str(model_name),
            duration_ms=duration_ms,
            user_id=str(initiated_by_user_id or "system"),
            source=_COMPONENT,
        )
    except Exception:  # noqa: BLE001 — 留痕 best-effort
        logger.debug(
            "branch_naming_usage_record_failed",
            component=_COMPONENT,
            category="sampling",
        )

    parsed = _parse_naming_json(_content_to_text(response.content))
    return _normalize_naming(parsed)


def _build_naming_prompt(requirement_text: str, project_name: str) -> str:
    types = "/".join(CONVENTIONAL_TYPES)
    return (
        f"项目跟踪看板名：{project_name}\n"
        f"需求（已脱敏）：\n{requirement_text}\n\n"
        "请判断本次变更最贴切的 conventional commits 类型，以及需求里是否含版本号，"
        "只输出如下 JSON：\n"
        "{\n"
        f'  "change_type": "从 {types} 中取一个",\n'
        '  "include_version": true 或 false,\n'
        '  "version": "若有版本号填如 v1.0，否则留空"\n'
        "}\n"
    )


def _normalize_naming(parsed: dict | None) -> dict[str, Any]:
    raw = parsed if isinstance(parsed, dict) else {}
    return {
        "change_type": _normalize_type(raw.get("change_type")),
        "include_version": bool(raw.get("include_version")),
        "version": str(raw.get("version") or "").strip(),
    }


def _content_to_text(content: Any) -> str:
    """把 LLM response.content（str / list[block]）归一化为文本。"""
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


def _parse_naming_json(text: str) -> dict | None:
    """健壮解析命名 JSON：取首 ``{`` 到末 ``}``，不 eval（半可信产物防御）。"""
    import json

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
