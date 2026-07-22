"""里程碑四面检索端到端验收测试（Phase 104 / v0.17.0「统一知识库与全链路联动」验收门）。

ROADMAP Phase 104 成功标准 4：种同一条 learning case（create → ingestion → 向量入库），
断言它在四处均可检索到，且排序统一（同一 ``DeliveryKnowledgeSearchService``）：

1. **Chat 工具面**：``agents/tools/knowledge_read_tools.py`` 的 ``search_learning_cases``
   （Phase 102 产物，会话 owner fail-closed 权限前置）；
2. **编排召回面**：``DeliveryKnowledgeRecallAdapter.recall``（Phase 102 扩容后默认
   kinds 含 learning_case）；
3. **MCP view 面**：POST ``/api/mcp/tools/search_learning_cases/``（Phase 100 向量版）；
4. **容器知识 MCP 链**：同 URL 契约（``reverse`` 反查 == task 侧转调字面 URL 模板）
   + 组合覆盖文档化（详见对应用例 docstring）。

统一排序断言（locked）：MCP 面与 Chat 面 top-1 的 case_id（以 MCP 面返回的 entity
标识为准）一致且为强相关种子条——两面同经
``mcp_tools.learning_case_service.search_learning_cases`` →
``DeliveryKnowledgeSearchService`` 排序，本断言是该收口的外部可观察证明。

测试基建自包含（里程碑验收不跨测试模块 import）：本地复刻
``tests/mcp_tools/test_learning_cases.py`` 的 golden_vector_stack 范式（内存 Qdrant +
确定性 bag-of-words 假 dense/sparse embedding + 后台摄取 no-op、测试内显式
``ingest()`` 同步补摄避免 on_commit 后台竞态）与 ``tests/mcp_tools/conftest.py`` 的
mcp_client 范式（PAT 铸造 + APIClient Bearer 认证）。

双种子区分度设计（T-104-07）：强相关条（与查询共享「登录超时/token/刷新」token）
与弱相关条（无共享 token）并存，top-1 必须命中强相关条，防「返回任意结果即过」
的验收假通过；容器链 URL 用 reverse 反查而非硬编码复读。
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from rest_framework.test import APIClient

from interactions.ledger import create_interaction_run
from knowledge.collection import DEFAULT_EMBEDDING_DIMENSION
from knowledge.ingestion import IngestionRequest, ingest
from knowledge.models import generate_entity_id
from mcp_tools.models import McpLearningCase, McpWorkItemContext
from runners.models import hash_token

# SQLite + async（ingest 内 sync_to_async 跨线程）需要 transaction=True（knowledge 域同款纪律）。
pytestmark = pytest.mark.django_db(transaction=True)

_SEARCH_URL = "/api/mcp/tools/search_learning_cases/"

# 强/弱种子共用的检索 query：与强相关条共享「登录超时/token/刷新」token，
# 与弱相关条零共享 token（排序断言的区分度来源）。
_QUERY = "登录超时 token 刷新"


# ============================================================================
# 自包含基建：内存 Qdrant + 确定性假 embedding（本地复刻，不跨测试模块 import）
# ============================================================================

_TERM_RE = re.compile(r"[A-Za-z0-9_\-/.]{2,}|[\u4e00-\u9fff]")


def _terms(text: str) -> list[str]:
    """ASCII 词/路径整体成 token、中文逐字成 token（共享 token 越多余弦越近）。"""
    return _TERM_RE.findall(text.lower())


def _stable_index(token: str, space: int) -> int:
    """确定性 token → 索引（禁 builtin hash：进程级随机化会破坏确定性）。"""
    return int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % space


def _bow_dense(text: str) -> list[float]:
    """bag-of-words 假 dense 向量（L2 归一化，维度对齐建集合维度）。"""
    vector = [0.0] * DEFAULT_EMBEDDING_DIMENSION
    for token in _terms(text):
        vector[_stable_index(token, DEFAULT_EMBEDDING_DIMENSION)] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _bow_sparse(text: str) -> dict:
    """token-hash 假 sparse 编码（Qdrant SparseVector 格式）。"""
    counts: dict[int, float] = {}
    for token in _terms(text):
        index = _stable_index(token, 2**31)
        counts[index] = counts.get(index, 0.0) + 1.0
    indices = sorted(counts)
    return {"indices": indices, "values": [counts[index] for index in indices]}


@pytest.fixture
def golden_vector_stack(monkeypatch: pytest.MonkeyPatch):
    """内存 Qdrant + 确定性假 dense/sparse embedding + 后台摄取 no-op。"""
    from qdrant_client import QdrantClient

    from services.embedding import EmbeddingService
    from services.qdrant_service import QdrantService
    from services.sparse_encoder import SparseEncoderService

    local_client = QdrantClient(":memory:")
    monkeypatch.setattr(QdrantService, "get_client", classmethod(lambda cls: local_client))
    # aschedule_ingestion 的 on_commit → 后台线程摄取改 no-op：transaction=True 下
    # on_commit 会真触发，测试内显式 await ingest(...) 同步补摄避免竞态。
    monkeypatch.setattr("knowledge.ingestion.run_in_background", lambda *args, **kwargs: None)

    async def _dense_one(text: str) -> list[float]:
        return _bow_dense(text)

    async def _dense_batch(texts: list[str], **_kwargs) -> list[list[float]]:
        return [_bow_dense(text) for text in texts]

    monkeypatch.setattr(EmbeddingService, "generate_embedding", staticmethod(_dense_one))
    monkeypatch.setattr(EmbeddingService, "generate_embeddings_batch", staticmethod(_dense_batch))
    monkeypatch.setattr(SparseEncoderService, "encode", staticmethod(_bow_sparse))
    monkeypatch.setattr(
        SparseEncoderService,
        "encode_batch",
        staticmethod(lambda texts: [_bow_sparse(text) for text in texts]),
    )
    return local_client


@pytest.fixture
def mcp_client(make_access_token) -> tuple[APIClient, str]:
    """PAT 铸造 + APIClient Bearer 认证（tests/mcp_tools/conftest.py 范式本地复刻）。

    PAT 归属 ``access_user`` == ``user`` fixture（project admin 成员）——与 Chat 面的
    会话 owner、编排召回面的 ``session.created_by`` 是**同一 actor**，保证四面权限
    scope 一致、排序断言可比。
    """
    _token, plaintext = make_access_token(name="milestone-e2e-token")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    return client, plaintext


# ============================================================================
# 种子：强相关 + 弱相关双 learning case（create → 显式 ingest 向量入库）
# ============================================================================


def _make_case(
    project,
    *,
    title: str,
    problem: str,
    root_cause: str,
    solution: str,
    repositories: list[str],
    files: list[str],
    symbols: list[str],
    work_item_id: int,
) -> McpLearningCase:
    """建 learning case 行（含 context 锚料，space→project 供权限闸）。"""
    run = create_interaction_run(
        token_fingerprint=hash_token(f"milestone-{uuid.uuid4().hex[:8]}"),
        source="mcp",
    )
    context = McpWorkItemContext.objects.create(
        run=run,
        space=project,
        feishu_project_key=project.feishu_project_key,
        work_item_type="bug",
        work_item_id=work_item_id,
        name=title,
        status=McpWorkItemContext.Status.COMPLETED,
        work_item_status="done",
        description=problem,
    )
    embedding_text = "\n".join(
        [
            title,
            problem,
            root_cause,
            solution,
            "merged",
            " ".join(repositories),
            " ".join(files),
            " ".join(symbols),
        ]
    )
    return McpLearningCase.objects.create(
        run=run,
        context=context,
        work_item_type="bug",
        work_item_id=work_item_id,
        title=title,
        problem=problem,
        root_cause=root_cause,
        solution=solution,
        outcome="merged",
        repositories=repositories,
        files=files,
        symbols=symbols,
        embedding_text=embedding_text,
    )


def _seed_dual_cases(project) -> tuple[McpLearningCase, McpLearningCase]:
    """种双 case：强相关（共享「登录超时/token/刷新」token）+ 弱相关（零共享 token）。

    均走 create → 显式 ``await ingest(...)`` 真实全链路向量入库（PG 实体/版本 +
    内存 Qdrant 向量点）。返回 (strong, weak)。
    """
    strong = _make_case(
        project,
        title="登录超时 Bug 修复",
        problem="登录超时后错误提示不清晰，token 刷新边界遗漏。",
        root_cause="session token 过期边界判断遗漏",
        solution="统一刷新 token 后再显示超时提示。",
        repositories=["auth-service"],
        files=["src/auth/session.py", "tests/test_session.py"],
        symbols=["refresh_session"],
        work_item_id=201,
    )
    weak = _make_case(
        project,
        title="支付回调重试风暴治理",
        problem="支付回调重复重试导致订单重复入账。",
        root_cause="回调幂等键缺失",
        solution="按订单号加幂等锁，重试指数退避。",
        repositories=["payments-service"],
        files=["src/payment/callback.py"],
        symbols=["retry_callback"],
        work_item_id=202,
    )
    for case in (strong, weak):
        assert (
            async_to_sync(ingest)(
                IngestionRequest("learning_case", str(case.id), "milestone_e2e_seed")
            )
            >= 1
        )
    return strong, weak


# ============================================================================
# 面 3（MCP view）+ 面 1（Chat 工具）+ 统一排序断言
# ============================================================================


def test_mcp_view_and_chat_tool_unified_top1(
    golden_vector_stack,
    mcp_client: tuple[APIClient, str],
    project,
    project_memberships,
    user,
) -> None:
    """面 3 + 面 1 + 统一排序：MCP view 与 Chat 工具均命中强相关条且 top-1 一致。

    统一排序断言（locked）：MCP 面 top-1 case_id == Chat 面 top-1 case_id ==
    强相关种子条。两面同经 ``mcp_tools.learning_case_service.search_learning_cases``
    → ``DeliveryKnowledgeSearchService`` 的同一排序，本断言是该收口（工具面收敛
    后检索质量不降级、排序统一）的外部可观察证明；弱相关条在场保证断言有区分度
    （T-104-07：防「返回任意结果即过」）。
    """
    from agents.tools.knowledge_read_tools import search_learning_cases as chat_search
    from chat.models import Conversation

    client, _plaintext = mcp_client
    strong, weak = _seed_dual_cases(project)

    # ---- 面 3（MCP view）：POST /api/mcp/tools/search_learning_cases/ ----
    mcp_response = client.post(_SEARCH_URL, {"query": _QUERY, "limit": 5}, format="json")
    assert mcp_response.status_code == 200
    mcp_body = mcp_response.json()
    assert mcp_body["results"], "MCP view 面召回集合不得为空"
    mcp_hit_ids = [item["case_id"] for item in mcp_body["results"]]
    assert str(strong.id) in mcp_hit_ids, "强相关种子条必须经 MCP view 面可检索"
    # 记录 MCP 面返回的 entity 标识（case_id）——统一排序断言以此为准。
    mcp_top1 = mcp_body["results"][0]["case_id"]
    assert mcp_top1 == str(strong.id), "MCP 面 top-1 必须是强相关条（弱相关条不得抢位）"

    # ---- 面 1（Chat 工具）：会话 owner 权限前置 + 工具函数直调 ----
    # 会话 owner == PAT 归属用户（同一 actor，权限 scope 与 MCP 面一致）。
    conversation = Conversation.objects.create(title="milestone-e2e", created_by=user)
    chat_result = async_to_sync(chat_search)(
        query=_QUERY, limit=5, conversation_id=str(conversation.id)
    )
    assert chat_result.success is True
    chat_results = chat_result.output["results"]
    assert chat_results, "Chat 工具面召回集合不得为空"
    chat_hit_ids = [item["case_id"] for item in chat_results]
    assert str(strong.id) in chat_hit_ids, "同一条 case 必须经 Chat 工具面可检索"

    # ---- 统一排序断言（locked）：两面 top-1 entity 标识一致 ----
    chat_top1 = chat_results[0]["case_id"]
    assert mcp_top1 == chat_top1, "MCP 与 Chat 两面 top-1 必须一致（同一排序服务）"


# ============================================================================
# 面 2（编排召回）：DeliveryKnowledgeRecallAdapter.recall（learning_case kind）
# ============================================================================


def test_recall_adapter_surface_hits_seed_case(
    golden_vector_stack,
    project,
    project_memberships,
    user,
) -> None:
    """面 2：编排召回 hits 中存在 kind/entity 指向种子 learning case 的命中。

    ``ConvergenceSession.stage_state.decomposition.requirement_text`` 作 query
    （engine 同款取数路径）；``created_by`` 为召回权限 actor（与面 1/3 同一用户）。
    learning_case kind 在 Phase 102 扩容后的默认 kinds 集合内，无需额外配置。
    命中经知识实体 id 精确断言：``generate_entity_id("learning_case",
    "learning_case", str(case.id))`` 是 ingest 入图的唯一派生入口（uuid5 稳定）。
    """
    from delivery.models import ConvergenceSession, ConvergenceSessionEntrypoint
    from services.process_runtime import DeliveryKnowledgeRecallAdapter

    strong, _weak = _seed_dual_cases(project)
    session = ConvergenceSession.objects.create(
        process_type="technical_plan",
        entrypoint=ConvergenceSessionEntrypoint.CHAT,
        current_stage="recall",
        stage_state={"decomposition": {"requirement_text": _QUERY}},
        created_by=user,
    )

    result = async_to_sync(DeliveryKnowledgeRecallAdapter().recall)(session)

    assert result["query"] == _QUERY
    assert "learning_case" in result["kinds"], "learning_case 必须在默认召回 kinds 集合内"
    expected_entity_id = str(generate_entity_id("learning_case", "learning_case", str(strong.id)))
    learning_hits = [hit for hit in result["hits"] if hit["kind"] == "learning_case"]
    assert learning_hits, "编排召回面必须命中 learning_case kind"
    assert expected_entity_id in [hit["entity_id"] for hit in learning_hits], (
        "编排召回命中的 entity 必须指向强相关种子 learning case"
    )


# ============================================================================
# 面 4（容器知识 MCP 链）：同 URL 契约 + 组合覆盖文档化
# ============================================================================


def test_container_chain_same_url_contract(db) -> None:
    """面 4：容器链同 URL 契约——reverse 反查 == task 侧转调的字面 URL 模板。

    组合覆盖逻辑（locked，per CONTEXT 决策）：

    - **task 侧半边**：``task/tests/test_knowledge_tools.py``（mock 端点模式）已验证
      task 进程内 SDK MCP server handler 对
      ``{base}/api/mcp/tools/{tool_name}/``（``task/core/knowledge_tools.py``
      的字面拼接模板）的请求构造与响应解析契约；
    - **服务端半边**：本文件面 3 用例已断言同一 URL 上的 view 行为是真实向量检索
      （种子 case 可召回、排序统一）；
    - **胶合断言（本用例）**：``reverse("mcp-tool-search-learning-cases")`` 反查出的
      服务端挂载路径 == 容器侧转调拼出的字面 URL——两半边说的是同一个端点。

    三者组合即证明：容器内编码代理经知识 MCP 代理可检索到同一条 case
    （服务端链路回归另见 ``server/tests/mcp_tools/test_container_knowledge_chain.py``）。
    reverse 反查而非硬编码复读（T-104-07）：URL 挂载漂移时本断言显形，
    而不是测试与生产一起漂移。
    """
    # task/core/knowledge_tools.py: url = f"{base}/api/mcp/tools/{tool_name}/"
    container_url_template = "/api/mcp/tools/{tool_name}/"
    assert reverse("mcp-tool-search-learning-cases") == container_url_template.format(
        tool_name="search_learning_cases"
    )
    assert reverse("mcp-tool-search-learning-cases") == _SEARCH_URL
