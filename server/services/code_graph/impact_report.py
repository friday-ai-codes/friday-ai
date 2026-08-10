"""MR 描述影响面报告：消费 ``run_detect_changes`` 的共享 formatter（DIFF-04 / D-05）。

契约
====
- ``build_impact_report_section`` **永不 raise 阻断建 MR**（D-09）：超时 / ACL /
  ``ok=False`` / 渲染异常一律折成 stub 或空串。
- 四段结构固定：``## 影响面`` → Changes / Affected / Risk / Recommendations（D-07）。
- 体积软上限 + ``truncated`` 标注；⛔ 不嵌入源码正文（D-08 / T-124-03）。
- 观测 best-effort，失败吞掉（D-15）。
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog
from django.conf import settings

from common.logging import redact_secrets_in_text
from services.code_graph.model import GraphAccessDenied
from services.code_graph_tools import run_detect_changes

logger = structlog.get_logger(__name__)

IMPACT_SECTION_MARKER: Final[str] = "## 影响面"

_TOP_FILES: Final[int] = 15
_TOP_SYMBOLS_PER_FILE: Final[int] = 8
_TOP_IMPACT_SEEDS: Final[int] = 10
_TOP_AFFECTED_ITEMS_PER_GROUP: Final[int] = 8
_TOP_AFFECTED_PROCESSES: Final[int] = 10

_RISK_RANK: Final[dict[str, int]] = {
    "low": 1,
    "medium": 2,
    "high": 3,
    "critical": 4,
}

# T-124-02：日志/ stub 旁路文本禁止绝对路径与堆栈帧。
_ABS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:/Users|/home|/var|/tmp|/opt|/usr|/[A-Za-z]+)(?:/[^\s:'\"]+)+)"
)

__all__ = [
    "IMPACT_SECTION_MARKER",
    "append_impact_report",
    "build_impact_report_section",
]


def append_impact_report(description: str, section: str) -> str:
    """幂等追加影响面段：已含 ``## 影响面`` 则不重复（D-06）。"""
    if not section:
        return description or ""
    if IMPACT_SECTION_MARKER in (description or ""):
        return description
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section


def _initiated_by_user_id(user: Any) -> str:
    if user is not None and getattr(user, "id", None) is not None:
        return str(user.id)
    return "system"


def _map_error_code(raw: str | None) -> str:
    code = (raw or "").strip() or "unavailable"
    if code == "repository_not_indexed":
        return "not_indexed"
    # 稳定短码透传；过长 / 含路径的退回 unavailable
    if len(code) > 64 or "/" in code or "\\" in code or " " in code:
        return "unavailable"
    return code


def _sanitize_error_text(text: str) -> str:
    """凭证脱敏 + 去掉 Traceback / 绝对路径（T-124-02）。"""
    cleaned = redact_secrets_in_text(text or "")
    if "Traceback" in cleaned:
        cleaned = cleaned.split("Traceback", 1)[0].rstrip()
    cleaned = _ABS_PATH_RE.sub("[path]", cleaned)
    return cleaned[:500]


