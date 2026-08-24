"""v0.22 图查询能力 benchmark command —— 薄 I/O 层（冻结 gold + 水位闸 + 真跑被测能力）。

**为什么需要它。** Phase 133 要建立可复现、无阈值污染的 v0.22 原始基线（BENCH-01/03）。
本 command 是把 Plan 01/03 的纯函数地基（``codegraph.services.graph_bench_eval``）与
Plan 02 的冻结 gold 数据集接成可运行只读评测的**唯一 I/O 层**：加载 gold → 按
``(repository_id, branch)`` 解析三方水位做 fail-closed 闸 → 逐 case 调**未修改**的
v0.22 能力（get_graph/resolve/impact/trace/检索 lane）冷/热计时 → 落 run manifest 与
无阈值 baseline JSON。复刻 recall eval「纯模块 + 薄 command」分工：本文件只做 I/O、
计时、落盘与观测埋点，⛔ 不复制任何被测管线逻辑、不修改被测能力行为。

口径（读数字前必须知道）
========================

- **水位闸 fail-closed（BENCH-01）**：索引 ``last_indexed_commit_sha``、gold
  ``annotated_at_sha``、源码 checkout ``--commit-sha`` 三方任一为空或不全相等 → run 标
  ``INVALID``，写 manifest 含 ``invalid_reason``、非零退出，⛔ 此路径**绝不调用**
  ``get_graph`` 或任何被测能力、绝不跑任何 case。可选第四参 ``process_built_at_sha``
  （ProcessTrace 投影）漂移同样 INVALID。
- **只读（BENCH-03）**：全程只调只读入口 + ORM 读，⛔ 不写生产索引、不触发任何
  索引回填或重建路径。
- **holdout 拒读**：``--split holdout`` 直接 ``CommandError``——holdout 保留给 Phase 140
  最终验收，baseline 阶段不读。
- **无阈值**：baseline JSON 只含原始值与空结果标记，⛔ 不含任何回归门/目标值/容差/比对
  字段（阈值决策权属 Phase 140，BENCH-06/07）。
- **冷/热计时**：每 case 先 ``invalidate_repository`` 驱逐缓存再 ``get_graph`` 计时得
  ``cold_ms``；紧接第二次 ``get_graph``（缓存命中）计时得 ``warm_ms``（``--cold-only``
  跳过热跑）。
- **观测**：caller 生命周期事件（started/completed/failed/invalid，含 ``duration_ms`` /
  ``run_id`` / ``initiated_by_user_id=system``）+ 逐 case sampling 事件；只记
  sha/计数/闭集枚举/run_id，⛔ 不记 query 正文或凭证；异常文本经
  ``redact_secrets_in_text``；观测 best-effort 绝不反噬评测。

CLI 用例
========

::

    # 在已索引仓上跑 dev + locked_test 全量 baseline，落 manifest 与报告
    python manage.py evaluate_graph_bench \\
        --repo <repository_id> --branch main --commit-sha <checkout_sha> \\
        --output-manifest /tmp/bench-manifest.json --output-json /tmp/bench.json

    # 只跑 dev 切分、只测冷延迟
    python manage.py evaluate_graph_bench --repo <id> --commit-sha <sha> \\
        --split dev --cold-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from codegraph.services.graph_bench_eval import (
    build_report,
    build_run_identity,
    evaluate_case,
    validate_gold_dataset,
    validate_watermark,
)
from common.logging import redact_secrets_in_text

logger = structlog.get_logger(__name__)

# 公共 kv：category=caller（本 command 是一次性调用入口）、component=codegraph、
# 无触发用户（运维/CI 显式执行）→ initiated_by_user_id=system（LOGGING-SPEC §3/§5）。
_LOG_KV = {
    "category": "caller",
    "component": "codegraph",
    "initiated_by_user_id": "system",
}

_DEFAULT_GOLD = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "graph_bench"

# baseline 只读 dev + locked_test；holdout 保留 Phase 140 最终验收，本阶段不读。
_BASELINE_SPLITS = ("dev", "locked_test")


def _load_gold(gold_dir: Path, split: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """加载 gold manifest 与选定 split 的 case 列表（只读 fixtures 目录）。

    ``split="all"`` 在 baseline 阶段意为 dev + locked_test（绝不读 holdout）。
    文件缺失或 JSON 不合法 → ``CommandError``（fail-closed）。
    """
    manifest_path = gold_dir / "manifest.json"
    if not manifest_path.exists():
        raise CommandError(f"gold manifest 不存在：{manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"gold manifest 读取失败：{exc}") from exc

    split_names = list(_BASELINE_SPLITS) if split == "all" else [split]
    cases: list[dict[str, Any]] = []
    splits_map = manifest.get("splits") or {}
    for name in split_names:
        rel = str(splits_map.get(name) or f"{name}.json")
        path = gold_dir / rel
        if not path.exists():
            raise CommandError(f"gold split 文件不存在：{path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"gold split 文件读取失败：{path}：{exc}") from exc
        cases.extend(data.get("cases") or [])
    return manifest, cases


def _resolve_watermarks(
    repository_id: str, branch: str, commit_sha: str
) -> dict[str, Any]:
    """按 ``(repository_id, branch)`` 解析三方水位（同步 ORM，调用方经 sync_to_async）。

    - ``index_built_at_sha`` ← ``RepositoryBranchIndex.last_indexed_commit_sha``；
      无该分支行则仓级兜底 ``Repository.last_indexed_commit_sha``。
    - ``head_sha`` ← 分支行 ``head_sha``（供与 ``--commit-sha`` 一致性校验）。
    - ``process_built_at_sha`` ← 该仓该分支任一 ``ProcessTrace.built_at_sha``（无则 None）。

    仓库不存在时 ``repository_found=False``，其余字段置 None（fail-closed → INVALID）。
    """
    from repositories.models import Repository, RepositoryBranchIndex

    repo = Repository.objects.filter(id=repository_id).first()
    if repo is None:
        return {
            "repository_found": False,
            "effective_branch": branch,
            "index_built_at_sha": None,
            "head_sha": None,
            "process_built_at_sha": None,
            "index_key_source": "last_indexed_commit_sha",
        }

    # branch="" = base 分支：解析到实际分支名以命中 RepositoryBranchIndex 行。
    effective_branch = branch or repo.base_branch or repo.default_branch or ""
    branch_index = None
    if effective_branch:
        branch_index = RepositoryBranchIndex.objects.filter(
            repository_id=repository_id, branch_name=effective_branch
        ).first()

    if branch_index is not None:
        index_built_at_sha = branch_index.last_indexed_commit_sha
        head_sha = branch_index.head_sha
    else:
        index_built_at_sha = repo.last_indexed_commit_sha
        head_sha = None

    from codegraph.models import ProcessTrace

    process_built_at_sha = (
        ProcessTrace.objects.filter(repository_id=repository_id, branch_name=branch)
        .exclude(built_at_sha="")
        .values_list("built_at_sha", flat=True)
        .first()
    )

    return {
        "repository_found": True,
        "effective_branch": effective_branch,
        "index_built_at_sha": index_built_at_sha,
        "head_sha": head_sha,
        "process_built_at_sha": process_built_at_sha,
        "index_key_source": "last_indexed_commit_sha",
    }


def _load_process_candidates(repository_id: str, branch: str) -> list[dict[str, Any]]:
    """读取 ProcessTrace 的最小测量投影；不修改事实源。"""
    from codegraph.models import ProcessTrace

    branch_filter = ["", branch] if branch else [""]
    rows = ProcessTrace.objects.filter(
        repository_id=repository_id,
        branch_name__in=branch_filter,
    ).values("process_key", "steps")
    return [
        {
            "process_key": str(row["process_key"]),
            "step_symbol_uids": [
                str(step.get("symbol_id") or "")
                for step in (row["steps"] or [])
                if step.get("symbol_id")
            ],
        }
        for row in rows
    ]


def _load_predicted_edges(
    repository_id: str,
    branch: str,
    caller_uids: set[str],
) -> list[dict[str, str]]:
    """按独立 gold 的 caller 范围读取预测侧 resolved CallEdge。"""
    if not caller_uids:
        return []

    from codegraph.models import CallEdge

    branch_filter = ["", branch] if branch else [""]
    rows = CallEdge.objects.filter(
        repository_id=repository_id,
        branch_name__in=branch_filter,
        caller_symbol_id__in=caller_uids,
        callee_symbol_id__isnull=False,
    ).values_list("caller_symbol_id", "callee_symbol_id")
    return [
        {"caller_uid": str(caller_uid), "callee_uid": str(callee_uid)}
        for caller_uid, callee_uid in rows
    ]


class Command(BaseCommand):
    help = "v0.22 图查询能力 benchmark（冻结 gold + 水位闸 fail-closed + 无阈值 baseline）"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--repo", required=True, help="repository_id（评测目标仓）")
        parser.add_argument("--branch", default="", help="分支名；空串 = base 分支")
        parser.add_argument(
            "--commit-sha", required=True, help="源码 checkout sha（须与分支 head 对齐）"
        )
        parser.add_argument(
            "--split",
            default="all",
            choices=["dev", "locked_test", "all", "holdout"],
            help="评测切分；all = dev + locked_test；holdout 保留 Phase 140，baseline 拒读",
        )
        parser.add_argument(
            "--gold",
            default=str(_DEFAULT_GOLD),
            help="冻结 gold 数据集目录（含 manifest.json 与各 split 文件）",
        )
        parser.add_argument("--output-manifest", default="", help="run manifest 输出路径")
        parser.add_argument("--output-json", default="", help="无阈值 baseline JSON 输出路径")
        parser.add_argument(
            "--cold-only", action="store_true", help="只测冷延迟，跳过热跑（缓存命中）"
        )
        parser.add_argument(
            "--min-bucket-samples",
            type=int,
            default=3,
            help="稀疏桶样本下限（低于此值标 INSUFFICIENT_DATA）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        split = options["split"]
        if split == "holdout":
            # holdout 保留给 Phase 140 最终验收，baseline 阶段拒绝读取（CONTEXT 硬约束）。
            raise CommandError(
                "holdout 切分保留给 Phase 140 最终验收，baseline 阶段拒绝读取"
            )

        gold_dir = Path(options["gold"])
        manifest, cases = _load_gold(gold_dir, split)
        try:
            dataset = validate_gold_dataset(manifest, cases)
        except ValueError as exc:
            raise CommandError(f"gold 数据集 schema 校验失败：{exc}") from exc

        asyncio.run(self._arun(options, dataset, manifest))

    async def _arun(
        self, options: dict[str, Any], dataset: Any, manifest: dict[str, Any]
    ) -> None:
        repository_id = str(options["repo"])
        branch = str(options["branch"])
        commit_sha = str(options["commit_sha"])
        split = str(options["split"])
        run_id = str(uuid.uuid4())
        started = time.monotonic()
        started_at = timezone.now().isoformat()
        reproducible = self._reproducible_command(options)

        watermarks = await sync_to_async(_resolve_watermarks)(
            repository_id, branch, commit_sha
        )

        identity = build_run_identity(
            repository=repository_id,
            branch=branch,
            commit_sha=commit_sha,
            index_key=str(watermarks["index_built_at_sha"] or ""),
            gold_version=dataset.gold_version,
            index_key_source="last_indexed_commit_sha",
        )

        watermark = validate_watermark(
            index_built_at_sha=watermarks["index_built_at_sha"],
            gold_annotated_at_sha=dataset.annotated_at_sha,
            source_checkout_sha=commit_sha,
            process_built_at_sha=watermarks["process_built_at_sha"],
        )

        invalid_reasons: list[str] = []
        if not watermarks["repository_found"]:
            invalid_reasons.append(f"repository 不存在：{repository_id}")
        if watermark == "INVALID":
            invalid_reasons.append(
                "三方水位不一致或为空（index_built_at_sha / gold_annotated_at_sha / "
                "source_checkout_sha 须非空且全相等）"
            )
        head_sha = watermarks["head_sha"]
        if head_sha and head_sha != commit_sha:
            watermark = "INVALID"
            invalid_reasons.append(
                f"分支 head_sha（{head_sha}）与 --commit-sha（{commit_sha}）不一致"
            )

        if watermark == "INVALID":
            # 水位闸 fail-closed：写 manifest 含 invalid_reason，非零退出；⛔ 绝不调用
            # get_graph 或任何被测能力、绝不跑任何 case（BENCH-01）。
            invalid_reason = "；".join(invalid_reasons) or "水位校验失败"
            self._write_manifest(
                options,
                identity=identity.to_dict(),
                watermark="INVALID",
                invalid_reason=invalid_reason,
                watermarks=watermarks,
                run_id=run_id,
                split=split,
                reproducible=reproducible,
                started_at=started_at,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            try:
                logger.info(
                    "graph_bench_run_invalid",
                    run_id=run_id,
                    repository=repository_id,
                    branch=branch,
                    commit_sha=commit_sha,
                    gold_version=dataset.gold_version,
                    split=split,
                    index_built_at_sha=watermarks["index_built_at_sha"],
                    gold_annotated_at_sha=dataset.annotated_at_sha,
                    source_checkout_sha=commit_sha,
                    process_built_at_sha=watermarks["process_built_at_sha"],
                    invalid_reason=invalid_reason,
                    **_LOG_KV,
                )
            except Exception:  # noqa: BLE001 — 观测 best-effort
                pass
            raise CommandError(f"水位校验 INVALID：{invalid_reason}")

        # OK 路径：逐 case 真跑被测能力（Task 2 填充）。
        try:
            logger.info(
                "graph_bench_run_started",
                run_id=run_id,
                repository=repository_id,
                branch=branch,
                commit_sha=commit_sha,
                gold_version=dataset.gold_version,
                split=split,
                **_LOG_KV,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass

        try:
            outcomes = await self._run_all_cases(
                dataset,
                repository_id=repository_id,
                branch=branch,
                run_id=run_id,
                cold_only=bool(options["cold_only"]),
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            try:
                logger.error(
                    "graph_bench_run_failed",
                    run_id=run_id,
                    repository=repository_id,
                    branch=branch,
                    commit_sha=commit_sha,
                    split=split,
                    duration_ms=duration_ms,
                    error=redact_secrets_in_text(str(exc))[:200],
                    **_LOG_KV,
                )
            except Exception:  # noqa: BLE001 — 观测 best-effort
                pass
            raise

        report = build_report(
            identity=identity,
            watermark="OK",
            split=split,
            cases=outcomes,
            min_samples=int(options["min_bucket_samples"]),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        payload = {
            **report,
            "run_id": run_id,
            "duration_ms": duration_ms,
            "reproducible_command": reproducible,
        }

        self._write_manifest(
            options,
            identity=identity.to_dict(),
            watermark="OK",
            invalid_reason="",
            watermarks=watermarks,
            run_id=run_id,
            split=split,
            reproducible=reproducible,
            started_at=started_at,
            duration_ms=duration_ms,
        )
        if options["output_json"]:
            Path(options["output_json"]).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.stdout.write(f"baseline 已写入 {options['output_json']}")

        self._print(report, run_id, duration_ms)

        try:
            logger.info(
                "graph_bench_run_completed",
                run_id=run_id,
                repository=repository_id,
                branch=branch,
                commit_sha=commit_sha,
                split=split,
                total_cases=report.get("total_cases", 0),
                duration_ms=duration_ms,
                **_LOG_KV,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass

    async def _run_all_cases(
        self,
        dataset: Any,
        *,
        repository_id: str,
        branch: str,
        run_id: str,
        cold_only: bool,
    ) -> list[Any]:
        """逐 case 串行跑被测能力并折算（Task 2 填充编排）。

        串行沿袭 recall command：并发只会撞上游限流且让延迟数字失真。
        """
        return [
            await self._run_case(
                gold,
                repository_id=repository_id,
                branch=branch,
                run_id=run_id,
                cold_only=cold_only,
            )
            for gold in dataset.cases
        ]

    async def _run_case(
        self,
        gold: Any,
        *,
        repository_id: str,
        branch: str,
        run_id: str,
        cold_only: bool,
    ) -> Any:
        """单 case 串行编排 v0.22 只读能力并折算为 CaseOutcome。"""
        from services.code_graph import get_graph_service, invalidate_repository
        from services.code_graph.impact import analyze_impact
        from services.code_graph.symbol_resolve import resolve_symbol_in_graph
        from services.code_graph.trace import trace_path
        from services.retrieval.rag_search import search_rag

        started = time.monotonic()
        cold_ms = 0
        warm_ms = 0
        try:
            await sync_to_async(invalidate_repository)(repository_id)
            service = get_graph_service()

            cold_started = time.monotonic()
            code_graph = await service.get_graph(repository_id, branch, user=None)
            cold_ms = int((time.monotonic() - cold_started) * 1000)

            if not cold_only:
                warm_started = time.monotonic()
                code_graph = await service.get_graph(repository_id, branch, user=None)
                warm_ms = int((time.monotonic() - warm_started) * 1000)

            snapshot = await search_rag(
                gold.query,
                repo_ids=[repository_id],
                branch_name=branch or None,
                top_k=30,
            )
            predicted_symbol_uids: list[str] = []
            for item in snapshot.items:
                payload = item.get("payload") or {}
                uid = (
                    payload.get("symbol_uid")
                    or payload.get("symbol_id")
                    or payload.get("uid")
                )
                if uid:
                    resolved = resolve_symbol_in_graph(
                        code_graph.graph,
                        symbol_id=str(uid),
                    )
                    if resolved.resolved and str(uid) not in predicted_symbol_uids:
                        predicted_symbol_uids.append(str(uid))

            candidate_processes = await sync_to_async(_load_process_candidates)(
                repository_id, branch
            )
            callers = {
                str(edge.get("caller_uid") or "")
                for edge in gold.edge_golds
                if edge.get("caller_uid")
            }
            predicted_edges = await sync_to_async(_load_predicted_edges)(
                repository_id, branch, callers
            )

            impact_result: dict[str, Any] = {
                "seed_in_graph": True,
                "affected_uids": [],
            }
            if gold.impact_golds:
                seed_uid = str(gold.impact_golds[0].get("seed_uid") or "")
                raw_impact = analyze_impact(code_graph.graph, seed_uid)
                impact_result = {
                    "seed_in_graph": bool(raw_impact.get("seed_in_graph", False)),
                    "affected_uids": [
                        str(item.get("symbol_id") or "")
                        for item in (raw_impact.get("items") or [])
                        if item.get("symbol_id")
                    ],
                }

            trace_results = [
                trace_path(
                    code_graph.graph,
                    str(trace_gold.get("source_uid") or ""),
                    str(trace_gold.get("target_uid") or ""),
                )
                for trace_gold in gold.trace_golds
            ]
            outcome = evaluate_case(
                gold=gold,
                predicted_symbol_uids=predicted_symbol_uids,
                candidate_processes=candidate_processes,
                predicted_edges=predicted_edges,
                impact_result=impact_result,
                trace_results=trace_results,
                cold_ms=cold_ms,
                warm_ms=warm_ms,
                tokens=0,
            )
        except Exception as exc:  # 单 case 失败不反噬整轮
            outcome = evaluate_case(
                gold=gold,
                predicted_symbol_uids=[],
                candidate_processes=[],
                predicted_edges=[],
                impact_result={},
                trace_results=[],
                cold_ms=cold_ms,
                warm_ms=warm_ms,
                tokens=0,
                error=f"{type(exc).__name__}: {redact_secrets_in_text(str(exc))[:200]}",
            )

        try:
            logger.debug(
                "graph_bench_case_scored",
                run_id=run_id,
                case_id=gold.case_id,
                language=gold.language,
                framework=gold.framework,
                entry_type=gold.entry_type,
                symbol_recall=outcome.symbol_recall,
                duration_ms=int((time.monotonic() - started) * 1000),
                category="sampling",
                component="codegraph",
                initiated_by_user_id="system",
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass
        return outcome

    def _reproducible_command(self, options: dict[str, Any]) -> str:
        """拼一条可复现命令行（供 Phase 140 同条件对比复用，BENCH-01）。"""
        parts = [
            "python manage.py evaluate_graph_bench",
            f"--repo {options['repo']}",
            f"--branch {options['branch']}",
            f"--commit-sha {options['commit_sha']}",
            f"--split {options['split']}",
            f"--gold {options['gold']}",
            f"--min-bucket-samples {options['min_bucket_samples']}",
        ]
        if options["cold_only"]:
            parts.append("--cold-only")
        return " ".join(parts)

    def _write_manifest(
        self,
        options: dict[str, Any],
        *,
        identity: dict[str, Any],
        watermark: str,
        invalid_reason: str,
        watermarks: dict[str, Any],
        run_id: str,
        split: str,
        reproducible: str,
        started_at: str,
        duration_ms: int,
    ) -> None:
        """写 run manifest（identity 五元组 + index_key_source + 三方水位输入与校验结果
        + run_id + 可复现命令行），供 Phase 140 同条件对比复用（BENCH-01）。"""
        payload = {
            "run_id": run_id,
            "identity": identity,
            "watermark": watermark,
            "invalid_reason": invalid_reason,
            "split": split,
            "watermark_inputs": {
                "index_built_at_sha": watermarks["index_built_at_sha"],
                "head_sha": watermarks["head_sha"],
                "process_built_at_sha": watermarks["process_built_at_sha"],
                "effective_branch": watermarks["effective_branch"],
            },
            "reproducible_command": reproducible,
            "started_at": started_at,
            "duration_ms": duration_ms,
        }
        output = str(options.get("output_manifest") or "")
        if output:
            Path(output).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.stdout.write(f"run manifest 已写入 {output}")

    def _print(self, report: dict[str, Any], run_id: str, duration_ms: int) -> None:
        """CLI 输出：total_cases + overall 各指标 + INSUFFICIENT_DATA / 受保护桶清单。"""
        w = self.stdout.write
        overall = report.get("overall") or {}
        w("=" * 78)
        w(f"v0.22 图查询 baseline：{report.get('total_cases', 0)} 条 case，"
          f"run_id={run_id}，耗时 {duration_ms}ms")
        w("=" * 78)
        for metric, value in overall.items():
            w(f"  {metric:<22}: {value}")
        insufficient = report.get("insufficient_buckets") or []
        if insufficient:
            w("-" * 78)
            w(f"  INSUFFICIENT_DATA 桶（{len(insufficient)}，样本不足不进 overall）：")
            for bucket in insufficient:
                key = bucket.get("key") or {}
                w(f"    n={bucket.get('n')} "
                  f"{key.get('language')}/{key.get('framework')}/{key.get('entry_type')}")
        protected = report.get("protected_buckets") or []
        if protected:
            w("-" * 78)
            w(f"  受保护桶（{len(protected)}，单列不被 overall 抵消）：")
            for bucket in protected:
                key = bucket.get("key") or {}
                w(f"    n={bucket.get('n')} "
                  f"{key.get('language')}/{key.get('framework')}/{key.get('entry_type')}")
