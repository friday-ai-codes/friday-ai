#!/usr/bin/env python3
"""Bulk-import ricelove Feature pages into Friday Projects.

Run from server/:
  uv run python ../.planning/quick/260807-ricelove-import/import_ricelove.py

Requires scraped JSON under /tmp/ricelove-features/*.json
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
from urllib.parse import urlparse

# Bootstrap Django
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
from initiatives.models import (  # noqa: E402
    Artifact,
    ArtifactCarrier,
    ArtifactType,
    Project,
)
from initiatives.services.artifact_service import ArtifactService  # noqa: E402
from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService  # noqa: E402
from initiatives.services.project_branch_service import ProjectBranchService  # noqa: E402
from initiatives.services.project_service import ProjectService  # noqa: E402
from initiatives.services.repo_association_service import RepoAssociationService  # noqa: E402
from projects.models import Space  # noqa: E402
from repositories.models import Repository  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

FEATURES_DIR = Path("/tmp/ricelove-features")
MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
REPORT_PATH = Path("/tmp/ricelove-import-report.json")

DOMAIN_SPACE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"学习|学生|student.?learning|learn", re.I), "学习工具"),
    (re.compile(r"商业|交易|权益|commerce|entitlement|营收|订单|支付", re.I), "商业化"),
    (re.compile(r"入校|学校|教师|teacher|school", re.I), "入校"),
    (re.compile(r"\bAPP\b|客户端|android|ios", re.I), "APP组"),
    (re.compile(r"技术|基建|中台|infra|平台|支撑", re.I), "技术支撑"),
    (re.compile(r"硬件|设备|device", re.I), "智能硬件"),
    (re.compile(r"电销|crm|转化", re.I), "武汉电销"),
]


def _gitlab_repo_name(url: str) -> str | None:
    """https://gitlab.yc345.tv/backend/wrong-problem -> backend/wrong-problem"""
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return None
    path = re.sub(r"\.git$", "", path)
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return None


def _classify_feishu_heuristic(title: str) -> str:
    t = title or ""
    if re.search(r"埋点评审|checklist|check\s*list", t, re.I):
        return "tracking_review"
    if re.search(r"埋点", t):
        return "tracking_doc"
    if re.search(r"复盘|效果分析|问题跟踪|上线后", t):
        return "retrospective"
    if re.search(r"方案|PRD|需求|评审版|项目\]|立项", t):
        return "requirement_doc"
    if re.search(r"UI|设计稿|figma|蓝湖", t, re.I):
        return "ui_design"
    return "requirement_doc"


def _pick_space_name(feature: dict[str, Any]) -> str:
    crumbs = feature.get("crumbs") or []
    blob = " ".join(f"{c.get('text','')} {c.get('href','')}" for c in crumbs)
    blob += " " + (feature.get("mainText") or "")[:500]
    for pat, space_name in DOMAIN_SPACE_RULES:
        if pat.search(blob):
            return space_name
    slug = feature.get("slug") or ""
    if slug.startswith(("cs-", "learn", "study", "problem", "trial", "friend", "match", "reward", "home-")):
        return "学习工具"
    if slug.startswith(("ce-", "order", "commerce", "channel", "training-camp", "ai-custom")):
        return "商业化"
    if slug.startswith(("ccp-", "aop-")):
        return "技术支撑"
    return "未分类"


def _desc_from_feature(feature: dict[str, Any]) -> str:
    main = (feature.get("mainText") or "").strip()
    # take first meaningful paragraph after title lines
    lines = [ln.strip() for ln in main.splitlines() if ln.strip()]
    body = []
    for ln in lines[1:]:
        if ln.startswith("#") or ln in {"全部展开", "全部折叠"}:
            continue
        body.append(ln)
        if sum(len(x) for x in body) > 400:
            break
    text = " ".join(body)[:600]
    cluster = ""
    for c in feature.get("crumbs") or []:
        if "/cluster/" in (c.get("href") or ""):
            cluster = c.get("text") or ""
            break
    prefix = f"能力簇：{cluster}。" if cluster else ""
    return (prefix + text).strip() or f"导入自洋葱产品知识库 Feature {feature.get('slug')}"


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
            # fallback call_source enum
            print("mimo call failed", type(exc).__name__, str(exc)[:200])
            return None


