"""Phase 35 Plan 01 — screenshot_recall 服务守护测试（VIS-01，TDD）。

锁定截图 → 多模态 LLM 提语义 → 文本 query → 既有交付知识检索召回的三态契约：

1. **vision 提语义**：mock vision 模型 → extract_semantics 返回结构化三段语义。
2. **graceful 降级**：无 provider / 无 default_model / 非 vision 模型 / 调用异常 → 返回 None
   （不抛、不冒泡），对齐 Phase 24 sensitive_detect 可选 LLM 降级范式。
3. **不建图片向量库**（VIS-01 标准 3）：模块源码不含 qdrant / EmbeddingService 图片向量
   写入面，亦不持久化原图（不调 store_image_bytes / 不写盘）。
4. **文本 query 召回 work_item**：拼接语义 → 复用 DeliveryKnowledgeSearchService.search_similar
   且 entity_kinds 锁定 ["work_item"]；提取降级 → degraded=true；召回异常 → degraded=false
   + results=[]（区分降级与空召回）。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import screenshot_recall
from services.provider_config import ProviderMissingError, ProviderType
from services.screenshot_recall import (
    DEGRADE_EXTRACTION_FAILED,
    DEGRADE_NO_VISION_MODEL,
    ExtractedSemantics,
    extract_semantics,
    recall_from_screenshot,
)

# 最小合法 PNG（1x1），仅用于喂 extract_semantics 的 image bytes；绝不落盘。
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000d49444154789c63f8cf0000000201010adf3b9b0000000049454e44ae426082"
)


class _FakeChatModel:
    """记录 ainvoke 入参的假 vision 模型，返回预置 JSON content。"""

    def __init__(self, payload: str, recorder: dict) -> None:
        self._payload = payload
        self._recorder = recorder

    async def ainvoke(self, messages):
        self._recorder["messages"] = messages
        return SimpleNamespace(content=self._payload)


def _patch_vision_ok(
    monkeypatch: pytest.MonkeyPatch,
    payload: str,
    recorder: dict,
    *,
    provider_type: ProviderType = ProviderType.ANTHROPIC,
    model: str = "claude-sonnet-4-5-20250929",
) -> None:
    """monkeypatch provider 可用（vision 模型）+ 假 model 返回 payload。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(
            provider_type=provider_type,
            api_key="fake-key",
            base_url="",
            extra={"default_model": model},
        )

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *_a, **_k: _FakeChatModel(payload, recorder),
        raising=True,
    )


# ===========================================================================
# 1. vision 提语义
# ===========================================================================


async def test_extract_semantics_returns_three_segments(monkeypatch) -> None:
    """mock vision 模型 → extract_semantics 返回 text/ui_elements/business_intent。"""
    recorder: dict = {}
    payload = json.dumps(
        {
            "text": "登录页标题：欢迎回来",
            "ui_elements": "用户名输入框、密码输入框、登录按钮",
            "business_intent": "用户认证登录流程",
        },
        ensure_ascii=False,
    )
    _patch_vision_ok(monkeypatch, payload, recorder)

    result, reason = await extract_semantics(PNG_1X1, "image/png")

    assert reason is None  # 成功路径无降级原因码（WR-01）。
    assert isinstance(result, ExtractedSemantics)
    assert result.text == "登录页标题：欢迎回来"
    assert result.ui_elements == "用户名输入框、密码输入框、登录按钮"
    assert result.business_intent == "用户认证登录流程"
    # 多模态 HumanMessage 含 image block（base64 inline，未落盘）。
    assert "messages" in recorder


async def test_extract_semantics_tolerates_json_wrapped_in_text(monkeypatch) -> None:
    """模型输出含额外文字时，截取首个 {} 块解析（容错）。"""
    recorder: dict = {}
    payload = '这是结果：{"text": "标题", "ui_elements": "", "business_intent": "下单"} 完毕'
    _patch_vision_ok(monkeypatch, payload, recorder)

    result, reason = await extract_semantics(PNG_1X1, "image/png")
    assert reason is None
    assert result is not None
    assert result.text == "标题"
    assert result.business_intent == "下单"


# ===========================================================================
# 2. graceful 降级（一律返回 None，不抛）
# ===========================================================================


async def test_extract_semantics_provider_missing_returns_none(monkeypatch) -> None:
    """provider 未配置（ProviderMissingError）→ (None, no_vision_model)（降级，不抛）。"""

    async def _missing(*_a, **_k):
        return ProviderMissingError(
            missing_provider="anthropic",
            recommended_action="配置凭证",
            source_attempted="system",
        )

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_missing),
        raising=True,
    )

    sem, reason = await extract_semantics(PNG_1X1, "image/png")
    assert sem is None
    assert reason == DEGRADE_NO_VISION_MODEL


