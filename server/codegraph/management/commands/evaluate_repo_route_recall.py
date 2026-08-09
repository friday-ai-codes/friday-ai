"""端到端仓库路由召回评测 command —— 真跑 embedding + Qdrant + LLM 的 Recall@k。

与既有离线 golden 门禁（``evaluate_blueprint_golden`` /
``test_repo_router_golden``）**互补而非重复**：那套 case 内联 ``node_hits``、零网络，
测的是「给定候选池之后排序对不对」；本命令测的是「**该进候选池的仓有没有进来**」。
两者缺一不可——``_QUERY_CHAR_BUDGET=4000`` 那个把召回压死两个月的缺陷，离线门禁
在结构上就看不见（详见 ``codegraph.services.repo_route_recall_eval`` 模块 docstring）。

口径（读数字前必须知道）
========================

- **打真实上游**：每条 case 会发 embedding、Qdrant、以及 Stage 1 的 LLM 调用，
  有网络与 token 成本。故不进默认 pytest 套件（``--disable-socket`` 下必失败），
  由运维/CI 定时任务显式执行。
- **每条 case 跑两次 route**：``use_llm=False`` 取检索层与聚合层，``use_llm=True``
  取最终层。走的都是生产 ``RepoRouterV2.route``，**不复刻任何管线逻辑**，杜绝
  评测与生产漂移。
- **Stage 1 有输入哈希缓存**：同输入重复跑会命中缓存、零 LLM 调用。要测真实
  LLM 波动请配合 ``--repeat`` 并接受首轮之外可能是缓存命中（本命令不旁路缓存，
  因为缓存命中本身就是生产行为）。
- **只读**：不写任何业务表。

标注来源
========

- ``--from-associations``：取 ``RepoAssociation`` 中 ``confirmed`` / ``verified``
  的人工确认结果作为 ground truth。这是**自我补充**的标注源——每次有人在关联面板
  上确认一次仓库集，评测集就长一条，不需要单独维护标注文件。
- ``--fixtures``：JSON 文件，用于合成回归 case（如「用户贴了 3 万字长文本」这种
  真实业务里不常见、但必须永不回归的场景）。

CLI 用例
========

::

    # 用人工确认的关联做标注，跑全部 case
    python manage.py evaluate_repo_route_recall --from-associations

    # 跑固定回归 case 并与基线比对（回退即非零退出）
    python manage.py evaluate_repo_route_recall \\
        --fixtures tests/fixtures/repo_route_recall/cases.json \\
        --baseline tests/fixtures/repo_route_recall/baseline.json

    # 生成/刷新基线
    python manage.py evaluate_repo_route_recall --from-associations \\
        --output-json /tmp/recall.json --write-baseline tests/fixtures/repo_route_recall/baseline.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import structlog
from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError

from codegraph.services.repo_route_recall_eval import (
    CaseOutcome,
    aggregate_report,
    compare_to_baseline,
    evaluate_case,
)

logger = structlog.get_logger(__name__)

_LOG_KV = {
    "category": "caller",
    "component": "repo_router_v2",
    "initiated_by_user_id": "system",
}

_DEFAULT_FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "tests" / "fixtures" / "repo_route_recall" / "cases.json"
)


def _repo_ids_from_hits(node_hits: Any) -> list[str]:
    """从 snapshot 的 stage0.node_hits 抽出去重后的仓 id（保序）。"""
    out: list[str] = []
    seen: set[str] = set()
    for hit in node_hits or []:
        payload = hit.get("payload") if isinstance(hit, dict) else None
        rid = str((payload or {}).get("repository_id") or "")
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


async def _build_project_query(project_id: str) -> str:
    """用生产 service 把项目 feature list 拼成选仓 query（与 propose 同口径）。"""
    from initiatives.services.feature_list_service import FeatureListService
    from initiatives.services.repo_association_service import RepoAssociationService

    tree = await FeatureListService().build_tree(project_id)
    flat: list[dict[str, Any]] = []
    for module in tree.get("modules", []):
        module_name = str(module.get("module") or "")
        for feature in module.get("features") or []:
            name = str(feature.get("name") or "").strip()
            if not name:
                continue
            description = str(feature.get("source") or "").strip() or " ".join(
                str(a) for a in (feature.get("acceptance") or [])
            )
            flat.append(
                {"module": module_name, "name": name, "description": description}
            )
    return RepoAssociationService._build_query(flat)


@sync_to_async
def _space_repository_ids(space_id: str) -> list[str] | None:
    from projects.models import Space

    space = Space.objects.filter(id=space_id).first()
    if space is None:
        return None
    return [str(r) for r in space.repositories.values_list("id", flat=True)] or None


async def _run_case(case: dict[str, Any], *, top_k: int) -> CaseOutcome:
    """跑单条 case：两次生产 route 取三层，折算成 CaseOutcome。"""
    from codegraph.services.repo_router_v2 import STAGE0_REPO_K, RepoRouterV2
    from services.query_embedding import embed_query

    case_id = str(case.get("id") or "unnamed")
    corpus_kind = str(case.get("corpus_kind") or "conversation")
    expected = [str(r) for r in (case.get("expected_repos") or [])]
    repo_ids = [str(r) for r in (case.get("repository_ids") or [])] or None
    if repo_ids is None and case.get("space_id"):
        # 候选范围限定到空间（与 RepoAssociationService 同口径，防全库噪声）
        repo_ids = await _space_repository_ids(str(case["space_id"]))
    started = time.monotonic()

    try:
        query = str(case.get("query") or "")
        if not query and case.get("project_id"):
            query = await _build_project_query(str(case["project_id"]))
        if not query:
            raise ValueError("case 既无 query 也无可解析的 project_id")

        embedded = await embed_query(query, drop_noise=(corpus_kind != "requirement"))

        # 第一次：Stage 0 + 聚合层（不打 LLM）
        r0 = await RepoRouterV2.route(
            query,
            top_k=STAGE0_REPO_K,
            repository_ids=repo_ids,
            use_llm=False,
            corpus_kind=corpus_kind,
        )
        retrieved = _repo_ids_from_hits((r0.snapshot or {}).get("stage0", {}).get("node_hits"))
        # 兜底：老快照/降级路径可能不带 node_hits，用 repo_meta 的键集（记的是全部分桶仓）
        if not retrieved:
            retrieved = [str(k) for k in ((r0.snapshot or {}).get("repo_meta") or {})]
        candidates = [str(c.repo_id) for c in r0.candidates]

        # 第二次：完整链路取最终层
        r1 = await RepoRouterV2.route(
            query,
            top_k=top_k,
            repository_ids=repo_ids,
            use_llm=True,
            corpus_kind=corpus_kind,
        )
        final = [str(c.repo_id) for c in r1.candidates]

        return evaluate_case(
            case_id=case_id,
            corpus_kind=corpus_kind,
            query_len=len(query),
            probe_count=len(embedded.vectors),
            expected=expected,
            retrieved=retrieved,
            candidates=candidates,
            final=final,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001 — 单 case 失败不中断整轮评测
        from common.logging import redact_secrets_in_text

        return evaluate_case(
            case_id=case_id,
            corpus_kind=corpus_kind,
            query_len=0,
            probe_count=0,
            expected=expected,
            retrieved=[],
            candidates=[],
            final=[],
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(exc).__name__}: {redact_secrets_in_text(str(exc))[:200]}",
        )


@sync_to_async
def _cases_from_associations(limit: int) -> list[dict[str, Any]]:
    """把人工确认的 RepoAssociation 折算成评测 case（每个项目一条）。"""
    from initiatives.models import Project, RepoAssociation

    by_project: dict[str, list[str]] = {}
    rows = (
        RepoAssociation.objects.filter(status__in=["confirmed", "verified"])
        .values_list("project_id", "repository_id")
    )
    for project_id, repository_id in rows:
        by_project.setdefault(str(project_id), []).append(str(repository_id))

    cases: list[dict[str, Any]] = []
    for project_id, repos in by_project.items():
        project = Project.objects.filter(id=project_id).select_related("space").first()
        if project is None or project.space_id is None:
            continue
        scoped = [
            str(r) for r in project.space.repositories.values_list("id", flat=True)
        ]
        if not scoped:
            continue
        cases.append({
            "id": f"assoc:{project.name[:40]}",
            "project_id": project_id,
            "corpus_kind": "requirement",
            "expected_repos": sorted(set(repos)),
            "repository_ids": scoped,
        })
        if len(cases) >= limit:
            break
    return cases


class Command(BaseCommand):
    help = "端到端仓库路由召回评测（真跑 embedding + Qdrant + LLM，按层归因）"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--fixtures", default="", help="case JSON 路径")
        parser.add_argument(
            "--from-associations",
            action="store_true",
            help="用人工确认的 RepoAssociation 作为标注来源",
        )
        parser.add_argument("--limit", type=int, default=20, help="关联标注最多取几条 case")
        parser.add_argument("--top-k", type=int, default=5)
        parser.add_argument("--baseline", default="", help="基线 JSON；回退即非零退出")
        parser.add_argument(
            "--tolerance", type=float, default=0.0,
            help="确定性层（检索/聚合）允许的下滑幅度，默认 0",
        )
        parser.add_argument(
            "--llm-tolerance", type=float, default=None,
            help="最终层允许的下滑幅度（LLM 有轮次抖动），缺省用模块默认",
        )
        parser.add_argument("--output-json", default="")
        parser.add_argument("--write-baseline", default="", help="把本轮结果写成基线")

    def handle(self, *args: Any, **options: Any) -> None:
        cases: list[dict[str, Any]] = []

        fixtures_path = options["fixtures"]
        if fixtures_path or (not options["from_associations"] and _DEFAULT_FIXTURES.exists()):
            path = Path(fixtures_path) if fixtures_path else _DEFAULT_FIXTURES
            if not path.exists():
                raise CommandError(f"fixtures 不存在：{path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            cases.extend(data.get("cases") or [])

        if options["from_associations"]:
            cases.extend(asyncio.run(_cases_from_associations(options["limit"])))

        if not cases:
            raise CommandError("没有可评测的 case（用 --fixtures 或 --from-associations）")

        started = time.monotonic()
        outcomes = asyncio.run(self._run_all(cases, top_k=options["top_k"]))
        report = aggregate_report(outcomes)
        duration_ms = int((time.monotonic() - started) * 1000)

        self._print(report, duration_ms)

        try:
            logger.info(
                "repo_route_recall_evaluated",
                total_cases=report.total_cases,
                node_recall=round(report.node_recall, 4),
                candidate_recall=round(report.candidate_recall, 4),
                final_recall=round(report.final_recall, 4),
                full_recall_cases=report.full_recall_cases,
                duration_ms=duration_ms,
                **_LOG_KV,
            )
        except Exception:  # noqa: BLE001 — 观测 best-effort
            pass

        payload = {**report.to_dict(), "duration_ms": duration_ms}
        if options["output_json"]:
            Path(options["output_json"]).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.stdout.write(f"报告已写入 {options['output_json']}")
        if options["write_baseline"]:
            Path(options["write_baseline"]).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.stdout.write(f"基线已写入 {options['write_baseline']}")

        if options["baseline"]:
            base_path = Path(options["baseline"])
            if not base_path.exists():
                raise CommandError(f"基线不存在：{base_path}")
            baseline = json.loads(base_path.read_text(encoding="utf-8"))
            passed, failures = compare_to_baseline(
                report,
                baseline,
                tolerance=options["tolerance"],
                llm_tolerance=options["llm_tolerance"],
            )
            if not passed:
                raise CommandError("召回门禁未通过：\n  " + "\n  ".join(failures))
            self.stdout.write(self.style.SUCCESS("召回门禁通过"))

    async def _run_all(
        self, cases: list[dict[str, Any]], *, top_k: int
    ) -> list[CaseOutcome]:
        # 串行：每条 case 都打 LLM，并发只会撞上游限流且让延迟数字失真。
        return [await _run_case(case, top_k=top_k) for case in cases]

    def _print(self, report: Any, duration_ms: int) -> None:
        w = self.stdout.write
        w("=" * 78)
        w(f"端到端召回评测：{report.total_cases} 条 case，耗时 {duration_ms}ms")
        w("=" * 78)
        w(f"  检索层 node_recall      : {report.node_recall:.4f}")
        w(f"  聚合层 candidate_recall : {report.candidate_recall:.4f}")
        w(f"  最终层 final_recall     : {report.final_recall:.4f}")
        w(f"  全中 case               : {report.full_recall_cases}/{report.total_cases}")
        w(f"  丢失分层计数            : {json.dumps(report.lost_counts, ensure_ascii=False)}")
        w("-" * 78)
        for c in report.cases:
            flag = "✅" if c.final_recall >= 1.0 else "❌"
            w(f"{flag} {c.case_id}  (query {c.query_len} 字符 / {c.probe_count} 探针"
              f" / {c.duration_ms}ms)")
            if c.error:
                w(f"     错误: {c.error}")
                continue
            w(f"     node {c.node_recall:.2f} → cand {c.candidate_recall:.2f}"
              f" → final {c.final_recall:.2f}")
            lost = {k: v for k, v in c.lost_at.items() if v != "none"}
            if lost:
                for repo_id, layer in lost.items():
                    w(f"     漏 {repo_id} @ {layer}")
