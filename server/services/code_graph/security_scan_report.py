"""MR 描述安全扫描段：``## 安全扫描`` formatter / stub / 异步回填（TAINT-02/03；D-06..D-09）。

契约
====
- ``build_security_scan_section`` / ``stub_security_scan_section`` **永不 raise 阻断建 MR**。
- 全程 **advisory**：finding 带 severity 展示，无 blocking / merge-gate 语义（D-07）。
- 固定 CE 函数内 taint disclaimer + ``nosemgrep`` 说明；Pro 仅 opt-in 短句不夸大（D-08/D-09）。
- stub 稳定短码；禁止堆栈 / 绝对路径 / 凭证进 MR（T-127-01）。
- 观测 best-effort，失败吞掉。
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import structlog

from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

SECURITY_SECTION_MARKER: Final[str] = "## 安全扫描"

_SEVERITY_ORDER: Final[tuple[str, ...]] = ("ERROR", "WARNING", "INFO")
_TOP_FINDINGS_PER_SEVERITY: Final[int] = 20

# T-127-01：日志/ stub 旁路文本禁止绝对路径与堆栈帧。
_ABS_PATH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:(?:/Users|/home|/var|/tmp|/opt|/usr|/[A-Za-z]+)(?:/[^\s:'\"]+)+)"
)

_CE_DISCLAIMER: Final[str] = (
    "当前为 Semgrep **CE**：taint 分析**仅函数内**，"
    "不承诺跨函数/跨文件追踪；结论仅供人工复核（advisory，不阻断合并）。"
)
_NOSEMGREP_HINT: Final[str] = (
    "误报可按 Semgrep 原生语义在代码旁标注 `nosemgrep` 抑制；本系统不维护平行 suppress 表。"
)
_PRO_LINE: Final[str] = (
    "Pro 能力已启用（加密配置的 `SEMGREP_APP_TOKEN`）；"
    "跨文件覆盖率仍以实际规则与仓库为准，本段不夸大未验证能力。"
)

__all__ = [
    "SECURITY_SECTION_MARKER",
    "append_security_scan",
    "attach_security_scan_pending",
    "build_security_scan_section",
    "replace_security_scan_section",
    "stub_security_scan_section",
    "is_security_scan_stub_section",
    "patch_mr_security_scan_section",
]


def append_security_scan(description: str, section: str) -> str:
    """幂等追加安全扫描段：已含 ``## 安全扫描`` 则不重复（D-06）。"""
    if not section:
        return description or ""
    if SECURITY_SECTION_MARKER in (description or ""):
        return description
    base = (description or "").rstrip()
    return f"{base}\n\n{section}" if base else section


def _map_error_code(raw: str | None) -> str:
    code = (raw or "").strip() or "unavailable"
    # 允许常见短码；脏串（含路径/空格/过长）退回 unavailable
    if code in {"timeout", "unavailable", "pending", "not_indexed", "mirror_unavailable"}:
        return code
    # 若以短码开头（如 timeout token=...）取首词
    first = code.split()[0] if code.split() else "unavailable"
    first = first.split("=")[0].strip("`")
    if first in {"timeout", "unavailable", "pending", "not_indexed", "mirror_unavailable"}:
        return first
    if len(code) > 64 or "/" in code or "\\" in code or " " in code or "\n" in code:
        return "unavailable"
    return code


def _sanitize_error_text(text: str) -> str:
    """凭证脱敏 + 去掉 Traceback / 绝对路径（T-127-01）。"""
    cleaned = redact_secrets_in_text(text or "")
    if "Traceback" in cleaned:
        cleaned = cleaned.split("Traceback", 1)[0].rstrip()
    cleaned = _ABS_PATH_RE.sub("[path]", cleaned)
    return cleaned[:500]


def stub_security_scan_section(error_code: str = "unavailable") -> str:
    """D-04/D-06 固定 stub；自身失败由调用方折空串。"""
    safe = _map_error_code(error_code)
    return (
        f"{SECURITY_SECTION_MARKER}\n\n"
        f"_安全扫描未能生成（`{safe}`）。MR 已照常创建，请人工复核（advisory，不阻断合并）。_\n"
    )


def _stub_section(error_code: str) -> str:
    """与 impact_report 对称的私有别名。"""
    return stub_security_scan_section(error_code)


