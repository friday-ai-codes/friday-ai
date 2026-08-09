"""``services.query_embedding`` 单测：分块 / 噪声闸 / 探针选取 / embed_query 编排。

纯函数部分零 I/O；``embed_query`` 用 monkeypatch 替 ``EmbeddingService``，
全程无网络（默认 ``--disable-socket`` 下即为零网络证明）。

守的核心契约（回归即出大事）：

1. **短文本走单发**：``generate_embedding`` 调一次、``generate_embeddings_batch``
   零次。99% 的查询是短文本，绝不能因为长文本改造把正常查询拖慢或改变调用次数
   （既有测试就断言过 ``calls["embed"] == 1``）。
2. **长文本绝不返回空**：文本超长是可处理条件而非失败——这正是历史上四个查询入口
   静默零召回的成因。
3. 噪声闸**永不清空**：全被判噪声时保底留最长块，宁可探一次弱信号也不静默零召回。
"""

from __future__ import annotations

from typing import Any

import pytest

from services.query_embedding import (
    MAX_SEGMENT_CHARS,
    embed_query,
    is_low_information,
    select_probe_segments,
    split_for_embedding,
)

# ---------------------------------------------------------------------------
# split_for_embedding
# ---------------------------------------------------------------------------


def test_split_empty_returns_empty() -> None:
    assert split_for_embedding("") == []
    assert split_for_embedding("   \n\n  ") == []


def test_split_short_text_is_single_segment_verbatim() -> None:
    text = "高中数学培优课入口鉴权"
    assert split_for_embedding(text) == [text]


def test_split_respects_max_chars() -> None:
    text = "\n\n".join("段落%d：%s" % (i, "字" * 500) for i in range(20))
    segments = split_for_embedding(text, max_chars=1000)
    assert len(segments) > 1
    assert all(len(s) <= 1000 for s in segments)


def test_split_handles_no_boundary_text() -> None:
    """无换行无标点的超长单行（base64 / 压缩 JSON）必须能硬切，不能抛也不能吞。"""
    text = "A" * 9000
    segments = split_for_embedding(text, max_chars=4000)
    assert all(len(s) <= 4000 for s in segments)
    assert "".join(segments) == text


def test_split_preserves_all_content() -> None:
    """切分不得丢内容——丢了就等于又一次静默截断。"""
    text = "\n\n".join(f"模块{i}的验收项与交互逻辑说明" * 40 for i in range(12))
    segments = split_for_embedding(text, max_chars=1000)
    joined = "".join(segments).replace("\n", "")
    assert joined == text.replace("\n", "")


def test_split_default_max_is_safe_for_embedding_limit() -> None:
    """默认块大小必须留足 token 余量：doubao-embedding-text 上限 4096 token，
    最坏情况（近 1 字符/token 的病态输入）下 4000 字符仍在界内。"""
    assert MAX_SEGMENT_CHARS <= 4096


# ---------------------------------------------------------------------------
# 噪声闸
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["好的", "嗯", "----------------", "|||  ---  |||", "  "])
def test_low_information_detects_noise(text: str) -> None:
    assert is_low_information(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "用户点击极速提分营入口后跳转到题型图谱页",
        "def resolve_permission(user, package_id): return has_course_package(user, package_id)",
    ],
)
def test_low_information_keeps_real_content(text: str) -> None:
    assert is_low_information(text) is False


def test_select_dedupes_repeated_segments() -> None:
    """对话里同一段被反复引用很常见；重复探针零收益还占名额。"""
    seg = "真题检测页复用端内做题组件并展示答案解析"
    kept, _, _ = select_probe_segments([seg, seg + "  ", seg], drop_noise=True)
    assert kept == [seg]


def test_select_drops_noise_when_enabled() -> None:
    real = "同型题检验页提交后进入完成页并更新掌握程度"
    kept, dropped, _ = select_probe_segments(["好的", real, "----"], drop_noise=True)
    assert kept == [real]
    assert dropped == 2


def test_select_keeps_noise_for_requirement_corpus() -> None:
    """需求型语料整篇都是检索意图，不过闸。"""
    segs = ["好的", "同型题检验页提交后进入完成页"]
    kept, dropped, _ = select_probe_segments(segs, drop_noise=False)
    assert kept == segs
    assert dropped == 0