def _stub_section(error_code: str) -> str:
    """D-11 固定 stub 模板；自身失败由调用方折空串。"""
    safe = _map_error_code(error_code)
    return (
        f"{IMPACT_SECTION_MARKER}\n\n"
        f"_影响面报告未能生成（`{safe}`）。MR 已照常创建，请人工复核变更影响。_\n"
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _aggregate_risk(envelope: Mapping[str, Any]) -> tuple[str, list[str]]:
    """返回展示用大写 risk + 依据短语。"""
    reasons: list[str] = []
    best = "low"
    for item in _as_list(envelope.get("impacts")):
        impact = _as_mapping(_as_mapping(item).get("impact"))
        level = str(impact.get("risk_level") or "").strip().lower()
        if level in _RISK_RANK and _RISK_RANK[level] > _RISK_RANK[best]:
            best = level

    summary = _as_mapping(envelope.get("summary"))
    if summary.get("file_level_only") or summary.get("truncated") or summary.get("not_expanded"):
        if _RISK_RANK[best] < _RISK_RANK["medium"]:
            best = "medium"
        reasons.append("变更面未完全展开（file_level_only/truncated），风险至少 MEDIUM")

    staleness = _as_mapping(envelope.get("staleness"))
    behind = staleness.get("behind_commits")
    if isinstance(behind, int) and behind > 0:
        reasons.append(f"索引落后 {behind} commits（as_of={staleness.get('as_of') or 'n/a'}）")
    decl = str(staleness.get("declaration") or "").strip()
    if decl:
        reasons.append(decl)

    graph = _as_mapping(envelope.get("graph"))
    if graph.get("degraded"):
        reasons.append("图服务降级（degraded），结论置信度下调")

    if not reasons:
        reasons.append(f"聚合 impacts[*].impact.risk_level → {best.upper()}")
    return best.upper(), reasons


def _render_changes(envelope: Mapping[str, Any]) -> list[str]:
    lines = ["### Changes", ""]
    files = _as_list(envelope.get("files"))[:_TOP_FILES]
    summary = _as_mapping(envelope.get("summary"))
    file_level_only = bool(summary.get("file_level_only"))
    if not files:
        lines.append("- （无变更文件）")
        lines.append("")
        return lines

    total_files = len(_as_list(envelope.get("files")))
    for group in files:
        g = _as_mapping(group)
        path = str(g.get("path") or "").strip() or "(unknown)"
        fs = _as_mapping(g.get("file_summary"))
        ctype = str(fs.get("changeType") or g.get("change_type") or "modified")
        lines.append(f"- `{path}` ({ctype})")
        if file_level_only:
            continue
        symbols = _as_list(g.get("symbols"))[:_TOP_SYMBOLS_PER_FILE]
        for sym in symbols:
            s = _as_mapping(sym)
            name = str(s.get("name") or s.get("uid") or "?")
            sctype = str(s.get("changeType") or ctype)
            loc = str(s.get("file_line") or "").strip()
            lines_changed = s.get("lines_changed")
            detail = f"{name} · {sctype}"
            if loc:
                detail += f" · {loc}"
            if isinstance(lines_changed, int):
                detail += f" · Δ{lines_changed}"
            lines.append(f"  - {detail}")
        omitted_syms = max(0, len(_as_list(g.get("symbols"))) - _TOP_SYMBOLS_PER_FILE)
        if omitted_syms:
            lines.append(f"  - … 另有 {omitted_syms} 个符号未列出")

    omitted_files = max(0, total_files - len(files))
    if omitted_files:
        lines.append(f"- … 另有 {omitted_files} 个文件未列出（top-{_TOP_FILES}）")
    lines.append("")
    return lines


def _render_affected(envelope: Mapping[str, Any]) -> list[str]:
    lines = ["### Affected", ""]
    impacts = _as_list(envelope.get("impacts"))[:_TOP_IMPACT_SEEDS]
    summary = _as_mapping(envelope.get("summary"))
    if summary.get("not_expanded"):
        lines.append("- 影响种子超过阈值，未展开批量 impact（not_expanded）")
    if summary.get("truncated"):
        lines.append("- 变更面已截断（summary.truncated=true）")

    if not impacts:
        lines.append("- （无 impact 种子 / 未展开）")
        lines.append("")
        return lines

    for item in impacts:
        row = _as_mapping(item)
        uid = str(row.get("uid") or "?")
        if "impact_error" in row:
            err = _as_mapping(row.get("impact_error"))
            code = str(err.get("error_code") or "impact_error")
            lines.append(f"- seed `{uid}`：impact 失败（`{code}`）")
            continue
        impact = _as_mapping(row.get("impact"))
        isum = _as_mapping(impact.get("summary"))
        total_found = isum.get("total_found")
        returned = isum.get("returned")
        head = f"- seed `{uid}`"
        if isinstance(total_found, int):
            head += f"：找到 {total_found}"
            if isinstance(returned, int):
                head += f"，返回 {returned}"
        lines.append(head)
        for group in _as_list(impact.get("groups")):
            g = _as_mapping(group)
            depth = g.get("depth")
            items = _as_list(g.get("items"))
            shown = items[:_TOP_AFFECTED_ITEMS_PER_GROUP]
            names = []
            for it in shown:
                m = _as_mapping(it)
                n = str(m.get("name") or "?")
                fp = str(m.get("file_path") or "").strip()
                names.append(f"{n}@{fp}" if fp else n)
            depth_label = f"d{depth}" if depth is not None else "d?"
            lines.append(
                f"  - {depth_label}: {', '.join(names) if names else '（空）'}"
            )
            omitted = max(0, len(items) - len(shown))
            if omitted:
                lines.append(f"  - … 该深度另有 {omitted} 项未列出")
        if isum.get("truncated_by_depth") or isum.get("truncated_by_nodes"):
            lines.append("  - （impact 内部截断：truncated_by_depth/nodes）")

    omitted = max(0, len(_as_list(envelope.get("impacts"))) - len(impacts))
    if omitted:
        lines.append(f"- … 另有 {omitted} 个 impact 种子未列出（top-{_TOP_IMPACT_SEEDS}）")

    lines.extend(_render_affected_processes(envelope))
    lines.append("")
    return lines


def _render_affected_processes(envelope: Mapping[str, Any]) -> list[str]:
    """Affected 小节内的「受影响执行流」清单（D-08）；空则短声明不编造。"""
    processes = _as_list(envelope.get("affected_processes"))
    lines = ["", "#### 受影响执行流", ""]
    if not processes:
        lines.append("- 暂无匹配执行流 / 未构建 Process")
        return lines

    shown = processes[:_TOP_AFFECTED_PROCESSES]
    for row in shown:
        m = _as_mapping(row)
        name = str(m.get("name") or m.get("process_key") or "?")
        step = m.get("step")
        total = m.get("total_steps")
        detail = ""
        if isinstance(step, int) and isinstance(total, int):
            detail = f"（step {step}/{total}）"
        elif isinstance(total, int):
            detail = f"（{total} steps）"
        lines.append(f"- {name}{detail}")

    omitted = max(0, len(processes) - len(shown))
    if omitted:
        lines.append(
            f"- … 另有 {omitted} 条执行流未列出（top-{_TOP_AFFECTED_PROCESSES}）"
        )
    return lines


def _render_risk(envelope: Mapping[str, Any]) -> list[str]:
    level, reasons = _aggregate_risk(envelope)
    lines = ["### Risk", "", f"- **{level}**"]
    for r in reasons:
        lines.append(f"- {r}")
    # D-12：部分成功醒目声明降级
    graph = _as_mapping(envelope.get("graph"))
    staleness = _as_mapping(envelope.get("staleness"))
    behind = staleness.get("behind_commits")
    if graph.get("degraded") or (isinstance(behind, int) and behind > 0):
        lines.append("- ⚠ 部分成功 / 降级：请结合索引水位复核，勿将行号视为最终真相")
    lines.append("")
    return lines


def _render_recommendations(envelope: Mapping[str, Any]) -> list[str]:
    lines = ["### Recommendations", ""]
    summary = _as_mapping(envelope.get("summary"))
    staleness = _as_mapping(envelope.get("staleness"))
    behind = staleness.get("behind_commits")
    graph = _as_mapping(envelope.get("graph"))

    has_d1 = False
    for item in _as_list(envelope.get("impacts")):
        impact = _as_mapping(_as_mapping(item).get("impact"))
        for group in _as_list(impact.get("groups")):
            if _as_mapping(group).get("depth") == 1 and _as_list(_as_mapping(group).get("items")):
                has_d1 = True
                break
        if has_d1:
            break

    if has_d1:
        lines.append("- 复核 d1 callers，确认直接调用方是否需要同步改动")
    if summary.get("truncated") or summary.get("not_expanded") or summary.get("file_level_only"):
        lines.append("- 变更面已截断或未展开；建议缩小 diff 范围或提高索引覆盖后再信行号")
    if isinstance(behind, int) and behind > 0:
        lines.append("- 建议重索引后再信行号交叠结果（索引落后）")
    if graph.get("degraded"):
        lines.append("- 图服务处于降级态，影响面可能不完整")
    processes = _as_list(envelope.get("affected_processes"))
    if processes:
        lines.append("- 复核受影响执行流中标注的步骤，确认跨社区路径是否需同步改动")
    else:
        lines.append("- 暂无匹配执行流；若业务路径应受影响，请先构建 Process 后再信本段")
    if len(lines) == 2:
        lines.append("- 按常规 code review 复核变更影响即可")
    lines.append("")
    return lines


def _render_four_sections(envelope: Mapping[str, Any]) -> str:
    parts: list[str] = [IMPACT_SECTION_MARKER, ""]
    parts.extend(_render_changes(envelope))
    parts.extend(_render_affected(envelope))
    parts.extend(_render_risk(envelope))
    parts.extend(_render_recommendations(envelope))
    text = "\n".join(parts).rstrip() + "\n"
    max_chars = int(getattr(settings, "CODE_GRAPH_IMPACT_REPORT_MAX_CHARS", 10240))
    if max_chars > 0 and len(text) > max_chars:
        note = "\n\n_… truncated（超过 CODE_GRAPH_IMPACT_REPORT_MAX_CHARS）_\n"
        keep = max(0, max_chars - len(note))
        text = text[:keep].rstrip() + note
    return text


async def build_impact_report_section(
    *,
    repository: Any,
    user: Any,
    compare: str,
    base_ref: str | None = None,
) -> str:
    """生成 MR 描述用 ``## 影响面`` 段。

    **永不 raise 阻断建 MR**（D-09）：失败返回 stub 或 ``""``。
    """
    started = time.perf_counter()
    repository_id = str(getattr(repository, "id", "") or "")
    initiated_by = _initiated_by_user_id(user)

    def _duration_ms() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        logger.info(
            "code_graph_impact_report_started",
            component="code_graph",
            category="sampling",
            repository_id=repository_id,
            initiated_by_user_id=initiated_by,
        )
    except Exception:  # noqa: BLE001 — 观测永不反噬
        pass

    def _log_completed(*, section: str, ok: bool) -> None:
        try:
            logger.info(
                "code_graph_impact_report_completed",
                component="code_graph",
                category="sampling",
                repository_id=repository_id,
                initiated_by_user_id=initiated_by,
                duration_ms=_duration_ms(),
                section_chars=len(section),
                ok=ok,
            )
        except Exception:  # noqa: BLE001
            pass

    def _log_failed(*, error_code: str, error: str = "") -> None:
        try:
            logger.info(
                "code_graph_impact_report_failed",
                component="code_graph",
                category="sampling",
                repository_id=repository_id,
                initiated_by_user_id=initiated_by,
                duration_ms=_duration_ms(),
                error_code=error_code,
                # ⚠️ 埋点处**显式**再过一遍 redact_secrets_in_text：脱敏幂等，但包内观测契约
                # （tests/services/code_graph/test_access.py::test_observability_contract）
                # 是静态 AST 判据——藏在 helper 里它看不见。
                error=redact_secrets_in_text(_sanitize_error_text(error)),
            )
        except Exception:  # noqa: BLE001
            pass

    def _safe_stub(error_code: str, *, error: str = "") -> str:
        try:
            stub = _stub_section(error_code)
        except Exception:  # noqa: BLE001 — 对齐 pr_cross_reference 空串兜底
            _log_failed(error_code="unavailable", error=error or "stub_failed")
            return ""
        _log_failed(error_code=_map_error_code(error_code), error=error)
        return stub

    # user 缺失：不调用编排撞 ACL 绕过；直接 stub（D-15 / 124-03 接线约定）。
    # 使用独立 error_code=user_missing，与图谱/ACL 出站失败的 unavailable 区分（ME-03）。
    if user is None:
        return _safe_stub("user_missing", error="user_missing")

    timeout = float(
        getattr(settings, "CODE_GRAPH_IMPACT_REPORT_TIMEOUT_SECONDS", 30.0)
    )
    try:
        envelope = await asyncio.wait_for(
            run_detect_changes(
                repository_id=repository_id,
                repo=repository,
                user=user,
                compare=compare,
                base_ref=base_ref,
            ),
            timeout=timeout,
        )
    except TimeoutError:
        return _safe_stub("timeout", error="wait_for_timeout")
    except GraphAccessDenied as exc:
        return _safe_stub("unavailable", error=_sanitize_error_text(str(exc)))
    except Exception as exc:  # noqa: BLE001 — fail-soft
        return _safe_stub("unavailable", error=_sanitize_error_text(str(exc)))

    try:
        if not isinstance(envelope, Mapping) or not envelope.get("ok"):
            raw_code = None
            err_text = ""
            if isinstance(envelope, Mapping):
                raw_code = envelope.get("error_code")
                err_text = str(envelope.get("error") or "")
            return _safe_stub(
                _map_error_code(str(raw_code) if raw_code is not None else None),
                error=_sanitize_error_text(err_text),
            )

        section = _render_four_sections(envelope)
        _log_completed(section=section, ok=True)
        return section
    except Exception as exc:  # noqa: BLE001 — 渲染失败仍 fail-soft
        return _safe_stub("unavailable", error=_sanitize_error_text(str(exc)))
