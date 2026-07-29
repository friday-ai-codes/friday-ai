"""统计全仓 repo_index_nodes 能力树节点数分布（O-1）与 dense 余弦可得性验证（O-3）。

Phase 105 success criterion 5：Phase 106 公式定版（MaxP 主干口径、pivoted size
normalization 常数 N̄/b）的一次性输入实测命令。

- O-1：按仓 exact count 统计 N_r 分布（p50/p90/p99/max/mean/median + top-N 倾斜表）。
- O-3：``--verify-cosine`` 对任一有索引仓发一次 dense-only 查询（``using="dense"``，
  collection 距离为 COSINE），打印返回 score 样例与耗时 ms，确证「余弦需单独
  dense 查询可得 + 延迟代价」。注意 ``QdrantService.search_by_name`` 查询的是
  匿名默认向量，对 hybrid collection（命名向量 dense/sparse）不可用，故本命令
  直接以 ``using="dense"`` 发 query_points。

CLI 用例
========

::

    python manage.py measure_repo_index_stats --json --top 20 --verify-cosine

必须在有真实索引的部署实例上执行才能产出有意义的 N_r 分布；本地开发库
跑出的全 0 结果不得写入 105-MEASUREMENTS.md。
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

import structlog
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "repo_index_nodes"

_EVENT_STARTED = "measure_repo_index_stats_started"
_EVENT_COMPLETED = "measure_repo_index_stats_completed"
_EVENT_FAILED = "measure_repo_index_stats_failed"
_EVENT_REPO_COUNT_FAILED = "measure_repo_index_stats_repo_count_failed"

# management command 由运维手动触发，无请求上下文——initiated_by 语义标 system。
_LOG_KV = {"category": "caller", "component": "codegraph", "initiated_by": "system"}


def _compute_stats(counts: list[int]) -> dict[str, Any]:
    """N_r 分位数统计（stdlib statistics，禁 numpy/scipy）。

    ROUTING-RANKING §2.3：N̄ 建议用中位数，故 median 单列。
    """
    if not counts:
        return {"p50": 0, "p90": 0, "p99": 0, "max": 0, "mean": 0.0, "median": 0}
    if len(counts) == 1:
        value = counts[0]
        return {
            "p50": value,
            "p90": value,
            "p99": value,
            "max": value,
            "mean": float(value),
            "median": value,
        }
    quantiles = statistics.quantiles(counts, n=100)  # quantiles[i] 即第 i+1 百分位
    return {
        "p50": quantiles[49],
        "p90": quantiles[89],
        "p99": quantiles[98],
        "max": max(counts),
        "mean": statistics.fmean(counts),
        "median": statistics.median(counts),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    """人读输出：指标/值 markdown 表 + top-N 倾斜表。"""
    lines = [
        "## repo_index_nodes N_r 分布（O-1）",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        f"| 总仓数（is_deleted=False） | {report['total_repos']} |",
        f"| 成功计数仓数 | {report['counted_repos']} |",
        f"| 有索引仓数（N_r > 0） | {report['indexed_repos']} |",
        f"| p50 | {report['p50']} |",
        f"| p90 | {report['p90']} |",
        f"| p99 | {report['p99']} |",
        f"| max | {report['max']} |",
        f"| mean | {report['mean']} |",
        f"| median（N̄ 建议口径） | {report['median']} |",
        "",
        f"## 节点数 Top-{len(report['top'])}（monorepo 倾斜确认）",
        "",
        "| 仓库 | N_r |",
        "|------|-----|",
    ]
    for row in report["top"]:
        lines.append(f"| {row['name']} | {row['node_count']} |")
    probe = report.get("cosine_probe")
    if probe is not None:
        lines += [
            "",
            "## dense 余弦可得性（O-3 verify）",
            "",
            f"- status: {probe['status']}",
        ]
        if probe["status"] == "ok":
            lines += [
                f"- probe_repo: {probe['repository_name']}",
                f"- dense-only 查询耗时: {probe['duration_ms']} ms",
                f"- 返回 score 样例（COSINE）: {probe['scores']}",
            ]
        else:
            lines.append(f"- reason: {probe.get('reason', '')}")
        lines += [
            "",
            "说明：hybrid_search_by_name 的 FusionQuery(RRF) 返回分是融合分，"
            "不含 per-prefetch dense 余弦；取余弦须单独发一次 dense-only 查询"
            '（query_points 带 using="dense"）。',
        ]
    return "\n".join(lines)


class Command(BaseCommand):
    help = (
        "统计全仓 repo_index_nodes 节点数分布（O-1 直方图）"
        "并可选验证 dense 余弦可得性（O-3）——Phase 106 公式定版输入实测"
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="输出机器可读 JSON（供转写 105-MEASUREMENTS.md）",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="打印节点数最多的 N 个仓（默认 10），确认 monorepo 倾斜程度",
        )
        parser.add_argument(
            "--verify-cosine",
            action="store_true",
            dest="verify_cosine",
            help="对任一有索引仓发一次 dense-only 查询，验证余弦分可得性与延迟（O-3）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from repositories.models import Repository
        from services.qdrant_service import QdrantService

        start = time.monotonic()
        repos = list(Repository.objects.filter(is_deleted=False).only("id", "name"))
        logger.info(_EVENT_STARTED, repo_count=len(repos), **_LOG_KV)

        try:
            client = QdrantService.get_client()
            per_repo = self._count_per_repo(client, repos)

            counts = [row["node_count"] for row in per_repo]
            top_n = sorted(per_repo, key=lambda row: (-row["node_count"], row["repository_id"]))[
                : max(int(options["top"]), 0)
            ]

            report: dict[str, Any] = {
                "collection": COLLECTION_NAME,
                "total_repos": len(repos),
                "counted_repos": len(per_repo),
                "indexed_repos": sum(1 for c in counts if c > 0),
                **_compute_stats(counts),
                "top": top_n,
                "per_repo": per_repo,
            }
            if options["verify_cosine"]:
                report["cosine_probe"] = self._verify_cosine(client, per_repo)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start) * 1000)
            logger.error(_EVENT_FAILED, error=str(exc), duration_ms=duration_ms, **_LOG_KV)
            raise

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            _EVENT_COMPLETED,
            repo_count=len(repos),
            indexed_repos=report["indexed_repos"],
            duration_ms=duration_ms,
            **_LOG_KV,
        )

        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(_render_markdown(report))

    def _count_per_repo(self, client: Any, repos: list[Any]) -> list[dict[str, Any]]:
        """按仓 exact count；单仓异常 warning 跳过，不中断全量统计（best-effort）。"""
        from qdrant_client import models

        per_repo: list[dict[str, Any]] = []
        for repo in repos:
            try:
                result = client.count(
                    collection_name=COLLECTION_NAME,
                    count_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="repository_id",
                                match=models.MatchValue(value=str(repo.id)),
                            )
                        ]
                    ),
                    exact=True,
                )
                per_repo.append(
                    {
                        "repository_id": str(repo.id),
                        "name": repo.name,
                        "node_count": int(result.count),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — best-effort，观测不反噬统计
                logger.warning(
                    _EVENT_REPO_COUNT_FAILED,
                    repository_id=str(repo.id),
                    repository_name=repo.name,
                    error=str(exc),
                    **_LOG_KV,
                )
        return per_repo

    def _verify_cosine(self, client: Any, per_repo: list[dict[str, Any]]) -> dict[str, Any]:
        """O-3 验证：对任一有索引仓发一次 dense-only 查询，取余弦 score 样例与耗时。

        用该仓任一现存点的 dense 向量做自查询（top-1 预期余弦 ≈ 1.0），最直接地
        确证返回分就是 COSINE 相似度而非 RRF 融合分。
        """
        from qdrant_client import models

        indexed = [row for row in per_repo if row["node_count"] > 0]
        if not indexed:
            return {"status": "skipped", "reason": "no_indexed_repo"}

        probe_repo = indexed[0]
        try:
            points, _offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="repository_id",
                            match=models.MatchValue(value=probe_repo["repository_id"]),
                        )
                    ]
                ),
                limit=1,
                with_payload=False,
                with_vectors=["dense"],
            )
            if not points:
                return {"status": "skipped", "reason": "scroll_returned_no_points"}
            vector = points[0].vector
            dense_vector = vector.get("dense") if isinstance(vector, dict) else vector
            if not dense_vector:
                return {"status": "skipped", "reason": "point_has_no_dense_vector"}

            query_start = time.monotonic()
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=list(dense_vector),
                using="dense",
                limit=3,
                with_payload=False,
            )
            query_ms = int((time.monotonic() - query_start) * 1000)
            return {
                "status": "ok",
                "repository_id": probe_repo["repository_id"],
                "repository_name": probe_repo["name"],
                "duration_ms": query_ms,
                "scores": [round(float(p.score), 6) for p in results.points],
                "note": (
                    "scores 为 dense COSINE 相似度（自查询 top-1 预期 ≈ 1.0）；"
                    "hybrid_search_by_name 的 FusionQuery(RRF) 融合分不含此值，"
                    '取余弦须单独 dense-only 查询（using="dense"）'
                ),
            }
        except Exception as exc:  # noqa: BLE001 — 验证失败不影响 O-1 主统计
            logger.warning(
                "measure_repo_index_stats_cosine_probe_failed", error=str(exc), **_LOG_KV
            )
            return {"status": "failed", "reason": str(exc)}
