"""CodeChangeArchive 归档模型 + diff_archive 纯函数测试（Plan 14-01/14-03，KMOD-05）。

覆盖（14-01）：
1. zlib 压缩往返：diff 原文压缩落库后重读解压逐字节一致，尺寸/sha256 与实算一致
2. unique 幂等锚：同 (source_kind, source_id, commit_sha) 二次 create
   → IntegrityError（uniq_codechange_source_commit，T-14-01 防线）
3. 字段完整性：repository SET_NULL FK + Git 元数据 + 文件级 JSON 全部落库可读
4. KnowledgeEdge chunk partial unique（Pitfall 4 DB 防线）：同
   (source_entity, target_chunk_id, relation) 双活跃边 → IntegrityError
   （uniq_kedge_chunk_active）；invalidate 后可再建

覆盖（14-03 Task 1，``TestDiffPureFunctions`` / ``TestLargeDiff``）：
1. parse_diff_files golden：新增/删除/重命名/多 hunk 解析与手算一致
2. 畸形 diff 降级：parse_failed=True + 其余文件正常，无异常逃逸（T-14-08）
3. is_generated_file：路径模式 / 内容标记 / 行数阈值三种命中 + 普通文件不命中
4. compress/decompress 逐字节往返 + build_code_change_content 预算截断与生成文件剔除
5. 大 diff 夹具（test_large_* 前缀，``-k large`` 锚定）：≥10k 行解析完成、
   lockfile is_generated、chunk 数 ≤ MAX_DIFF_CHUNKS、不超时（T-14-09）

覆盖（14-03 Task 3，``TestDiffArchiverService``）：archive_code_change 端到端。
"""

from __future__ import annotations

import datetime
import hashlib
import uuid
import zlib

import pytest
from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.utils import timezone

from knowledge.diff_archive import (
    MAX_CONTENT_BYTES,
    MAX_DIFF_CHUNKS,
    FileDiff,
    build_code_change_content,
    compress_diff,
    decompress_diff,
    is_generated_file,
    parse_diff_files,
)
from knowledge.models import CodeChangeArchive, EdgeRelation, KnowledgeEdge
from services.git_platform.models import MRDiffFile

# acreate（sync_to_async 跨线程）需要真实事务隔离
pytestmark = pytest.mark.django_db(transaction=True)

# 多行 diff 夹具：含文件头/hunk 头/中文内容，覆盖 utf-8 多字节往返
SAMPLE_DIFF = """diff --git a/src/auth.py b/src/auth.py
--- a/src/auth.py
+++ b/src/auth.py
@@ -1,3 +1,5 @@
 def login(user):
+    # 增加登录审计日志
+    audit(user)
     return token(user)
diff --git a/src/views.py b/src/views.py
--- a/src/views.py
+++ b/src/views.py
@@ -10,2 +10,3 @@
 class LoginView:
+    permission_classes = [IsAuthenticated]
     pass
"""


def _make_archive_kwargs(**kw) -> dict:
    """CodeChangeArchive 构造参数工厂：默认 task_result 来源 + 压缩 SAMPLE_DIFF。"""
    raw = kw.pop("diff_text", SAMPLE_DIFF).encode("utf-8")
    compressed = zlib.compress(raw, 6)
    defaults: dict = {
        "source_kind": "task_result",
        "source_id": "sub-session-001",
        "commit_sha": "a" * 40,
        "diff_compressed": compressed,
        "diff_size": len(raw),
        "compressed_size": len(compressed),
        "diff_sha256": hashlib.sha256(raw).hexdigest(),
        "event_time": timezone.now(),
    }
    defaults.update(kw)
    return defaults


