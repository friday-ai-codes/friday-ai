"""ingest_from_urls 三步编排守护测试（Phase 32-02 Task 1，ING-01）。

覆盖（best-effort 降级 + 检索可测代理）：

- 三步全 ok：WorkItem 经 upsert 落库（三元组幂等）、Document + REFERENCES knowledge
  边存在、CodeChangeArchive + code_change knowledge 实体存在；steps 三项 ok + identifier。
- 任一步失败（工作项 upsert 抛 / MR archive 返回 None / 文档 ingest 抛）→ 该步
  failed/skipped + 脱敏 error，其余步仍各自产出结果（独立降级）。
- board_url / mr_url 解析失败 → 对应步 skipped + error，编排不抛、status=completed。
- 编排级异常 → status=failed + error，且 error 不含明文 token/Bearer（脱敏）。
- 重复摄取同一 MR（archive 已存在）→ mr_diff 不报 failed（ok + identifier）。

检索可测代理（不依赖真实 Qdrant 召回，对齐 25-04 范式）：断言 KnowledgeEntity
（kind work_item/document/code_change）+ REFERENCES KnowledgeEdge + CodeChangeArchive
行存在。飞书 client / doc client / git platform / embedding / qdrant 全 monkeypatch，
pytest-socket 第二保险。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async

from delivery.models import IngestRun, WorkItem
from delivery.services import ingest_from_urls
from feishu.models import KeyFields
from knowledge.models import (
    CodeChangeArchive,
    EdgeRelation,
    EntityKind,
    KnowledgeEdge,
    KnowledgeEntity,
    generate_entity_id,
)
from knowledge.sources import feishu_document, feishu_work_item
from services.feishu import WorkItemInfo
from services.git_platform.models import MRDiffFile, MRDiffResult

# 回源 upsert / ingest 经 sync_to_async 跨线程 ORM 写库 → 须 transaction=True。
pytestmark = pytest.mark.django_db(transaction=True)

# DOMAIN §16 实测自然键
PROJECT_KEY = "000000000000000000000001"
STORY_ID = 1000000002
WORK_ITEM_TYPE = "story"
SOURCE_ID = f"{PROJECT_KEY}:{WORK_ITEM_TYPE}:{STORY_ID}"
PRD_TOKEN = "PrdDocToken123456"
PRD_URL = f"https://acme.feishu.cn/docx/{PRD_TOKEN}"
PRD_BODY = "# PRD 标题\n\nPRD 正文内容，验收点若干。"

BOARD_URL = f"https://project.feishu.cn/{PROJECT_KEY}/{WORK_ITEM_TYPE}/detail/{STORY_ID}"
REPO_PATH = "test/ingest-repo"
MR_IID = "5"
MR_URL = f"https://gitlab.com/{REPO_PATH}/-/merge_requests/{MR_IID}"

_MR_FILES = [
    MRDiffFile(
        old_path="src/auth.py",
        new_path="src/auth.py",
        diff="@@ -1,2 +1,4 @@\n def login(user):\n+    audit(user)\n+    log(user)\n     return token(user)\n",
    ),
]


async def _make_project():
    from projects.models import Space

    return await Space.objects.acreate(name="测试项目", feishu_project_key=PROJECT_KEY)


def _make_repo_with_credential():
    """Repository + GitCredential（明文 fallback），git_url 匹配 MR_URL。"""
    from repositories.models import GitCredential, Repository

    repo = Repository.objects.create(
        name="ingest-repo",
        git_url=f"https://gitlab.com/{REPO_PATH}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    GitCredential.objects.create(repository=repo, encrypted_token="plain-test-token")
    return repo


def _work_item_info() -> WorkItemInfo:
    """完整 WorkItemInfo（feishu_fields/raw_response 齐全，供 upsert + normalizer）。"""
    return WorkItemInfo(
        id=STORY_ID,
        name="一键摄取需求 A",
        description="需求描述",
        status="developing",
        project_key=PROJECT_KEY,
        work_item_type=WORK_ITEM_TYPE,
        fields={KeyFields.PRD_URL: PRD_URL},
        raw_response=json.dumps(
            {
                "data": [
                    {
                        "id": STORY_ID,
                        "name": "一键摄取需求 A",
                        "work_item_status": {
                            "state_key": "dev",
                            "current_nodes": [{"id": "s2", "name": "开发中"}],
                        },
                    }
                ]
            }
        ),
        feishu_fields=[
            {
                "field_key": "field_000001",
                "field_name": "需求文档",
                "field_value": PRD_URL,
                "field_type_key": "link",
                "field_alias": "prd_url",
            }
        ],
    )


@pytest.fixture
def mock_feishu(monkeypatch: pytest.MonkeyPatch):
    """monkeypatch 飞书 work_item client（upsert + normalizer）+ doc client。

    返回可调配置对象：``raise_doc`` 控制文档拉取异常（降级测试用）。
    """
    cfg = SimpleNamespace(raise_doc=False)

    class _FakeFeishuClient:
        async def get_work_item(self, *, project_key, work_item_id, work_item_type):
            return _work_item_info()

        async def get_work_item_relations(self, *, project_key, work_item_id, work_item_type):
            return []

    class _FakeDocClient:
        async def get_document_content(self, token):
            if cfg.raise_doc:
                raise RuntimeError("doc fetch boom")
            return PRD_BODY, []

    from unittest.mock import AsyncMock

    fake_client = _FakeFeishuClient()
    doc_factory = AsyncMock(return_value=_FakeDocClient())

    # WorkItemService.upsert 路径
    monkeypatch.setattr(
        "delivery.services.work_item_service.create_feishu_client_for_project",
        lambda project: fake_client,
    )
    # feishu_work_item.normalize 路径
    monkeypatch.setattr(
        feishu_work_item, "create_feishu_client_for_project", lambda project: fake_client
    )
    monkeypatch.setattr(feishu_work_item, "create_feishu_doc_client_for_project", doc_factory)
    # feishu_document.normalize 路径
    monkeypatch.setattr(feishu_document, "create_feishu_doc_client_for_project", doc_factory)
    return cfg


async def _make_run(board_url: str = BOARD_URL, mr_url: str = MR_URL) -> IngestRun:
    return await IngestRun.objects.acreate(
        board_url=board_url, mr_url=mr_url, status=IngestRun.Status.RUNNING
    )


# ============================================================================
# 三步全 ok：检索可测代理（实体 + 边 + 归档行存在）
# ============================================================================


async def test_three_steps_all_ok_persist_and_retrievable(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform
) -> None:
    """三步全 ok：WorkItem 落库 + Document/REFERENCES + CodeChangeArchive/code_change 实体。"""
    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)
    run = await _make_run()

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED
    assert result.completed_at is not None

    steps = result.steps
    assert steps["work_item"]["status"] == "ok"
    assert steps["work_item"]["identifier"]
    assert steps["document"]["status"] == "ok"
    assert steps["mr_diff"]["status"] == "ok"
    assert steps["mr_diff"]["identifier"]

    # 步 1：WorkItem 经 upsert 落库（三元组幂等命中）
    assert await WorkItem.objects.filter(
        feishu_project_key=PROJECT_KEY,
        work_item_type=WORK_ITEM_TYPE,
        work_item_id=STORY_ID,
    ).aexists()

    # 步 2：work_item + document knowledge 实体 + REFERENCES 边
    wi_entity_id = generate_entity_id("work_item", "feishu_work_item", SOURCE_ID)
    doc_entity_id = generate_entity_id("document", "feishu_document", PRD_TOKEN)
    assert await KnowledgeEntity.objects.filter(id=wi_entity_id).aexists()
    assert await KnowledgeEntity.objects.filter(id=doc_entity_id, kind="document").aexists()
    edge = await KnowledgeEdge.objects.aget(relation=EdgeRelation.REFERENCES)
    assert edge.source_entity_id == wi_entity_id
    assert edge.target_entity_id == doc_entity_id

    # 步 3：CodeChangeArchive 行 + code_change knowledge 实体
    # HDIFF-01：commit 锚定真实 merge_commit_sha + target_branch（非合成 mr-5 / 非 master）
    archive = await CodeChangeArchive.objects.aget(source_kind="mr_ingest")
    assert archive.commit_sha == "deadbeef" * 5
    assert archive.base_branch == "release/v1"
    assert archive.commit_sha != f"mr-{MR_IID}"
    # event_time（→ edge valid_at）锚定到 merge commit 业务时间（merged_at）
    assert archive.event_time == fake_git_platform.mr_metadata.merged_at
    assert fake_git_platform.mr_metadata_calls == [MR_IID]
    assert await KnowledgeEntity.objects.filter(kind=EntityKind.CODE_CHANGE).aexists()


# ============================================================================
# best-effort 独立降级：工作项 upsert 抛 → 其余步仍各自产出
# ============================================================================


async def test_work_item_step_failure_does_not_block_others(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform,
    monkeypatch,
) -> None:
    """WorkItemService.upsert 抛 → work_item failed + error，document / mr_diff 仍各自 ok。"""
    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)
    run = await _make_run()

    async def _boom(self, identity, source, *, fetch=True):
        raise RuntimeError("upsert boom")

    monkeypatch.setattr(
        "delivery.services.work_item_service.WorkItemService.upsert", _boom
    )

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED  # 步级失败不掀翻编排
    assert result.steps["work_item"]["status"] == "failed"
    assert result.steps["work_item"]["error"]
    # 其余步未被阻断
    assert result.steps["document"]["status"] == "ok"
    assert result.steps["mr_diff"]["status"] == "ok"


async def test_document_step_failure_does_not_block_mr(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform,
    monkeypatch,
) -> None:
    """文档 ingest 抛 → document failed + error，mr_diff 仍 ok（独立降级）。"""
    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)
    run = await _make_run()

    async def _ingest_boom(request):
        raise RuntimeError("ingest boom")

    monkeypatch.setattr("knowledge.ingestion.ingest", _ingest_boom)

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED
    assert result.steps["document"]["status"] == "failed"
    assert result.steps["document"]["error"]
    assert result.steps["mr_diff"]["status"] == "ok"


async def test_document_step_zero_output_marks_skipped(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform,
    monkeypatch,
) -> None:
    """normalizer 零产出（Space 不存在 / 无可摄取文档）→ document skipped（非 ok）+ error。

    WR-01 守护：``ingest()`` 在 normalizer 返回 ``[]`` 时静默返回 0（不抛异常），
    编排须据真实产出数记 ``skipped`` 而非 ``ok``，避免「零实体入库却显示成功」。
    其余步不受影响（独立降级）。
    """
    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)
    run = await _make_run()

    async def _ingest_empty(request):
        return 0

    monkeypatch.setattr("knowledge.ingestion.ingest", _ingest_empty)

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED
    assert result.steps["document"]["status"] == "skipped"
    assert result.steps["document"]["status"] != "ok"
    assert result.steps["document"]["error"]
    # 其余步未被阻断
    assert result.steps["work_item"]["status"] == "ok"
    assert result.steps["mr_diff"]["status"] == "ok"


async def test_mr_no_credential_marks_skipped(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform
) -> None:
    """凭证缺失 → 无法解析 commit 锚（merge_commit_sha 取不到）→ mr_diff skipped；
    绝不合成归档；其余步 ok（WR-02：anchor 不可用如实降级）。"""
    await _make_project()
    # 仓库存在但无凭证 → aresolve_mr_commit_anchor 缺凭证返回 None（早于 archive）
    from repositories.models import Repository

    await Repository.objects.acreate(
        name="ingest-repo",
        git_url=f"https://gitlab.com/{REPO_PATH}.git",
        git_platform="gitlab",
        default_branch="main",
    )
    run = await _make_run()

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED
    assert result.steps["work_item"]["status"] == "ok"
    assert result.steps["document"]["status"] == "ok"
    assert result.steps["mr_diff"]["status"] == "skipped"
    assert result.steps["mr_diff"]["error"]
    assert not await CodeChangeArchive.objects.filter(source_kind="mr_ingest").aexists()


async def test_mr_anchor_unavailable_marks_skipped_no_synthetic_archive(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform
) -> None:
    """有凭证但 merge_commit_sha 取不到（未合并 / 元数据失败）→ mr_diff skipped + error，
    绝不写入合成 mr-{iid} 归档（HDIFF-01 / WR-02 / T-33-03）；其余步不受影响。"""
    from services.git_platform.models import MRMetadataResult

    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    # anchor 不可用：success=True 但 merge_commit_sha 为空（未合并）
    fake_git_platform.mr_metadata = MRMetadataResult(
        success=True, merge_commit_sha="", target_branch="main"
    )
    run = await _make_run()

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.COMPLETED
    assert result.steps["work_item"]["status"] == "ok"
    assert result.steps["document"]["status"] == "ok"
    assert result.steps["mr_diff"]["status"] == "skipped"
    assert result.steps["mr_diff"]["error"]
    # 绝不合成归档：既无真实 sha 也无 mr-5 合成行
    assert not await CodeChangeArchive.objects.filter(source_kind="mr_ingest").aexists()
    # diff 拉取从未发生（anchor 解析在 archive 之前短路）
    assert fake_git_platform.mr_diff_calls == []


async def test_mr_modifies_chunk_edge_valid_at_anchored_to_merged_at(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform
) -> None:
    """MODIFIES_CHUNK 边 valid_at 锚定到 merge commit 业务时间（merged_at）。"""
    import uuid

    from code_relations.models import ChunkRegistry

    await _make_project()
    repo = await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)

    # 行号级 chunk：与 _MR_FILES 中 src/auth.py 的 hunk（新侧 1..4）行区间重叠
    cid = uuid.uuid4()
    await ChunkRegistry.objects.acreate(
        chunk_id=cid,
        content_hash="f" * 64,
        repository=repo,
        branch_name="",
        file_path="src/auth.py",
        chunk_index=0,
        line_start=1,
        line_end=10,
    )
    run = await _make_run()

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.steps["mr_diff"]["status"] == "ok"
    edge = await KnowledgeEdge.objects.aget(
        relation=EdgeRelation.MODIFIES_CHUNK, target_chunk_id=cid
    )
    assert edge.valid_at == fake_git_platform.mr_metadata.merged_at
    # chunk 指纹冻结进边 metadata（HDIFF-01 → HDIFF-02 对账依据）
    assert edge.metadata["chunk_content_hash"] == "f" * 64


# ============================================================================
# 重复摄取同一 MR：archive 已存在 → ok（幂等，不报 failed）
# ============================================================================


async def test_duplicate_mr_ingest_is_ok(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert, fake_git_platform
) -> None:
    """二次摄取同一 MR（archive 已存在，aexists 短路返回 None）→ mr_diff ok + identifier。"""
    await _make_project()
    await sync_to_async(_make_repo_with_credential)()
    fake_git_platform.mr_result = MRDiffResult(success=True, files=_MR_FILES)

    run1 = await _make_run()
    first = await ingest_from_urls(str(run1.id), BOARD_URL, MR_URL)
    assert first.steps["mr_diff"]["status"] == "ok"

    run2 = await _make_run()
    second = await ingest_from_urls(str(run2.id), BOARD_URL, MR_URL)

    assert second.steps["mr_diff"]["status"] == "ok"
    assert second.steps["mr_diff"]["identifier"]
    # 只归档一次（幂等锚）
    assert await CodeChangeArchive.objects.filter(source_kind="mr_ingest").acount() == 1


# ============================================================================
# URL 解析失败 → 对应步 skipped，编排不抛、status=completed
# ============================================================================


async def test_unparseable_urls_skip_steps_without_crash(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """board_url / mr_url 均不可解析 → 三步 skipped，编排不抛、status=completed。"""
    run = await _make_run(board_url="https://example.com/not-a-board", mr_url="not-a-url")

    result = await ingest_from_urls(
        str(run.id), "https://example.com/not-a-board", "not-a-url"
    )

    assert result.status == IngestRun.Status.COMPLETED
    assert result.steps["work_item"]["status"] == "skipped"
    assert result.steps["work_item"]["error"]
    assert result.steps["document"]["status"] == "skipped"
    assert result.steps["mr_diff"]["status"] == "skipped"
    assert result.steps["mr_diff"]["error"]


async def test_unmatched_mr_url_skipped(
    mock_feishu, mock_ensure, mock_embedding, mock_qdrant_client, mock_upsert
) -> None:
    """mr_url 可解析但无匹配 Repository（SSRF 边界）→ mr_diff skipped，不 fetch。"""
    await _make_project()
    run = await _make_run()

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    # 无任何 Repository 落库 → aresolve_repo_and_mr 返回 None
    assert result.steps["mr_diff"]["status"] == "skipped"
    assert result.status == IngestRun.Status.COMPLETED


# ============================================================================
# 编排级异常 → status=failed + 脱敏 error（无明文 token/Bearer）
# ============================================================================


async def test_orchestration_level_exception_failed_and_redacted(
    mock_feishu, monkeypatch
) -> None:
    """编排级异常 → status=failed + error，error 抹掉 Bearer token（T-32-02）。"""
    run = await _make_run()

    def _boom(url):
        raise RuntimeError("auth failed Bearer abc.def.ghi token=supersecretvalue")

    monkeypatch.setattr("delivery.services.ingest_orchestrator.parse_board_url", _boom)

    result = await ingest_from_urls(str(run.id), BOARD_URL, MR_URL)

    assert result.status == IngestRun.Status.FAILED
    assert result.error
    # 脱敏：明文 token 不落库
    assert "abc.def.ghi" not in result.error
    assert "supersecretvalue" not in result.error
    assert "Bearer ***" in result.error
