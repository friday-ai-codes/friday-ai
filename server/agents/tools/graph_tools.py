"""``impact_analysis`` / ``trace_call_path`` / ``detect_changes`` 对话工具薄壳。

与 MCP 壳共用 ``run_impact`` / ``run_trace`` / ``run_detect_changes`` 编排入口
（D-21 / D-13）：壳内零算法，``output["data"]`` 原样透出编排信封。

**注册路径**：通过 ``agents/tools/__init__.py`` 顶层 import 触发 ``@tool`` 注册；
还必须同时挂进 ``chat_runner._INDEXED_TOOL_NAMES``——注册 ≠ 暴露
（``chat_runner.py:92-100`` 的注释是这笔债的现场记录）。
"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from pydantic import ValidationError

from agents.tools.base import ToolCategory, ToolResult, tool
from agents.tools.delivery_knowledge_tools import _resolve_conversation_user
from agents.tools.project_read_tools import _CONV_ID_PARAM
from agents.tools.schemas.graph_tools import (
    DetectChangesToolInput,
    GetProcessToolInput,
    ImpactAnalysisToolInput,
    ListProcessesToolInput,
    RenamePreviewToolInput,
    TraceCallPathToolInput,
)
from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

_COMPONENT = "agents.tools"

_REPO_ERR_MESSAGES = {
    "repository_not_found": "仓库不存在",
    "repository_not_indexed": "仓库尚未建立索引",
}


_DESC_IMPACT = (
    "Analyze the impact surface of changing a code symbol: who / what would break "
    "if this function, class, or method is modified.\n"
    "\n"
    "USE WHEN you need structural blast-radius answers:\n"
    "  - 'if I change LoginHandler, what else breaks?' → impact_analysis(...)\n"
    "  - 'who depends on UserService.create?' → impact_analysis(symbol='create', ...)\n"
    "\n"
    "IMPORTANT agent notes:\n"
    "  - When a symbol name is ambiguous the tool returns a **candidate list** "
    "(error_code=ambiguous_symbol) instead of guessing — ~19.3% of names in "
    "production are non-unique. Retry with symbol_id (or file_path / symbol_type).\n"
    "  - Results include `staleness` and `graph` declarations; read those before "
    "trusting conclusions.\n"
    "\n"
    "DO NOT USE FOR finding a handler by URL — use `find_api_handler`.\n"
    "DO NOT USE FOR fuzzy semantic retrieval — use `search_repository_code`.\n"
    "DO NOT USE FOR chunk-level relation walks — use `find_related_code`."
)

_DESC_TRACE = (
    "Trace the call path between two code symbols: how does A reach B in the "
    "in-memory code graph (shortest path + equal-length alternates).\n"
    "\n"
    "USE WHEN you need a concrete path, not a blast radius:\n"
    "  - 'how does CheckoutController call PaymentGateway?' → trace_call_path(...)\n"
    "  - 'is there a call chain from A to B?' → trace_call_path(...)\n"
    "\n"
    "IMPORTANT agent notes:\n"
    "  - Ambiguous source/target names return candidate lists "
    "(error_code=ambiguous_symbol); never silently pick the first — retry with "
    "symbol_id.\n"
    "  - `found=false` with `ok=true` means 'no path exists' (a successful query), "
    "not a tool failure.\n"
    "  - Results include `staleness` and `graph` declarations; read those first.\n"
    "\n"
    "DO NOT USE FOR finding a handler by URL — use `find_api_handler`.\n"
    "DO NOT USE FOR fuzzy semantic retrieval — use `search_repository_code`.\n"
    "DO NOT USE FOR chunk-level relation walks — use `find_related_code`."
)

_DESC_DETECT = (
    "Detect which indexed symbols are affected by a git range, then batch-run "
    "impact analysis on those seeds.\n"
    "\n"
    "USE WHEN the user asks what broke / what is impacted by commits on a branch "
    "or SHA relative to the last indexed snapshot:\n"
    "  - 'what did feature/foo change vs our index?' → "
    "detect_changes(compare='feature/foo', ...)\n"
    "  - 'MR blast radius for this tip SHA' → detect_changes(compare='<sha>', "
    "base_ref='origin/main' for declaration only)\n"
    "\n"
    "IMPORTANT agent notes:\n"
    "  - `compare` is the **diff head** (branch / tag / SHA).\n"
    "  - Diff **base is always the repository's last_indexed_commit_sha** — "
    "not user-chosen. Optional `base_ref` is declarative MR metadata only; "
    "it never changes the left side of the diff.\n"
    "  - There is **no** `branch` overlay param; graph coordinates stay on the "
    "index watermark.\n"
    "  - Results include `staleness`, `graph`, `diff_base_sha`, `diff_head_sha`; "
    "read those before trusting conclusions.\n"
    "  - Orchestration `ok=false` (e.g. empty_diff_range) is a query outcome "
    "inside the envelope, not a tool crash.\n"
    "\n"
    "DO NOT USE FOR a single known symbol blast radius — use `impact_analysis`.\n"
    "DO NOT USE FOR call-path between two symbols — use `trace_call_path`.\n"
    "DO NOT USE FOR fuzzy semantic retrieval — use `search_repository_code`."
)

_PARAMS_IMPACT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "branch": {
            "type": "string",
            "description": "查询分支；缺省走 base 图",
        },
        "symbol_id": {
            "type": "string",
            "description": "符号 UUID；与 symbol 必须且只能提供其一",
        },
        "symbol": {
            "type": "string",
            "description": "符号名；与 symbol_id 必须且只能提供其一",
        },
        "file_path": {
            "type": "string",
            "description": "可选：文件路径，收窄同名符号",
        },
        "symbol_type": {
            "type": "string",
            "description": "可选：符号类型（function / class 等）",
        },
        "max_depth": {
            "type": "integer",
            "description": "遍历深度 1–3，默认 3",
            "default": 3,
        },
        "min_confidence": {
            "type": "number",
            "description": "边置信度下限 0.0–1.0，默认 1.0",
            "default": 1.0,
        },
        "include_low_confidence": {
            "type": "boolean",
            "description": "是否纳入低置信度边",
            "default": False,
        },
        "limit": {
            "type": "integer",
            "description": "响应条数上限 1–200，默认 200",
            "default": 200,
        },
        "max_cross_repo_hops": {
            "type": "integer",
            "description": "跨仓跳数 0–1，默认 1",
            "default": 1,
        },
        "exclude_test_files": {
            "type": "boolean",
            "description": "是否排除测试文件节点",
            "default": False,
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "conversation_id"],
}

_PARAMS_TRACE: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "branch": {
            "type": "string",
            "description": "查询分支；缺省走 base 图",
        },
        "source_symbol_id": {
            "type": "string",
            "description": "起点符号 UUID；与 source 必须且只能提供其一",
        },
        "source": {
            "type": "string",
            "description": "起点符号名；与 source_symbol_id 必须且只能提供其一",
        },
        "source_file_path": {
            "type": "string",
            "description": "可选：起点文件路径",
        },
        "target_symbol_id": {
            "type": "string",
            "description": "终点符号 UUID；与 target 必须且只能提供其一",
        },
        "target": {
            "type": "string",
            "description": "终点符号名；与 target_symbol_id 必须且只能提供其一",
        },
        "target_file_path": {
            "type": "string",
            "description": "可选：终点文件路径",
        },
        "min_confidence": {
            "type": "number",
            "description": "边置信度下限 0.0–1.0，默认 1.0",
            "default": 1.0,
        },
        "include_low_confidence": {
            "type": "boolean",
            "description": "是否纳入低置信度边",
            "default": False,
        },
        "alt_path_cap": {
            "type": "integer",
            "description": "等长备选路径条数 1–50，默认 10",
            "default": 10,
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "conversation_id"],
}

_PARAMS_DETECT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "compare": {
            "type": "string",
            "description": (
                "**REQUIRED.** diff head（分支名 / tag / 完整 SHA）；"
                "diff 左端永远是索引水位 last_indexed_commit_sha"
            ),
        },
        "base_ref": {
            "type": "string",
            "description": (
                "可选：MR 语义声明透出（如 origin/main）；不参与 diff 左端，不改图坐标"
            ),
        },
        "max_depth": {
            "type": "integer",
            "description": "遍历深度 1–3，默认 3",
            "default": 3,
        },
        "min_confidence": {
            "type": "number",
            "description": "边置信度下限 0.0–1.0，默认 1.0",
            "default": 1.0,
        },
        "include_low_confidence": {
            "type": "boolean",
            "description": "是否纳入低置信度边",
            "default": False,
        },
        "limit": {
            "type": "integer",
            "description": "响应条数上限 1–200，默认 200",
            "default": 200,
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "compare", "conversation_id"],
}


async def _record_chat_retrieval(
    kind: str,
    payload: dict[str, Any],
    *,
    conversation_id: str,
    user: Any,
) -> None:
    """Chat 链召回留痕（RetrievalTrace；best-effort 吞异常，绝不反噬对话）。"""
    try:
        from interactions.ledger import arecord_retrieval_trace

        await arecord_retrieval_trace(
            None,
            kind=kind,
            payload=payload,
            user_id=str(user.id) if user else None,
            conversation_id=conversation_id,
            source="chat",
        )
    except Exception:  # noqa: BLE001 — 留痕 best-effort
        pass


async def _resolve_tool_repo(repository_id: str) -> tuple[Any | None, str | None]:
    """取已索引仓对象，供 staleness 与未索引早退。

    🚨 这次 ORM 取仓**不是权限校验**——它只为拿 ``staleness_payload`` 需要的
    ``Repository`` 对象与「未索引」这条早退；真正的授权是 ``run_impact`` /
    ``run_trace`` 内部 ``get_graph`` 每次都跑的 ``ensure_repository_readable(user=…)``
    （⛔ 不在壳里自查可见性，PATTERNS §权限：唯一收口点）。
    """
    from repositories.models import IndexStatus, Repository

    try:
        repo = await Repository.objects.aget(id=repository_id, is_deleted=False)
    except (Repository.DoesNotExist, ValueError, TypeError):
        return None, "repository_not_found"
    if repo.index_status != IndexStatus.INDEXED:
        return None, "repository_not_indexed"
    return repo, None


@tool(
    name="impact_analysis",
    description=_DESC_IMPACT,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_IMPACT,
)
async def impact_analysis(
    repository_id: str | None = None,
    branch: str | None = None,
    symbol_id: str | None = None,
    symbol: str = "",
    file_path: str = "",
    symbol_type: str = "",
    max_depth: int = 3,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    limit: int = 200,
    max_cross_repo_hops: int = 1,
    exclude_test_files: bool = False,
    conversation_id: str = "",
) -> ToolResult:
    """影响面分析对话薄壳。

    ``success=False`` 只留给：会话 owner 解析失败、输入校验失败、翻译后的
    ``GraphError``（对应 MCP 面 401/400/4xx-5xx）。编排层 ``ok=False``
    （``symbol_not_found`` / ``ambiguous_symbol``）仍返回
    ``success=True``，信封里的 ``ok`` 才是查询结论——与 MCP HTTP 200 对齐（D-21）。
    """
    try:
        return await _impact_analysis_impl(
            repository_id=repository_id,
            branch=branch,
            symbol_id=symbol_id,
            symbol=symbol,
            file_path=file_path,
            symbol_type=symbol_type,
            max_depth=max_depth,
            min_confidence=min_confidence,
            include_low_confidence=include_low_confidence,
            limit=limit,
            max_cross_repo_hops=max_cross_repo_hops,
            exclude_test_files=exclude_test_files,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "impact_analysis_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001 — 双层防御：永不冒泡
        logger.warning(
            "impact_analysis_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(
            success=False,
            error=redact_secrets_in_text(str(exc))[:500],
        )


async def _impact_analysis_impl(
    *,
    repository_id: str | None,
    branch: str | None,
    symbol_id: str | None,
    symbol: str,
    file_path: str,
    symbol_type: str,
    max_depth: int,
    min_confidence: float,
    include_low_confidence: bool,
    limit: int,
    max_cross_repo_hops: int,
    exclude_test_files: bool,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    # 🚨 fail-closed 第一步：get_graph(user=None) 走的是系统路径
    # （access._initiated_by 返回 "system"、_check_user_acl 空实现放行），**不会**被拒，
    # 所以这道闸是对话面唯一的权限起点，不是防御性冗余。在此之前不做任何取仓/取图动作。
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝分析（fail-closed）",
        )

    try:
        validated = ImpactAnalysisToolInput(
            repository_id=repository_id or "",
            branch=branch,
            symbol_id=symbol_id,
            symbol=symbol or "",
            file_path=file_path or "",
            symbol_type=symbol_type or "",
            max_depth=int(max_depth),
            min_confidence=float(min_confidence),
            include_low_confidence=bool(include_low_confidence),
            limit=int(limit),
            max_cross_repo_hops=int(max_cross_repo_hops),
            exclude_test_files=bool(exclude_test_files),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        resolve_tool_graph_branch,
        run_impact,
        tool_trace_payload,
    )

    graph_branch = await resolve_tool_graph_branch(validated.repository_id, repo, validated.branch)
    orch_started = perf_counter()
    try:
        result = await run_impact(
            repository_id=validated.repository_id,
            repo=repo,
            graph_branch=graph_branch,
            user=user,
            symbol_id=validated.symbol_id,
            symbol=(validated.symbol or "").strip() or None,
            file_path=(validated.file_path or "").strip() or None,
            symbol_type=(validated.symbol_type or "").strip() or None,
            max_depth=validated.max_depth,
            min_confidence=validated.min_confidence,
            include_low_confidence=validated.include_low_confidence,
            limit=validated.limit,
            max_cross_repo_hops=validated.max_cross_repo_hops,
            exclude_test_files=validated.exclude_test_files,
        )
    except GraphError as exc:
        code, message = graph_error_to_tool_error(exc)
        logger.warning(
            "impact_analysis_tool_failed",
            error_code=code,
            error=redact_secrets_in_text(str(exc))[:500],
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=str(user.id),
        )
        return ToolResult(success=False, error=message)

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="impact_analysis",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    logger.info(
        "impact_analysis_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        error_code=str(result.get("error_code") or ""),
        result_count=int(summary.get("returned") or 0) if summary else 0,
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "branch": validated.branch,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


@tool(
    name="trace_call_path",
    description=_DESC_TRACE,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_TRACE,
)
async def trace_call_path(
    repository_id: str | None = None,
    branch: str | None = None,
    source_symbol_id: str | None = None,
    source: str = "",
    source_file_path: str = "",
    target_symbol_id: str | None = None,
    target: str = "",
    target_file_path: str = "",
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    alt_path_cap: int = 10,
    conversation_id: str = "",
) -> ToolResult:
    """调用路径追踪对话薄壳。

    ``found is False`` 是成功结果（D-20），⛔ 不映射成 ``success=False``。
    ``success=False`` 只留给会话 owner / 校验 / ``GraphError`` 三类故障。
    """
    try:
        return await _trace_call_path_impl(
            repository_id=repository_id,
            branch=branch,
            source_symbol_id=source_symbol_id,
            source=source,
            source_file_path=source_file_path,
            target_symbol_id=target_symbol_id,
            target=target,
            target_file_path=target_file_path,
            min_confidence=min_confidence,
            include_low_confidence=include_low_confidence,
            alt_path_cap=alt_path_cap,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "trace_call_path_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001 — 双层防御：永不冒泡
        logger.warning(
            "trace_call_path_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(
            success=False,
            error=redact_secrets_in_text(str(exc))[:500],
        )


async def _trace_call_path_impl(
    *,
    repository_id: str | None,
    branch: str | None,
    source_symbol_id: str | None,
    source: str,
    source_file_path: str,
    target_symbol_id: str | None,
    target: str,
    target_file_path: str,
    min_confidence: float,
    include_low_confidence: bool,
    alt_path_cap: int,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    # 🚨 fail-closed 第一步：get_graph(user=None) 走的是系统路径
    # （access._initiated_by 返回 "system"、_check_user_acl 空实现放行），**不会**被拒，
    # 所以这道闸是对话面唯一的权限起点，不是防御性冗余。在此之前不做任何取仓/取图动作。
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝分析（fail-closed）",
        )

    try:
        validated = TraceCallPathToolInput(
            repository_id=repository_id or "",
            branch=branch,
            source_symbol_id=source_symbol_id,
            source=source or "",
            source_file_path=source_file_path or "",
            target_symbol_id=target_symbol_id,
            target=target or "",
            target_file_path=target_file_path or "",
            min_confidence=float(min_confidence),
            include_low_confidence=bool(include_low_confidence),
            alt_path_cap=int(alt_path_cap),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        resolve_tool_graph_branch,
        run_trace,
        tool_trace_payload,
    )

    graph_branch = await resolve_tool_graph_branch(validated.repository_id, repo, validated.branch)
    orch_started = perf_counter()
    try:
        result = await run_trace(
            repository_id=validated.repository_id,
            repo=repo,
            graph_branch=graph_branch,
            user=user,
            source_symbol_id=validated.source_symbol_id,
            source=(validated.source or "").strip() or None,
            source_file_path=(validated.source_file_path or "").strip() or None,
            target_symbol_id=validated.target_symbol_id,
            target=(validated.target or "").strip() or None,
            target_file_path=(validated.target_file_path or "").strip() or None,
            min_confidence=validated.min_confidence,
            include_low_confidence=validated.include_low_confidence,
            alt_path_cap=validated.alt_path_cap,
        )
    except GraphError as exc:
        code, message = graph_error_to_tool_error(exc)
        logger.warning(
            "trace_call_path_tool_failed",
            error_code=code,
            error=redact_secrets_in_text(str(exc))[:500],
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=str(user.id),
        )
        return ToolResult(success=False, error=message)

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="trace_call_path",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    hops_raw = result.get("hops")
    hops: list[Any] = hops_raw if isinstance(hops_raw, list) else []
    logger.info(
        "trace_call_path_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        error_code=str(result.get("error_code") or ""),
        result_count=len(hops),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "branch": validated.branch,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


@tool(
    name="detect_changes",
    description=_DESC_DETECT,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_DETECT,
)
async def detect_changes(
    repository_id: str | None = None,
    compare: str = "",
    base_ref: str | None = None,
    max_depth: int = 3,
    min_confidence: float = 1.0,
    include_low_confidence: bool = False,
    limit: int = 200,
    conversation_id: str = "",
) -> ToolResult:
    """变更检测对话薄壳（Phase 123 DIFF-01/02 / D-13）。

    ``success=False`` 只留给：会话 owner 解析失败、输入校验失败、翻译后的
    ``GraphError``。编排层 ``ok=False`` 仍返回 ``success=True``，信封里的
    ``ok`` 才是查询结论——与 MCP HTTP 200 对齐（D-13）。
    """
    try:
        return await _detect_changes_impl(
            repository_id=repository_id,
            compare=compare,
            base_ref=base_ref,
            max_depth=max_depth,
            min_confidence=min_confidence,
            include_low_confidence=include_low_confidence,
            limit=limit,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "detect_changes_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001 — 双层防御：永不冒泡
        logger.warning(
            "detect_changes_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(
            success=False,
            error=redact_secrets_in_text(str(exc))[:500],
        )


async def _detect_changes_impl(
    *,
    repository_id: str | None,
    compare: str,
    base_ref: str | None,
    max_depth: int,
    min_confidence: float,
    include_low_confidence: bool,
    limit: int,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    # 🚨 fail-closed 第一步：与 impact 同构——会话 owner 未解析则硬拒。
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝分析（fail-closed）",
        )

    try:
        validated = DetectChangesToolInput(
            repository_id=repository_id or "",
            compare=compare or "",
            base_ref=base_ref,
            max_depth=int(max_depth),
            min_confidence=float(min_confidence),
            include_low_confidence=bool(include_low_confidence),
            limit=int(limit),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        run_detect_changes,
        tool_trace_payload,
    )

    # ⛔ 不调 resolve_tool_graph_branch——交叠坐标由编排锁定索引水位（D-01/D-02）
    orch_started = perf_counter()
    try:
        result = await run_detect_changes(
            repository_id=validated.repository_id,
            repo=repo,
            user=user,
            compare=validated.compare,
            base_ref=validated.base_ref,
            max_depth=validated.max_depth,
            min_confidence=validated.min_confidence,
            include_low_confidence=validated.include_low_confidence,
            limit=validated.limit,
        )
    except GraphError as exc:
        code, message = graph_error_to_tool_error(exc)
        logger.warning(
            "detect_changes_tool_failed",
            error_code=code,
            error=redact_secrets_in_text(str(exc))[:500],
            error_type=type(exc).__name__,
            component=_COMPONENT,
            category="caller",
            initiated_by_user_id=str(user.id),
        )
        return ToolResult(success=False, error=message)

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="detect_changes",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    logger.info(
        "detect_changes_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        error_code=str(result.get("error_code") or ""),
        result_count=int(summary.get("affected_symbol_count") or 0) if summary else 0,
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "compare": validated.compare,
                "base_ref": validated.base_ref,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


_DESC_LIST_PROCESSES = (
    "List execution-flow ProcessTrace summaries for a repository "
    "(entry → main path narrative).\n"
    "\n"
    "USE WHEN you need which business flows exist or which cross-community "
    "flows to inspect before impact/rename work:\n"
    "  - 'what processes touch this repo?' → list_processes(...)\n"
    "  - 'show cross-community flows' → list_processes(community_class='cross_community')\n"
    "\n"
    "IMPORTANT: default sort prefers cross_community. Results include "
    "staleness / degradation / as_of; read those first.\n"
    "DO NOT USE FOR blast radius of one symbol — use impact_analysis.\n"
    "DO NOT USE FOR rename edits — use rename_preview (when available)."
)

_DESC_GET_PROCESS = (
    "Fetch one ProcessTrace by process_key, including ordered steps.\n"
    "\n"
    "USE WHEN list_processes already gave a process_key and you need step detail.\n"
    "IMPORTANT: ok=false with process_not_found is a query outcome, not a crash.\n"
    "DO NOT USE FOR inventing flows — empty/not found means no persisted Process."
)

_PARAMS_LIST_PROCESSES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "branch": {
            "type": "string",
            "description": "查询分支；缺省走 base",
        },
        "community_class": {
            "type": "string",
            "description": "可选：intra_community | cross_community",
        },
        "symbol_id": {
            "type": "string",
            "description": "可选：只返回含该 symbol_id 的执行流",
        },
        "limit": {
            "type": "integer",
            "description": "条数上限 1–200，默认 50",
            "default": 50,
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "conversation_id"],
}

_PARAMS_GET_PROCESS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "branch": {
            "type": "string",
            "description": "查询分支；缺省走 base",
        },
        "process_key": {
            "type": "string",
            "description": "**REQUIRED.** 执行流稳定键",
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "process_key", "conversation_id"],
}

_DESC_RENAME_PREVIEW = (
    "Read-only rename preview: dual-source edit list (graph refs + text_search "
    "via grep_mirror). Never rewrites the repo; applied is always false.\n"
    "\n"
    "USE WHEN planning a symbol rename before you edit files yourself:\n"
    "  - 'what would rename Foo to Bar touch?' → rename_preview(...)\n"
    "\n"
    "IMPORTANT: preview first, then edit locally. Dynamic refs "
    "(templates/getattr/reflection) may be missed — read coverage_limitations.\n"
    "DO NOT USE FOR applying renames — there is no apply API; edit yourself.\n"
    "DO NOT USE FOR blast radius alone — use impact_analysis."
)

_PARAMS_RENAME_PREVIEW: dict[str, Any] = {
    "type": "object",
    "properties": {
        "repository_id": {
            "type": "string",
            "description": "**REQUIRED.** 目标仓库 UUID",
        },
        "branch": {
            "type": "string",
            "description": "查询分支；缺省走 base",
        },
        "symbol_id": {
            "type": "string",
            "description": "符号 UUID；与 symbol 必须且只能提供其一",
        },
        "symbol": {
            "type": "string",
            "description": "符号名；与 symbol_id 必须且只能提供其一",
        },
        "file_path": {
            "type": "string",
            "description": "可选：文件路径，收窄同名符号",
        },
        "symbol_type": {
            "type": "string",
            "description": "可选：符号类型（function / class 等）",
        },
        "new_name": {
            "type": "string",
            "description": "**REQUIRED.** 新名称",
        },
        "context_lines": {
            "type": "integer",
            "description": "上下文行数 0–5，默认 2",
            "default": 2,
        },
        **_CONV_ID_PARAM,
    },
    "required": ["repository_id", "new_name", "conversation_id"],
}


@tool(
    name="list_processes",
    description=_DESC_LIST_PROCESSES,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_LIST_PROCESSES,
)
async def list_processes(
    repository_id: str | None = None,
    branch: str | None = None,
    community_class: str | None = None,
    symbol_id: str | None = None,
    limit: int = 50,
    conversation_id: str = "",
) -> ToolResult:
    """列出执行流对话薄壳——只调 ``run_list_processes``。"""
    try:
        return await _list_processes_impl(
            repository_id=repository_id,
            branch=branch,
            community_class=community_class,
            symbol_id=symbol_id,
            limit=limit,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "list_processes_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "list_processes_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])


async def _list_processes_impl(
    *,
    repository_id: str | None,
    branch: str | None,
    community_class: str | None,
    symbol_id: str | None,
    limit: int,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝查询（fail-closed）",
        )
    try:
        validated = ListProcessesToolInput(
            repository_id=repository_id or "",
            branch=branch,
            community_class=community_class,
            symbol_id=symbol_id,
            limit=int(limit),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        resolve_tool_graph_branch,
        run_list_processes,
        tool_trace_payload,
    )

    graph_branch = await resolve_tool_graph_branch(
        validated.repository_id, repo, validated.branch
    )
    orch_started = perf_counter()
    try:
        result = await run_list_processes(
            repository_id=validated.repository_id,
            repo=repo,
            graph_branch=graph_branch,
            user=user,
            community_class=validated.community_class,
            symbol_id=validated.symbol_id,
            limit=validated.limit,
        )
    except GraphError as exc:
        code, message = graph_error_to_tool_error(exc)
        return ToolResult(success=False, error=message)

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="list_processes",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "list_processes_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "branch": validated.branch,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


@tool(
    name="get_process",
    description=_DESC_GET_PROCESS,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_GET_PROCESS,
)
async def get_process(
    repository_id: str | None = None,
    branch: str | None = None,
    process_key: str = "",
    conversation_id: str = "",
) -> ToolResult:
    """获取单条执行流对话薄壳——只调 ``run_get_process``。"""
    try:
        return await _get_process_impl(
            repository_id=repository_id,
            branch=branch,
            process_key=process_key,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "get_process_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "get_process_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])


async def _get_process_impl(
    *,
    repository_id: str | None,
    branch: str | None,
    process_key: str,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝查询（fail-closed）",
        )
    try:
        validated = GetProcessToolInput(
            repository_id=repository_id or "",
            branch=branch,
            process_key=(process_key or "").strip(),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        resolve_tool_graph_branch,
        run_get_process,
        tool_trace_payload,
    )

    graph_branch = await resolve_tool_graph_branch(
        validated.repository_id, repo, validated.branch
    )
    orch_started = perf_counter()
    try:
        result = await run_get_process(
            repository_id=validated.repository_id,
            repo=repo,
            graph_branch=graph_branch,
            user=user,
            process_key=validated.process_key,
        )
    except GraphError as exc:
        _code, message = graph_error_to_tool_error(exc)
        return ToolResult(success=False, error=message)

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="get_process",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    logger.info(
        "get_process_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "branch": validated.branch,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


@tool(
    name="rename_preview",
    description=_DESC_RENAME_PREVIEW,
    category=ToolCategory.PROJECT.value,
    parameters=_PARAMS_RENAME_PREVIEW,
)
async def rename_preview(
    repository_id: str | None = None,
    branch: str | None = None,
    symbol_id: str | None = None,
    symbol: str = "",
    file_path: str = "",
    symbol_type: str = "",
    new_name: str = "",
    context_lines: int = 2,
    conversation_id: str = "",
) -> ToolResult:
    """只读改名预览对话薄壳——只调 ``run_rename_preview``；强制 chat RetrievalTrace。"""
    try:
        return await _rename_preview_impl(
            repository_id=repository_id,
            branch=branch,
            symbol_id=symbol_id,
            symbol=symbol,
            file_path=file_path,
            symbol_type=symbol_type,
            new_name=new_name,
            context_lines=context_lines,
            conversation_id=conversation_id,
        )
    except ValidationError as exc:
        logger.warning(
            "rename_preview_tool_failed",
            error_type="ValidationError",
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "rename_preview_tool_failed",
            error_type=type(exc).__name__,
            error=redact_secrets_in_text(str(exc))[:500],
            component=_COMPONENT,
            category="caller",
        )
        return ToolResult(
            success=False,
            error=redact_secrets_in_text(str(exc))[:500],
        )


async def _rename_preview_impl(
    *,
    repository_id: str | None,
    branch: str | None,
    symbol_id: str | None,
    symbol: str,
    file_path: str,
    symbol_type: str,
    new_name: str,
    context_lines: int,
    conversation_id: str,
) -> ToolResult:
    started = perf_counter()
    user = await _resolve_conversation_user(conversation_id)
    if user is None:
        return ToolResult(
            success=False,
            error="无法解析会话 owner，拒绝预览（fail-closed）",
        )
    try:
        validated = RenamePreviewToolInput(
            repository_id=repository_id or "",
            branch=branch,
            symbol_id=symbol_id,
            symbol=symbol or "",
            file_path=file_path or "",
            symbol_type=symbol_type or "",
            new_name=new_name or "",
            context_lines=int(context_lines),
        )
    except ValidationError as exc:
        return ToolResult(success=False, error=redact_secrets_in_text(str(exc))[:500])

    repo, err_code = await _resolve_tool_repo(validated.repository_id)
    if repo is None:
        return ToolResult(
            success=False,
            error=_REPO_ERR_MESSAGES.get(err_code or "", "仓库不可用"),
        )

    from interactions.models import RetrievalTrace
    from services.code_graph import GraphError
    from services.code_graph.rename_preview import COVERAGE_LIMITATIONS
    from services.code_graph_tools import (
        graph_error_to_tool_error,
        resolve_tool_graph_branch,
        run_rename_preview,
        tool_trace_payload,
    )

    graph_branch = await resolve_tool_graph_branch(
        validated.repository_id, repo, validated.branch
    )
    orch_started = perf_counter()
    try:
        result = await run_rename_preview(
            repository_id=validated.repository_id,
            repo=repo,
            graph_branch=graph_branch,
            user=user,
            symbol_id=validated.symbol_id,
            symbol=validated.symbol or None,
            file_path=validated.file_path or None,
            symbol_type=validated.symbol_type or None,
            new_name=validated.new_name,
            context_lines=validated.context_lines,
        )
    except GraphError as exc:
        # WR-05：与编排软信封同形，applied=false；勿把图故障当成 ToolResult 硬失败
        code, message = graph_error_to_tool_error(exc)
        result = {
            "ok": False,
            "error_code": code,
            "error": message,
            "tool": "rename_preview",
            "applied": False,
            "coverage_limitations": COVERAGE_LIMITATIONS,
            "query": {
                "symbol_id": validated.symbol_id,
                "symbol": validated.symbol or None,
                "file_path": validated.file_path or None,
                "symbol_type": validated.symbol_type or None,
                "new_name": validated.new_name,
                "context_lines": validated.context_lines,
            },
        }

    orchestration_ms = int((perf_counter() - orch_started) * 1000)
    duration_ms = int((perf_counter() - started) * 1000)
    await _record_chat_retrieval(
        RetrievalTrace.Kind.EDGE,
        tool_trace_payload(
            result,
            tool="rename_preview",
            duration_ms=duration_ms,
            orchestration_ms=orchestration_ms,
        ),
        conversation_id=conversation_id,
        user=user,
    )
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    logger.info(
        "rename_preview_tool_done",
        conversation_id=conversation_id,
        repository_id=validated.repository_id,
        ok=bool(result.get("ok")),
        applied=bool(result.get("applied")),
        result_count=int(summary.get("total_edits") or 0) if summary else 0,
        duration_ms=duration_ms,
        component=_COMPONENT,
        category="caller",
        initiated_by_user_id=str(user.id),
    )
    return ToolResult(
        success=True,
        output={
            "data": result,
            "metadata": {
                "repository_id": validated.repository_id,
                "branch": validated.branch,
                "conversation_id": conversation_id,
                "duration_ms": duration_ms,
            },
        },
    )


__all__ = [
    "impact_analysis",
    "trace_call_path",
    "detect_changes",
    "list_processes",
    "get_process",
    "rename_preview",
]