def test_select_never_returns_empty() -> None:
    """全是噪声也要保底探一次——静默零召回比弱信号更糟。"""
    kept, _, _ = select_probe_segments(["嗯", "好的", "---"], drop_noise=True)
    assert len(kept) == 1


def test_select_caps_probe_budget() -> None:
    segs = [f"第{i}个功能点的验收项与交互逻辑" for i in range(20)]
    kept, _, over = select_probe_segments(segs, drop_noise=False, max_probes=8)
    assert len(kept) == 8
    assert over == 12


# ---------------------------------------------------------------------------
# embed_query 编排
# ---------------------------------------------------------------------------


class _EmbedSpy:
    def __init__(self, dim: int = 4, fail_indices: set[int] | None = None) -> None:
        self.single_calls = 0
        self.batch_calls = 0
        self.batch_sizes: list[int] = []
        self._dim = dim
        self._fail = fail_indices or set()

    async def generate_embedding(self, text: str) -> list[float] | None:
        self.single_calls += 1
        return [0.1] * self._dim

    async def generate_embeddings_batch(self, texts: list[str], **_: Any):
        self.batch_calls += 1
        self.batch_sizes.append(len(texts))
        return [
            None if i in self._fail else [0.1] * self._dim for i in range(len(texts))
        ]


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _EmbedSpy:
    s = _EmbedSpy()
    import services.embedding as embedding_module

    monkeypatch.setattr(
        embedding_module.EmbeddingService, "generate_embedding", s.generate_embedding
    )
    monkeypatch.setattr(
        embedding_module.EmbeddingService,
        "generate_embeddings_batch",
        s.generate_embeddings_batch,
    )
    return s


async def test_embed_query_short_uses_single_call(spy: _EmbedSpy) -> None:
    """短文本必须与改造前逐字同路径：单发一次，绝不走批量。"""
    result = await embed_query("极速提分营入口鉴权在哪个服务")
    assert result.ok
    assert result.is_multi is False
    assert spy.single_calls == 1
    assert spy.batch_calls == 0


async def test_embed_query_long_produces_multi_probe(spy: _EmbedSpy) -> None:
    text = "\n\n".join(f"模块{i}：{'功能点验收项与交互逻辑' * 200}" for i in range(6))
    result = await embed_query(text, drop_noise=False)
    assert result.ok
    assert result.is_multi is True
    assert len(result.vectors) == result.total_segments <= 8
    # 批量一次打包，不是逐块单发
    assert spy.batch_calls == 1
    assert spy.single_calls == 0


async def test_embed_query_never_empty_on_oversized_text(spy: _EmbedSpy) -> None:
    """改造前这里 generate_embedding 返回 None → 调用方静默返回空。"""
    result = await embed_query("字" * 30000, drop_noise=False)
    assert result.ok is True
    assert result.vectors


async def test_embed_query_empty_text_marks_reason(spy: _EmbedSpy) -> None:
    result = await embed_query("   ")
    assert result.ok is False
    assert result.degrade_reason == "empty_query"
    assert spy.single_calls == 0


async def test_embed_query_partial_failure_is_degraded_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """部分块失败仍返回其余向量并留证——不能因一块失败就整体判失败。"""
    s = _EmbedSpy(fail_indices={0})
    import services.embedding as embedding_module

    monkeypatch.setattr(
        embedding_module.EmbeddingService,
        "generate_embeddings_batch",
        s.generate_embeddings_batch,
    )
    text = "\n\n".join(f"模块{i}：{'验收项与交互逻辑说明' * 200}" for i in range(4))
    result = await embed_query(text, drop_noise=False)
    assert result.ok is True
    assert result.degraded is True
    assert result.degrade_reason == "partial_embedding_failed"


async def test_embed_query_respects_probe_budget(spy: _EmbedSpy) -> None:
    text = "\n\n".join(f"模块{i}：{'验收项与交互逻辑' * 300}" for i in range(30))
    result = await embed_query(text, drop_noise=False, max_probes=3)
    assert len(result.vectors) == 3
    assert result.dropped_over_budget > 0