def is_security_scan_stub_section(section_or_body: str) -> bool:
    """判断段/全文中的安全扫描段是否仍为 stub/pending（可被异步回填替换）。"""
    text = section_or_body or ""
    if SECURITY_SECTION_MARKER not in text:
        return False
    # 截取本段（到下一个 ## 或文末）
    start = text.find(SECURITY_SECTION_MARKER)
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    chunk = rest if nxt < 0 else rest[:nxt]
    if "安全扫描未能生成" in chunk:
        return True
    if "`pending`" in chunk or "pending" in chunk.lower() and "未能生成" in chunk:
        return True
    # 成功段必含 CE disclaimer；缺则视为可替换的占位
    if "仅函数内" not in chunk and "未能生成" in chunk:
        return True
    return "安全扫描未能生成" in chunk


def replace_security_scan_section(description: str, new_section: str) -> str:
    """用完整段替换描述中已有的 ``## 安全扫描`` 段；无标记则 append。"""
    if not new_section:
        return description or ""
    text = description or ""
    if SECURITY_SECTION_MARKER not in text:
        return append_security_scan(text, new_section)
    start = text.find(SECURITY_SECTION_MARKER)
    # 向后找到下一个顶级 ## 或文末
    after = text[start + len(SECURITY_SECTION_MARKER) :]
    nxt_rel = after.find("\n## ")
    if nxt_rel < 0:
        end = len(text)
    else:
        end = start + len(SECURITY_SECTION_MARKER) + nxt_rel
    prefix = text[:start].rstrip()
    suffix = text[end:].lstrip("\n")
    body = new_section.strip() + "\n"
    if prefix and suffix:
        return f"{prefix}\n\n{body}\n{suffix}"
    if prefix:
        return f"{prefix}\n\n{body}"
    if suffix:
        return f"{body}\n{suffix}"
    return body


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return list(value)
    return []


