"""确定性知识文本 chunker（Phase 13 / INGEST-08 契约）。

本模块是知识文本（提炼后的 markdown / 纯文本，OQ-3 定案：不复用 indexer 的
tree-sitter 代码切块）切块的唯一实现，全部为无 I/O 纯函数：

- 同一 ``content`` 输入两次，得到字节级一致的 chunk 列表；
- 同一 ``version_id`` 派生两次，得到完全相同的 point id 列表；
- 不同 version 的 point id 必不重叠（version_id 为 uuid4 PK）——
  版本翻转时"删旧写新"天然不冲突，同版本重复 upsert 即覆盖（点级幂等）。
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from knowledge.models import KNOWLEDGE_NAMESPACE

__all__ = [
    "MAX_CHUNK_CHARS",
    "KnowledgeChunk",
    "chunk_knowledge_text",
    "derive_point_ids",
]

# 单 chunk 字符上限：对 bge-m3 / doubao 类 embedding 模型的 token 上限留足余量，
# 部署模型变化时可调（A3：超限会在摄取路径响亮报错，调整成本低）。
MAX_CHUNK_CHARS = 3000

# markdown 二级及以下标题行（lookahead split：标题行保留在所属段首）
_HEADING_SPLIT_RE = re.compile(r"^(?=##+ )", re.MULTILINE)
_HEADING_PROBE_RE = re.compile(r"^##+ ", re.MULTILINE)
_BLANK_LINE_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class KnowledgeChunk:
    """切块值对象：chunk 0 固定 ``summary``（整体召回面），其余 ``section``。"""

    index: int
    text: str
    chunk_kind: str


def _split_segments(content: str) -> list[str]:
    """按 markdown 标题（``^##+ ``）分段；无标题时按双换行分段。"""
    if _HEADING_PROBE_RE.search(content):
        parts = _HEADING_SPLIT_RE.split(content)
    else:
        parts = _BLANK_LINE_RE.split(content)
    return [part.strip() for part in parts if part.strip()]


def _hard_split(text: str, limit: int) -> list[str]:
    """超长单段按字符硬切（确定性：固定步长切片，不丢字符）。"""
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _greedy_merge(pieces: list[str]) -> list[str]:
    """贪心合并相邻段至 ≤ MAX_CHUNK_CHARS（段间以双换行拼接）。"""
    merged: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 2 + len(piece) <= MAX_CHUNK_CHARS:
            current = f"{current}\n\n{piece}"
        else:
            merged.append(current)
            current = piece
    if current:
        merged.append(current)
    return merged


def chunk_knowledge_text(title: str, content: str) -> list[KnowledgeChunk]:
    """将知识文本确定性切块。

    规格（RESEARCH Pattern 5）：
    1. 按 markdown 二级/三级标题分段，无标题时按双换行分段；
    2. 贪心合并相邻段至 ≤ ``MAX_CHUNK_CHARS``，超长单段按字符硬切（不丢内容）；
    3. chunk 0 固定 ``chunk_kind="summary"``（title + 首段；首段为 summary
       预留 title 空间，整 chunk 不超上限），其余 ``chunk_kind="section"``；
       空 content 仍产出单个 summary chunk（title 本身）。
    """
    title = title.strip()
    content = content.strip()
    if not content:
        return [KnowledgeChunk(index=0, text=title, chunk_kind="summary")]

    segments = _split_segments(content)

    # summary = title + 首段：为 title 与分隔符预留空间，保证整 chunk ≤ 上限；
    # 首段硬切的剩余部分回流 section，不截断丢弃。
    title_overhead = len(title) + 2 if title else 0
    summary_budget = max(MAX_CHUNK_CHARS - title_overhead, 1)
    first_pieces = _hard_split(segments[0], summary_budget)
    summary_text = f"{title}\n\n{first_pieces[0]}" if title else first_pieces[0]

    rest_pieces: list[str] = list(first_pieces[1:])
    for segment in segments[1:]:
        rest_pieces.extend(_hard_split(segment, MAX_CHUNK_CHARS))

    chunks = [KnowledgeChunk(index=0, text=summary_text, chunk_kind="summary")]
    for offset, text in enumerate(_greedy_merge(rest_pieces)):
        chunks.append(KnowledgeChunk(index=offset + 1, text=text, chunk_kind="section"))
    return chunks


def derive_point_ids(version_id: uuid.UUID, chunk_count: int) -> list[str]:
    """派生版本内各 chunk 的确定性 Qdrant point id。

    拼接格式 ``point:{version_id}:{index}`` 是**锁定契约**
    （``generate_entity_id`` 同款警告）：任何顺序 / 分隔符变更都构成
    point id 漂移，届时需要全量向量数据迁移而非简单改函数。
    命名空间唯一来源为 ``knowledge.models.KNOWLEDGE_NAMESPACE``，
    禁止散落复刻 uuid5 派生。
    """
    return [
        str(uuid.uuid5(KNOWLEDGE_NAMESPACE, f"point:{version_id}:{index}"))
        for index in range(chunk_count)
    ]
