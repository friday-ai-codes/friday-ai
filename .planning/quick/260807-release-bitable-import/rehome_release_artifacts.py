#!/usr/bin/env python3
"""把「上线记录」工件从临时项目迁到相关的现有项目下（MiMo 匹配 + 图谱关联）。

流程：
  Phase A（匹配）：
    - 每个发布计划的「服务名称」→ Repository（名称/尾段精确匹配，确定性）
    - 候选项目 = 名称相似项目（bigram 相似度 top8）+ 匹配仓库经 ProjectBranch
      绑定的项目（绑定过多的仓库不参与，无区分度）
    - MiMo 批量裁决：每计划选最佳项目或 null → /tmp/release-match-plan.json
  Phase B（应用）：
    - artifact.project 迁移 + KnowledgeEntity.space_id 同步
    - content_ref 追加「归属项目/关联仓库」行（content hash 变化 → 版本翻转，
      重摄取刷新向量 payload.project_id 与 REFERENCES 边）
    - 失效指向旧「上线记录」项目节点的 REFERENCES 边
    - 追加 artifact → repo 的 RELATES_TO 边（metadata.source=release_bitable_import，
      避开 artifact 路由收敛逻辑）
  未匹配的工件留在原项目（改名「未归类上线记录」），数量见报告。

Run from server/:
  uv run python ../.planning/quick/260807-release-bitable-import/rehome_release_artifacts.py [--apply-only|--match-only]
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

from django.contrib.auth import get_user_model  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from agents.call_source import CallSource, use_call_source  # noqa: E402
from agents.llm_factory import build_chat_model, content_to_text  # noqa: E402
from initiatives.models import Artifact, ArtifactType, Project, ProjectBranch  # noqa: E402
from repositories.models import Repository  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

CACHE = Path("/tmp/release-bitable-records.json")
MATCH_PATH = Path("/tmp/release-match-plan.json")
REPORT = Path("/tmp/release-rehome-report.json")
MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
OLD_PROJECT_KEY = "release-bitable:CFQCbbtoVaEhT8sM9XPcPvExnGe:tbls2oct7kJNjXtf"
# 绑定项目数超过此阈值的仓库对匹配无区分度，不产候选
REPO_BINDING_CAP = 10
NAME_CANDIDATES = 8
# 批次要小：mimo-v2.5-pro 是推理模型，思考 token 计入 max_output_tokens，
# 25 条/批 + 3000 上限会截断 JSON → 整批解析失败归零（首轮 5-8% 匹配率的另一半根因）
MIMO_BATCH = 10
MIMO_MAX_TOKENS = 8000  # 模型硬上限 8192，超过直接被参数校验拒


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or value.get("name") or "").strip()
    if isinstance(value, list):
        return "、".join(p for p in (_text(v) for v in value) if p)
    return str(value)


def _plan_of(fields: dict) -> str:
    return re.sub(r"\s+", " ", _text(fields.get("发布计划名称"))).strip()


_DECOR = re.compile(r"[\s:：\-_/\[\]【】()（）\.\d]+")


def _bigrams(s: str) -> set[str]:
    s = _DECOR.sub("", s.lower())
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s} if s else set()


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


async def phase_match() -> dict[str, Any]:
    records = json.loads(CACHE.read_text())
    plans: dict[str, dict[str, Any]] = {}
    for r in records:
        fields = r.get("fields", {}) or {}
        plan = _plan_of(fields) or "(无发布计划)"
        node = plans.setdefault(plan, {"biz": set(), "services": set()})
        biz = _text(fields.get("上线业务"))
        if biz:
            node["biz"].add(biz)
        svcs = fields.get("服务名称")
        if isinstance(svcs, list):
            node["services"].update(str(s) for s in svcs if s)

    # 仓库目录：全名 + 尾段索引
    repos = [(str(rid), name) async for rid, name in Repository.objects.values_list("id", "name")]
    by_name: dict[str, list[str]] = defaultdict(list)
    for rid, name in repos:
        by_name[name.lower()].append(rid)
        tail = name.split("/")[-1].lower()
        if tail != name.lower():
            by_name[tail].append(rid)

    # 项目目录（排除旧临时项目）+ 仓库→项目绑定
    old_project = await Project.objects.filter(feishu_project_key=OLD_PROJECT_KEY).afirst()
    projects = [
        (str(pid), name)
        async for pid, name in Project.objects.exclude(
            id=old_project.id if old_project else None
        ).values_list("id", "name")
    ]
    proj_names = {pid: name for pid, name in projects}
    # IDF 加权 bigram 倒排索引：低频词（如「习题」「背诵」）对归属判定信号强，
    # min 归一化相似度会把只共享一个核心词的能力簇项目滤掉（上一轮 5% 匹配率的根因）。
    import math

    gram_postings: dict[str, list[str]] = defaultdict(list)
    for pid, name in projects:
        for g in _bigrams(name):
            gram_postings[g].append(pid)
    n_projects = max(1, len(projects))
    gram_idf = {
        g: math.log(n_projects / len(pids)) for g, pids in gram_postings.items()
    }

    repo_projects: dict[str, list[str]] = defaultdict(list)
    async for repo_id, project_id in ProjectBranch.objects.values_list(
        "repository_id", "project_id"
    ):
        if old_project and str(project_id) == str(old_project.id):
            continue
        repo_projects[str(repo_id)].append(str(project_id))

    matches: dict[str, dict[str, Any]] = {}
    mimo_queue: list[dict[str, Any]] = []
    for plan, node in plans.items():
        services = sorted(node["services"])
        biz = "；".join(sorted(node["biz"]))[:200]
        repo_ids: list[str] = []
        for svc in services:
            repo_ids.extend(by_name.get(svc.lower(), []))
        repo_ids = sorted(set(repo_ids))

        cand: dict[str, float] = {}
        # 仓库绑定候选（低区分度仓库跳过）
        for rid in repo_ids:
            bound = repo_projects.get(rid, [])
            if 0 < len(bound) <= REPO_BINDING_CAP:
                for pid in bound:
                    cand[pid] = max(cand.get(pid, 0), 1.0)
        # 名称候选：IDF 加权共享 bigram（共享一个「习题」这类低频核心词即可入围；
        # 上一轮 min 归一化 + 0.25 阈值把能力簇项目全滤掉，是 5% 匹配率的根因）
        grams = _bigrams(plan.split(":", 1)[-1] + " " + biz)
        name_scores: dict[str, float] = defaultdict(float)
        for g in grams:
            idf = gram_idf.get(g)
            if idf is None or idf < 1.0:  # 高频装饰词（项目/组件/优化…）不计
                continue
            for pid in gram_postings[g]:
                name_scores[pid] += idf
        for pid, score in sorted(name_scores.items(), key=lambda x: x[1], reverse=True)[
            :NAME_CANDIDATES
        ]:
            cand[pid] = max(cand.get(pid, 0), score)

        matches[plan] = {"repo_ids": repo_ids, "project_id": None, "via": ""}
        if cand:
            mimo_queue.append(
                {
                    "plan": plan,
                    "biz": biz,
                    "services": services[:10],
                    "candidates": sorted(cand, key=cand.get, reverse=True)[:15],
                }
            )

    print(f"plans={len(plans)} with_candidates={len(mimo_queue)}")

    # MiMo 批量裁决（并发，信号量限流）
    sem = asyncio.Semaphore(6)
    done_count = 0

    async def _judge_chunk(chunk: list[dict[str, Any]]) -> None:
        nonlocal done_count
        items = [
            {
                "id": str(idx),
                "发布计划": item["plan"][:120],
                "上线业务": item["biz"][:150],
                "服务": item["services"],
                "候选项目": [
                    {"pid": pid, "name": proj_names.get(pid, "")[:60]}
                    for pid in item["candidates"]
                ],
            }
            for idx, item in enumerate(chunk)
        ]
        prompt = (
            "你是发布记录归属分类器。对每条上线发布计划，从候选项目中选出它最应归属的产品项目。\n"
            "判定规则：\n"
            "1. 发布计划通常是某产品能力的一次迭代/灰度/修复，归属到该能力的项目或能力簇项目"
            "（如「习题 4.0 灰度」→「题型及习题组件梳理」、「错题本 bug 修复」→ 错题本相关项目）。\n"
            "2. 优先选能力最贴合的；具体方案项目与能力簇项目都在时选更贴合的那个。\n"
            "3. 纯基建升级（golang 升级、K8S 配置）或与所有候选无关时填 null。\n"
            '只返回 JSON 对象：{"<id>": "<pid>" 或 null}，不要解释。\n\n'
            + json.dumps(items, ensure_ascii=False)
        )
        async with sem:
            raw = await _call_mimo(prompt, max_tokens=MIMO_MAX_TOKENS)
        picked: dict[str, Any] = {}
        if raw:
            m = re.search(r"\{[\s\S]*\}", raw)
            if m:
                try:
                    picked = json.loads(m.group(0))
                except json.JSONDecodeError:
                    print("PARSE FAIL:", raw[:200].replace("\n", " "))
        else:
            print("EMPTY RAW (call failed or truncated)")
        for idx, item in enumerate(chunk):
            pid = picked.get(str(idx))
            if pid and str(pid) in proj_names:
                matches[item["plan"]]["project_id"] = str(pid)
                matches[item["plan"]]["via"] = "mimo"
        done_count += len(chunk)
        print(f"mimo {done_count}/{len(mimo_queue)}")

    await asyncio.gather(
        *(
            _judge_chunk(mimo_queue[i : i + MIMO_BATCH])
            for i in range(0, len(mimo_queue), MIMO_BATCH)
        )
    )

    MATCH_PATH.write_text(json.dumps(matches, ensure_ascii=False))
    matched = sum(1 for v in matches.values() if v["project_id"])
    print(f"MATCH DONE matched={matched}/{len(matches)} -> {MATCH_PATH}")
    return matches


async def phase_apply(matches: dict[str, Any]) -> None:
    from asgiref.sync import sync_to_async

    from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService
    from knowledge import ingestion
    from knowledge.graph_store import graph_store
    from knowledge.models import (
        EdgeRelation,
        EntityKind,
        KnowledgeEntity,
        generate_entity_id,
    )
    from knowledge.sources import artifact as artifact_source

    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()

    old_project = await Project.objects.select_related("space").aget(
        feishu_project_key=OLD_PROJECT_KEY
    )
    atype = await ArtifactType.objects.aget(key="release_record")
    old_node_id = generate_entity_id(EntityKind.PROJECT, "project", str(old_project.id))

    projects_cache: dict[str, Project] = {}
    repos_cache: dict[str, Repository] = {}

    async def _no_route(**kwargs):  # noqa: ANN003
        return ()

    artifact_source._route_artifact_body_edges = _no_route  # type: ignore[assignment]
    graph_svc = ProjectKnowledgeGraphService()

    report = {"moved": 0, "unmatched": 0, "repo_edges": 0, "errors": []}
    arts = [
        a
        async for a in Artifact.objects.filter(project_id=old_project.id, type_id=atype.id)
    ]
    print("artifacts to process:", len(arts))

    from django.utils import timezone

    for i, art in enumerate(arts, 1):
        info = matches.get(art.title) or {}
        target_pid = info.get("project_id")
        repo_ids = info.get("repo_ids") or []
        try:
            if not target_pid:
                report["unmatched"] += 1
                continue
            if target_pid not in projects_cache:
                projects_cache[target_pid] = await Project.objects.select_related(
                    "space"
                ).aget(id=target_pid)
            target = projects_cache[target_pid]

            repo_names = []
            for rid in repo_ids:
                if rid not in repos_cache:
                    r = await Repository.objects.filter(id=rid).afirst()
                    if r is None:
                        continue
                    repos_cache[rid] = r
                repo_names.append(repos_cache[rid].name)

            # 1) 迁移归属 + 正文追加（hash 变化 → 重摄取翻版本）
            extra = [f"\n## 关联\n", f"- 归属项目：{target.name}"]
            if repo_names:
                extra.append(f"- 关联仓库：{'、'.join(sorted(repo_names))}")
            art.project = target
            art.content_ref = (art.content_ref or "") + "\n".join(extra) + "\n"
            await art.asave(update_fields=["project", "content_ref", "updated_at"])

            # 2) 知识实体空间同步（get_or_create 不刷已有实体的 space）
            entity_id = generate_entity_id(EntityKind.DOCUMENT, "artifact", str(art.id))
            await KnowledgeEntity.objects.filter(id=entity_id).aupdate(
                space_id=target.space_id
            )

            # 3) 重摄取：刷新向量 payload.project_id + REFERENCES→新项目节点边
            await ingestion.ingest(
                ingestion.IngestionRequest(
                    source_kind="artifact",
                    source_id=str(art.id),
                    trigger="release_rehome",
                )
            )

            # 4) 失效指向旧项目节点的 REFERENCES 边
            now = timezone.now()
            for edge in await graph_store.neighbors(
                entity_id, relations=[EdgeRelation.REFERENCES], direction="out"
            ):
                if edge.target_id == old_node_id:
                    await graph_store.invalidate_edge(edge.edge_id, invalid_at=now)

            # 5) artifact → repo RELATES_TO 边（确定性，来源标记避开路由收敛）
            specs = []
            for rid in repo_ids:
                repo = repos_cache.get(rid)
                if repo is None:
                    continue
                repo_node = await graph_svc.ensure_repository_node(repo)
                specs.append(
                    ingestion.EdgeSpec(
                        relation=EdgeRelation.RELATES_TO,
                        target_entity_id=repo_node,
                        metadata={
                            "source": "release_bitable_import",
                            "artifact_id": str(art.id),
                            "services": True,
                            "score": 1.0,
                        },
                    )
                )
            if specs:
                await ingestion.apply_edge_specs(
                    entity_id, tuple(specs), event_time=now
                )
                report["repo_edges"] += len(specs)

            report["moved"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(
                {"artifact": str(art.id), "title": art.title[:60], "error": f"{type(exc).__name__}: {exc}"}
            )
        if i % 100 == 0:
            print(
                f"apply {i}/{len(arts)} moved={report['moved']} "
                f"unmatched={report['unmatched']} errors={len(report['errors'])}"
            )

    # 收尾：旧项目改名（留未匹配工件），若已空则提示可删
    remaining = await Artifact.objects.filter(project_id=old_project.id).acount()
    if remaining:
        old_project.name = "未归类上线记录"
        old_project.description = (
            "MiMo 无法归属到具体产品项目的上线记录（多为跨服务基建/日常 bugfix/杂项）。"
            + old_project.description
        )
        await old_project.asave(update_fields=["name", "description", "updated_at"])
        print(f"old project renamed -> 未归类上线记录 (remaining={remaining})")
    else:
        print("old project is empty, can be deleted")

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT ->", REPORT)
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, ensure_ascii=False))
    print("errors:", len(report["errors"]))
    print("ALL DONE")


LOCK = Path("/tmp/release-rehome.lock")


async def main() -> None:
    # 防并发：启动重试故障可能同时拉起多个实例（O_EXCL 原子抢锁）
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        print(f"another instance holds {LOCK}, exit")
        return
    try:
        if "--apply-only" in sys.argv:
            matches = json.loads(MATCH_PATH.read_text())
        else:
            matches = await phase_match()
            if "--match-only" in sys.argv:
                return
        await phase_apply(matches)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
