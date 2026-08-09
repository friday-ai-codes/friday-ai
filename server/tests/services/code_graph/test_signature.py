"""``services/code_graph/signature.py`` 的复合签名用例（覆盖 GRAPH-02、GRAPH-04）。

本文件目前只有用例桩，由 **Plan 121-04** 填充：签名 = 水位 ‖ 轨 A（IndexHistory /
ChunkEdge）‖ 轨 B（GraphBuildHistory / Symbol·CallEdge）‖ 计数 ‖ exclusion 规则指纹。

桩的存在是 Wave 0 的 Nyquist 要求：121-VALIDATION.md 里每个 ``-k`` 选择器都必须
从第一个 task 起就能解析到真实用例名。
"""

from __future__ import annotations

import pytest


# 121-VALIDATION.md 121-04-T1：签名对 last_indexed_commit_sha 变化敏感。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_signature_watermark_sensitive() -> None:
    pass


# 121-VALIDATION.md 121-04-T1：无变更时签名稳定（连算两次相等）。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_signature_stable_without_changes() -> None:
    pass


# 121-VALIDATION.md 121-04-T2：签名对**两条**边构建轨各自的变化都敏感（D-02）——
# 只看 IndexHistory 一条轨会漏失效，CallEdge 抽取走的是另一条轨。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_signature_generation_two_tracks() -> None:
    pass


# 121-VALIDATION.md 121-04-T1：exclusion 规则变更 ⇒ 指纹变 ⇒ 签名变 ⇒ 旧图失效
# （不依赖 matcher 的 60s TTL，TTL 不是版本号）。
@pytest.mark.skip(reason="stub：由 Plan 121-04 实现")
def test_signature_exclusion_fingerprint_changes() -> None:
    pass
