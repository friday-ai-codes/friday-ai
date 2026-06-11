"""CodeChangeArchive 归档模型测试（Plan 14-01 Task 1，KMOD-05 持久层）。

覆盖：
1. zlib 压缩往返：diff 原文压缩落库后重读解压逐字节一致，尺寸/sha256 与实算一致
2. unique 幂等锚：同 (source_kind, source_id, commit_sha) 二次 create
   → IntegrityError（uniq_codechange_source_commit，T-14-01 防线）
3. 字段完整性：repository SET_NULL FK + Git 元数据 + 文件级 JSON 全部落库可读
4. KnowledgeEdge chunk partial unique（Pitfall 4 DB 防线）：同
   (source_entity, target_chunk_id, relation) 双活跃边 → IntegrityError
   （uniq_kedge_chunk_active）；invalidate 后可再建

14-03 在本文件扩展纯函数（unidiff 解析/生成文件判定）与大 diff（test_large_*）用例组。
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

from knowledge.models import CodeChangeArchive, EdgeRelation, KnowledgeEdge

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
