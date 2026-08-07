#!/usr/bin/env python3
"""用 MiMo 为 ricelove-scheme 项目补齐 feature_list（格式对齐「高三提分专项」）。

Run from server/:
  # 先验证新用户引导相关
  uv run python ../.planning/quick/260807-ricelove-import/fill_feature_lists.py --filter 新用户引导
  # 全量
  uv run python ../.planning/quick/260807-ricelove-import/fill_feature_lists.py
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
from django.contrib.auth import get_user_model  # noqa: E402
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from agents.call_source import CallSource, use_call_source  # noqa: E402
from agents.llm_factory import build_chat_model, content_to_text  # noqa: E402
from initiatives.models import Artifact, Project  # noqa: E402
from initiatives.services.feature_list_service import FeatureListService  # noqa: E402
from services.provider_config import ProviderConfigService, ProviderMissingError  # noqa: E402

MIMO_CREDENTIAL_ID = "bcbdd68d-a7b8-4bdf-bb16-66a993588041"
MIMO_MODEL = "mimo-v2.5-pro"
REPORT_PATH = Path("/tmp/ricelove-feature-list-report.json")
MAX_PRD_CHARS = 28000

SYSTEM_PROMPT = """你是资深产品经理，负责把 PRD/方案文档整理成 Friday 的 feature list。
必须严格输出一个 JSON 对象，不要 markdown 代码块、不要解释。

JSON schema：
{
  "modules": [
    {
      "module": "模块 N：模块名",
      "features": [
        {
          "name": "功能点短名（不要带「功能点 A：」前缀更好）",
          "acceptance": [
            "- [ ] **当** … **时**，系统应…",
            "测试数据：…",
            "- [ ] **如果** …，**那么** 系统应…"
          ],
          "source": "#### 功能点 X：标题\\n\\n- **功能描述**：…\\n- **交互逻辑**：…\\n- **业务规则与约束**：\\n  - …\\n- **影响范围**：…"
        }
      ]
    }
  ]
}

