"""FeatureListExtractor 守护测试（Phase 87，BOARD-01 输入侧）：

- 多源输入归一化 fail-soft（文件 + 飞书链接回拉 + 粘贴文本；单源失败仅降级）。
- 三源全空 → ValueError。
- 结构化抽取（FakeChatModel seam）：模块→功能点→验收项；features_flat 每条含 module/name/description。
- 82KB demo 冒烟：分块生效（chunk_count>1）+ degraded 标志置位 + 不抛。
- 抽取处于 board_split call_source 作用域；board_split 已纳入受控枚举。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from agents.call_source import CallSource, get_call_source
from initiatives.services import FeatureListExtractor

_DEMO_PATH = (
    Path(__file__).resolve().parents[3] / ".planning" / "feature-list-demo.md"
)

_EXTRACTOR_MOD = "initiatives.services.feature_list_extractor"

# LLM 抽取返回的固定结构化 JSON（两模块，各含功能点 + 验收项）。
_FAKE_JSON = (
    '{"modules":[{"name":"模块A","features":[{"name":"功能点A1",'
    '"description":"A1 原文片段","acceptance":["验收A1-1","验收A1-2"]}]},'
    '{"name":"模块B","features":[{"name":"功能点B1",'
    '"description":"B1 原文片段","acceptance":["验收B1-1"]}]}]}'
)


class _FakeChatModel:
    """测试用 chat model：ainvoke 恒返回固定 JSON（多次调用安全，供分块场景复用）。"""

    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, _messages: list[object]) -> AIMessage:
        return AIMessage(
            content=self._content,
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def _patch_llm(monkeypatch: pytest.MonkeyPatch, content: str = _FAKE_JSON) -> list[str]:
    """patch provider 解析 + build_chat_model；返回 call_source 捕获列表。"""
    monkeypatch.setattr(
        FeatureListExtractor,
        "_aresolve_model",
        AsyncMock(return_value=(SimpleNamespace(provider_type="anthropic"), "claude-x")),
    )
    fake = _FakeChatModel(content)
    captured: list[str | None] = []

    def _fake_build(*_args: object, **_kwargs: object) -> _FakeChatModel:
        captured.append(get_call_source())
        return fake

    monkeypatch.setattr("agents.llm_factory.build_chat_model", _fake_build)
    return captured


# ===========================================================================
# normalize_sources（多源 fail-soft）
# ===========================================================================


async def test_normalize_merges_three_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = SimpleNamespace(
        get_document_content=AsyncMock(return_value=("# 飞书正文\n飞书功能点", []))
    )
    monkeypatch.setattr(
        f"{_EXTRACTOR_MOD}.create_feishu_doc_client_for_project",
        AsyncMock(return_value=fake_client),
    )
    merged = await FeatureListExtractor().normalize_sources(
        uploaded_text="文件功能点",
        feishu_url="https://x.feishu.cn/docx/doxcnABC",
        pasted_text="粘贴功能点",
        space=SimpleNamespace(id="s1"),
    )
    assert "[来源:文件]" in merged
    assert "[来源:飞书文档]" in merged
    assert "[来源:粘贴]" in merged
    assert "文件功能点" in merged
    assert "飞书功能点" in merged
    assert "粘贴功能点" in merged


async def test_normalize_feishu_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    """飞书源回拉失败 → 仅降级跳过，其余源仍合并（不抛）。"""
    monkeypatch.setattr(
        f"{_EXTRACTOR_MOD}.create_feishu_doc_client_for_project",
        AsyncMock(side_effect=RuntimeError("feishu down")),
    )
    merged = await FeatureListExtractor().normalize_sources(
        feishu_url="https://x.feishu.cn/docx/doxcnABC",
        pasted_text="粘贴功能点",
        space=SimpleNamespace(id="s1"),
    )
    assert "[来源:飞书文档]" not in merged
    assert "粘贴功能点" in merged


async def test_normalize_all_empty_raises() -> None:
    with pytest.raises(ValueError, match="无可用 feature list 输入源"):
        await FeatureListExtractor().normalize_sources(
            uploaded_text="  ", feishu_url=None, pasted_text=""
        )


# ===========================================================================
# extract_structure（分块 + LLM 抽取 + call_source）
# ===========================================================================


@pytest.mark.django_db(transaction=True)
async def test_extract_structure_multi_module(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_llm(monkeypatch)
    raw = (
        "## 模块A\n功能点 A1 描述\n\n"
        "## 模块B\n功能点 B1 描述\n"
    )
    result = await FeatureListExtractor().extract_structure(
        raw, space=SimpleNamespace(id="s1")
    )
    assert {m["name"] for m in result["modules"]} == {"模块A", "模块B"}
    assert result["features_flat"]
    for feat in result["features_flat"]:
        assert feat["name"]
        assert feat["module"]
        assert "description" in feat
        assert isinstance(feat["acceptance"], list)
    # 抽取调用在 board_split call_source 作用域内。
    assert captured and all(c == "board_split" for c in captured)


@pytest.mark.django_db(transaction=True)
async def test_extract_structure_82kb_chunks_and_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """82KB demo → 分块生效（chunk_count>1）+ degraded 置位 + 不整篇塞 LLM。"""
    assert _DEMO_PATH.exists(), f"demo 样本缺失: {_DEMO_PATH}"
    raw = _DEMO_PATH.read_text(encoding="utf-8")
    # 真实富文档（~79KB UTF-8 字节 / ~3.2 万中文字符），远超 token 预算阈值。
    assert len(raw) > 30_000

    captured = _patch_llm(monkeypatch)
    result = await FeatureListExtractor().extract_structure(
        raw, space=SimpleNamespace(id="s1")
    )
    assert result["chunk_count"] > 1  # 分块生效
    assert result["degraded"] is True  # 超 token 预算降级
    assert captured  # LLM 至少被调一次
    assert all(c == "board_split" for c in captured)


def test_board_split_call_source_in_enum() -> None:
    """board_split 已纳入受控 call_source 枚举（LOGGING-SPEC §4.1）。"""
    assert CallSource.normalize("board_split") == CallSource.BOARD_SPLIT.value
