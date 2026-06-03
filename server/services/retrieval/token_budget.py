"""Token 预算辅助函数 —— per 。
把 `LayeredSearchService._trim_to_token_budget` 与 `_l5_context_reassembly`
中的 token 预算逻辑沉淀为 3 个无副作用的纯函数 + 2 个常量，跨多 caller 复用。
行为契约（与 `codegraph.services.layered_search.LayeredSearchService` 对齐）：
- `TOKEN_BUFFER_RATIO = 0.9` — 与 `LayeredSearchService.TOKEN_BUFFER_RATIO` 同值
 （per RESEARCH Pitfall 4 防止 token 计数误差导致超预算）
- `estimate_tokens(text)` — 用 `tiktoken.get_encoding("cl100k_base")` 数 token
- `trim_to_budget(text, budget)` — 复刻 `_trim_to_token_budget` 行 work-item 的
 按行截断逻辑，超 budget 时附加 `(truncated: N lines omitted)` 标记
- `split_budget(max_tokens, ratios=...)` — 按比例分配子预算，等价于
 `_l5_context_reassembly` 中先 `int(max_tokens * TOKEN_BUFFER_RATIO)` 再分配
 L4-1hop / L3 / L4-2hop 的子预算逻辑
不依赖 Django，单元可测。
"""
from __future__ import annotations
import re
from functools import lru_cache
from typing import Any
TOKEN_BUFFER_RATIO: float = 0.9
DEFAULT_ENCODING: str = "cl100k_base"
class _FallbackEncoding:
 """Offline token estimator used when tiktoken cannot load its BPE data."""
 _TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
 def encode(self, text: str) -> list[str]:
 return self._TOKEN_PATTERN.findall(text)
@lru_cache(maxsize=4)
def _get_encoding(encoding: str) -> Any:
 """缓存 encoder 实例；tiktoken 资源不可用时保持离线可用。"""
 try:
 import tiktoken
 return tiktoken.get_encoding(encoding)
 except Exception:
 return _FallbackEncoding
def estimate_tokens(text: str, *, encoding: str = DEFAULT_ENCODING) -> int:
 """估算文本 token 数；空字符串返回 0。"""
 if not text:
 return 0
 enc = _get_encoding(encoding)
 return len(enc.encode(text))
def trim_to_budget(text: str, budget: int, *, encoding: str = DEFAULT_ENCODING) -> str:
 """按 token 预算裁剪文本，保持 markdown 行结构完整。
 行为与 `LayeredSearchService._trim_to_token_budget` 完全等价：
 1. 按 `\\n` 切行，逐行累加 token 数（含行尾 `\\n`）
 2. 累加超 budget 时，追加 `(truncated: {len(lines) - len(result)} lines omitted)`
 注意：`len(result)` 是已收纳的行数（不含 truncated 提示行本身），
 与现状实现一致
 3. budget ≤ 0 直接返回空串
 """
 if budget <= 0:
 return ""
 enc = _get_encoding(encoding)
 lines = text.split("\n")
 result: list[str] =
 used = 0
 for line in lines:
 line_tokens = len(enc.encode(line + "\n"))
 if used + line_tokens > budget:
 result.append(f"(truncated: {len(lines) - len(result)} lines omitted)")
 break
 result.append(line)
 used += line_tokens
 return "\n".join(result)
def split_budget(
 max_tokens: int,
 *,
 ratios: dict[str, float],
 buffer_ratio: float = TOKEN_BUFFER_RATIO,
) -> dict[str, int]:
 """按 ratios 分配子预算，先按 buffer_ratio 折算有效预算。
 例：`split_budget(8000, ratios={"rag": 0.6, "graph": 0.4})`
 → effective = int(8000 * 0.9) = 7200
 → {"rag": int(7200 * 0.6) = 4320, "graph": int(7200 * 0.4) = 2880}
 Raises:
 ValueError: 当 ratios 累加 > 1.0 时抛出（允许 ≤ 1.0 留余量）。
 """
 total_ratio = sum(ratios.values)
 if total_ratio > 1.0 + 1e-9:
 raise ValueError(f"split_budget ratios sum to {total_ratio:.3f}, must be ≤ 1.0")
 effective = int(max_tokens * buffer_ratio)
 return {key: int(effective * ratio) for key, ratio in ratios.items}
__all__ = [
 "TOKEN_BUFFER_RATIO",
 "DEFAULT_ENCODING",
 "estimate_tokens",
 "trim_to_budget",
 "split_budget",
]
