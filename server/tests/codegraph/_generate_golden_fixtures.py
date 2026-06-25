"""implementation Task 2: golden snapshot fixture 一次性生成脚本。

per contract / contract。本脚本：
1. 在 `golden_mock_environment` 上下文里按 `GOLDEN_QUERIES_REGISTRY` 顺序逐条
   调用 `await LayeredSearchService.search(...)`。
2. 把 `result.final_context` 原文写入 `tests/fixtures/layered_search_golden/{NN}-{slug}.txt`，
   并在文件末尾追加一空行后写元数据注释行：
   `# tokens=N source_layer=L final_chunks=K`。
3. `source_layer` 选取逻辑：按 L2 → L4 → L3 优先级取首个 `result_count > 0` 的
   layer 标识；全部 empty 时记 `EMPTY`。
4. `final_chunks` = `L2.result_count + L3 出现在 final_context 的去重后条数 + L4.result_count`。

文件名前缀 `_` 故意保留——pytest 默认不收集 `_` 前缀文件，本脚本作为
regenerate baseline 工具长期 commit 进 repo。

Regenerate 用法（项目根）：
    cd server && uv run python -m tests.codegraph._generate_golden_fixtures
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import django


# 不依赖 pytest plugin，自行 setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "friday.settings")
django.setup()

from codegraph.services.layered_search import (  # noqa: E402
    LayeredSearchResult,
    LayeredSearchService,
)
from tests.codegraph.conftest import (  # noqa: E402
    GOLDEN_QUERIES_REGISTRY,
    GoldenQueryEntry,
    golden_mock_environment_context,
)


FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "fixtures" / "layered_search_golden"
)


def _select_source_layer(result: LayeredSearchResult) -> str:
    """按 L2 → L4 → L3 优先级取首个非空 layer 标识；全 empty 记 EMPTY。"""
    priority = ("L2", "L4", "L3")
    by_layer = {lr.layer: lr for lr in result.layers}
    for tag in priority:
        lr = by_layer.get(tag)
        if lr is not None and lr.result_count > 0:
            return tag
    return "EMPTY"


def _count_final_chunks(result: LayeredSearchResult) -> int:
    """final_chunks = L2.result_count + L3 实际进入 final_context 的去重项 + L4.result_count。

    L5 重组阶段 L3 会被 `_filter_l3_dedup` 过滤掉与 L2 重合的 file_path，
    且可能被 token 预算裁剪。本计数取裁剪前的 L3 去重后条数（L5 之前的 L3
    layer.items 长度已是 BranchAwareSearchService 去重 + score 排序的结果，
    与 fixture 文件内 markdown chunk 节数高度对齐）。
    """
    by_layer = {lr.layer: lr.result_count for lr in result.layers}
    return by_layer.get("L2", 0) + by_layer.get("L3", 0) + by_layer.get("L4", 0)


async def _generate_one(
    entry: GoldenQueryEntry,
    mock_env: Any,
) -> tuple[Path, LayeredSearchResult]:
    repo_ids = list(entry.repository_ids) if entry.repository_ids else None
    result = await LayeredSearchService.search(
        entry.query,
        repository_ids=repo_ids,
        project_id=entry.space_id,
        branch_name=entry.branch_name,
        max_tokens=entry.max_tokens,
        top_k=entry.top_k,
    )

    source_layer = _select_source_layer(result)
    final_chunks = _count_final_chunks(result)
    metadata_line = (
        f"# tokens={result.total_tokens} "
        f"source_layer={source_layer} "
        f"final_chunks={final_chunks}"
    )

    fixture_path = FIXTURE_DIR / f"{entry.nn}-{entry.slug}.txt"
    # 文件正文 = final_context + (恰一个空行) + 元数据行 + 末尾换行
    body = result.final_context.rstrip("\n")
    payload = f"{body}\n\n{metadata_line}\n"
    fixture_path.write_text(payload, encoding="utf-8", newline="\n")
    return fixture_path, result


async def _drive_generation() -> None:
    """串行跑 20 条 query，确保 mock 状态不会因并发互相污染。"""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    with golden_mock_environment_context() as mock_env:
        for entry in GOLDEN_QUERIES_REGISTRY:
            path, result = await _generate_one(entry, mock_env)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
            print(
                f"[{entry.nn}] {entry.slug:<24s} "
                f"tokens={result.total_tokens:>5d} "
                f"layers={len(result.layers)} "
                f"sha256={digest} -> {path.relative_to(FIXTURE_DIR.parent.parent)}"
            )


def main() -> int:
    asyncio.run(_drive_generation())
    return 0


if __name__ == "__main__":
    sys.exit(main())