class TestCodeChangeArchiveModel:
    """KMOD-05 归档表四用例（压缩往返 / unique 幂等 / 字段完整性 / chunk partial unique）。"""

    async def test_compression_roundtrip_bytes_identical(self) -> None:
        """zlib 压缩落库后重读解压，与原文逐字节一致；尺寸/sha256 与实算一致。"""
        raw = SAMPLE_DIFF.encode("utf-8")
        archive = await CodeChangeArchive.objects.acreate(**_make_archive_kwargs())

        fetched = await CodeChangeArchive.objects.aget(pk=archive.pk)
        decompressed = zlib.decompress(bytes(fetched.diff_compressed))
        assert decompressed == raw
        assert decompressed.decode("utf-8") == SAMPLE_DIFF
        assert fetched.diff_size == len(raw)
        assert fetched.compressed_size == len(zlib.compress(raw, 6))
        assert fetched.diff_sha256 == hashlib.sha256(raw).hexdigest()

    async def test_duplicate_source_commit_rejected(self) -> None:
        """同 (source_kind, source_id, commit_sha) 第二次 create → IntegrityError（幂等锚）。"""
        await CodeChangeArchive.objects.acreate(**_make_archive_kwargs())

        def _dup() -> None:
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    CodeChangeArchive.objects.create(**_make_archive_kwargs())

        await sync_to_async(_dup)()
        assert await CodeChangeArchive.objects.acount() == 1

    async def test_full_field_persistence(self) -> None:
        """repository FK（SET_NULL）、MR 元数据、文件级 JSON、统计字段全部落库可读。"""
        from repositories.models import Repository

        repo = await sync_to_async(Repository.objects.create)(
            name="archive-repo",
            git_url="https://gitlab.com/test/archive-repo.git",
            git_platform="gitlab",
            default_branch="main",
        )
        event_time = timezone.now()
        files = [
            {
                "path": "src/auth.py",
                "old_path": "src/auth.py",
                "change_type": "modified",
                "additions": 2,
                "deletions": 0,
                "is_generated": False,
                "hunk_ranges": [[1, 5]],
                "unresolved_symbols": [],
            },
        ]
        archive = await CodeChangeArchive.objects.acreate(
            **_make_archive_kwargs(
                repository=repo,
                mr_url="https://gitlab.com/test/archive-repo/-/merge_requests/7",
                mr_id="7",
                branch_name="feature/login-audit",
                base_branch="main",
                truncated=True,
                files=files,
                file_count=1,
                total_additions=2,
                total_deletions=0,
                event_time=event_time,
            )
        )

        fetched = await CodeChangeArchive.objects.select_related("repository").aget(pk=archive.pk)
        assert fetched.repository_id == repo.pk
        assert fetched.mr_url == "https://gitlab.com/test/archive-repo/-/merge_requests/7"
        assert fetched.mr_id == "7"
        assert fetched.branch_name == "feature/login-audit"
        assert fetched.base_branch == "main"
        assert fetched.truncated is True
        assert fetched.files == files
        assert fetched.file_count == 1
        assert fetched.total_additions == 2
        assert fetched.total_deletions == 0
        assert fetched.event_time == event_time
        assert fetched.created_at is not None

        # SET_NULL：删除仓库不抹掉归档历史
        await sync_to_async(repo.delete)()
        await fetched.arefresh_from_db()
        assert fetched.repository_id is None

    async def test_chunk_edge_partial_unique(self, entity_factory) -> None:
        """同 (source_entity, target_chunk_id, MODIFIES_CHUNK) 双活跃边
        → IntegrityError（uniq_kedge_chunk_active）；先 invalidate 后可再建。"""
        source = await sync_to_async(entity_factory)()
        chunk_id = uuid.uuid4()
        valid_at = timezone.now()

        first = await KnowledgeEdge.objects.acreate(
            source_entity=source,
            target_chunk_id=chunk_id,
            relation=EdgeRelation.MODIFIES_CHUNK,
            valid_at=valid_at,
        )

        def _dup() -> None:
            with pytest.raises(IntegrityError):
                with transaction.atomic():
                    KnowledgeEdge.objects.create(
                        source_entity=source,
                        target_chunk_id=chunk_id,
                        relation=EdgeRelation.MODIFIES_CHUNK,
                        valid_at=valid_at,
                    )

        await sync_to_async(_dup)()

        # 失效置位后约束放行（条件唯一仅约束活跃边）
        first.invalid_at = valid_at + datetime.timedelta(minutes=1)
        await first.asave(update_fields=["invalid_at"])
        second = await KnowledgeEdge.objects.acreate(
            source_entity=source,
            target_chunk_id=chunk_id,
            relation=EdgeRelation.MODIFIES_CHUNK,
            valid_at=valid_at,
        )
        assert second.pk != first.pk
        active = await KnowledgeEdge.objects.filter(
            target_chunk_id=chunk_id, invalid_at__isnull=True
        ).acount()
        assert active == 1


# ---------------------------------------------------------------------------
# 14-03 Task 1：纯函数层（unidiff 解析 / 生成文件判定 / 压缩 / content 构造）
# ---------------------------------------------------------------------------


def build_large_diff(
    files: int = 30, lines_per_file: int = 400, with_lockfile: bool = True
) -> list[MRDiffFile]:
    """≥10k 行混合大 diff 夹具（RESEARCH Code Examples 原型，程序化生成不提交大文件）。

    返回 MRDiffFile 列表（diff 为 hunk 级文本，不含 ``diff --git`` 头——
    与 14-02 双客户端实际返回形态一致）：lockfile 生成文件 + 多源码文件。
    """
    entries: list[MRDiffFile] = []
    if with_lockfile:
        body = "\n".join(f"+dep-{i}: 1.0.{i}" for i in range(8000))
        entries.append(
            MRDiffFile(
                old_path="pnpm-lock.yaml",
                new_path="pnpm-lock.yaml",
                diff=f"@@ -0,0 +1,8000 @@\n{body}\n",
                new_file=False,
            )
        )
    for n in range(files):
        body = "\n".join(f"+    line_{i} = {i}" for i in range(lines_per_file))
        entries.append(
            MRDiffFile(
                old_path=f"src/mod_{n}.py",
                new_path=f"src/mod_{n}.py",
                diff=f"@@ -0,0 +1,{lines_per_file} @@\n{body}\n",
            )
        )
    return entries