async def _mimo_classify_docs(items: list[dict[str, str]]) -> dict[str, str]:
    """items: [{id, title}] -> {id: artifact_type_key}"""
    if not items:
        return {}
    prompt = (
        "你是产品文档分类器。把每条飞书文档标题分类到以下之一：\n"
        "requirement_doc, tracking_doc, tracking_review, retrospective, ui_design, ui_review, dev_spec\n"
        "只返回 JSON 对象：{doc_id: type_key}，不要解释。\n\n"
        + json.dumps(items, ensure_ascii=False)
    )
    raw = await _call_mimo(prompt)
    if not raw:
        return {}
    # extract json object
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return {str(k): str(v) for k, v in data.items()}
    except json.JSONDecodeError:
        return {}


async def _mimo_match_repos(
    missing: list[str], catalog: list[str]
) -> dict[str, str | None]:
    """Map gitlab path -> friday repo name or null."""
    if not missing:
        return {}
    prompt = (
        "把左侧 GitLab 路径匹配到右侧 Friday 仓库名（完全一致优先；"
        "可同义/改名对应）。无法匹配填 null。\n"
        "只返回 JSON 对象。\n\n"
        f"gitlab_paths={json.dumps(missing, ensure_ascii=False)}\n"
        f"friday_repos={json.dumps(catalog, ensure_ascii=False)}\n"
    )
    raw = await _call_mimo(prompt, max_tokens=6000)
    if not raw:
        return {}
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        out: dict[str, str | None] = {}
        for k, v in data.items():
            if v in (None, "null", ""):
                out[str(k)] = None
            else:
                out[str(k)] = str(v)
        return out
    except json.JSONDecodeError:
        return {}