async def test_extract_semantics_no_default_model_returns_none(monkeypatch) -> None:
    """resolved.extra 无 default_model → (None, no_vision_model)。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(provider_type=ProviderType.ANTHROPIC, extra={})

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )

    sem, reason = await extract_semantics(PNG_1X1, "image/png")
    assert sem is None
    assert reason == DEGRADE_NO_VISION_MODEL


async def test_extract_semantics_text_only_model_returns_none(monkeypatch) -> None:
    """已知 text-only 模型（deepseek）→ 无 vision 能力降级，返回 None。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(
            provider_type=ProviderType.ANTHROPIC,
            api_key="k",
            base_url="",
            extra={"default_model": "deepseek-chat"},
        )

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )
    # build_chat_model 不应被调用（能力判定先短路）。
    monkeypatch.setattr(
        "agents.llm_factory.build_chat_model",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("不应构造模型")),
        raising=True,
    )

    sem, reason = await extract_semantics(PNG_1X1, "image/png")
    assert sem is None
    assert reason == DEGRADE_NO_VISION_MODEL


async def test_extract_semantics_invoke_raises_returns_none(monkeypatch) -> None:
    """provider 可用但模型调用抛异常 → (None, extraction_failed)，不冒泡（WR-01）。"""

    async def _resolve(*_a, **_k):
        return SimpleNamespace(
            provider_type=ProviderType.ANTHROPIC,
            api_key="k",
            base_url="",
            extra={"default_model": "claude-sonnet-4-5-20250929"},
        )

    def _boom(*_a, **_k):
        raise RuntimeError("vision exploded")

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_resolve),
        raising=True,
    )
    monkeypatch.setattr("agents.llm_factory.build_chat_model", _boom, raising=True)

    sem, reason = await extract_semantics(PNG_1X1, "image/png")
    assert sem is None
    assert reason == DEGRADE_EXTRACTION_FAILED


async def test_extract_semantics_unparseable_output_is_extraction_failed(monkeypatch) -> None:
    """模型已配置但输出无法解析为 JSON → (None, extraction_failed)（非配置降级，WR-01）。"""
    recorder: dict = {}
    _patch_vision_ok(monkeypatch, "这不是 JSON，只是一段普通文字。", recorder)

    sem, reason = await extract_semantics(PNG_1X1, "image/png")
    assert sem is None
    assert reason == DEGRADE_EXTRACTION_FAILED


# ===========================================================================
# 3. 不建图片向量库 / 不持久化原图（grep 守护）
# ===========================================================================


def test_module_has_no_image_vector_db_or_persistence() -> None:
    """源码守护：不 import qdrant / EmbeddingService，不持久化原图（store_image_bytes/write_bytes）。"""
    source = Path(screenshot_recall.__file__).read_text(encoding="utf-8")
    for forbidden in ("qdrant", "EmbeddingService", "store_image_bytes", "write_bytes"):
        assert forbidden not in source, f"screenshot_recall 不应出现 {forbidden!r}"


# ===========================================================================
# 4. 文本 query 召回 work_item（Task 2）
# ===========================================================================


def _make_search_result(
    *,
    source_id: str,
    title: str,
    score: float,
    feishu_url: str | None = None,
):
    """构造一条 work_item kind 的 SearchResultDTO。"""
    from knowledge.retrieval_types import (
        EntityMetadata,
        ProvenanceLinks,
        SearchResultDTO,
    )

    meta = EntityMetadata(
        entity_id=uuid.uuid4(),
        entity_kind="work_item",
        version=1,
        title=title,
        valid_at=None,
        invalid_at=None,
        source_kind="feishu",
        source_id=source_id,
        origin="feishu",
        event_time=None,
        space_id=None,
        repository_id=None,
        provenance=ProvenanceLinks(feishu_url=feishu_url),
    )
    return SearchResultDTO(
        score=score, vector_score=score, recency_score=0.0, entity=meta
    )


def _patch_search(monkeypatch: pytest.MonkeyPatch, results, recorder: dict):
    """monkeypatch DeliveryKnowledgeSearchService.search_similar 记录入参并返回 results。"""
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    async def _search(self, query, *, user, top_k=10, entity_kinds=None, **kw):
        recorder["query"] = query
        recorder["entity_kinds"] = entity_kinds
        recorder["top_k"] = top_k
        return results

    monkeypatch.setattr(
        DeliveryKnowledgeSearchService, "search_similar", _search, raising=True
    )