def _raw_by_path(file_diffs: list[FileDiff], mr_files: list[MRDiffFile]) -> dict[str, str]:
    """测试用：按 service 步 ④ 同款形态拼回逐文件原文（diff --git 头 + diff 文本）。"""
    diff_by_path = {f.new_path or f.old_path: f.diff for f in mr_files}
    return {
        fd.path: (
            f"diff --git a/{fd.old_path} b/{fd.path}\n"
            f"--- a/{fd.old_path}\n+++ b/{fd.path}\n{diff_by_path[fd.path]}"
        )
        for fd in file_diffs
    }


class TestDiffPureFunctions:
    """parse_diff_files / is_generated_file / compress / build_code_change_content。"""

    def test_parse_diff_files_golden(self) -> None:
        """新增/删除/重命名/多 hunk 四形态解析结果与手算一致。"""
        mr_files = [
            MRDiffFile(
                old_path="src/new.py",
                new_path="src/new.py",
                diff="@@ -0,0 +1,3 @@\n+a = 1\n+b = 2\n+c = 3\n",
                new_file=True,
            ),
            MRDiffFile(
                old_path="src/old.py",
                new_path="src/old.py",
                diff="@@ -1,2 +0,0 @@\n-x = 1\n-y = 2\n",
                deleted_file=True,
            ),
            MRDiffFile(
                old_path="src/a.py",
                new_path="src/b.py",
                diff="@@ -1,2 +1,3 @@\n ctx\n+added\n line2\n",
                renamed_file=True,
            ),
            MRDiffFile(
                old_path="src/multi.py",
                new_path="src/multi.py",
                diff="@@ -1,2 +1,3 @@\n a\n+b\n c\n@@ -10,3 +11,2 @@\n d\n-e\n f\n",
            ),
        ]

        added, deleted, renamed, multi = parse_diff_files(mr_files)

        assert (added.path, added.change_type) == ("src/new.py", "added")
        assert (added.additions, added.deletions) == (3, 0)
        assert added.hunk_ranges == [(1, 3)]
        assert added.parse_failed is False

        assert (deleted.path, deleted.change_type) == ("src/old.py", "deleted")
        assert (deleted.additions, deleted.deletions) == (0, 2)
        assert deleted.hunk_ranges == []  # 删除文件无新文件侧行区间

        assert (renamed.path, renamed.old_path) == ("src/b.py", "src/a.py")
        assert renamed.change_type == "renamed"
        assert (renamed.additions, renamed.deletions) == (1, 0)
        assert renamed.hunk_ranges == [(1, 3)]

        assert multi.change_type == "modified"
        assert (multi.additions, multi.deletions) == (1, 1)
        assert multi.hunk_ranges == [(1, 3), (11, 12)]

    def test_malformed_diff_degrades_to_parse_failed(self) -> None:
        """畸形 diff → 该文件 parse_failed=True，其余文件正常解析，无异常逃逸。"""
        mr_files = [
            MRDiffFile(
                old_path="src/bad.py",
                new_path="src/bad.py",
                # hunk 头声明 5 行实际只给 1 行（Hunk is shorter than expected）
                diff="@@ -1,5 +1,5 @@\n only one line\n",
            ),
            MRDiffFile(
                old_path="src/garbage.py",
                new_path="src/garbage.py",
                diff="this is not a diff at all\nrandom text without hunks\n",
            ),
            MRDiffFile(
                old_path="src/ok.py",
                new_path="src/ok.py",
                diff="@@ -1,1 +1,2 @@\n keep\n+new\n",
            ),
        ]

        bad, garbage, ok = parse_diff_files(mr_files)

        assert bad.parse_failed is True
        assert garbage.parse_failed is True
        assert ok.parse_failed is False
        assert (ok.additions, ok.deletions) == (1, 0)
        assert ok.hunk_ranges == [(1, 2)]

    def test_is_generated_file_rules(self) -> None:
        """路径模式 / 内容标记（前 20 行）/ 行数阈值命中；普通源码文件不命中。"""
        assert is_generated_file("web/pnpm-lock.yaml", "", 10) is True
        assert is_generated_file("dist/bundle.js", "", 10) is True
        marker_diff = "@@ -0,0 +1,2 @@\n+// DO NOT EDIT\n+export const x = 1\n"
        assert is_generated_file("src/gen.ts", marker_diff, 3) is True
        assert is_generated_file("src/big.py", "@@ -0,0 +1,3001 @@\n", 3001) is True
        assert is_generated_file("src/app.py", "@@ -1,1 +1,2 @@\n keep\n+x = 1\n", 3) is False

    def test_compress_roundtrip_and_content_budget(self) -> None:
        """compress/decompress 逐字节往返；content 超预算截断 + 生成文件剔除。"""
        text = SAMPLE_DIFF + "中文多字节内容\n" * 100
        assert decompress_diff(compress_diff(text)) == text

        big_body = "\n".join(f"+line_{i} padding padding padding" for i in range(12000))
        file_diffs = [
            FileDiff(
                path="src/huge.py",
                old_path="src/huge.py",
                change_type="modified",
                additions=12000,
                deletions=0,
            ),
            FileDiff(
                path="pnpm-lock.yaml",
                old_path="pnpm-lock.yaml",
                change_type="modified",
                additions=10,
                deletions=0,
                is_generated=True,
            ),
        ]
        raw_by_path = {
            "src/huge.py": f"diff --git a/src/huge.py b/src/huge.py\n{big_body}",
            "pnpm-lock.yaml": "diff --git a/pnpm-lock.yaml b/pnpm-lock.yaml\n+dep: 1",
        }

        content = build_code_change_content(
            "feat: 大改动 (repo @ abc1234)",
            ["共 2 个文件，+12010/-0"],
            file_diffs,
            raw_by_path,
            archive_id="archive-uuid-001",
        )

        assert content.startswith("feat: 大改动 (repo @ abc1234)\n\n## 变更摘要\n")
        assert "## diff" in content
        assert len(content.encode("utf-8")) <= MAX_CONTENT_BYTES
        assert "[diff truncated" in content
        assert "archive-uuid-001" in content
        assert "pnpm-lock.yaml" not in content.split("## diff", 1)[1]  # 生成文件剔除

    def test_content_under_budget_not_truncated(self) -> None:
        """预算内 content 不截断、无 truncated 标注。"""
        file_diffs = [
            FileDiff(
                path="src/app.py",
                old_path="src/app.py",
                change_type="modified",
                additions=1,
                deletions=0,
            ),
        ]
        raw_by_path = {"src/app.py": "diff --git a/src/app.py b/src/app.py\n+x = 1"}
        content = build_code_change_content(
            "fix: 小改动", ["共 1 个文件"], file_diffs, raw_by_path, archive_id="aid"
        )
        assert "[diff truncated" not in content
        assert "+x = 1" in content