async def main() -> None:
    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin user")

    spaces = {s.name: s async for s in Space.objects.all()}
    types = {t.key: t async for t in ArtifactType.objects.all()}
    artifact_svc = ArtifactService()

    # ensure custom types
    for key, name in (("product_kb", "产品知识库页"), ("product_h5", "产品 H5 / 原型")):
        if key not in types:
            t = await artifact_svc.create_type(
                key=key,
                name=name,
                carrier=ArtifactCarrier.EXTERNAL_LINK,
                ragable=False,
                enabled=True,
                actor=admin,
                initiated_by_user_id=admin.id,
            )
            types[key] = t

    repos_by_name = {r.name: r async for r in Repository.objects.all()}
    repo_catalog = sorted(repos_by_name.keys())

    files = sorted(FEATURES_DIR.glob("*.json"))
    features: list[dict[str, Any]] = []
    for f in files:
        if f.name.endswith(".err"):
            continue
        features.append(json.loads(f.read_text()))
    print(f"loaded features: {len(features)}")

    # Patch Feishu provision to no-op for bulk
    from initiatives.services import project_doc_service as pds

    original_dispatch = pds.ProjectDocService.provision_dispatch

    def _noop_provision(self, *args, **kwargs):  # noqa: ANN001
        return None

    pds.ProjectDocService.provision_dispatch = _noop_provision  # type: ignore[method-assign]

    # Collect unmatched gitlab + ambiguous docs for MiMo
    unmatched_gitlab: set[str] = set()
    ambiguous_docs: list[dict[str, str]] = []

    for feat in features:
        for g in feat.get("gitlab") or []:
            name = _gitlab_repo_name(g.get("href") or "")
            if name and name not in repos_by_name:
                unmatched_gitlab.add(name)
        for doc in feat.get("feishu") or []:
            title = (doc.get("text") or "").strip()
            href = doc.get("href") or ""
            if not title or title.startswith("http") or len(title) < 4:
                continue
            heur = _classify_feishu_heuristic(title)
            # 仅把「标题像中文但不含方案/PRD/埋点/复盘」的少量样本交给 MiMo
            if (
                heur == "requirement_doc"
                and not re.search(r"方案|PRD|需求|Spec|设计", title, re.I)
                and re.search(r"[\u4e00-\u9fff]", title)
            ):
                ambiguous_docs.append({"id": href or title, "title": title[:120]})

    # unique ambiguous — MiMo 额度够，但为导入吞吐封顶 200
    seen_doc = set()
    amb_unique = []
    for d in ambiguous_docs:
        if d["id"] in seen_doc:
            continue
        seen_doc.add(d["id"])
        amb_unique.append(d)
    amb_unique = amb_unique[:200]

    print(f"unmatched gitlab: {len(unmatched_gitlab)}, ambiguous docs(to mimo): {len(amb_unique)}")

    mimo_doc_map: dict[str, str] = {}
    for i in range(0, len(amb_unique), 50):
        chunk = amb_unique[i : i + 50]
        mapped = await _mimo_classify_docs(chunk)
        mimo_doc_map.update(mapped)
        print(f"mimo docs classified {min(i+50, len(amb_unique))}/{len(amb_unique)}")

    mimo_repo_map: dict[str, str | None] = {}
    missing_list = sorted(unmatched_gitlab)
    for i in range(0, len(missing_list), 40):
        chunk = missing_list[i : i + 40]
        # shrink catalog with fuzzy candidates
        cats = []
        for m in chunk:
            tail = m.split("/")[-1]
            cats.extend([c for c in repo_catalog if tail in c or c.split("/")[-1] in m])
        cats = sorted(set(cats))[:250] or repo_catalog[:250]
        mapped = await _mimo_match_repos(chunk, cats)
        mimo_repo_map.update(mapped)
        print(f"mimo repos matched {min(i+40, len(missing_list))}/{len(missing_list)}")

    project_svc = ProjectService()
    repo_assoc_svc = RepoAssociationService()
    branch_svc = ProjectBranchService()
    graph_svc = ProjectKnowledgeGraphService()

    slug_to_project: dict[str, Project] = {}
    report: dict[str, Any] = {
        "projects_created": 0,
        "projects_existing": 0,
        "artifacts": 0,
        "repos_confirmed": 0,
        "relations": 0,
        "errors": [],
    }

    # Pass 1: create projects + artifacts + repos
    for idx, feat in enumerate(features, 1):
        slug = feat.get("slug") or ""
        if not slug:
            continue
        try:
            space_name = _pick_space_name(feat)
            space = spaces.get(space_name) or spaces["未分类"]
            name = (feat.get("h1") or slug).strip()[:120]
            project, created = await project_svc.create(
                space=space,
                name=name,
                description=_desc_from_feature(feat),
                feishu_project_key=f"ricelove:{slug}",
                created_by=admin,
                initiated_by_user_id=admin.id,
            )
            slug_to_project[slug] = project
            if created:
                report["projects_created"] += 1
            else:
                report["projects_existing"] += 1

            # Artifacts
            arts: list[tuple[str, str, str, str]] = []
            arts.append(
                (
                    "product_kb",
                    f"洋葱产品知识库 · {name}",
                    feat.get("url") or f"https://prototype.ricelove.cc/f/{slug}/",
                    ArtifactCarrier.EXTERNAL_LINK,
                )
            )
            for h in feat.get("h5") or []:
                href = h.get("href") or ""
                if href:
                    arts.append(
                        (
                            "product_h5",
                            (h.get("text") or "产品 H5")[:120],
                            href,
                            ArtifactCarrier.EXTERNAL_LINK,
                        )
                    )
            for doc in feat.get("feishu") or []:
                href = doc.get("href") or ""
                title = (doc.get("text") or href)[:160]
                if not href:
                    continue
                tkey = mimo_doc_map.get(href) or _classify_feishu_heuristic(title)
                if tkey not in types:
                    tkey = "requirement_doc"
                carrier = (
                    ArtifactCarrier.EXTERNAL_LINK
                    if tkey == "ui_design"
                    else ArtifactCarrier.FEISHU_DOC
                )
                arts.append((tkey, title, href, carrier))

            for type_key, title, url, carrier in arts:
                exists = await Artifact.objects.filter(project_id=project.id, url=url).afirst()
                if exists:
                    continue
                await artifact_svc.create_artifact(
                    project_id=project.id,
                    type_id=types[type_key].id,
                    title=title,
                    carrier=carrier,
                    url=url,
                    contributor=admin,
                    actor=admin,
                    initiated_by_user_id=admin.id,
                )
                report["artifacts"] += 1

            # Repos
            resolved_repos: list[Repository] = []
            seen_repo: set[str] = set()
            for g in feat.get("gitlab") or []:
                gname = _gitlab_repo_name(g.get("href") or "")
                if not gname:
                    continue
                mapped = gname if gname in repos_by_name else mimo_repo_map.get(gname)
                if not mapped or mapped not in repos_by_name:
                    continue
                if mapped in seen_repo:
                    continue
                seen_repo.add(mapped)
                resolved_repos.append(repos_by_name[mapped])

            if resolved_repos:
                candidates = [
                    {
                        "repo_id": str(r.id),
                        "repo_name": r.name,
                        "score": 1.0,
                        "confidence": "high",
                        "reason": f"imported from ricelove feature {slug}",
                        "matched_node_paths": [],
                    }
                    for r in resolved_repos
                ]
                await repo_assoc_svc._persist_candidates(
                    space=space,
                    project=project,
                    candidates=candidates,
                    initiated_by_user_id=str(admin.id),
                )
                confirmed = await repo_assoc_svc.confirm_repos(
                    project=project,
                    repo_ids=[r.id for r in resolved_repos],
                    initiated_by_user_id=admin.id,
                )
                report["repos_confirmed"] += len(confirmed)
                for r in resolved_repos:
                    branch = (r.default_branch or "master").strip() or "master"
                    await branch_svc.bind(
                        project_id=project.id,
                        repository_id=r.id,
                        branch_name=branch,
                        source="manual",
                        actor=admin,
                        initiated_by_user_id=admin.id,
                        _skip_member_check=True,
                    )

            if idx % 20 == 0:
                print(
                    f"pass1 {idx}/{len(features)} created={report['projects_created']} "
                    f"arts={report['artifacts']}"
                )
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"slug": slug, "error": f"{type(exc).__name__}: {exc}"})
            print("ERR", slug, type(exc).__name__, str(exc)[:160])

    # Pass 2: feature relations via knowledge graph
    for feat in features:
        slug = feat.get("slug") or ""
        src = slug_to_project.get(slug)
        if not src:
            continue
        related_slugs = set()
        for rel in feat.get("relatedFeatures") or []:
            href = rel.get("href") or ""
            m = re.search(r"/f/([^/]+)", href)
            if m:
                related_slugs.add(m.group(1))
        for other_slug in related_slugs:
            tgt = slug_to_project.get(other_slug)
            if not tgt or tgt.id == src.id:
                continue
            try:
                created = await graph_svc.link_project(
                    project=src,
                    other_project=tgt,
                    actor=admin,
                    initiated_by_user_id=admin.id,
                )
                if created:
                    report["relations"] += 1
            except Exception as exc:  # noqa: BLE001
                report["errors"].append(
                    {"slug": slug, "rel": other_slug, "error": str(exc)[:160]}
                )

    # restore provision
    pds.ProjectDocService.provision_dispatch = original_dispatch  # type: ignore[method-assign]

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT", REPORT_PATH)
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, ensure_ascii=False, indent=2))
    print("errors", len(report["errors"]))


if __name__ == "__main__":
    asyncio.run(main())
