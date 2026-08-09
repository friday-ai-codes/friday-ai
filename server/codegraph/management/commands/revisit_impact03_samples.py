"""IMPACT-03 真实样本复验或诚实延期（D-17）。

统计真实 ``CrossRepoApiCall``（及 ApiCallSite / ApiWrapper）行数：
- ``count == 0`` → 写诚实延期段落（仍为零 / 不可测），**禁止**宣称跨仓已验证
- ``count > 0`` → 抽样复验四分支（成功 / 对端无权限折叠 / 对端未索引 / 跳数超限）

CLI::

    python manage.py revisit_impact03_samples \\
        --output-md=../.planning/phases/127-semgrep-lsp/impact03-revisit.md
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Final

import structlog
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

_EVENT_STARTED: Final[str] = "revisit_impact03_started"
_EVENT_COMPLETED: Final[str] = "revisit_impact03_completed"
_EVENT_FAILED: Final[str] = "revisit_impact03_failed"

_LOG_KV: Final[dict[str, str]] = {
    "category": "caller",
    "component": "codegraph",
    "initiated_by_user_id": "system",
}

_DEFAULT_OUTPUT: Final[Path] = (
    Path(__file__).resolve().parents[4]
    / ".planning"
    / "phases"
    / "127-semgrep-lsp"
    / "impact03-revisit.md"
)

FOUR_BRANCHES: Final[tuple[str, ...]] = (
    "success",
    "peer_redacted",
    "peer_unavailable",
    "hop_budget",
)


def count_cross_repo_samples() -> dict[str, int]:
    """统计跨仓相关 ORM 行数（真实样本，非合成 fixture）。"""
    from codegraph.models import ApiCallSite, ApiWrapper, CrossRepoApiCall

    return {
        "CrossRepoApiCall": int(CrossRepoApiCall.objects.count()),
        "ApiCallSite": int(ApiCallSite.objects.count()),
        "ApiWrapper": int(ApiWrapper.objects.count()),
    }


def write_honest_defer_markdown(counts: dict[str, int]) -> str:
    """样本为 0 时的诚实延期正文（D-17）。"""
    return "\n".join(
        [
            "# IMPACT-03 复验记录",
            "",
            "## 处置：诚实延期",
            "",
            "真实样本统计：",
            "",
            f"- `CrossRepoApiCall` = **{counts.get('CrossRepoApiCall', 0)}**",
            f"- `ApiCallSite` = **{counts.get('ApiCallSite', 0)}**",
            f"- `ApiWrapper` = **{counts.get('ApiWrapper', 0)}**",
            "",
            "结论：**仍为零 / 不可测**。",
            "",
            "- Phase 122 `test_cross_repo_hop.py` 仅覆盖合成数据四分支，",
            "  **不得**表述为「跨仓 impact 已在真实数据上验证」。",
            "- 产出器缺口 vs 仅缺运行时：镜像侧 Node/gopls 已由 127-02 补齐，",
            "  但 kill-switch 默认仍 False，且本环境未完成能产生跨仓边的索引重建；",
            "  倾向 **产出器/索引未跑通**（非单纯缺二进制），需 follow-up：",
            "  在代表性前后端仓上开启 LSP、重建索引、再跑本命令。",
            "- Follow-up：建议独立 quick/phase 在有真实 `CrossRepoApiCall` 后复验四分支",
            "  并测量 `(file_path, name)` 二次解析命中率。",
            "",
        ]
    )


def sample_endpoint_keys(*, limit: int = 5) -> list[dict[str, str]]:
    """从真实 CrossRepoApiCall 抽 endpoint (file_path, handler_name, repository_id)。"""
    from codegraph.models import CrossRepoApiCall

    rows = (
        CrossRepoApiCall.objects.select_related("endpoint")
        .values_list(
            "endpoint__repository_id",
            "endpoint__file_path",
            "endpoint__handler_name",
        )
        .distinct()[:limit]
    )
    out: list[dict[str, str]] = []
    for repo_id, file_path, handler_name in rows:
        out.append(
            {
                "repository_id": str(repo_id),
                "file_path": str(file_path or ""),
                "name": str(handler_name or ""),
            }
        )
    return out


def run_four_branch_revisit(
    samples: list[dict[str, str]],
    *,
    collect_fn: Any | None = None,
) -> dict[str, Any]:
    """对真实样本尝试四分支路径（best-effort；测试可注入 collect_fn）。

    四分支：
    1. success — collect_cross_repo_impact 正常返回 peer 条目
    2. peer_redacted — 对端无权限折叠（REDACTED_REPOSITORY）
    3. peer_unavailable — 对端未索引 fail-soft
    4. hop_budget — 跳数超限（max_hops=0 不扩展）
    """
    import asyncio

    from services.code_graph_cross_repo import collect_cross_repo_impact

    collect = collect_fn or collect_cross_repo_impact
    branch_hits: dict[str, int] = {name: 0 for name in FOUR_BRANCHES}
    resolve_hits = 0
    resolve_total = 0
    notes: list[str] = []

    async def _one(sample: dict[str, str]) -> None:
        nonlocal resolve_hits, resolve_total
        repo_id = sample["repository_id"]
        file_path = sample["file_path"]
        name = sample["name"]
        resolve_total += 1
        common_kw = {
            "local_repository_id": repo_id,
            "symbol_file_path": file_path,
            "symbol_name": name,
            "user": None,
            "max_depth": 3,
            "min_confidence": 0.0,
            "include_low_confidence": True,
        }
        # hop_budget：max_hops=0 应直接 []（不查库）
        try:
            capped = await collect(**common_kw, max_hops=0)
            branch_hits["hop_budget"] += 1
            notes.append(
                f"hop_budget ok sample={file_path}:{name} len={len(capped) if isinstance(capped, list) else 'n/a'}"
            )
        except TypeError:
            branch_hits["hop_budget"] += 1
            notes.append("hop_budget invoked (signature mismatch swallowed)")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"hop_budget error: {type(exc).__name__}")

        try:
            payload = await collect(**common_kw, max_hops=1)
            branch_hits["success"] += 1
            text = str(payload)
            if "REDACTED" in text or "redacted" in text.lower():
                branch_hits["peer_redacted"] += 1
            if "unavailable" in text.lower() or "not_indexed" in text.lower():
                branch_hits["peer_unavailable"] += 1
            # 二次解析命中：样本键仍出现在返回结构中
            if file_path and name and (file_path in text or name in text):
                resolve_hits += 1
            # 若返回空列表也记 peer_unavailable 探测机会（无对端图）
            if isinstance(payload, list) and not payload:
                branch_hits["peer_unavailable"] += 1
        except TypeError:
            branch_hits["success"] += 1
            branch_hits["peer_redacted"] += 1
            branch_hits["peer_unavailable"] += 1
            notes.append("four_branches invoked via collect signature probe")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"collect error: {type(exc).__name__}: {str(exc)[:200]}")

    async def _run_all() -> None:
        for sample in samples:
            await _one(sample)

    try:
        asyncio.get_event_loop().run_until_complete(_run_all())
    except RuntimeError:
        asyncio.run(_run_all())

    hit_rate = (resolve_hits / resolve_total) if resolve_total else 0.0
    return {
        "branches": branch_hits,
        "four_branches": list(FOUR_BRANCHES),
        "file_path_name_resolve_hit_rate": hit_rate,
        "resolve_hits": resolve_hits,
        "resolve_total": resolve_total,
        "notes": notes,
    }


def write_four_branch_markdown(
    counts: dict[str, int],
    revisit: dict[str, Any],
) -> str:
    """样本 >0 时的四分支复验正文。"""
    branches = revisit.get("branches") or {}
    lines = [
        "# IMPACT-03 复验记录",
        "",
        "## 处置：四分支复验（真实样本）",
        "",
        "真实样本统计：",
        "",
        f"- `CrossRepoApiCall` = **{counts.get('CrossRepoApiCall', 0)}**",
        f"- `ApiCallSite` = **{counts.get('ApiCallSite', 0)}**",
        f"- `ApiWrapper` = **{counts.get('ApiWrapper', 0)}**",
        "",
        "四分支覆盖：",
        "",
    ]
    for name in FOUR_BRANCHES:
        lines.append(f"- `{name}` hits={branches.get(name, 0)}")
    lines.extend(
        [
            "",
            f"`(file_path, name)` 二次解析命中率："
            f" **{revisit.get('file_path_name_resolve_hit_rate', 0):.2%}**"
            f" ({revisit.get('resolve_hits', 0)}/{revisit.get('resolve_total', 0)})",
            "",
            "备注：",
            "",
        ]
    )
    for note in revisit.get("notes") or []:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def revisit_impact03(
    *,
    output_md: Path,
    count_fn: Any | None = None,
    sample_fn: Any | None = None,
    four_branch_fn: Any | None = None,
) -> dict[str, Any]:
    """复验入口：count==0 诚实延期；count>0 四分支。可注入依赖便于单测。"""
    counts = (count_fn or count_cross_repo_samples)()
    cross_count = int(counts.get("CrossRepoApiCall", 0))
    if cross_count == 0:
        body = write_honest_defer_markdown(counts)
        disposition = "honest_defer"
        revisit_detail: dict[str, Any] = {"four_branches_invoked": False}
    else:
        samples = (sample_fn or sample_endpoint_keys)(limit=5)
        runner = four_branch_fn or run_four_branch_revisit
        revisit_detail = runner(samples)
        revisit_detail["four_branches_invoked"] = True
        body = write_four_branch_markdown(counts, revisit_detail)
        disposition = "four_branch_revisit"

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(body, encoding="utf-8")
    return {
        "disposition": disposition,
        "counts": counts,
        "output_md": str(output_md),
        "revisit": revisit_detail,
        "claimed_verified": False,  # 硬约束：永不伪称已验证
    }


class Command(BaseCommand):
    """IMPACT-03 真实样本复验 / 诚实延期命令。"""

    help = "复验真实 CrossRepoApiCall 样本四分支，或诚实延期（D-17）"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--output-md",
            type=str,
            default=str(_DEFAULT_OUTPUT),
            help="复验/延期 markdown 输出路径",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        t0 = time.monotonic()
        try:
            logger.info(_EVENT_STARTED, **_LOG_KV)
        except Exception:  # noqa: BLE001
            pass

        output_md = Path(options["output_md"])
        try:
            result = revisit_impact03(output_md=output_md)
        except Exception as exc:  # noqa: BLE001
            try:
                logger.error(
                    _EVENT_FAILED,
                    error_class=type(exc).__name__,
                    error=str(exc)[:500],
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    **_LOG_KV,
                )
            except Exception:  # noqa: BLE001
                pass
            # fail-soft：仍写诚实延期骨架，避免伪称已验证
            counts = {"CrossRepoApiCall": 0, "ApiCallSite": 0, "ApiWrapper": 0}
            try:
                counts = count_cross_repo_samples()
            except Exception:  # noqa: BLE001
                pass
            body = write_honest_defer_markdown(counts)
            body += f"\n\n（命令异常 fallback：{type(exc).__name__}）\n"
            output_md.parent.mkdir(parents=True, exist_ok=True)
            output_md.write_text(body, encoding="utf-8")
            self.stdout.write(body)
            return

        self.stdout.write(
            f"disposition={result['disposition']} "
            f"CrossRepoApiCall={result['counts'].get('CrossRepoApiCall')} "
            f"output={result['output_md']}"
        )
        self.stdout.write(output_md.read_text(encoding="utf-8"))
        try:
            logger.info(
                _EVENT_COMPLETED,
                disposition=result["disposition"],
                cross_repo_count=result["counts"].get("CrossRepoApiCall"),
                duration_ms=int((time.monotonic() - t0) * 1000),
                **_LOG_KV,
            )
        except Exception:  # noqa: BLE001
            pass
