"""查询侧 embedding 收口：长文本分块 → 多向量 → 多探针检索（RETRIEVAL-01）。

**为什么需要这一层。** `EmbeddingService.generate_embedding` 对超长文本会返回
``None``（上游 400 ``max_sequence_length``），而查询侧六个入口全部把 ``None`` 当
"检索失败"处理，其中四个**静默返回空**。实测：``doubao-embedding-text`` 上限
4096 token，约 6000 中文字符；用户在对话里贴一篇 PRD / 一段长堆栈就会命中，
界面表现为"什么都没搜到"，日志里只有一句 ``embedding_api_failed``。

**核心立场：文本超长是可处理条件，不是失败。** 本模块把长文本切成若干语义块，
每块各出一个向量，交给检索层做多探针 + RRF 融合（Qdrant 服务端 ``prefetch``
列表原生支持，零额外网络往返）。

**为什么块大小取 4000 字符而不是贴着 6000。** chars/token 比率随内容剧烈变化：
纯中文约 1.58（实测），中英混排约 2，英文散文约 4，而 base64 / 压缩 JSON 可低至
约 1。6000 字符只对中文安全，碰上贴进来的 base64 必炸。4000 字符对上述所有内容
类型都落在 4096 token 以内。

**为什么不是"摘要成一句话"。** 实测过：LLM 把需求语料摘要成一句话后，目标仓
从 3/4 掉到 2/4——摘要说的是业务语言，而前端仓的能力树节点是页面/组件语言，
概括必然抹掉实现侧词汇。长文本的长度本身就是信息，压缩就是丢信息。

**两类长文本走不同策略**（``drop_noise`` 开关）：

- **需求型**（feature list / PRD / 技术方案）：整篇都是检索意图，每段指向不同
  落点 → 全切全探（``drop_noise=False``）。
- **对话型**（聊天历史 + 贴的文档 + 报错）：只有一小部分是意图 → 过噪声闸
  （``drop_noise=True``），否则"好的我看看"也会变成一个探针，各自捞回一批节点
  挤占候选池名额（实测：无关仓稳占 top-5，把该进的仓挤出去）。

纯函数（``split_for_embedding`` / ``is_low_information`` / ``select_probe_segments``）
零 I/O 零 ORM，便于单测与离线复现。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "MAX_SEGMENT_CHARS",
    "MAX_PROBES",
    "QueryVectors",
    "split_for_embedding",
    "is_low_information",
    "select_probe_segments",
    "embed_query",
]

_COMPONENT = "query_embedding"

# 单块字符上界。见模块 docstring：对中文/英文/代码/base64 全部落在 4096 token 内。
MAX_SEGMENT_CHARS = 4000

# 单次查询的探针数上界。探针不是免费的——每条都会捞回一批节点竞争候选池名额，
# 无关探针会把真正相关的仓挤出去。超限时保留靠前的块（需求文档的前部通常信息密度最高）。
MAX_PROBES = 8

# 切分优先级：段落 → 行 → 句 → 硬切。前三级都尽量落在语义边界上。
_PARAGRAPH_RE = re.compile(r"\n\s*\n")
_SENTENCE_RE = re.compile(r"(?<=[。！？；!?;])\s*")

# 噪声闸阈值（仅 drop_noise=True 时生效）。
_MIN_INFORMATIVE_CHARS = 12
# 纯符号/标点/空白占比超过此值视为无信息（分隔线、表格框、日志噪声）。
_MAX_PUNCT_RATIO = 0.6
_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]")


@dataclass
class QueryVectors:
    """查询侧 embedding 结果：1..N 个向量 + 降级留证。

    ``vectors`` 为空表示**真失败**（网络/鉴权/未配置），调用方应按失败处理并留证；
    文本超长绝不会产出空向量——那是本模块负责消化的可处理条件。
    """

    vectors: list[list[float]] = field(default_factory=list)
    # 实际参与 embedding 的块文本（供留痕/排查；调用方不应回显进日志正文）
    segments: list[str] = field(default_factory=list)
    # 切分出的原始块数（未经噪声闸/探针上限裁剪）
    total_segments: int = 0
    # 被噪声闸丢弃的块数
    dropped_noise: int = 0
    # 被探针上限截掉的块数
    dropped_over_budget: int = 0
    # 部分块 embedding 失败（其余仍可用）时为 True
    degraded: bool = False
    degrade_reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.vectors)

    @property
    def primary(self) -> list[float] | None:
        """首个向量。供仍需单向量的下游（如 dense-only 余弦复用）取用。"""
        return self.vectors[0] if self.vectors else None

    @property
    def is_multi(self) -> bool:
        return len(self.vectors) > 1


def _hard_slice(text: str, max_chars: int) -> list[str]:
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _split_oversized(unit: str, max_chars: int) -> list[str]:
    """单个语义单元仍超长时逐级降级切分：句 → 硬切。"""
    if len(unit) <= max_chars:
        return [unit]
    out: list[str] = []
    buf = ""
    for sentence in _SENTENCE_RE.split(unit):
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_hard_slice(sentence, max_chars))
            continue
        if len(buf) + len(sentence) <= max_chars:
            buf += sentence
        else:
            if buf:
                out.append(buf)
            buf = sentence
    if buf:
        out.append(buf)
    return out


def split_for_embedding(text: str, *, max_chars: int = MAX_SEGMENT_CHARS) -> list[str]:
    """把文本切成每块 <= ``max_chars`` 的语义块（纯函数，保序）。

    贪心装箱：优先按段落聚合，段落内超长再降到行/句，最后才硬切——保证任何输入
    都能切出结果（含无换行无标点的超长单行，如 base64）。

    ``text`` 为空/纯空白 → 返回 ``[]``（调用方据此判定"无可检索内容"）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    # 一级单元：段落；段落自身超长则先按行拆，仍超长交给 _split_oversized
    units: list[str] = []
    for para in _PARAGRAPH_RE.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            units.append(para)
            continue
        for line in para.split("\n"):
            line = line.strip()
            if not line:
                continue
            units.extend(_split_oversized(line, max_chars))

    # 二级：贪心装箱回 max_chars（避免切得过碎——块越碎语义越稀薄，探针质量越差）
    segments: list[str] = []
    buf = ""
    for unit in units:
        candidate = f"{buf}\n{unit}" if buf else unit
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                segments.append(buf)
            buf = unit
    if buf:
        segments.append(buf)
    return segments


