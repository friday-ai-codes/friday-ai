"""feature 变更类型分类 helper 单测（feature list 方案编排 classify 阶段）。

对齐 ``test_decompose_segments.py`` 的写法：纯 helper 测试（归一防御 + LLM 降级），
不碰 DB、不真调 provider。
"""

from __future__ import annotations

import pytest

from services.process_runtime.feature_classify import (
    aclassify_feature_changes,
    build_feature_key,
    normalize_feature_classifications,
)


def test_build_feature_key_joins_module_and_name() -> None:
    assert build_feature_key("入口与权益", "课程包鉴权") == "入口与权益::课程包鉴权"
    assert build_feature_key("  ", " 裸功能点 ") == "::裸功能点"


def test_normalize_drops_items_without_key() -> None:
    """缺 key 的项跳过——key 是与输入功能点对齐的唯一凭据。"""
    result = normalize_feature_classifications(
        [{"change_type": "new"}, {"key": "m::a", "change_type": "new"}]
    )
    assert [i["key"] for i in result] == ["m::a"]


def test_normalize_dedupes_repeated_keys() -> None:
    result = normalize_feature_classifications(
        [{"key": "m::a", "change_type": "new"}, {"key": "m::a", "change_type": "modify"}]
    )
    assert len(result) == 1
    assert result[0]["change_type"] == "new"


def test_normalize_rejects_hallucinated_keys() -> None:
    """allowed_keys 之外的 key 丢弃——防 LLM 编造输入里不存在的功能点。"""
    result = normalize_feature_classifications(
        [{"key": "m::real", "change_type": "new"}, {"key": "m::fake", "change_type": "new"}],
        allowed_keys={"m::real"},
    )
    assert [i["key"] for i in result] == ["m::real"]


def test_normalize_falls_back_on_invalid_enums() -> None:
    result = normalize_feature_classifications(
        [{"key": "m::a", "change_type": "REWRITE", "confidence": "certain"}]
    )
    assert result[0]["change_type"] == "unclear"
    assert result[0]["confidence"] == "low"


def test_normalize_filters_hallucinated_evidence_files() -> None:
    """证据文件必须真实出现在该功能点的检索结果里，编造的路径剔除。"""
    result = normalize_feature_classifications(
        [
            {
                "key": "m::a",
                "change_type": "modify",
                "confidence": "high",
                "evidence_files": ["real/path.py", "imagined/path.py"],
            }
        ],
        allowed_files={"m::a": {"real/path.py"}},
    )
    assert result[0]["evidence_files"] == ["real/path.py"]
    assert result[0]["change_type"] == "modify"


def test_modify_without_surviving_evidence_downgrades_to_unclear() -> None:
    """判 modify 却给不出真实证据 → 判定无依据，降级 unclear 交回用户确认。"""
    result = normalize_feature_classifications(
        [
            {
                "key": "m::a",
                "change_type": "modify",
                "confidence": "high",
                "evidence_files": ["imagined/path.py"],
            }
        ],
        allowed_files={"m::a": {"real/path.py"}},
    )
    assert result[0]["change_type"] == "unclear"
    assert result[0]["confidence"] == "low"


def test_normalize_truncates_to_max_items() -> None:
    raw = [{"key": f"m::{i}", "change_type": "new"} for i in range(10)]
    assert len(normalize_feature_classifications(raw, max_items=3)) == 3


@pytest.mark.asyncio
async def test_classify_returns_none_on_empty_features() -> None:
    """无功能点 → None（不调 LLM），上游据此跳过分类。"""
    assert await aclassify_feature_changes(features=[]) is None


@pytest.mark.asyncio
async def test_classify_returns_none_when_provider_unavailable(monkeypatch) -> None:
    """provider 解析异常 → best-effort 返回 None，绝不抛（不阻断编排）。"""

    async def _boom():
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "services.provider_config.ProviderConfigService.aresolve", staticmethod(_boom)
    )
    result = await aclassify_feature_changes(
        features=[{"key": "m::a", "title": "a", "module": "m", "layer": ""}]
    )
    assert result is None