async def test_recall_maps_work_items_and_locks_entity_kind(monkeypatch) -> None:
    """正常路径 → degraded=false + results 映射含 work_item_id/title/relevance/link，
    且 entity_kinds 锁定 ["work_item"]。"""
    recorder_llm: dict = {}
    _patch_vision_ok(
        monkeypatch,
        json.dumps({"text": "下单页", "ui_elements": "提交按钮", "business_intent": "下单"}),
        recorder_llm,
    )
    recorder_search: dict = {}
    results = [
        _make_search_result(
            source_id="WI-100",
            title="下单需求",
            score=0.87,
            feishu_url="https://feishu.cn/wi/100",
        ),
    ]
    _patch_search(monkeypatch, results, recorder_search)

    out = await recall_from_screenshot(
        PNG_1X1, "image/png", user=SimpleNamespace(id=1)
    )

    assert out["degraded"] is False
    assert out["semantics"]["business_intent"] == "下单"
    assert out["query"]
    assert recorder_search["entity_kinds"] == ["work_item"]
    assert len(out["results"]) == 1
    item = out["results"][0]
    assert item["work_item_id"] == "WI-100"
    assert item["title"] == "下单需求"
    assert item["relevance"] == pytest.approx(0.87)
    assert item["link"] == "https://feishu.cn/wi/100"
    assert item["source"] == "delivery_knowledge"


async def test_recall_clamps_relevance_to_unit_interval(monkeypatch) -> None:
    """融合分越界（>1 / <0）→ relevance 钳制到 [0,1]，且不破坏排序（WR-03）。"""
    recorder_llm: dict = {}
    _patch_vision_ok(
        monkeypatch,
        json.dumps({"text": "页", "ui_elements": "", "business_intent": "查询"}),
        recorder_llm,
    )
    recorder_search: dict = {}
    results = [
        _make_search_result(source_id="WI-A", title="高分", score=1.42),
        _make_search_result(source_id="WI-B", title="负分", score=-0.3),
    ]
    _patch_search(monkeypatch, results, recorder_search)

    out = await recall_from_screenshot(
        PNG_1X1, "image/png", user=SimpleNamespace(id=1)
    )

    assert out["degraded"] is False
    assert out["results"][0]["relevance"] == pytest.approx(1.0)
    assert out["results"][1]["relevance"] == pytest.approx(0.0)
    # 钳制单调，保留原始顺序（WI-A 在前）。
    assert [r["work_item_id"] for r in out["results"]] == ["WI-A", "WI-B"]


async def test_recall_degraded_when_extract_fails(monkeypatch) -> None:
    """提取降级（ProviderMissingError）→ degraded=true + results=[] + degraded_reason。"""

    async def _missing(*_a, **_k):
        return ProviderMissingError(missing_provider="anthropic")

    monkeypatch.setattr(
        screenshot_recall.ProviderConfigService,
        "aresolve_or_error",
        staticmethod(_missing),
        raising=True,
    )

    out = await recall_from_screenshot(
        PNG_1X1, "image/png", user=SimpleNamespace(id=1)
    )
    assert out["degraded"] is True
    assert out["degraded_code"] == DEGRADE_NO_VISION_MODEL
    assert out["results"] == []
    assert out["degraded_reason"]
    assert out["semantics"] is None


async def test_recall_empty_semantics_skips_search(monkeypatch) -> None:
    """三段语义全空 → 不发起向量检索，按 extraction_failed 降级返回（WR-02）。"""
    recorder_llm: dict = {}
    # 模型返回合法 JSON 但三段全空（_parse_semantics_json 仍得非 None 空语义）。
    _patch_vision_ok(
        monkeypatch,
        json.dumps({"text": "", "ui_elements": "", "business_intent": ""}),
        recorder_llm,
    )
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    async def _must_not_call(self, *_a, **_k):
        raise AssertionError("空 query 不应触发 search_similar")

    monkeypatch.setattr(
        DeliveryKnowledgeSearchService, "search_similar", _must_not_call, raising=True
    )

    out = await recall_from_screenshot(
        PNG_1X1, "image/png", user=SimpleNamespace(id=1)
    )
    assert out["degraded"] is True
    assert out["degraded_code"] == DEGRADE_EXTRACTION_FAILED
    assert out["results"] == []


async def test_recall_search_error_is_not_degraded(monkeypatch) -> None:
    """召回阶段异常 → degraded=false + results=[]（语义在、召回空，no-results 而非 error）。"""
    recorder_llm: dict = {}
    _patch_vision_ok(
        monkeypatch,
        json.dumps({"text": "页面", "ui_elements": "", "business_intent": "查询"}),
        recorder_llm,
    )
    from knowledge.retrieval import DeliveryKnowledgeSearchService

    async def _boom(self, *_a, **_k):
        raise RuntimeError("retrieval down")

    monkeypatch.setattr(
        DeliveryKnowledgeSearchService, "search_similar", _boom, raising=True
    )

    out = await recall_from_screenshot(
        PNG_1X1, "image/png", user=SimpleNamespace(id=1)
    )
    assert out["degraded"] is False
    assert out["results"] == []
    assert out["semantics"] is not None
