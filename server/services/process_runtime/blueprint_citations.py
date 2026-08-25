"""blueprint_citations —— 蓝图裸引用串的确定性引用池归一化（纯函数）。

确认门与融合阶段都需要把调研产出的裸文件路径转成文档级引用池条目。两处必须共享同一套
id、截断和去重口径，否则同一证据会生成不同 id，破坏幂等与引用覆盖率。
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

__all__ = [
    "CITATION_ID_PREFIX",
    "build_citation_entries",
    "citation_id_for",
]

CITATION_ID_PREFIX = "cit_"
_MAX_TITLE_CHARS = 300


def citation_id_for(raw: str) -> str:
    """为裸引用串生成稳定 id：``cit_`` + ``sha1(raw)[:12]``。"""
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"{CITATION_ID_PREFIX}{digest[:12]}"


def build_citation_entries(raws: Iterable[str]) -> tuple[list[dict], dict[str, str]]:
    """把裸引用串归一成引用池条目与 ``raw → id`` 映射。

    输入按原序保序去重；空值和已有 ``cit_`` 前缀的池内 id 跳过，避免再次生成
    ``cit_sha1("cit_xxx")`` 导致引用池逐轮膨胀。
    """
    entries: list[dict] = []
    cite_map: dict[str, str] = {}
    seen: set[str] = set()
    for value in raws:
        raw = str(value or "").strip()
        if not raw or raw in seen or raw.startswith(CITATION_ID_PREFIX):
            continue
        seen.add(raw)
        citation_id = citation_id_for(raw)
        cite_map[raw] = citation_id
        title = raw[:_MAX_TITLE_CHARS]
        entries.append(
            {
                "citation_id": citation_id,
                "source_type": "repo_file",
                "source_id": title,
                "locator": {"path": title},
                "title": title,
            }
        )
    return entries, cite_map