def _normalize_severity(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text in _SEVERITY_ORDER:
        return text
    if text in {"CRITICAL", "HIGH"}:
        return "ERROR"
    if text in {"MEDIUM", "MODERATE"}:
        return "WARNING"
    if text in {"LOW", "NOTE"}:
        return "INFO"
    return "INFO"


def _render_findings(findings: Sequence[Mapping[str, Any] | dict[str, Any]]) -> list[str]:
    buckets: dict[str, list[Mapping[str, Any]]] = {s: [] for s in _SEVERITY_ORDER}
    for item in findings:
        m = _as_mapping(item)
        sev = _normalize_severity(m.get("severity"))
        buckets.setdefault(sev, []).append(m)

    lines = ["### Findings（advisory）", ""]
    any_shown = False
    for sev in _SEVERITY_ORDER:
        items = buckets.get(sev) or []
        if not items:
            continue
        any_shown = True
        lines.append(f"#### {sev}（{len(items)}）")
        shown = items[:_TOP_FINDINGS_PER_SEVERITY]
        for row in shown:
            rule = str(row.get("rule_id") or "unknown")
            path = str(row.get("file_path") or "").strip() or "(unknown)"
            line_no = row.get("line")
            msg = redact_secrets_in_text(str(row.get("message") or "")).strip()
            if len(msg) > 200:
                msg = msg[:200] + "…"
            loc = f"{path}:{line_no}" if line_no else path
            detail = f"- `{sev}` `{rule}` @ `{loc}`"
            if msg:
                detail += f" — {msg}"
            lines.append(detail)
        omitted = max(0, len(items) - len(shown))
        if omitted:
            lines.append(f"- … 另有 {omitted} 条 {sev} 未列出")
        lines.append("")
    if not any_shown:
        lines.append("- （本次 diff-aware 扫描无新增 finding）")
        lines.append("")
    return lines


def build_security_scan_section(
    *,
    findings: Sequence[Mapping[str, Any] | dict[str, Any]] | None = None,
    pro_enabled: bool = False,
    error_code: str | None = None,
) -> str:
    """生成 MR 描述用 ``## 安全扫描`` 段。

    **永不 raise**；``error_code`` 非空时返回 stub。
    """
    started = time.perf_counter()

    def _duration_ms() -> float:
        return round((time.perf_counter() - started) * 1000, 2)

    try:
        logger.info(
            "security_scan_report_started",
            component="code_graph",
            category="caller",
            pro_enabled=bool(pro_enabled),
            findings_count=len(findings or []),
        )
    except Exception:  # noqa: BLE001 — 观测永不反噬
        pass

    try:
        if error_code:
            section = _stub_section(error_code)
            try:
                logger.info(
                    "security_scan_report_failed",
                    component="code_graph",
                    category="caller",
                    error_code=_map_error_code(error_code),
                    duration_ms=_duration_ms(),
                )
            except Exception:  # noqa: BLE001
                pass
            return section

        parts: list[str] = [SECURITY_SECTION_MARKER, "", _CE_DISCLAIMER, ""]
        if pro_enabled:
            parts.extend([_PRO_LINE, ""])
        parts.append(_NOSEMGREP_HINT)
        parts.append("")
        parts.extend(_render_findings(_as_list(findings)))
        section = "\n".join(parts).rstrip() + "\n"
        try:
            logger.info(
                "security_scan_report_completed",
                component="code_graph",
                category="caller",
                duration_ms=_duration_ms(),
                section_chars=len(section),
                pro_enabled=bool(pro_enabled),
                findings_count=len(findings or []),
                ok=True,
            )
        except Exception:  # noqa: BLE001
            pass
        return section
    except Exception as exc:  # noqa: BLE001 — fail-soft
        try:
            logger.info(
                "security_scan_report_failed",
                component="code_graph",
                category="caller",
                error_code="unavailable",
                error=_sanitize_error_text(str(exc)),
                duration_ms=_duration_ms(),
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            return _stub_section("unavailable")
        except Exception:  # noqa: BLE001
            return ""


async def _load_findings_for_mr(repository_id: str, mr_key: str) -> list[dict[str, Any]]:
    from asgiref.sync import sync_to_async

    @sync_to_async
    def _query() -> list[dict[str, Any]]:
        from codegraph.models import SecurityFinding

        rows = list(
            SecurityFinding.objects.filter(
                repository_id=repository_id,
                mr_key=mr_key,
                status="open",
            )
            .order_by("severity", "file_path", "line")
            .values("severity", "rule_id", "file_path", "line", "message")[:200]
        )
        return rows

    try:
        return await _query()
    except Exception:  # noqa: BLE001
        return []


async def _read_mr_description(client: Any, mr_id: str) -> str | None:
    """GitHub/GitLab 读当前 MR/PR body；失败返回 None。"""
    import asyncio

    try:
        if hasattr(client, "_get_repo"):
            repo_obj = client._get_repo()
            pr = await asyncio.to_thread(repo_obj.get_pull, int(mr_id))
            return str(getattr(pr, "body", None) or "")
        if hasattr(client, "_get_project"):
            project = client._get_project()
            mr_obj = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
            return str(getattr(mr_obj, "description", None) or "")
    except Exception:  # noqa: BLE001
        return None
    return None


async def _write_mr_description(client: Any, mr_id: str, body: str) -> bool:
    """对齐 pr_cross_reference：GitHub ``pr.edit`` / GitLab ``description``+``save``。"""
    import asyncio

    try:
        if hasattr(client, "_get_repo"):
            repo_obj = client._get_repo()
            pr = await asyncio.to_thread(repo_obj.get_pull, int(mr_id))
            await asyncio.to_thread(pr.edit, body=body)
            return True
        if hasattr(client, "_get_project"):
            project = client._get_project()
            mr_obj = await asyncio.to_thread(project.mergerequests.get, int(mr_id))
            mr_obj.description = body
            await asyncio.to_thread(mr_obj.save)
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


async def patch_mr_security_scan_section(
    *,
    repository_id: str,
    mr_key: str,
    scan_result: Mapping[str, Any] | None = None,
    branch_name: str = "",
) -> bool:
    """异步回填 MR 描述中的 ``## 安全扫描`` 段（stub/pending → 完整结果）。

    fail-soft：缺凭证 / 平台失败 / 非 stub 段 → 返回 False，不抛、不重试风暴。
    """
    from asgiref.sync import sync_to_async

    repo_id = str(repository_id or "").strip()
    key = str(mr_key or "").strip()
    scan = dict(scan_result or {})
    branch = (branch_name or str(scan.get("branch_name") or "") or key).strip()
    if not repo_id or (not key and not branch):
        return False

    started = time.perf_counter()

    try:
        from repositories.models import Repository
        from services.git_credentials import aresolve_git_token
        from services.git_platform import get_git_platform_client

        repo = await Repository.objects.filter(id=repo_id).afirst()
        if repo is None:
            return False

        token = await aresolve_git_token(repo)
        if not token:
            return False

        client = get_git_platform_client(repo, token)
        mr_id = key if key.isdigit() else ""
        if not mr_id and branch and hasattr(client, "find_open_merge_request"):
            target = str(
                scan.get("target_branch") or getattr(repo, "default_branch", None) or "main"
            )
            try:
                existing = await client.find_open_merge_request(branch, target)
                if existing and getattr(existing, "success", False):
                    mr_id = str(getattr(existing, "mr_id", "") or "")
            except Exception:  # noqa: BLE001
                mr_id = ""
        if not mr_id:
            return False

        # 构建完整段：error_code → stub；否则从 SecurityFinding 拉 findings
        error_code = scan.get("error_code")
        pro_enabled = False
        try:
            # 与扫描注入同一判定（含 env escape hatch），避免「跑了 Pro 却不声明」
            from services.code_graph.semgrep_token import is_semgrep_pro_enabled

            pro_enabled = bool(await sync_to_async(is_semgrep_pro_enabled)())
        except Exception:  # noqa: BLE001
            pro_enabled = False

        if error_code:
            new_section = build_security_scan_section(
                findings=[],
                pro_enabled=pro_enabled,
                error_code=str(error_code),
            )
        else:
            findings = await _load_findings_for_mr(repo_id, key or mr_id)
            if not findings and branch and branch != key:
                findings = await _load_findings_for_mr(repo_id, branch)
            new_section = build_security_scan_section(
                findings=findings,
                pro_enabled=pro_enabled,
            )

        if not new_section:
            return False

        current_body = await _read_mr_description(client, mr_id)
        if current_body is None:
            return False

        # 已是完整结果（非 stub）→ 幂等 skip
        if SECURITY_SECTION_MARKER in current_body and not is_security_scan_stub_section(
            current_body
        ):
            return True

        new_body = replace_security_scan_section(current_body, new_section)
        if new_body == current_body:
            return True

        ok = await _write_mr_description(client, mr_id, new_body)
        try:
            logger.info(
                "security_scan_mr_patch_completed" if ok else "security_scan_mr_patch_failed",
                component="code_graph",
                category="caller",
                repository_id=repo_id,
                mr_key=key or mr_id,
                ok=ok,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return ok
    except Exception as exc:  # noqa: BLE001 — 回填永不反噬扫描
        try:
            logger.warning(
                "security_scan_mr_patch_failed",
                component="code_graph",
                category="caller",
                repository_id=repo_id,
                mr_key=key,
                error=_sanitize_error_text(str(exc)),
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except Exception:  # noqa: BLE001
            pass
        return False


async def attach_security_scan_pending(
    description: str,
    *,
    repository: Any = None,
    source_branch: str = "",
    target_branch: str = "",
    user: Any = None,
    mr_key: str = "",
    source_sha: str = "",
    target_sha: str = "",
    enqueue: bool = True,
) -> str:
    """创建路径：幂等挂 pending stub，并可选 fire-and-forget 入队扫描。

    外壳异常由调用方吞；本函数自身也 fail-soft（返回原 description）。
    """
    try:
        section = stub_security_scan_section("pending")
        out = append_security_scan(description, section)
    except Exception:  # noqa: BLE001
        return description or ""

    if not enqueue:
        return out

    try:
        from services.code_graph.semgrep_enqueue import enqueue_semgrep_scan_for_branches

        repo_id = str(getattr(repository, "id", "") or "")
        initiated_by = "system"
        if user is not None and getattr(user, "id", None) is not None:
            initiated_by = str(user.id)
        if repo_id:
            # 两端 sha 缺失时由 helper 记 skip 并保留 pending stub（⛔ 不入队恒失败任务）
            await enqueue_semgrep_scan_for_branches(
                repo_id,
                mr_key=mr_key or "",
                source_branch=source_branch or "",
                target_branch=target_branch or "",
                source_sha=source_sha or "",
                target_sha=target_sha or "",
                initiated_by_user_id=initiated_by,
            )
    except Exception:  # noqa: BLE001 — enqueue 失败不阻断建 MR
        try:
            logger.warning(
                "security_scan_attach_enqueue_failed",
                component="code_graph",
                category="caller",
                repository_id=str(getattr(repository, "id", "") or ""),
                error="enqueue_failed",
            )
        except Exception:  # noqa: BLE001
            pass
    return out
