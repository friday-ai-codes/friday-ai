"""把 mimo 细化产出落库到四仓 charter（owned_domains + boundaries）。

遵守 P11 不变量：四仓均 ``source=ai_draft``，整体替换 owned_domains/boundaries 合法
（不动 positioning/placement/version，不碰 human_confirmed 仓）。经 normalize_charter_draft
归一化保证结构合法。

用法:
    uv run python ../.planning/quick/260810-index-counter-fix/apply_charters.py [--dry-run]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

TARGETS = {
    "onion-learning": "050e49b2-633a-44ad-96e8-9262546756db",
    "onion-practice": "cee27ee1-cc73-4937-9a9e-730edd6c93b2",
    "study-user-status": "a1bef5cc-b5e4-4869-8a5a-e1c4f5db4663",
    "study-course": "47991a7f-c8e4-4da6-b42c-2ce81d8b137f",
}


async def main() -> None:
    from asgiref.sync import sync_to_async

    from repositories.models import Repository
    from repositories.services.charter_service import normalize_charter_draft

    dry = "--dry-run" in sys.argv
    preview = json.load(open("/tmp/charter_refine_preview.json"))

    for name, rid in TARGETS.items():
        draft = preview.get(name)
        if not draft:
            print(f"[skip] {name}: 无预览产出")
            continue
        norm = normalize_charter_draft(draft)
        od = norm["owned_domains"]
        bd = norm["boundaries"]

        def _apply():
            repo = Repository.objects.get(id=rid)
            ch = repo.charter
            if ch is None:
                return "no_charter_row"
            if ch.source != "ai_draft":
                return f"skip_source_{ch.source}"  # P11：不碰人工确认章程
            ch.owned_domains = od
            ch.boundaries = bd
            if not dry:
                ch.save(update_fields=["owned_domains", "boundaries", "updated_at"])
            return f"od={len(od)} bd={len(bd)}"

        result = await sync_to_async(_apply, thread_sensitive=False)()
        tag = "(dry-run) " if dry else ""
        print(f"{tag}{name}: {result}")


asyncio.run(main())