def is_low_information(segment: str) -> bool:
    """判定块是否无检索价值（噪声闸，纯函数）。

    只拦**结构性无信息**的块——过短、几乎全是标点/分隔符。刻意不做语义判断：
    误杀有信息的块比放进噪声块更糟（漏召回不可逆，噪声块还能被后续精排压下去）。
    """
    s = (segment or "").strip()
    if len(s) < _MIN_INFORMATIVE_CHARS:
        return True
    word_chars = len(_WORD_RE.findall(s))
    if word_chars == 0:
        return True
    punct_ratio = 1.0 - (word_chars / len(s))
    return punct_ratio > _MAX_PUNCT_RATIO


def select_probe_segments(
    segments: list[str],
    *,
    drop_noise: bool = True,
    max_probes: int = MAX_PROBES,
) -> tuple[list[str], int, int]:
    """挑出真正值得当探针的块（去重 → 噪声闸 → 探针上限）。

    Returns:
        ``(selected, dropped_noise, dropped_over_budget)``

    去重按归一化文本（去空白）——对话里"同一段被反复引用"很常见，重复探针
    零收益还占名额（实测：三条同义摘要各检索一次，召回集合与单条完全一致）。
    全部被判噪声时**保底返回最长的一块**，绝不返回空（宁可探一次弱信号，
    也不要静默零召回）。
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for seg in segments:
        key = re.sub(r"\s+", "", seg)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(seg)

    if drop_noise:
        kept = [s for s in deduped if not is_low_information(s)]
        dropped_noise = len(deduped) - len(kept)
    else:
        kept = deduped
        dropped_noise = 0

    if not kept:
        # 保底：全被判噪声也要探一次，取最长块（信息量相对最高）
        kept = [max(deduped, key=len)] if deduped else []
        dropped_noise = max(0, dropped_noise - 1)

    dropped_over_budget = max(0, len(kept) - max_probes)
    return kept[:max_probes], dropped_noise, dropped_over_budget


async def embed_query(
    text: str,
    *,
    drop_noise: bool = True,
    max_probes: int = MAX_PROBES,
    max_chars: int = MAX_SEGMENT_CHARS,
) -> QueryVectors:
    """查询侧唯一 embedding 入口：短文本单向量，长文本多向量，**绝不因超长返回空**。

    Args:
        text: 查询文本，长度不限。
        drop_noise: 对话型上下文置 True（过噪声闸）；需求型语料置 False（全切全探）。
        max_probes: 探针数上界。
        max_chars: 单块字符上界。

    Returns:
        :class:`QueryVectors`。``ok`` 为 False 仅代表**真失败**（未配置/网络/鉴权）。

    单块时走 ``generate_embedding`` 单发（与改造前逐字一致：调用次数、延迟、
    成本均不变——99% 的查询是短文本，不能为了长文本把正常查询拖慢）；多块时走
    ``generate_embeddings_batch``，45 块也只是 2 个 HTTP 请求。
    """
    from agents.call_source import CallSource, use_call_source
    from services.embedding import EmbeddingService

    started = time.monotonic()
    segments = split_for_embedding(text, max_chars=max_chars)
    if not segments:
        return QueryVectors(degrade_reason="empty_query")

    total_segments = len(segments)
    selected, dropped_noise, dropped_over_budget = select_probe_segments(
        segments, drop_noise=drop_noise, max_probes=max_probes
    )

    with use_call_source(CallSource.EMBEDDING):
        if len(selected) == 1:
            vec = await EmbeddingService.generate_embedding(selected[0])
            raw: list[list[float] | None] = [vec]
        else:
            raw = await EmbeddingService.generate_embeddings_batch(selected)

    vectors = [v for v in (raw or []) if isinstance(v, list) and v]
    failed = len(selected) - len(vectors)

    result = QueryVectors(
        vectors=vectors,
        segments=selected[: len(vectors)],
        total_segments=total_segments,
        dropped_noise=dropped_noise,
        dropped_over_budget=dropped_over_budget,
        degraded=failed > 0,
        degrade_reason="partial_embedding_failed" if failed > 0 and vectors else (
            "embedding_failed" if not vectors else ""
        ),
    )

    # 观测：只记长度/块数，绝不回显查询正文（可能含用户贴的敏感内容）。
    try:
        event = "query_embedding_completed" if result.ok else "query_embedding_failed"
        log = logger.info if result.ok else logger.warning
        log(
            event,
            query_len=len(text or ""),
            total_segments=total_segments,
            probe_count=len(vectors),
            dropped_noise=dropped_noise,
            dropped_over_budget=dropped_over_budget,
            failed_segments=failed,
            multi_probe=result.is_multi,
            degrade_reason=result.degrade_reason,
            duration_ms=int((time.monotonic() - started) * 1000),
            category="sampling",
            component=_COMPONENT,
        )
    except Exception:  # noqa: BLE001 — 观测 best-effort，绝不反噬检索
        pass

    return result
