"""统计全仓 repo_index_nodes 能力树节点数分布（O-1）与 dense 余弦可得性验证（O-3）。

Phase 105 success criterion 5：Phase 106 公式定版（MaxP 主干口径、pivoted size
normalization 常数 N̄/b）的一次性输入实测命令。Phase 106-04 扩展 O-5 统计与
N_r 快照写入。

- O-1：按仓 exact count 统计 N_r 分布（p50/p90/p99/max/mean/median + top-N 倾斜表）。
- O-3：``--verify-cosine`` 对任一有索引仓发一次 dense-only 查询（``using="dense"``，
  collection 距离为 COSINE），打印返回 score 样例与耗时 ms，确证「余弦需单独
  dense 查询可得 + 延迟代价」。注意 ``QdrantService.search_by_name`` 查询的是
  匿名默认向量，对 hybrid collection（命名向量 dense/sparse）不可用，故本命令
  直接以 ``using="dense"`` 发 query_points。
- O-5（106-04）：``--activity`` 输出全仓 ``last_commit_at`` 口径（FileIndex
  按仓 Max(last_commit_authored_at)）覆盖率与新鲜度分位数 p50/p90，以及
  facets 五维覆盖率——覆盖不足的仓在打分侧自动走枚举回退（ROUTE-05）。
- N_r 快照（106-04）：``--write-snapshot`` 把 per-repo 计数 + N̄ 中位数写入
  SystemSetting ``repo_router.nr_snapshot``（ROUTE-03 数据管线）——router
  （106-06）据此计算 pivoted breadth 而不逐次 count。

CLI 用例
========

::

    python manage.py measure_repo_index_stats --json --top 20 --verify-cosine
    python manage.py measure_repo_index_stats --activity --write-snapshot

必须在有真实索引的部署实例上执行才能产出有意义的 N_r 分布；本地开发库
跑出的全 0 结果不得写入 105/106-MEASUREMENTS.md。
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import UTC, datetime
from typing import Any

import structlog
from django.core.management.base import BaseCommand

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "repo_index_nodes"

_EVENT_STARTED = "measure_repo_index_stats_started"
_EVENT_COMPLETED = "measure_repo_index_stats_completed"
_EVENT_FAILED = "measure_repo_index_stats_failed"
_EVENT_REPO_COUNT_FAILED = "measure_repo_index_stats_repo_count_failed"
_EVENT_ACTIVITY_COMPLETED = "measure_activity_stats_completed"
_EVENT_SNAPSHOT_WRITTEN = "nr_snapshot_written"

# management command 由运维手动触发，无请求上下文——按 LOGGING-SPEC 字段名
# initiated_by_user_id 标 system（无触发用户记 system）。
_LOG_KV = {
    "category": "caller",
    "component": "codegraph",
    "initiated_by_user_id": "system",
}


def _compute_stats(counts: list[int]) -> dict[str, Any]:
    """N_r 分位数统计（stdlib statistics，禁第三方数值库）。

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


