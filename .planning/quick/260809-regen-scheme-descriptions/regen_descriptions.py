#!/usr/bin/env python3
"""用 MiMo 为 ricelove-scheme 项目重写描述（替换「从能力簇…拆出」占位文案）。

材料优先级：feature_list（模块/功能点名）> 能力簇描述 > 关联文档标题。
生成后保留「源文档：URL」行以便追溯。

Run from server/:
  uv run python ../.planning/quick/260809-regen-scheme-descriptions/regen_descriptions.py --dry-run --limit 3
  uv run python ../.planning/quick/260809-regen-scheme-descriptions/regen_descriptions.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

import django

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from agents.call_source import CallSource, use_call_source  # noqa: E402
from agents.llm_factory import build_chat_model, content_to_text  # noqa: E402
from initiatives.models import Artifact, Project  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
REPORT_PATH = Path("/tmp/ricelove-regen-desc-report.json")
PLACEHOLDER_RE = re.compile(r"^从能力簇「([^」]+)」")
SOURCE_RE = re.compile(r"源文档：(\S+)")

SYSTEM_PROMPT = """你是资深产品经理，为内部研发项目管理系统撰写项目描述。
根据给定材料，为项目写一段中文描述，要求：
1. 100～250 字，纯文本，不要 markdown 标题/列表/代码块。
2. 第一句说清这个项目做什么（面向谁、解决什么问题）；后面概括核心功能范围。
3. 只依据材料归纳，禁止臆造材料里没有的业务细节、数据或指标。
4. 不要出现「本项目」「该项目」以外的套话（如"旨在""致力于"），直接陈述。
5. 只输出描述正文，不要任何前后缀或解释。"""


async def _call_mimo(messages: list[Any], *, max_tokens: int = 4096) -> str | None:
    resolved = await ProviderConfigService.aresolve_or_error(
        node_config={"provider_credential_id": MIMO_CREDENTIAL_ID}
    )
    if isinstance(resolved, ProviderMissingError):
        print("MIMO missing:", resolved)
        return None
    with use_call_source(CallSource.AUX_CRAWL.value):
        try:
            model = build_chat_model(
                resolved, MIMO_MODEL, max_output_tokens=max_tokens, streaming=False, temperature=0.3
            )
            msg = await model.ainvoke(messages)
            return content_to_text(getattr(msg, "content", "")).strip()
        except Exception as exc:  # noqa: BLE001
            print("mimo call failed", type(exc).__name__, str(exc)[:200])
            return None


def _feature_list_digest(content_ref: str | None, *, max_chars: int = 3500) -> str:
    """把 feature_list JSON 压缩成「模块 - 功能点」清单文本。"""
    if not content_ref:
        return ""
    try:
        data = json.loads(content_ref)
    except json.JSONDecodeError:
        return ""
    lines: list[str] = []
    for mod in data.get("modules") or []:
        if not isinstance(mod, dict):
            continue
        lines.append(f"- {mod.get('module') or ''}")
        for f in mod.get("features") or []:
            if isinstance(f, dict) and f.get("name"):
                lines.append(f"  - {f['name']}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n…（已截断）"
    return text


@sync_to_async
def _list_targets(name_filter: str | None) -> list[dict[str, Any]]:
    qs = Project.objects.filter(
        feishu_project_key__startswith="ricelove-scheme:",
        description__startswith="从能力簇",
    ).order_by("name")
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    clusters_by_name = {
        p.name: (p.description or "")
        for p in Project.objects.filter(feishu_project_key__startswith="ricelove:")
    }
    out = []
    for p in qs:
        desc = p.description or ""
        m = PLACEHOLDER_RE.search(desc)
        cluster_name = m.group(1) if m else ""
        src = SOURCE_RE.search(desc)
        source_url = src.group(1) if src else ""
        cluster_desc = clusters_by_name.get(cluster_name, "")
        # 能力簇容器描述里拆出的项目列表对生成没帮助，截掉
        cluster_desc = cluster_desc.split("【能力簇容器】")[0].strip()[:1200]
        fl = (
            Artifact.objects.filter(project=p, type__key="feature_list")
            .values_list("content_ref", flat=True)
            .first()
        )
        art_titles = list(
            Artifact.objects.filter(project=p)
            .exclude(type__key="feature_list")
            .values_list("title", flat=True)[:20]
        )
        out.append(
            {
                "id": str(p.id),
                "name": p.name,
                "cluster_name": cluster_name,
                "cluster_desc": cluster_desc,
                "source_url": source_url,
                "fl_digest": _feature_list_digest(fl),
                "art_titles": art_titles,
            }
        )
    return out


@sync_to_async
def _save_description(project_id: str, desc: str) -> None:
    Project.objects.filter(id=project_id).update(description=desc[:8000])


def _build_prompt(item: dict[str, Any]) -> str:
    parts = [f"项目名：{item['name']}"]
    if item["cluster_name"]:
        parts.append(f"所属能力簇：{item['cluster_name']}")
    if item["cluster_desc"]:
        parts.append(f"能力簇背景：\n{item['cluster_desc']}")
    if item["fl_digest"]:
        parts.append(f"功能清单（模块与功能点）：\n{item['fl_digest']}")
    if item["art_titles"]:
        titles = "\n".join(f"- {t}" for t in item["art_titles"])
        parts.append(f"关联文档标题：\n{titles}")
    return "\n\n".join(parts)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="", help="按项目名包含过滤")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=不限）")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = await _list_targets(args.filter or None)
    if args.limit > 0:
        targets = targets[: args.limit]
    print(f"targets={len(targets)} filter={args.filter!r} dry_run={args.dry_run}", flush=True)

    report: dict[str, Any] = {"ok": 0, "failed": 0, "items": []}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(max(1, args.concurrency))
    total = len(targets)
    done_n = 0

    async def _one(i: int, item: dict[str, Any]) -> None:
        nonlocal done_n
        async with sem:
            raw = await _call_mimo(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=_build_prompt(item)),
                ]
            )
            text = (raw or "").strip()
            # 防御：模型偶尔套引号/代码块
            text = text.strip("`\"' \n")
            ok = 60 <= len(text) <= 600
            if ok:
                new_desc = text
                if item["source_url"]:
                    new_desc += f"\n\n源文档：{item['source_url']}"
                if not args.dry_run:
                    await _save_description(item["id"], new_desc)
            async with lock:
                done_n += 1
                if ok:
                    report["ok"] += 1
                    report["items"].append(
                        {"id": item["id"], "name": item["name"], "desc": text}
                    )
                    print(f"[{done_n}/{total}] OK {item['name'][:50]}", flush=True)
                    if args.dry_run:
                        print(f"  {text[:160]}", flush=True)
                else:
                    report["failed"] += 1
                    report["items"].append(
                        {
                            "id": item["id"],
                            "name": item["name"],
                            "status": "failed",
                            "raw_preview": text[:200],
                        }
                    )
                    print(f"[{done_n}/{total}] FAIL {item['name'][:50]} len={len(text)}", flush=True)

    await asyncio.gather(*[_one(i, item) for i, item in enumerate(targets, 1)])

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"SUMMARY ok={report['ok']} failed={report['failed']}", flush=True)
    print("report ->", REPORT_PATH, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
