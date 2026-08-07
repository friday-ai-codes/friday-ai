#!/usr/bin/env python3
"""把仍挂在 ricelove Feature 合集上的附属文档，归并到已拆出的 ricelove-scheme 项目。

前置：resplit_schemes.py 已创建方案项目并把【方案】/PRD 种子搬走。
本脚本用 MiMo + 启发式，把埋点/复盘/调研/其它需求文档挂到最相关的方案项目。

Run from server/:
  uv run python ../.planning/quick/260807-ricelove-import/assign_supports.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

import django

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from agents.call_source import CallSource, use_call_source  # noqa: E402
from agents.llm_factory import build_chat_model, content_to_text  # noqa: E402
from initiatives.models import Artifact, Project  # noqa: E402
from initiatives.services.artifact_service import ArtifactService  # noqa: E402
from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService  # noqa: E402
from knowledge.models import EdgeRelation  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
REPORT_PATH = Path("/tmp/ricelove-assign-supports-report.json")
CLUSTER_RE = re.compile(r"从能力簇「([^」]+)」")


async def _call_mimo(prompt: str, *, max_tokens: int = 4096) -> str | None:
    resolved = await ProviderConfigService.aresolve_or_error(
        node_config={"provider_credential_id": MIMO_CREDENTIAL_ID}
    )
    if isinstance(resolved, ProviderMissingError):
        print("MIMO missing:", resolved)
        return None
    with use_call_source(CallSource.AUX_CRAWL.value):
        try:
            model = build_chat_model(
                resolved, MIMO_MODEL, max_output_tokens=max_tokens, streaming=False, temperature=0.1
            )
            msg = await model.ainvoke([HumanMessage(content=prompt)])
            return content_to_text(getattr(msg, "content", "")).strip()
        except Exception as exc:  # noqa: BLE001
            print("mimo call failed", type(exc).__name__, str(exc)[:200])
            return None


def _parse_json_obj(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _heuristic_assign(seed_titles: list[tuple[str, str]], support_title: str) -> str | None:
    st = support_title or ""
    best = None
    best_score = 0
    for sid, title in seed_titles:
        score = 0
        for tok in re.findall(r"v?\d+\.\d+", title, re.I):
            if tok.lower() in st.lower():
                score += 4
        for tok in re.findall(r"[\u4e00-\u9fff]{2,10}", title):
            if len(tok) >= 3 and tok in st:
                score += 1
        if score > best_score:
            best_score = score
            best = sid
    return best if best_score >= 3 else None


async def _mimo_assign(
    seeds: list[dict[str, str]], supports: list[dict[str, str]]
) -> dict[str, str]:
    if not supports or not seeds:
        return {}
    prompt = (
        "你是产品知识库整理助手。seeds 是已拆出的具体方案/PRD 项目；supports 是仍挂在能力簇合集上的附属文档。\n"
        "把每条 support 归到最相关的 seed_id；若是合集级公共文档（总埋点、跨版本、知识库说明）则归 parent。\n"
        "只返回 JSON：{support_id: seed_id或\"parent\"}。\n\n"
        f"seeds={json.dumps(seeds, ensure_ascii=False)}\n"
        f"supports={json.dumps(supports, ensure_ascii=False)}\n"
    )
    return {str(k): str(v) for k, v in _parse_json_obj(await _call_mimo(prompt)).items()}


@sync_to_async
def _load() -> tuple[list[Project], list[Project], list[dict[str, Any]]]:
    features = list(Project.objects.filter(feishu_project_key__startswith="ricelove:"))
    schemes = list(Project.objects.filter(feishu_project_key__startswith="ricelove-scheme:"))
    leftover = []
    for a in (
        Artifact.objects.filter(project__feishu_project_key__startswith="ricelove:")
        .exclude(type__key="product_kb")
        .select_related("type", "project")
    ):
        leftover.append(
            {
                "id": str(a.id),
                "title": a.title or "",
                "type_key": a.type.key,
                "project_id": str(a.project_id),
                "project_name": a.project.name,
            }
        )
    return features, schemes, leftover


@sync_to_async
def _move(artifact_id: str, project_id: str) -> None:
    Artifact.objects.filter(id=artifact_id).update(project_id=project_id)


@sync_to_async
def _mark_cluster(project: Project, child_names: list[str]) -> None:
    note = (
        "\n\n【能力簇容器】本项目对应洋葱产品知识库 Feature 合集，具体方案已拆为独立项目：\n"
        + "\n".join(f"- {n}" for n in child_names[:50])
    )
    desc = project.description or ""
    if "【能力簇容器】" in desc:
        return
    project.description = (desc + note)[:8000]
    project.save(update_fields=["description", "updated_at"])


@sync_to_async
def _example() -> dict[str, Any]:
    parent = Project.objects.filter(feishu_project_key="ricelove:cs-b-xin-yong-hu-yin-dao").first()
    child = Project.objects.filter(
        feishu_project_key__startswith="ricelove-scheme:", name__icontains="新用户引导3.0"
    ).first()
    out: dict[str, Any] = {}
    if parent:
        out["parent"] = {
            "id": str(parent.id),
            "name": parent.name,
            "url": f"http://localhost:10240/projects/{parent.id}",
            "artifacts": list(
                Artifact.objects.filter(project=parent)
                .select_related("type")
                .values_list("type__key", "title")
            ),
        }
    if child:
        out["child_3_0"] = {
            "id": str(child.id),
            "name": child.name,
            "url": f"http://localhost:10240/projects/{child.id}",
            "artifacts": list(
                Artifact.objects.filter(project=child)
                .select_related("type")
                .values_list("type__key", "title")
            ),
            "repos": list(
                child.repo_associations.filter(status__in=["confirmed", "verified"]).values_list(
                    "repository__name", flat=True
                )
            ),
        }
    return out


@sync_to_async
def _gap_report() -> dict[str, Any]:
    from django.db.models import Count, Q

    from initiatives.models.repo_association import RepoAssociation

    scheme_qs = Project.objects.filter(feishu_project_key__startswith="ricelove-scheme:")
    feature_qs = Project.objects.filter(feishu_project_key__startswith="ricelove:")
    types = {
        r["type__key"]: r["n"]
        for r in Artifact.objects.filter(
            Q(project__feishu_project_key__startswith="ricelove:")
            | Q(project__feishu_project_key__startswith="ricelove-scheme:")
        )
        .values("type__key")
        .annotate(n=Count("id"))
    }
    leftover = Artifact.objects.filter(
        project__feishu_project_key__startswith="ricelove:"
    ).exclude(type__key="product_kb")
    return {
        "feature_projects": feature_qs.count(),
        "scheme_projects": scheme_qs.count(),
        "artifact_types": types,
        "leftover_on_features": leftover.count(),
        "leftover_by_type": list(leftover.values("type__key").annotate(n=Count("id"))),
        "scheme_without_repos": scheme_qs.annotate(r=Count("repo_associations")).filter(r=0).count(),
        "scheme_with_repos": scheme_qs.annotate(r=Count("repo_associations")).filter(r__gt=0).count(),
        "confirmed_repos": RepoAssociation.objects.filter(
            project__feishu_project_key__startswith="ricelove-scheme:",
            status__in=["confirmed", "verified"],
        ).count(),
        "feature_list_count": types.get("feature_list", 0),
        "test_case_count": types.get("test_case", 0),
        "dev_spec_count": types.get("dev_spec", 0),
        "ui_design_count": types.get("ui_design", 0),
        "gao_san": {
            "name": "高三提分专项",
            "has_feature_list": Artifact.objects.filter(
                project__name="高三提分专项", type__key="feature_list"
            ).exists(),
            "has_test_case": Artifact.objects.filter(
                project__name="高三提分专项", type__key="test_case"
            ).exists(),
        },
    }


async def main() -> None:
    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin")

    features, schemes, leftover = await _load()
    print(f"features={len(features)} schemes={len(schemes)} leftover={len(leftover)}")

    # map cluster name -> schemes
    by_cluster: dict[str, list[Project]] = defaultdict(list)
    for s in schemes:
        m = CLUSTER_RE.search(s.description or "")
        if m:
            by_cluster[m.group(1)].append(s)

    # also index feature by name
    feature_by_name = {p.name: p for p in features}
    feature_by_id = {str(p.id): p for p in features}

    leftover_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in leftover:
        leftover_by_parent[row["project_id"]].append(row)

    graph_svc = ProjectKnowledgeGraphService()
    report: dict[str, Any] = {
        "moved": 0,
        "left_on_parent": 0,
        "mimo_batches": 0,
        "mimo_mapped": 0,
        "heuristic": 0,
        "single_seed": 0,
        "clusters_annotated": 0,
        "links": 0,
        "errors": [],
    }

    parents = list(leftover_by_parent.keys())
    for idx, pid in enumerate(parents, 1):
        parent = feature_by_id.get(pid)
        if not parent:
            continue
        children = by_cluster.get(parent.name) or []
        if not children:
            # try fuzzy: description contains parent name
            children = [
                s
                for s in schemes
                if parent.name and parent.name in (s.description or "")
            ]
        if not children:
            report["left_on_parent"] += len(leftover_by_parent[pid])
            continue

        # ensure graph links
        for child in children:
            try:
                linked = await graph_svc.link_project(
                    project=parent,
                    other_project=child,
                    relation=EdgeRelation.RELATES_TO,
                    actor=admin,
                    initiated_by_user_id=admin.id,
                )
                if linked:
                    report["links"] += 1
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(f"link:{type(exc).__name__}:{exc}"[:200])

        seeds = [{"id": f"c{i}", "title": c.name[:100]} for i, c in enumerate(children)]
        sid_to_child = {f"c{i}": c for i, c in enumerate(children)}
        supports = [
            {"id": r["id"], "title": r["title"][:120]} for r in leftover_by_parent[pid]
        ]

        assignment: dict[str, str] = {}
        if len(children) == 1:
            only = seeds[0]["id"]
            assignment = {s["id"]: only for s in supports}
            report["single_seed"] += len(supports)
        else:
            for j in range(0, len(supports), 25):
                chunk = supports[j : j + 25]
                mapped = await _mimo_assign(seeds, chunk)
                report["mimo_batches"] += 1
                assignment.update(mapped)
                report["mimo_mapped"] += len(mapped)

        seed_titles = [(s["id"], s["title"]) for s in seeds]
        seed_ids = set(sid_to_child.keys())
        for s in supports:
            target = assignment.get(s["id"], "")
            if not target or target == "parent" or target not in seed_ids:
                heur = _heuristic_assign(seed_titles, s["title"])
                if heur:
                    target = heur
                    report["heuristic"] += 1
                else:
                    report["left_on_parent"] += 1
                    continue
            child = sid_to_child.get(target)
            if not child:
                report["left_on_parent"] += 1
                continue
            await _move(s["id"], str(child.id))
            report["moved"] += 1

        await _mark_cluster(parent, [c.name for c in children])
        report["clusters_annotated"] += 1

        if idx % 15 == 0 or parent.name == "新用户引导相关":
            print(
                f"[{idx}/{len(parents)}] {parent.name}: children={len(children)} "
                f"supports={len(supports)} moved_so_far={report['moved']}"
            )

    report["example"] = await _example()
    report["gaps"] = await _gap_report()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "example"}, ensure_ascii=False, indent=2))
    print("example:", json.dumps(report.get("example"), ensure_ascii=False, indent=2))
    print("report ->", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
