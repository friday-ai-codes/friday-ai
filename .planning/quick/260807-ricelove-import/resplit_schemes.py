#!/usr/bin/env python3
"""把 ricelove Feature 合集里的具体【方案】/PRD 拆成独立 Friday Project。

粒度（用户纠偏后）：
- 「新用户引导相关」= 能力簇容器（保留 product_kb + 关联）
- 「【方案】新用户引导3.0-新首页版」= 独立 Project
- 「高三提分专项」不动（非 ricelove，且已有 feature_list/test_case）

Run from server/:
  uv run python ../.planning/quick/260807-ricelove-import/resplit_schemes.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
from initiatives.models.repo_association import (  # noqa: E402
    RepoAssociation,
    RepoAssociationStatus,
)
from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService  # noqa: E402
from initiatives.services.project_service import ProjectService  # noqa: E402
from knowledge.models import EdgeRelation  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
REPORT_PATH = Path("/tmp/ricelove-resplit-report.json")
SKIP_PROJECT_NAMES = {"高三提分专项"}

# 具体交付单元：方案 / PRD / 项目一级
_SEED_PREFIX = re.compile(
    r"^(【方案】|\[方案\]|【PRD】|\[PRD\]|【项目一级】|【项目】|\[项目一级\]|\[项目\])"
)
_SUPPORT_DOC = re.compile(r"埋点|复盘|纪要|调研|check\s*list|评分卡|进度追溯|技术方案", re.I)


def _norm_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    try:
        p = urlparse(u)
        path = p.path.rstrip("/")
        return f"{p.scheme}://{p.netloc}{path}"
    except Exception:
        return u.split("?")[0].rstrip("/")


def _scheme_key(url: str) -> str:
    h = hashlib.sha1(_norm_url(url).encode("utf-8")).hexdigest()[:16]
    return f"ricelove-scheme:{h}"


def _is_seed_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or _SUPPORT_DOC.search(t):
        return False
    if _SEED_PREFIX.search(t):
        return True
    # 标题含 PRD，且不像附属文档
    if re.search(r"PRD", t, re.I) and not re.search(r"埋点|复盘|评分|进度", t):
        return True
    return False


def _clean_project_name(title: str) -> str:
    t = (title or "").strip()
    t = re.sub(r"^(【方案】|\[方案\]|【PRD】|\[PRD\]|【项目一级】|【项目】)\s*", "", t)
    return t[:120] or title[:120]


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


async def _mimo_assign_support(
    seeds: list[dict[str, str]],
    supports: list[dict[str, str]],
) -> dict[str, str]:
    """support artifact_id -> seed_id | 'parent'"""
    if not supports or not seeds:
        return {}
    prompt = (
        "你是产品知识库整理助手。下面有若干「具体方案/PRD 项目」(seeds) 和附属文档(supports)。\n"
        "把每条 support 归到最相关的 seed_id；无法判断则归 parent。\n"
        "只返回 JSON：{support_id: seed_id或\"parent\"}。\n\n"
        f"seeds={json.dumps(seeds, ensure_ascii=False)}\n"
        f"supports={json.dumps(supports, ensure_ascii=False)}\n"
    )
    return {str(k): str(v) for k, v in _parse_json_obj(await _call_mimo(prompt)).items()}


def _heuristic_assign(
    seed_titles: list[tuple[str, str]], support_title: str
) -> str | None:
    """Local fallback: version token overlap."""
    st = support_title or ""
    best = None
    best_score = 0
    for sid, title in seed_titles:
        score = 0
        for tok in re.findall(r"v?\d+\.\d+", title, re.I):
            if tok.lower() in st.lower():
                score += 3
        for tok in re.findall(r"[\u4e00-\u9fff]{2,8}", title):
            if len(tok) >= 3 and tok in st:
                score += 1
        if score > best_score:
            best_score = score
            best = sid
    return best if best_score >= 3 else None


@sync_to_async
def _load_ricelove_artifacts() -> list[dict[str, Any]]:
    rows = []
    qs = (
        Artifact.objects.filter(project__feishu_project_key__startswith="ricelove:")
        .exclude(project__name__in=SKIP_PROJECT_NAMES)
        .select_related("project", "type", "project__space")
        .order_by("project_id", "title")
    )
    for a in qs:
        rows.append(
            {
                "id": str(a.id),
                "title": a.title or "",
                "url": a.url or "",
                "type_key": a.type.key,
                "project_id": str(a.project_id),
                "project_name": a.project.name,
                "project_key": a.project.feishu_project_key or "",
                "space_id": str(a.project.space_id),
                "space": a.project.space,
                "project": a.project,
            }
        )
    return rows


@sync_to_async
def _move_artifact(artifact_id: str, project_id: str) -> None:
    Artifact.objects.filter(id=artifact_id).update(project_id=project_id)


@sync_to_async
def _copy_repos(parent: Project, child: Project, user_id: str) -> int:
    n = 0
    for assoc in RepoAssociation.objects.filter(
        project=parent,
        status__in=[
            RepoAssociationStatus.CONFIRMED,
            RepoAssociationStatus.VERIFIED,
            RepoAssociationStatus.VERIFYING,
        ],
    ):
        obj, created = RepoAssociation.objects.get_or_create(
            project=child,
            repository_id=assoc.repository_id,
            defaults={
                "status": RepoAssociationStatus.CONFIRMED,
                "score": assoc.score,
                "confidence": assoc.confidence,
                "routed_reason": f"inherited_from_cluster:{parent.feishu_project_key}",
                "source": "ricelove_resplit",
                "matched_node_paths": assoc.matched_node_paths or [],
                "initiated_by_user_id": user_id,
            },
        )
        if not created and obj.status == RepoAssociationStatus.PROPOSED:
            obj.status = RepoAssociationStatus.CONFIRMED
            obj.source = "ricelove_resplit"
            obj.save(update_fields=["status", "source", "updated_at"])
        n += 1
    return n


@sync_to_async
def _mark_cluster_desc(project: Project, child_names: list[str]) -> None:
    note = (
        "\n\n【能力簇容器】本项目对应洋葱产品知识库 Feature 合集，具体方案已拆为独立项目：\n"
        + "\n".join(f"- {n}" for n in child_names[:40])
    )
    desc = project.description or ""
    if "【能力簇容器】" in desc:
        return
    project.description = (desc + note)[:8000]
    project.save(update_fields=["description", "updated_at"])


async def main() -> None:
    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin user")

    # disable feishu workspace provision
    from initiatives.services import project_doc_service as pds

    pds.ProjectDocService.provision_dispatch = lambda *a, **k: None  # type: ignore[method-assign]

    rows = await _load_ricelove_artifacts()
    print(f"loaded artifacts: {len(rows)}")

    # group by parent feature project
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_parent[r["project_id"]].append(r)

    # collect unique seeds by URL
    seeds_by_url: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["type_key"] == "product_kb":
            continue
        if not _is_seed_title(r["title"]):
            continue
        nu = _norm_url(r["url"])
        if not nu:
            continue
        if nu not in seeds_by_url:
            seeds_by_url[nu] = {
                "url": nu,
                "title": r["title"],
                "artifact_ids": [r["id"]],
                "parent_ids": {r["project_id"]},
                "space": r["space"],
                "sample_parent": r["project"],
                "sample_parent_name": r["project_name"],
            }
        else:
            seeds_by_url[nu]["artifact_ids"].append(r["id"])
            seeds_by_url[nu]["parent_ids"].add(r["project_id"])

    print(f"unique seed docs: {len(seeds_by_url)}")

    project_svc = ProjectService()
    graph_svc = ProjectKnowledgeGraphService()

    url_to_child: dict[str, Project] = {}
    seed_id_to_url: dict[str, str] = {}  # synthetic seed id -> url
    report: dict[str, Any] = {
        "seeds": len(seeds_by_url),
        "projects_created": 0,
        "projects_existing": 0,
        "artifacts_moved": 0,
        "repos_copied": 0,
        "links": 0,
        "mimo_assigned": 0,
        "heuristic_assigned": 0,
        "left_on_parent": 0,
        "gaps": {},
        "errors": [],
        "example": {},
    }

    # Pass 1: create scheme projects + move seed artifacts
    for i, (nu, seed) in enumerate(seeds_by_url.items(), 1):
        key = _scheme_key(nu)
        name = _clean_project_name(seed["title"])
        parent = seed["sample_parent"]
        desc = (
            f"从能力簇「{seed['sample_parent_name']}」拆出的具体方案/项目。\n"
            f"源文档：{nu}"
        )
        try:
            child, created = await project_svc.create(
                space=seed["space"],
                name=name,
                description=desc,
                feishu_project_key=key,
                created_by=admin,
                initiated_by_user_id=admin.id,
            )
            if created:
                report["projects_created"] += 1
            else:
                report["projects_existing"] += 1
                # refresh name if empty-ish
                if child.name != name and created is False:
                    pass
            url_to_child[nu] = child
            sid = f"s{i}"
            seed_id_to_url[sid] = nu
            seed["sid"] = sid

            # move all duplicate seed artifacts onto child
            for aid in seed["artifact_ids"]:
                await _move_artifact(aid, str(child.id))
                report["artifacts_moved"] += 1

            # inherit repos from each parent
            for pid in seed["parent_ids"]:
                parent_obj = next(
                    (r["project"] for r in by_parent[pid][:1]),
                    parent,
                )
                # get actual parent project from any row
                parent_obj = by_parent[pid][0]["project"]
                report["repos_copied"] += await _copy_repos(parent_obj, child, str(admin.id))

            # link cluster parents ↔ child
            for pid in seed["parent_ids"]:
                parent_obj = by_parent[pid][0]["project"]
                linked = await graph_svc.link_project(
                    project=parent_obj,
                    other_project=child,
                    relation=EdgeRelation.RELATES_TO,
                    actor=admin,
                    initiated_by_user_id=admin.id,
                )
                if linked:
                    report["links"] += 1

            if i % 40 == 0:
                print(f"created/moved seeds {i}/{len(seeds_by_url)}")
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"url": nu, "error": f"{type(exc).__name__}: {exc}"[:300]})
            print("seed error", name[:40], type(exc).__name__, str(exc)[:120])

    # reverse map sid
    url_to_sid = {v: k for k, v in seed_id_to_url.items()}
    for nu, seed in seeds_by_url.items():
        seed["sid"] = url_to_sid.get(nu, seed.get("sid"))

    # Pass 2: assign support docs per parent via MiMo (+ heuristic fallback)
    parents_with_seeds = []
    for pid, arts in by_parent.items():
        parent_seeds = []
        for nu, seed in seeds_by_url.items():
            if pid in seed["parent_ids"] and nu in url_to_child:
                parent_seeds.append(
                    {
                        "id": seed["sid"],
                        "title": seed["title"][:100],
                    }
                )
        if not parent_seeds:
            continue
        supports = []
        for a in arts:
            if a["type_key"] == "product_kb":
                continue
            if _is_seed_title(a["title"]):
                continue  # already moved (or duplicate seed)
            # already moved? check — seed artifacts were moved; remaining are support
            supports.append({"id": a["id"], "title": a["title"][:120]})
        if parent_seeds:
            # 即使没有附属文档，也标注能力簇
            parents_with_seeds.append((pid, parent_seeds, supports, arts[0]["project"]))

    print(f"parents needing support assign: {len(parents_with_seeds)}")

    for idx, (pid, parent_seeds, supports, parent_obj) in enumerate(parents_with_seeds, 1):
        assignment: dict[str, str] = {}
        seed_ids = {x["id"] for x in parent_seeds}
        # 单方案：附属文档默认挂到该方案；多方案才呼叫 MiMo
        if len(parent_seeds) == 1:
            only = parent_seeds[0]["id"]
            assignment = {s["id"]: only for s in supports}
            report["heuristic_assigned"] += len(supports)
        else:
            for j in range(0, len(supports), 30):
                chunk = supports[j : j + 30]
                mapped = await _mimo_assign_support(parent_seeds, chunk)
                assignment.update(mapped)
                if mapped:
                    report["mimo_assigned"] += len(mapped)

        seed_titles = [(s["id"], s["title"]) for s in parent_seeds]
        for s in supports:
            target = assignment.get(s["id"], "")
            if not target or target == "parent" or target not in seed_ids:
                heur = _heuristic_assign(seed_titles, s["title"])
                if heur:
                    target = heur
                    report["heuristic_assigned"] += 1
                else:
                    report["left_on_parent"] += 1
                    continue
            nu = seed_id_to_url.get(target)
            child = url_to_child.get(nu or "")
            if not child:
                report["left_on_parent"] += 1
                continue
            await _move_artifact(s["id"], str(child.id))
            report["artifacts_moved"] += 1

        # annotate parent as cluster
        child_names = []
        for s in parent_seeds:
            nu = seed_id_to_url.get(s["id"])
            if nu and nu in url_to_child:
                child_names.append(url_to_child[nu].name)
        await _mark_cluster_desc(parent_obj, child_names)

        if idx % 20 == 0:
            print(f"support assign {idx}/{len(parents_with_seeds)}")

    # Example check: 新用户引导3.0
    @sync_to_async
    def _example_payload(child: Project) -> dict[str, Any]:
        arts = list(
            Artifact.objects.filter(project_id=child.id).values_list("title", flat=True)
        )
        return {
            "project_id": str(child.id),
            "name": child.name,
            "key": child.feishu_project_key,
            "url": f"http://localhost:10240/projects/{child.id}",
            "artifacts": arts,
        }

    for nu, seed in seeds_by_url.items():
        if "新用户引导3.0" in seed["title"] or "新首页版" in seed["title"]:
            child = url_to_child.get(nu)
            if child:
                report["example"] = await _example_payload(child)
            break

    # Gap inventory after resplit
    @sync_to_async
    def _gaps() -> dict[str, Any]:
        from django.db.models import Count, Q

        scheme_qs = Project.objects.filter(feishu_project_key__startswith="ricelove-scheme:")
        feature_qs = Project.objects.filter(feishu_project_key__startswith="ricelove:")
        type_counts = {
            row["type__key"]: row["n"]
            for row in Artifact.objects.filter(
                Q(project__feishu_project_key__startswith="ricelove:")
                | Q(project__feishu_project_key__startswith="ricelove-scheme:")
            )
            .values("type__key")
            .annotate(n=Count("id"))
        }
        return {
            "feature_projects": feature_qs.count(),
            "scheme_projects": scheme_qs.count(),
            "artifact_types": type_counts,
            "scheme_without_repos": scheme_qs.annotate(r=Count("repo_associations")).filter(r=0).count(),
            "missing_feature_list": type_counts.get("feature_list", 0),
            "missing_test_case": type_counts.get("test_case", 0),
            "note": (
                "ricelove 源站几乎不提供独立 feature_list / test_case；"
                "高三提分专项是人工录入范例。dev_spec/ui_design 仅少数文档标题可识别。"
            ),
        }

    report["gaps"] = await _gaps()
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("report ->", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
