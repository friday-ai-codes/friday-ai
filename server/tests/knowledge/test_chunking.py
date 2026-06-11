"""确定性知识文本 chunker 回归测试（INGEST-08）。

锁定契约：
- 同一 content 输入两次 chunk，得到字节级一致的 chunk 列表；
- 同一 version_id 派生两次 point id，列表完全一致；
- 不同 version_id 派生的 point id 集合不相交（版本翻转"删旧写新"天然不重叠）。

纯单元测试：chunking 模块为无 I/O 纯函数，不标 django_db。
"""

from __future__ import annotations

import uuid

from knowledge.chunking import (
    MAX_CHUNK_CHARS,
    KnowledgeChunk,
    chunk_knowledge_text,
    derive_point_ids,
)

MARKDOWN_CONTENT = """前言段落：本方案概述整体目标。

## 背景

需求来自飞书工作项，描述了用户登录流程的改造。

## 技术方案

### 后端改动

新增 accounts 接口与迁移。

## 风险

回滚依赖迁移可逆。
"""

PLAIN_CONTENT = """第一段：纯文本无标题。

第二段：按双换行分段。

第三段：贪心合并相邻段。
"""


# ---------------------------------------------------------------------------
# Test 1：确定性
# ---------------------------------------------------------------------------


def test_chunk_deterministic_byte_identical() -> None:
    """同一 content 调用两次，chunk 列表逐字段（含字节级 text）一致。"""
    first = chunk_knowledge_text("登录改造方案", MARKDOWN_CONTENT)
    second = chunk_knowledge_text("登录改造方案", MARKDOWN_CONTENT)
    assert first == second
    for a, b in zip(first, second, strict=True):
        assert a.index == b.index
        assert a.text.encode("utf-8") == b.text.encode("utf-8")
        assert a.chunk_kind == b.chunk_kind


def test_derive_point_ids_deterministic() -> None:
    """同一 version_id 调用两次，point id 列表完全一致。"""
    version_id = uuid.uuid4()
    assert derive_point_ids(version_id, 5) == derive_point_ids(version_id, 5)


# ---------------------------------------------------------------------------
# Test 2：markdown 标题分段
# ---------------------------------------------------------------------------


def test_markdown_split_by_headings_summary_first() -> None:
    """含 ``## `` 标题的文本按标题分段；chunk 0 为 summary（title + 首段），其余 section。"""
    chunks = chunk_knowledge_text("登录改造方案", MARKDOWN_CONTENT)
    assert len(chunks) >= 2
    assert chunks[0].chunk_kind == "summary"
    assert chunks[0].index == 0
    assert "登录改造方案" in chunks[0].text
    assert "前言段落" in chunks[0].text
    for chunk in chunks[1:]:
        assert chunk.chunk_kind == "section"
    joined = "\n".join(c.text for c in chunks[1:])
    assert "## 背景" in joined
    assert "## 技术方案" in joined


# ---------------------------------------------------------------------------
# Test 3：无标题纯文本
# ---------------------------------------------------------------------------


def test_plain_text_split_by_blank_lines_greedy_merge() -> None:
    """无标题纯文本按双换行分段后贪心合并（短段全部并入少量 chunk）。"""
    chunks = chunk_knowledge_text("纯文本", PLAIN_CONTENT)
    assert chunks[0].chunk_kind == "summary"
    # 三个短段远小于上限 → 贪心合并后总 chunk 数很小
    assert len(chunks) <= 2
    full_text = "\n".join(c.text for c in chunks)
    assert "第一段" in full_text
    assert "第三段" in full_text


def test_empty_content_still_yields_summary_chunk() -> None:
    """空 content 仍产出单个 summary chunk（title 本身）。"""
    chunks = chunk_knowledge_text("只有标题", "")
    assert len(chunks) == 1
    assert chunks[0] == KnowledgeChunk(index=0, text="只有标题", chunk_kind="summary")


# ---------------------------------------------------------------------------
# Test 4：上限硬切
# ---------------------------------------------------------------------------


def test_oversize_segment_hard_split_within_limit() -> None:
    """超过 MAX_CHUNK_CHARS 的单段被硬切，任何 chunk 长度 ≤ 上限。"""
    oversize = "字" * (MAX_CHUNK_CHARS * 2 + 100)
    chunks = chunk_knowledge_text("超长段", oversize)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS
    # 硬切不丢内容（summary 含 title 前缀，去除后所有正文字符仍齐全）
    body = "".join(c.text for c in chunks).replace("超长段", "", 1).replace("\n", "")
    assert body.count("字") == MAX_CHUNK_CHARS * 2 + 100


# ---------------------------------------------------------------------------
# Test 6：diff-aware 分支（Plan 14-01 Task 3）
# ---------------------------------------------------------------------------

DIFF_FILE_A = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,3 +1,5 @@
 def login(user):
+    # 增加登录审计
+    audit(user)
     return token(user)"""

DIFF_FILE_B = """diff --git a/src/views.py b/src/views.py
--- a/src/views.py
+++ b/src/views.py
@@ -10,2 +10,3 @@
 class LoginView:
