#!/usr/bin/env python3
"""上线文档多维表格 → 「上线记录」项目工件（每个发布计划一个 markdown 工件）。

数据源：/tmp/release-bitable-records.json（fetch_records.py 产出，6087 行）
落库：
  - Project 「上线记录」（技术支撑空间，feishu_project_key=release-bitable:{app}:{table}）
  - ArtifactType key=release_record（「上线记录」，markdown 载体，ragable=True）
  - 每个「发布计划名称」一个 Artifact（carrier=markdown，content_ref=该计划全部上线行汇总）
  - 创建后逐工件同步跑 knowledge ingest（走既有 artifact normalizer 全文向量化）

Run from server/:
  uv run python ../.planning/quick/260807-release-bitable-import/import_release_artifacts.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

import django

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402

from initiatives.models import Artifact, ArtifactCarrier, ArtifactType  # noqa: E402
from initiatives.services.artifact_service import ArtifactService  # noqa: E402
from initiatives.services.project_service import ProjectService  # noqa: E402
from projects.models import Space  # noqa: E402

CACHE = Path("/tmp/release-bitable-records.json")
APP_TOKEN = "CFQCbbtoVaEhT8sM9XPcPvExnGe"
TABLE_ID = "tbls2oct7kJNjXtf"
TABLE_URL = f"https://guanghe.feishu.cn/base/{APP_TOKEN}?table={TABLE_ID}"
PROJECT_KEY = f"release-bitable:{APP_TOKEN}:{TABLE_ID}"
TYPE_KEY = "release_record"
REPORT = Path("/tmp/release-artifact-import-report.json")


def _text(value: Any) -> str:
    """Bitable 单元格 → 纯文本。"""
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


def _names(value: Any) -> str:
    """人员列 → 姓名列表。"""
    if not isinstance(value, list):
        return _text(value)
    return "、".join(str(p.get("name") or "") for p in value if isinstance(p, dict) and p.get("name"))


def _date(ms: Any) -> str:
    if not isinstance(ms, (int, float)) or ms <= 0:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=dt_timezone.utc).strftime("%Y-%m-%d")


def _plan_of(fields: dict) -> str:
    plan = _text(fields.get("发布计划名称"))
    plan = re.sub(r"\s+", " ", plan).strip()
    return plan


def _domain_of(plan: str) -> str:
    if ":" in plan:
        prefix = plan.split(":", 1)[0].strip()
        if prefix:
            return prefix
    return "未标注"


def _row_lines(fields: dict) -> list[str]:
    """单条上线记录 → markdown 要点行。"""
    lines: list[str] = []

    def add(label: str, value: str) -> None:
        if value:
            lines.append(f"- {label}：{value}")

    add("上线业务", _text(fields.get("上线业务")))
    add("上线分类", _text(fields.get("上线分类")))
    add("上线日期", _date(fields.get("上线日期")))
    add("发版类型", _text(fields.get("发版类型（bugFix OR 正常发版）")))
    add("服务", _text(fields.get("服务名称")))
    mr = fields.get("MR（合并Master）")
    if isinstance(mr, dict) and mr.get("link"):
        add("MR", str(mr["link"]))
    add("feature 分支", _text(fields.get("feature分支")))
    add("tag 版本", _text(fields.get("tag版本")))
    add("生产镜像/配置", _text(fields.get("生产：镜像Tag/配置/archeySQL上线链接")))
    add("开发", _names(fields.get("开发")))
    add("测试", _names(fields.get("测试")))
    add("特殊说明", _text(fields.get("其他特殊说明")))
    return lines


def build_markdown(plan: str, rows: list[dict]) -> str:
    """一个发布计划的全部上线行 → markdown 正文。"""
    domain = _domain_of(plan)
    dates = sorted({d for d in (_date(r.get("上线日期")) for r in rows) if d})
    parts = [
        f"# 上线计划：{plan}",
        "",
        f"- 业务域：{domain}",
        f"- 上线日期：{'、'.join(dates) if dates else '未知'}",
        f"- 上线记录数：{len(rows)}",
        f"- 来源：飞书上线文档表格（{TABLE_URL}）",
        "",
    ]
    for i, fields in enumerate(rows, 1):
        cat = _text(fields.get("上线分类"))
        parts.append(f"## 记录 {i}" + (f"（{cat}）" if cat else ""))
        parts.extend(_row_lines(fields))
        parts.append("")
    return "\n".join(parts).strip()


async def main() -> None:
    ingest_only = "--ingest-only" in sys.argv

    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin user")

    space = await Space.objects.filter(name="技术支撑").afirst()
    if not space:
        raise SystemExit("no 技术支撑 space")

    records = json.loads(CACHE.read_text())
    plans: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        fields = r.get("fields", {}) or {}
        plan = _plan_of(fields) or "(无发布计划)"
        plans[plan].append(fields)
    print(f"records={len(records)} plans={len(plans)}")

    # ---- 项目（幂等：feishu_project_key 收敛）----
    from initiatives.services import project_doc_service as pds

    original_dispatch = pds.ProjectDocService.provision_dispatch
    pds.ProjectDocService.provision_dispatch = lambda self, *a, **k: None  # type: ignore[method-assign]

    project_svc = ProjectService()
    project, created = await project_svc.create(
        space=space,
        name="上线记录",
        description=(
            "全量导入自飞书「上线文档表格」多维表格的上线/发版记录，按发布计划聚合，"
            "每个发布计划一个上线记录工件（含上线业务、日期、服务、MR、分支、人员、说明）。"
            f"源表：{TABLE_URL}"
        ),
        feishu_project_key=PROJECT_KEY,
        created_by=admin,
        initiated_by_user_id=admin.id,
    )
    print("project:", project.id, "| created:", created)

    # ---- 工件类型（幂等）----
    artifact_svc = ArtifactService()
    atype = await ArtifactType.objects.filter(key=TYPE_KEY).afirst()
    if atype is None:
        atype = await artifact_svc.create_type(
            key=TYPE_KEY,
            name="上线记录",
            carrier=ArtifactCarrier.MARKDOWN,
            ragable=True,
            enabled=True,
            actor=admin,
            initiated_by_user_id=admin.id,
        )
        print("created artifact type:", atype.id)
    else:
        print("artifact type exists:", atype.id, "| ragable:", atype.ragable)

    report = {"artifacts_created": 0, "artifacts_existing": 0, "ingested": 0, "errors": []}

    # ---- 批量创建阶段关掉自动摄取调度（脚本退出会丢后台任务，改为下方同步 ingest）----
    original_schedule = ArtifactService._maybe_schedule_ingestion

    async def _noop_schedule(self, *a, **k):  # noqa: ANN001
        return None

    ArtifactService._maybe_schedule_ingestion = _noop_schedule  # type: ignore[method-assign]

    existing_titles = {
        t: aid
        async for aid, t in Artifact.objects.filter(project_id=project.id).values_list(
            "id", "title"
        )
    }
    print("existing artifacts:", len(existing_titles))

    artifact_ids: list[str] = []
    if not ingest_only:
        for idx, (plan, rows) in enumerate(sorted(plans.items()), 1):
            title = plan[:200]
            if title in existing_titles:
                report["artifacts_existing"] += 1
                artifact_ids.append(str(existing_titles[title]))
                continue
            try:
                artifact = await artifact_svc.create_artifact(
                    project_id=project.id,
                    type_id=atype.id,
                    title=title,
                    carrier=ArtifactCarrier.MARKDOWN,
                    url=TABLE_URL,
                    content_ref=build_markdown(plan, rows),
                    contributor=admin,
                    actor=admin,
                    initiated_by_user_id=admin.id,
                )
                artifact_ids.append(str(artifact.id))
                report["artifacts_created"] += 1
            except Exception as exc:  # noqa: BLE001
                report["errors"].append({"plan": plan[:80], "error": f"{type(exc).__name__}: {exc}"})
            if idx % 200 == 0:
                print(f"create {idx}/{len(plans)} created={report['artifacts_created']}")
    else:
        artifact_ids = [str(a) async for a in Artifact.objects.filter(
            project_id=project.id, type_id=atype.id
        ).values_list("id", flat=True)]

    ArtifactService._maybe_schedule_ingestion = original_schedule  # type: ignore[method-assign]
    pds.ProjectDocService.provision_dispatch = original_dispatch  # type: ignore[method-assign]
    print(f"artifacts total={len(artifact_ids)} created={report['artifacts_created']} "
          f"existing={report['artifacts_existing']} errors={len(report['errors'])}")

    # ---- 同步逐工件摄取（关掉 RepoRouterV2 路由，防 4000 次 LLM 调用）----
    from knowledge import ingestion
    from knowledge.sources import artifact as artifact_source

    async def _no_route(**kwargs):  # noqa: ANN003
        return ()

    artifact_source._route_artifact_body_edges = _no_route  # type: ignore[assignment]

    for i, aid in enumerate(artifact_ids, 1):
        try:
            await ingestion.ingest(
                ingestion.IngestionRequest(
                    source_kind="artifact", source_id=aid, trigger="release_bitable_import"
                )
            )
            report["ingested"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"artifact": aid, "error": f"{type(exc).__name__}: {exc}"})
        if i % 100 == 0:
            print(f"ingest {i}/{len(artifact_ids)} ok={report['ingested']} errors={len(report['errors'])}")

    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT ->", REPORT)
    print(json.dumps({k: v for k, v in report.items() if k != "errors"}, ensure_ascii=False))
    print("errors:", len(report["errors"]))
    print("ALL DONE")


if __name__ == "__main__":
    asyncio.run(main())