写作要求（对齐「高三提分专项」样例）：
1. 按用户可感知的功能模块拆分，模块名形如「模块 1：xxx」。
2. 每个功能点必须有 acceptance（Given/When/Then 口吻的勾选项 + 测试数据行可穿插）。
3. source 用 markdown，含功能描述 / 交互逻辑 / 业务规则与约束 / 影响范围（可按材料取舍，勿编造不存在的 ID/接口）。
4. 只依据给定材料归纳；材料不足时少写、标「待补充」，禁止臆造业务细节。
5. 不要输出技术方案实现细节（类名、表结构等），聚焦产品功能与验收。
"""


async def _call_mimo(messages: list[Any], *, max_tokens: int = 8192) -> str | None:
    resolved = await ProviderConfigService.aresolve_or_error(
        node_config={"provider_credential_id": MIMO_CREDENTIAL_ID}
    )
    if isinstance(resolved, ProviderMissingError):
        print("MIMO missing:", resolved)
        return None
    with use_call_source(CallSource.FEATURE_LIST_PARSE.value):
        try:
            model = build_chat_model(
                resolved, MIMO_MODEL, max_output_tokens=max_tokens, streaming=False, temperature=0.2
            )
            msg = await model.ainvoke(messages)
            return content_to_text(getattr(msg, "content", "")).strip()
        except Exception as exc:  # noqa: BLE001
            print("mimo call failed", type(exc).__name__, str(exc)[:240])
            return None


def _parse_modules(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return []
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        # try trim trailing junk
        text = m.group(0)
        for end in range(len(text), max(len(text) - 500, 0), -1):
            try:
                data = json.loads(text[:end])
                break
            except json.JSONDecodeError:
                data = None
        if not data:
            return []
    modules = data.get("modules") if isinstance(data, dict) else None
    return modules if isinstance(modules, list) else []


@sync_to_async
def _load_reference_sample() -> str:
    a = Artifact.objects.filter(
        project__name="高三提分专项", type__key="feature_list"
    ).first()
    if not a or not a.content_ref:
        return ""
    data = json.loads(a.content_ref)
    modules = data.get("modules") or []
    # 只取前 1 个模块作格式样例，并截断 source
    sample_mods = []
    for mod in modules[:1]:
        feats = []
        for f in (mod.get("features") or [])[:2]:
            src = str(f.get("source") or "")
            if len(src) > 600:
                src = src[:600] + "…"
            feats.append(
                {
                    "name": f.get("name"),
                    "acceptance": (f.get("acceptance") or [])[:4],
                    "source": src,
                }
            )
        sample_mods.append({"module": mod.get("module"), "features": feats})
    return json.dumps({"modules": sample_mods}, ensure_ascii=False)


@sync_to_async
def _list_targets(name_filter: str | None) -> list[dict[str, Any]]:
    qs = Project.objects.filter(feishu_project_key__startswith="ricelove-scheme:").order_by(
        "name"
    )
    if name_filter:
        qs = qs.filter(name__icontains=name_filter)
    features_by_name = {
        p.name: p
        for p in Project.objects.filter(feishu_project_key__startswith="ricelove:")
    }
    scrape_dir = Path("/tmp/ricelove-features")
    out = []
    for p in qs.select_related("space"):
        has_fl = Artifact.objects.filter(project=p, type__key="feature_list").exists()
        arts = list(
            Artifact.objects.filter(project=p)
            .exclude(type__key="feature_list")
            .select_related("type")
            .values("title", "url", "type__key")
        )
        # primary PRD = first requirement_doc with feishu url, else first with url
        primary = None
        for a in arts:
            if a["type__key"] == "requirement_doc" and a.get("url"):
                primary = a
                break
        if primary is None:
            for a in arts:
                if a.get("url"):
                    primary = a
                    break
        cluster_name = ""
        m = re.search(r"从能力簇「([^」]+)」", p.description or "")
        if m:
            cluster_name = m.group(1)
        cluster_desc = ""
        scrape_text = ""
        if cluster_name and cluster_name in features_by_name:
            fp = features_by_name[cluster_name]
            cluster_desc = (fp.description or "")[:2500]
            key = (fp.feishu_project_key or "").removeprefix("ricelove:")
            scrape_path = scrape_dir / f"{key}.json"
            if scrape_path.exists():
                try:
                    feat = json.loads(scrape_path.read_text(encoding="utf-8"))
                    scrape_text = (feat.get("mainText") or "")[:4000]
                except Exception:  # noqa: BLE001
                    scrape_text = ""
        out.append(
            {
                "id": str(p.id),
                "name": p.name,
                "description": (p.description or "")[:1500],
                "space": p.space,
                "has_fl": has_fl,
                "artifacts": arts,
                "primary": primary,
                "cluster_name": cluster_name,
                "cluster_desc": cluster_desc,
                "scrape_text": scrape_text,
            }
        )
    return out


async def _fetch_prd_text(space: Any, url: str) -> str:
    if not url:
        return ""
    try:
        from agents.tools.feishu_doc_tools import create_feishu_doc_client_for_project

        client = await create_feishu_doc_client_for_project(space)
        markdown, _blocks = await client.get_document_content_by_url(url)
        text = (markdown or "").strip()
        if len(text) > MAX_PRD_CHARS:
            text = text[:MAX_PRD_CHARS] + "\n…（已截断）"
        return text
    except Exception as exc:  # noqa: BLE001
        print(f"  feishu fetch fail: {type(exc).__name__}: {str(exc)[:160]}")
        return ""


def _fallback_context(item: dict[str, Any]) -> str:
    lines = [
        f"# 项目：{item['name']}",
        "",
        item.get("description") or "",
        "",
    ]
    if item.get("cluster_name"):
        lines += [
            f"## 所属能力簇：{item['cluster_name']}",
            item.get("cluster_desc") or "",
            "",
        ]
    if item.get("scrape_text"):
        lines += ["## 产品知识库 Feature 正文摘录", item["scrape_text"], ""]
    lines.append("## 关联文档标题")
    for a in item.get("artifacts") or []:
        lines.append(f"- [{a.get('type__key')}] {a.get('title')} | {a.get('url') or ''}")
    lines.append("")
    lines.append(
        "（未能完整读取飞书 PRD 正文。请结合能力簇叙述与文档标题归纳 feature list；"
        "不确定处在验收项标注「待补充：需对照原 PRD」。禁止臆造具体接口/ID。）"
    )
    return "\n".join(lines)


async def _generate_for_project(
    item: dict[str, Any], *, reference: str, force: bool
) -> dict[str, Any]:
    if item["has_fl"] and not force:
        return {"status": "skipped_exists", "project_id": item["id"], "name": item["name"]}

    primary = item.get("primary") or {}
    url = primary.get("url") or ""
    prd_text = await _fetch_prd_text(item["space"], url) if url else ""
    # wiki 常解析失败：再试同项目其它飞书 requirement_doc（优先 docx）
    if not prd_text:
        candidates = []
        for a in item.get("artifacts") or []:
            u = a.get("url") or ""
            if a.get("type__key") != "requirement_doc" or not u or u == url:
                continue
            candidates.append(u)
        candidates.sort(key=lambda u: (0 if "/docx/" in u else 1, u))
        for u in candidates[:3]:
            prd_text = await _fetch_prd_text(item["space"], u)
            if prd_text:
                url = u
                break
    source_mode = "feishu" if prd_text else "fallback_titles"
    if not prd_text:
        prd_text = _fallback_context(item)

    user_prompt = (
        f"项目名：{item['name']}\n"
        f"主文档：{(primary.get('title') or '')} | {url}\n\n"
        f"【格式样例（高三提分专项节选，只学结构与文风）】\n{reference}\n\n"
        f"【待整理材料】\n{prd_text}\n"
    )
    raw = await _call_mimo(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)],
        max_tokens=8192,
    )
    modules = _parse_modules(raw)
    if not modules:
        return {
            "status": "parse_failed",
            "project_id": item["id"],
            "name": item["name"],
            "source_mode": source_mode,
            "raw_preview": (raw or "")[:300],
        }

    return {
        "status": "ok",
        "project_id": item["id"],
        "name": item["name"],
        "source_mode": source_mode,
        "modules": modules,
        "module_count": len(modules),
        "feature_count": sum(len(m.get("features") or []) for m in modules if isinstance(m, dict)),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filter", default="", help="按项目名包含过滤")
    parser.add_argument("--force", action="store_true", help="覆盖已有 feature_list")
    parser.add_argument("--limit", type=int, default=0, help="最多处理 N 个（0=不限）")
    parser.add_argument("--concurrency", type=int, default=4, help="并发数（默认 4）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin")

    reference = await _load_reference_sample()
    if not reference:
        raise SystemExit("missing 高三提分专项 feature_list reference")

    targets = await _list_targets(args.filter or None)
    if args.limit > 0:
        targets = targets[: args.limit]
    conc = max(1, int(args.concurrency or 1))
    print(
        f"targets={len(targets)} filter={args.filter!r} force={args.force} concurrency={conc}",
        flush=True,
    )

    fl_svc = FeatureListService()
    report: dict[str, Any] = {
        "ok": 0,
        "skipped": 0,
        "failed": 0,
        "feishu_ok": 0,
        "fallback": 0,
        "items": [],
    }
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(conc)
    total = len(targets)
    done_n = 0

    async def _one(i: int, item: dict[str, Any]) -> None:
        nonlocal done_n
        async with sem:
            print(f"[{i}/{total}] {item['name'][:60]}", flush=True)
            try:
                result = await _generate_for_project(
                    item, reference=reference, force=args.force
                )
            except Exception as exc:  # noqa: BLE001
                result = {
                    "status": "error",
                    "project_id": item["id"],
                    "name": item["name"],
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                }

            status = result.get("status")
            async with lock:
                if status == "skipped_exists":
                    report["skipped"] += 1
                    report["items"].append(result)
                    done_n += 1
                    print(f"  SKIP exists ({done_n}/{total})", flush=True)
                    return
                if status != "ok":
                    report["failed"] += 1
                    report["items"].append(result)
                    done_n += 1
                    print(
                        "  FAIL",
                        status,
                        result.get("error") or result.get("raw_preview", "")[:120],
                        flush=True,
                    )
                    return

                if result.get("source_mode") == "feishu":
                    report["feishu_ok"] += 1
                else:
                    report["fallback"] += 1

            if args.dry_run:
                async with lock:
                    report["ok"] += 1
                    report["items"].append({**result, "modules": None, "dry_run": True})
                    done_n += 1
                print(
                    f"  DRY modules={result['module_count']} features={result['feature_count']} "
                    f"mode={result['source_mode']}",
                    flush=True,
                )
                return

            await fl_svc.aset_feature_list(
                item["id"],
                mode="manual",
                modules=result["modules"],
                title="Feature List（MiMo 从 PRD 生成）",
                actor=admin,
                initiated_by_user_id=admin.id,
            )
            async with lock:
                report["ok"] += 1
                report["items"].append(
                    {
                        "status": "ok",
                        "project_id": result["project_id"],
                        "name": result["name"],
                        "source_mode": result["source_mode"],
                        "module_count": result["module_count"],
                        "feature_count": result["feature_count"],
                        "url": f"http://localhost:10240/projects/{result['project_id']}",
                    }
                )
                done_n += 1
                cur = done_n
            print(
                f"  OK modules={result['module_count']} features={result['feature_count']} "
                f"mode={result['source_mode']} ({cur}/{total})",
                flush=True,
            )
            await asyncio.sleep(0.3)

    await asyncio.gather(*[_one(i, item) for i, item in enumerate(targets, 1)])

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {k: report[k] for k in ("ok", "skipped", "failed", "feishu_ok", "fallback")}
    print("SUMMARY", json.dumps(summary, ensure_ascii=False), flush=True)
    print("report ->", REPORT_PATH, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