+    permission_classes = [IsAuthenticated]
     pass"""

DIFF_CONTENT = f"""变更摘要段：本次提交为登录流程增加审计与权限。

## 变更文件

- src/auth.py
- src/views.py

## diff

{DIFF_FILE_A}
{DIFF_FILE_B}
"""


def _build_oversize_single_file_diff() -> str:
    """单文件多 hunk diff：hunk 1 小、hunk 2 超 MAX_CHUNK_CHARS（触发硬切兜底）。"""
    header = "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n"
    hunk1 = "@@ -1,2 +1,50 @@\n" + "\n".join(f"+line_{i} = {i}" for i in range(50))
    big_lines = "\n".join(f"+big_{i} = '{'x' * 60}'" for i in range(80))
    hunk2 = f"@@ -100,2 +100,80 @@\n{big_lines}"
    assert len(hunk2) > MAX_CHUNK_CHARS  # 夹具自检：hunk 2 必须超限
    return f"{header}{hunk1}\n{hunk2}"


def test_diff_content_split_by_file_boundary() -> None:
    """摘要段产出 summary/section（chunk_kind 不变）；diff 区段每文件一 chunk 且 kind=diff。"""
    chunks = chunk_knowledge_text("登录审计提交", DIFF_CONTENT)

    assert chunks[0].chunk_kind == "summary"
    assert "登录审计提交" in chunks[0].text
    assert "变更摘要段" in chunks[0].text
    diff_chunks = [c for c in chunks if c.chunk_kind == "diff"]
    non_diff = [c for c in chunks if c.chunk_kind != "diff"]
    # 前段只产出 summary/section 两种既有 kind
    assert {c.chunk_kind for c in non_diff} <= {"summary", "section"}
    # 两个文件段各一 chunk，文件边界切分且以 diff --git 起头
    assert len(diff_chunks) == 2
    assert diff_chunks[0].text == DIFF_FILE_A
    assert diff_chunks[1].text == DIFF_FILE_B
    for chunk in diff_chunks:
        assert chunk.text.startswith("diff --git ")
    # index 连续递增
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_diff_oversize_file_split_by_hunk_then_hard_split() -> None:
    """单文件超限按 ^@@ hunk 头再切（后续 hunk 拼回文件头两行上下文）；
    单 hunk 仍超长走硬切，全部 chunk ≤ MAX_CHUNK_CHARS 且 kind=diff。"""
    diff_text = _build_oversize_single_file_diff()
    chunks = chunk_knowledge_text("超大单文件", diff_text)

    diff_chunks = [c for c in chunks if c.chunk_kind == "diff"]
    assert len(diff_chunks) >= 2  # hunk 切分 + 硬切兜底至少产出多块
    for chunk in diff_chunks:
        assert len(chunk.text) <= MAX_CHUNK_CHARS
    # 首块携带文件头 + 首个 hunk；第二块以文件头两行上下文前缀起头
    assert diff_chunks[0].text.startswith("diff --git a/big.py b/big.py")
    assert "@@ -1,2 +1,50 @@" in diff_chunks[0].text
    assert diff_chunks[1].text.startswith("diff --git a/big.py b/big.py\n--- a/big.py\n@@ ")


def test_diff_chunking_deterministic() -> None:
    """同一 diff content 连调两次，输出逐项相等（index/text/chunk_kind）。"""
    first = chunk_knowledge_text("登录审计提交", DIFF_CONTENT)
    second = chunk_knowledge_text("登录审计提交", DIFF_CONTENT)
    assert first == second
    for a, b in zip(first, second, strict=True):
        assert (a.index, a.text, a.chunk_kind) == (b.index, b.text, b.chunk_kind)


def test_diff_absent_markdown_output_unchanged() -> None:
    """纯 markdown content（无 diff --git）零 diff chunk，输出与既有路径语义一致。"""
    chunks = chunk_knowledge_text("登录改造方案", MARKDOWN_CONTENT)
    assert all(c.chunk_kind in ("summary", "section") for c in chunks)
    assert not any(c.chunk_kind == "diff" for c in chunks)


# ---------------------------------------------------------------------------
# Test 5：point id 隔离
# ---------------------------------------------------------------------------


def test_point_ids_disjoint_across_versions() -> None:
    """不同 version_id 派生的 point id 集合不相交。"""
    v1, v2 = uuid.uuid4(), uuid.uuid4()
    ids_v1 = set(derive_point_ids(v1, 10))
    ids_v2 = set(derive_point_ids(v2, 10))
    assert len(ids_v1) == 10
    assert ids_v1.isdisjoint(ids_v2)


def test_point_ids_indexed_sequentially() -> None:
    """point id 按 index 逐个派生：前缀列表是全列表的前缀（拼接格式锁定的推论）。"""
    version_id = uuid.uuid4()
    assert derive_point_ids(version_id, 3) == derive_point_ids(version_id, 5)[:3]
