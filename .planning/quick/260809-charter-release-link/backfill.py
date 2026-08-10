#!/usr/bin/env python3
"""全量回填：上线记录→仓库挂边 + mimo 起草仓库章程。

Phase A — 确定性挂仓：解析正文「服务 / 关联仓库」→ Repository 名/尾段精确匹配。
Phase B — mimo 服务别名：对未命中的唯一服务名批量裁决 → 仓库 id 或 null，再落边。
Phase C — mimo 起草章程：有摘要的仓并发调用 adraft_charter（走 acquire_llm_slot）。

并发：mimo 凭证 max_concurrency + 本地 Semaphore（默认 8）双保险。
幂等：RELATES_TO 边按 target 去重；章程仍是 ai_draft 就地更新。

Run from server/:
  uv run python ../.planning/quick/260809-charter-release-link/backfill.py
  uv run python ../.planning/quick/260809-charter-release-link/backfill.py --link-only
  uv run python ../.planning/quick/260809-charter-release-link/backfill.py --charter-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
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
from django.utils import timezone  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from agents.call_source import CallSource, use_call_source  # noqa: E402
from agents.llm_concurrency import acquire_llm_slot  # noqa: E402
from agents.llm_factory import build_chat_model, content_to_text  # noqa: E402
from initiatives.services.knowledge_graph import ProjectKnowledgeGraphService  # noqa: E402
from knowledge import ingestion  # noqa: E402
from knowledge.models import (  # noqa: E402
    EdgeRelation,
    KnowledgeEdge,
    KnowledgeEntityVersion,
)
from repositories.models import Repository  # noqa: E402
from repositories.services.charter_service import adraft_charter  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent
ALIAS_PATH = OUT_DIR / "service-alias-map.json"
REPORT_PATH = OUT_DIR / "backfill-report.json"
LOCK = Path("/tmp/charter-release-backfill.lock")

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
# 推理模型：别名批不宜太大，思考 token 吃预算
ALIAS_BATCH = 40
CHARTER_CONCURRENCY = 8
# ⭐ 必须是 "artifact"：artifact_associations.py 正反向关联查询硬过滤该值，
# 自造来源名会让边写进去但在关联卡片里永远不可见。原来源留在 origin 里。
EDGE_SOURCE = "artifact"
EDGE_ORIGIN = "release_bitable_import"

_SVC_RE = re.compile(r"(?:服务|关联仓库)[：:]\s*([^\n]+)")
_SPLIT_RE = re.compile(r"[,，、/;；\|]+")


def _parts(raw: str) -> list[str]:
    out: list[str] = []
    for part in _SPLIT_RE.split(raw or ""):
        part = part.strip()
        if part and part not in {"无", "-", "—", "暂无"}:
            out.append(part)
    return out


def _build_repo_index(
    repos: list[Repository],
) -> tuple[dict[str, str], dict[str, str]]:
    """返回 (lookup_key→repo_id, repo_id→name)。"""
    by_key: dict[str, str] = {}
    by_id: dict[str, str] = {}
    for repo in repos:
        rid = str(repo.id)
        name = (repo.name or "").strip()
        by_id[rid] = name or rid
        if name:
            by_key[name.lower()] = rid
            by_key[name.lower().split("/")[-1]] = rid
        url = (repo.git_url or "").rstrip("/").removesuffix(".git")
        if url:
            segs = url.split("/")
            by_key[segs[-1].lower()] = rid
            if len(segs) >= 2:
                by_key[f"{segs[-2]}/{segs[-1]}".lower()] = rid
    return by_key, by_id


def _resolve_keys(keys: list[str], by_key: dict[str, str], alias: dict[str, str]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for key in keys:
        low = key.lower()
        rid = by_key.get(low) or by_key.get(low.split("/")[-1]) or alias.get(key) or alias.get(low)
        if rid and rid not in seen:
            seen.add(rid)
            ids.append(rid)
    return ids


async def _call_mimo(prompt: str, *, max_tokens: int = 8000) -> str | None:
    resolved = await ProviderConfigService.aresolve_or_error(
        node_config={"provider_credential_id": MIMO_CREDENTIAL_ID}
    )
    if isinstance(resolved, ProviderMissingError):
        print("MIMO missing:", resolved)
        return None
    model = build_chat_model(
        resolved,
        MIMO_MODEL,
        streaming=False,
        max_output_tokens=max_tokens,
        temperature=0.1,
    )
    cred_id = str(resolved.credential_id or MIMO_CREDENTIAL_ID)
    max_c = int(resolved.max_concurrency or 0)
    with use_call_source(CallSource.BLUEPRINT_CHARTER_DRAFT):
        async with acquire_llm_slot(cred_id, max_c):
            resp = await model.ainvoke([HumanMessage(content=prompt)])
    return content_to_text(getattr(resp, "content", resp))


def _parse_json_obj(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    text = text.strip()
    # 推理模型可能夹杂思考；抓最后一个 JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


async def _linked_entity_ids() -> set[Any]:
    return set(
        await sync_to_async(
            lambda: list(
                KnowledgeEdge.objects.filter(
                    relation=EdgeRelation.RELATES_TO,
                    invalid_at__isnull=True,
                    expired_at__isnull=True,
                    metadata__source=EDGE_SOURCE,
                ).values_list("source_entity_id", flat=True)
            )
        )()
    )


async def _release_versions() -> list[KnowledgeEntityVersion]:
    return await sync_to_async(
        lambda: list(
            KnowledgeEntityVersion.objects.filter(
                is_latest=True, payload__type="release_record"
            ).select_related("entity")
        )
    )()


async def _apply_edges(
    entity_id: Any,
    repo_ids: list[str],
    *,
    repos_by_id: dict[str, Repository],
    graph_svc: ProjectKnowledgeGraphService,
) -> int:
    if not repo_ids:
        return 0
    specs = []
    now = timezone.now()
    for rid in repo_ids:
        repo = repos_by_id.get(rid)
        if repo is None:
            continue
        node = await graph_svc.ensure_repository_node(repo)
        specs.append(
            ingestion.EdgeSpec(
                relation=EdgeRelation.RELATES_TO,
                target_entity_id=node,
                metadata={
                    "source": EDGE_SOURCE,
                    "origin": EDGE_ORIGIN,
                    "score": 1.0,
                    "linker": "backfill_260809",
                },
            )
        )
    if not specs:
        return 0
    await ingestion.apply_edge_specs(entity_id, tuple(specs), event_time=now)
    return len(specs)


async def phase_link(report: dict[str, Any]) -> dict[str, str]:
    print("=== Phase A/B: link release → repo ===")
    repos = await sync_to_async(lambda: list(Repository.objects.all()))()
    by_key, by_id_name = _build_repo_index(repos)
    repos_by_id = {str(r.id): r for r in repos}
    alias: dict[str, str] = {}
    if ALIAS_PATH.exists():
        try:
            raw = json.loads(ALIAS_PATH.read_text())
            if isinstance(raw, dict):
                alias = {str(k): str(v) for k, v in raw.items() if v}
        except json.JSONDecodeError:
            alias = {}

    linked = await _linked_entity_ids()
    versions = await _release_versions()
    graph_svc = ProjectKnowledgeGraphService()

    unmatched_services: dict[str, int] = defaultdict(int)
    pending: list[tuple[Any, list[str], str]] = []  # entity_id, service keys, title
    det_linked = 0
    edges_added = 0

    for ver in versions:
        eid = ver.entity_id
        if eid in linked:
            continue
        text = ver.content or ""
        keys: list[str] = []
        for m in _SVC_RE.finditer(text):
            keys.extend(_parts(m.group(1)))
        # 去重保序
        seen: set[str] = set()
        uniq_keys = []
        for k in keys:
            if k not in seen:
                seen.add(k)
                uniq_keys.append(k)
        ids = _resolve_keys(uniq_keys, by_key, alias)
        if ids:
            n = await _apply_edges(eid, ids, repos_by_id=repos_by_id, graph_svc=graph_svc)
            edges_added += n
            det_linked += 1
            linked.add(eid)
        else:
            title = (getattr(ver.entity, "title", None) or "")[:120]
            pending.append((eid, uniq_keys, title))
            for k in uniq_keys:
                unmatched_services[k] += 1

    print(f"deterministic linked={det_linked} edges+={edges_added} remaining={len(pending)}")
    report["deterministic_linked"] = det_linked
    report["deterministic_edges"] = edges_added

    # Phase B: mimo alias map for unique unmatched services
    services = sorted(unmatched_services.keys(), key=lambda s: (-unmatched_services[s], s))
    print(f"unique unmatched services={len(services)}")
    repo_catalog = "\n".join(f"- {rid}: {name}" for rid, name in sorted(by_id_name.items(), key=lambda x: x[1]))

    new_alias: dict[str, str | None] = {}
    for i in range(0, len(services), ALIAS_BATCH):
        batch = services[i : i + ALIAS_BATCH]
        prompt = (
            "你是仓库归属助手。把「上线记录里的服务名」映射到 Friday 已索引仓库。\n"
            "只输出 JSON 对象：键=服务名，值=仓库 UUID 字符串，或 null（库里没有对应仓）。\n"
            "不要解释，不要 Markdown。\n\n"
            f"## 候选仓库（id: name）\n{repo_catalog}\n\n"
            "## 待映射服务名\n"
            + "\n".join(f"- {s}（出现 {unmatched_services[s]} 次）" for s in batch)
        )
        print(f"mimo alias batch {i // ALIAS_BATCH + 1}/{(len(services) + ALIAS_BATCH - 1) // ALIAS_BATCH} size={len(batch)}")
        text = await _call_mimo(prompt, max_tokens=8000)
        data = _parse_json_obj(text)
        for svc in batch:
            val = data.get(svc)
            if isinstance(val, str) and val in by_id_name:
                new_alias[svc] = val
            else:
                new_alias[svc] = None
        # 轻微歇口气，避免打爆上游
        await asyncio.sleep(0.2)

    # merge alias（只保留命中）
    for k, v in new_alias.items():
        if v:
            alias[k] = v
    ALIAS_PATH.write_text(json.dumps(alias, ensure_ascii=False, indent=2))
    print(f"alias hits={sum(1 for v in new_alias.values() if v)} miss={sum(1 for v in new_alias.values() if not v)} -> {ALIAS_PATH}")

    # re-apply with alias
    alias_linked = 0
    alias_edges = 0
    still = 0
    for eid, keys, _title in pending:
        if eid in linked:
            continue
        ids = _resolve_keys(keys, by_key, alias)
        if ids:
            n = await _apply_edges(eid, ids, repos_by_id=repos_by_id, graph_svc=graph_svc)
            alias_edges += n
            alias_linked += 1
            linked.add(eid)
        else:
            still += 1

    print(f"alias linked={alias_linked} edges+={alias_edges} still_unlinked={still}")
    report["alias_linked"] = alias_linked
    report["alias_edges"] = alias_edges
    report["still_unlinked"] = still
    report["alias_hit_services"] = sum(1 for v in new_alias.values() if v)
    report["alias_miss_services"] = sum(1 for v in new_alias.values() if not v)
    return alias


async def phase_charter(report: dict[str, Any]) -> None:
    print("=== Phase C: draft charters with mimo ===")
    repos = await sync_to_async(
        lambda: list(
            Repository.objects.filter(ai_summary_status="completed").order_by("name")
        )
    )()
    print(f"repos with completed summary: {len(repos)}")
    sem = asyncio.Semaphore(CHARTER_CONCURRENCY)
    ok = 0
    fail = 0
    errors: list[dict[str, str]] = []
    started = time.monotonic()
    lock = asyncio.Lock()

    async def _one(repo: Repository, idx: int) -> None:
        nonlocal ok, fail
        async with sem:
            try:
                charter = await adraft_charter(
                    str(repo.id),
                    initiated_by_user_id="system",
                    provider_credential_id=MIMO_CREDENTIAL_ID,
                    model=MIMO_MODEL,
                )
                async with lock:
                    if charter is None:
                        fail += 1
                        errors.append({"repo": repo.name, "id": str(repo.id), "error": "None"})
                    else:
                        ok += 1
                    done = ok + fail
                    if done % 10 == 0 or done == len(repos):
                        elapsed = time.monotonic() - started
                        print(
                            f"charter {done}/{len(repos)} ok={ok} fail={fail} "
                            f"elapsed={elapsed:.0f}s"
                        )
            except Exception as exc:  # noqa: BLE001
                async with lock:
                    fail += 1
                    errors.append(
                        {
                            "repo": repo.name or "",
                            "id": str(repo.id),
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                        }
                    )

    await asyncio.gather(*[_one(r, i) for i, r in enumerate(repos)])
    report["charter_ok"] = ok
    report["charter_fail"] = fail
    report["charter_errors"] = errors[:50]
    print(f"charter done ok={ok} fail={fail}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--link-only", action="store_true")
    parser.add_argument("--charter-only", action="store_true")
    args = parser.parse_args()

    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
    except FileExistsError:
        print(f"another instance holds {LOCK}, exit")
        return

    report: dict[str, Any] = {"started_at": timezone.now().isoformat()}
    try:
        if not args.charter_only:
            await phase_link(report)
        if not args.link_only:
            await phase_charter(report)
        report["finished_at"] = timezone.now().isoformat()
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print("REPORT ->", REPORT_PATH)
        print(json.dumps({k: v for k, v in report.items() if k != "charter_errors"}, ensure_ascii=False))
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
