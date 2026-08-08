#!/usr/bin/env python3
"""归档批量导入的历史项目 + 清理其默认分支绑定（quick 260808-fn3）。

Run from server/:
  uv run python ../.planning/quick/260808-fn3-archive-imported-projects/cleanup_imported.py

范围（用户已确认）：
- 归档 feishu_project_key 前缀 ricelove: / ricelove-scheme: / release-bitable: 的项目；
- 删除这些项目名下全部分支绑定（导入时统一绑的 repository.default_branch，无反查价值）；
- ⛔ 不改任何 Repository.default_branch。

全走 service 层（INV-6），审计归因到最早的 superuser；幂等可重跑。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

import django

django.setup()

from asgiref.sync import sync_to_async  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402

from initiatives.models import Project, ProjectBranch, ProjectStatus  # noqa: E402
from initiatives.services.project_branch_service import ProjectBranchService  # noqa: E402
from initiatives.services.project_service import ProjectService  # noqa: E402

IMPORT_PREFIXES = ("ricelove:", "ricelove-scheme:", "release-bitable:")
REPORT_PATH = Path("/tmp/friday-archive-imported-report.json")


async def main() -> None:
    User = get_user_model()
    admin = await User.objects.filter(is_superuser=True).order_by("date_joined").afirst()
    if not admin:
        raise SystemExit("no admin user")

    project_svc = ProjectService()
    branch_svc = ProjectBranchService()

    report: dict = {"archived": 0, "already_archived": 0, "unbound": 0, "errors": []}

    # ---- 1) 归档导入项目 ----
    targets = [
        p
        async for p in Project.objects.all()
        if (p.feishu_project_key or "").startswith(IMPORT_PREFIXES)
    ]
    print(f"import projects: {len(targets)}")
    for i, p in enumerate(targets, 1):
        try:
            if p.status == ProjectStatus.ARCHIVED:
                report["already_archived"] += 1
            else:
                await project_svc.archive(
                    project_id=p.id, actor=admin, initiated_by_user_id=admin.id
                )
                report["archived"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append({"project": p.name[:60], "error": f"{type(exc).__name__}: {exc}"[:200]})
        if i % 100 == 0:
            print(f"archive {i}/{len(targets)}")

    # ---- 2) 删除导入项目名下的分支绑定 ----
    bindings = await sync_to_async(
        lambda: list(ProjectBranch.objects.select_related("project", "repository"))
    )()
    for b in bindings:
        key = b.project.feishu_project_key or ""
        if not key.startswith(IMPORT_PREFIXES):
            continue
        try:
            ok = await branch_svc.unbind(
                project_id=b.project_id,
                repository_id=b.repository_id,
                branch_name=b.branch_name,
                actor=admin,
                initiated_by_user_id=admin.id,
                _skip_member_check=True,
            )
            if ok:
                report["unbound"] += 1
        except Exception as exc:  # noqa: BLE001
            report["errors"].append(
                {
                    "binding": f"{b.repository.name}:{b.branch_name} @ {b.project.name[:40]}",
                    "error": f"{type(exc).__name__}: {exc}"[:200],
                }
            )

    # ---- 3) 复查 ----
    from django.db.models import Count

    status_rows = await sync_to_async(
        lambda: list(Project.objects.values("status").annotate(n=Count("id")))
    )()
    branch_rows = await sync_to_async(
        lambda: list(
            ProjectBranch.objects.values("branch_name").annotate(n=Count("id")).order_by("-n")
        )
    )()
    report["final_status"] = {r["status"]: r["n"] for r in status_rows}
    report["final_branches"] = {r["branch_name"]: r["n"] for r in branch_rows}

    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("REPORT", REPORT_PATH)


if __name__ == "__main__":
    asyncio.run(main())