class TestLargeDiff:
    """大 diff 夹具防线（SC#5 / T-14-09；方法名 test_large_* 前缀，-k large 锚定）。"""

    def test_large_diff_parse_and_generated_skip(self) -> None:
        """10k+ 行混合 diff 解析完成；lockfile is_generated=True、源码文件不误判。"""
        mr_files = build_large_diff(files=30, lines_per_file=400, with_lockfile=True)
        total_lines = sum(f.diff.count("\n") for f in mr_files)
        assert total_lines >= 10_000

        file_diffs = parse_diff_files(mr_files)
        assert len(file_diffs) == 31
        assert all(not fd.parse_failed for fd in file_diffs)

        lockfile = next(fd for fd in file_diffs if fd.path == "pnpm-lock.yaml")
        assert lockfile.is_generated is True
        assert lockfile.additions == 8000
        sources = [fd for fd in file_diffs if fd.path != "pnpm-lock.yaml"]
        assert all(fd.is_generated is False for fd in sources)
        assert all(fd.additions == 400 for fd in sources)

    def test_large_diff_content_chunk_capped(self) -> None:
        """大 diff content 受预算截断后，chunk_knowledge_text 切块数 ≤ MAX_DIFF_CHUNKS。"""
        from knowledge.chunking import chunk_knowledge_text

        mr_files = build_large_diff(files=30, lines_per_file=400, with_lockfile=True)
        file_diffs = parse_diff_files(mr_files)
        raw_by_path = _raw_by_path(file_diffs, mr_files)

        content = build_code_change_content(
            "feat: 大批量变更 (repo @ deadbee)",
            [f"共 {len(file_diffs)} 个文件"],
            file_diffs,
            raw_by_path,
            archive_id="archive-large",
        )
        assert len(content.encode("utf-8")) <= MAX_CONTENT_BYTES

        chunks = chunk_knowledge_text("feat: 大批量变更", content)
        diff_chunks = [c for c in chunks if c.chunk_kind == "diff"]
        assert 0 < len(diff_chunks) <= MAX_DIFF_CHUNKS
        assert len(chunks) <= MAX_DIFF_CHUNKS + 10  # summary/section 余量