def _quantile(sorted_vals: list[float], q: float) -> float:
    """线性插值分位数（与 repo_router_eval._quantile 同口径；stdlib，禁第三方数值库）。

    ``sorted_vals`` 必须已升序且非空。
    """
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


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
    activity = report.get("activity_stats")
    if activity is not None:
        lines += [
            "",
            "## last_commit_at 覆盖率与新鲜度（O-5 --activity）",
            "",
            "| 指标 | 值 |",
            "|------|-----|",
            f"| 总仓数（is_deleted=False） | {activity['total_repos']} |",
            f"| last_commit_at 有值仓数 | {activity['covered_repos']} |",
            f"| 覆盖率 | {activity['coverage']} |",
            f"| 新鲜度 p50（距 now 天数） | {activity['freshness_days_p50']} |",
            f"| 新鲜度 p90（距 now 天数） | {activity['freshness_days_p90']} |",
        ]
    facets_coverage = report.get("facets_coverage")
    if facets_coverage is not None:
        lines += [
            "",
            "## facets 五维覆盖率（O-5 --activity）",
            "",
            "| facet | 非空仓数 | 总仓数 | 覆盖率 |",
            "|-------|---------|--------|--------|",
        ]
        for dim, row in facets_coverage.items():
            lines.append(f"| {dim} | {row['covered']} | {row['total']} | {row['ratio']} |")
    snapshot = report.get("nr_snapshot")
    if snapshot is not None:
        lines += ["", "## N_r 快照写入（--write-snapshot）", ""]
        if snapshot.get("written"):
            lines.append(
                f"- 已写入 SystemSetting repo_router.nr_snapshot：n_bar（中位数）= {snapshot['n_bar']}，"
                f"仓数 {snapshot['repo_count']}（其中有索引 {snapshot['indexed_repos']}）"
            )
        else:
            lines.append("- 未写入：无任何已索引仓（N_r 全 0），拒绝用空快照覆盖既有值")
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
        parser.add_argument(
            "--activity",
            action="store_true",
            dest="activity",
            help="O-5：全仓 last_commit_at 覆盖率/新鲜度分位数（p50/p90）+ facets 五维覆盖率",
        )
        parser.add_argument(
            "--write-snapshot",
            action="store_true",
            dest="write_snapshot",
            help=(
                "把 per-repo N_r 计数 + N̄ 中位数写入 SystemSetting "
                "repo_router.nr_snapshot（106-06 breadth 供数，ROUTE-03）"
            ),
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
            if options["activity"]:
                activity_stats, facets_coverage = self._collect_activity_stats()
                report["activity_stats"] = activity_stats
                report["facets_coverage"] = facets_coverage
            if options["write_snapshot"]:
                report["nr_snapshot"] = self._write_nr_snapshot(per_repo)
        except Exception as exc:
            from common.logging import redact_secrets_in_text

            duration_ms = int((time.monotonic() - start) * 1000)
            # 异常文本可能含上游（Qdrant）连接串等敏感片段——手动脱敏兜底
            logger.error(
                _EVENT_FAILED,
                error=redact_secrets_in_text(str(exc)),
                duration_ms=duration_ms,
                **_LOG_KV,
            )
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

    def _collect_activity_stats(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """O-5：last_commit_at 覆盖率/新鲜度分位数 + facets 五维覆盖率。

        - ``last_commit_at`` 口径：``FileIndex`` 按仓 ``Max(last_commit_authored_at)``
          一次聚合（全仓单条 GROUP BY 查询，不逐仓查）；覆盖率 = 有值仓数 / 总仓数；
          新鲜度 = 距 now 天数的 p50/p90（线性插值，stdlib 实现）。
        - facets 覆盖率：``业务线/产品线``（非空且非「未分类」）与
          技术栈/团队归属/关键程度/活跃度（非空）逐键统计非空占比——覆盖不足的
          仓在打分侧自动走枚举回退（ROUTE-05）。
        """
        from django.db.models import Max
        from django.utils import timezone

        # facet 键名与「未分类」哨兵复用 resolver 常量（106-03），契约由代码保证。
        from codegraph.services.repo_router_metadata import (
            FACET_ACTIVITY,
            FACET_CRITICALITY,
            FACET_DOMAIN,
            FACET_STACK,
            FACET_TEAM,
            UNCLASSIFIED_VALUE,
        )
        from repositories.models import FileIndex, Repository

        start = time.monotonic()
        repos = list(Repository.objects.filter(is_deleted=False).only("id", "facets"))
        total = len(repos)

        latest_by_repo: dict[str, Any] = {}
        rows = FileIndex.objects.values("repository_id").annotate(
            latest=Max("last_commit_authored_at")
        )
        for row in rows:
            if row["latest"] is not None:
                latest_by_repo[str(row["repository_id"])] = row["latest"]

        now = timezone.now()
        ages_days: list[float] = []
        for repo in repos:
            latest = latest_by_repo.get(str(repo.id))
            if latest is None:
                continue  # 无 FileIndex 行 / 全行无 last_commit_authored_at → 未覆盖
            ages_days.append(max((now - latest).total_seconds() / 86400.0, 0.0))
        ages_days.sort()
        covered = len(ages_days)
        activity_stats: dict[str, Any] = {
            "total_repos": total,
            "covered_repos": covered,
            "coverage": round(covered / total, 4) if total else 0.0,
            "freshness_days_p50": round(_quantile(ages_days, 0.50), 2) if ages_days else None,
            "freshness_days_p90": round(_quantile(ages_days, 0.90), 2) if ages_days else None,
        }

        facets_coverage: dict[str, Any] = {}
        for dim in (FACET_DOMAIN, FACET_STACK, FACET_TEAM, FACET_CRITICALITY, FACET_ACTIVITY):
            covered_count = 0
            for repo in repos:
                facets = repo.facets if isinstance(repo.facets, dict) else {}
                value = facets.get(dim)
                if not isinstance(value, str) or not value.strip():
                    continue
                # 语义分面 LLM 选不出时填「未分类」——视为未覆盖（Pitfall 2）。
                if dim == FACET_DOMAIN and value.strip() == UNCLASSIFIED_VALUE:
                    continue
                covered_count += 1
            facets_coverage[dim] = {
                "covered": covered_count,
                "total": total,
                "ratio": round(covered_count / total, 4) if total else 0.0,
            }

        logger.info(
            _EVENT_ACTIVITY_COMPLETED,
            total_repos=total,
            covered_repos=covered,
            duration_ms=int((time.monotonic() - start) * 1000),
            **_LOG_KV,
        )
        return activity_stats, facets_coverage

    def _write_nr_snapshot(self, per_repo: list[dict[str, Any]]) -> dict[str, Any]:
        """把 per-repo N_r 计数组装为快照写入 SystemSetting（ROUTE-03 数据管线）。

        值形状与 ``repo_router_config.load_nr_snapshot`` 读取端契约对齐：
        ``{"n_r_by_repo": {rid: int}, "n_bar": float, "generated_at": iso}``。
        N̄ 取有索引仓（node_count > 0）的**中位数**而非均值——monorepo 会拉爆
        均值（ROUTING-RANKING §2.3 N̄ 行）。
        """
        from system.models import SettingKeys, SystemSetting

        start = time.monotonic()
        indexed_counts = [row["node_count"] for row in per_repo if row["node_count"] > 0]
        if not indexed_counts:
            # 防空快照覆盖有效值：本地空库 / Qdrant 无数据时拒绝写入（T-106-09）。
            return {"written": False, "reason": "no_indexed_repo"}

        n_bar = float(statistics.median(indexed_counts))
        snapshot = {
            "n_r_by_repo": {row["repository_id"]: row["node_count"] for row in per_repo},
            "n_bar": n_bar,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        # SystemSetting post_save signal（system/signals.py）自动失效 settings_service
        # 读缓存——写入后 router 下一次路由经 load_nr_snapshot 即读到新值，无需发版/重启。
        SystemSetting.objects.update_or_create(
            key=SettingKeys.REPO_ROUTER_NR_SNAPSHOT,
            defaults={
                "value": json.dumps(snapshot, ensure_ascii=False),
                "is_encrypted": False,
                "description": (
                    "repo router N_r/N̄ 快照（measure_repo_index_stats --write-snapshot 写入，"
                    "106-06 pivoted breadth 供数）"
                ),
            },
        )
        logger.info(
            _EVENT_SNAPSHOT_WRITTEN,
            n_bar=n_bar,
            repo_count=len(snapshot["n_r_by_repo"]),
            indexed_repos=len(indexed_counts),
            duration_ms=int((time.monotonic() - start) * 1000),
            **_LOG_KV,
        )
        return {
            "written": True,
            "n_bar": n_bar,
            "repo_count": len(snapshot["n_r_by_repo"]),
            "indexed_repos": len(indexed_counts),
        }

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
