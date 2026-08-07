#!/usr/bin/env python3
"""分页拉取「上线文档表格」多维表格全部记录，缓存到 /tmp/release-bitable-records.json。

Run from server/:
  uv run python ../.planning/quick/260807-release-bitable-import/fetch_records.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")

import django

django.setup()

from services.feishu_bitable import (  # noqa: E402
    BitableClient,
    RateLimitError,
    _aget_system_open_platform_credentials,
)

APP_TOKEN = "CFQCbbtoVaEhT8sM9XPcPvExnGe"
TABLE_ID = "tbls2oct7kJNjXtf"
CACHE = Path("/tmp/release-bitable-records.json")


def _cell_text(value) -> str:
    """Bitable 单元格 → 纯文本（text 数组 / link / 人员 / 标量统一收敛）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return str(value.get("text") or value.get("link") or value.get("name") or "").strip()
    if isinstance(value, list):
        parts = [_cell_text(v) for v in value]
        return "、".join(p for p in parts if p)
    return str(value)


async def main() -> None:
    creds = await _aget_system_open_platform_credentials()
    if not creds:
        raise SystemExit("no feishu open-platform credentials")
    client = BitableClient(app_id=creds[0], app_secret=creds[1])

    records: list[dict] = []
    page_token: str | None = None
    page = 0
    while True:
        for attempt in range(5):
            try:
                data = await client.list_records(
                    APP_TOKEN, TABLE_ID, page_token=page_token, page_size=500
                )
                break
            except RateLimitError:
                wait = 2 * (attempt + 1)
                print(f"rate limited, sleep {wait}s")
                await asyncio.sleep(wait)
        else:
            raise SystemExit("rate limit retries exhausted")
        items = data.get("items", []) or []
        records.extend(items)
        page += 1
        print(f"page {page}: +{len(items)} (total {len(records)}/{data.get('total')})")
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        await asyncio.sleep(0.3)

    CACHE.write_text(json.dumps(records, ensure_ascii=False))
    print("cached ->", CACHE, "records:", len(records))

    # 统计：发布计划 / 习题命中
    plans = Counter()
    xiti = 0
    for r in records:
        fields = r.get("fields", {}) or {}
        plan = _cell_text(fields.get("发布计划名称"))
        biz = _cell_text(fields.get("上线业务"))
        plans[plan or "(无发布计划)"] += 1
        if "习题" in plan or "习题" in biz:
            xiti += 1
    print("unique plans:", len(plans))
    print("rows mentioning 习题:", xiti)
    print("top plans:")
    for name, n in plans.most_common(10):
        print(f"  {n:4d}  {name[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
