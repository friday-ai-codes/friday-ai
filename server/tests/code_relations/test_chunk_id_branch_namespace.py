"""initial implementation plan（work item / Critical 1）：chunk_id 分支命名空间 golden 测试。

本文件是本 phase 的 **acceptance gate**：硬编码本 phase 实算的期望 UUID，钉死
``generate_chunk_id`` base 路径**字节级不变**（零漂移）+ feature 分支**必然不同**。

期望 UUID 由独立 python3 实算核对（NAMESPACE_REPO=00000000-0000-5000-a000-000000000001）：
- base   ``repo-A:src/foo.py:0``           → e2493b26-f8a8-5409-851d-cccef26fce91
- base   ``repo-A:src/foo.py:1``           → b826c76e-d5da-5e84-b5de-310a332e1882
- feature ``repo-A:feature/x:src/foo.py:0`` → 49e64e01-d376-5099-97bf-753d44049e77
"""

from __future__ import annotations

import uuid

from code_relations.utils import generate_chunk_id

# 本 phase 实算 golden 期望值（base 字节不变护栏）。
_BASE_FOO_0 = uuid.UUID("e2493b26-f8a8-5409-851d-cccef26fce91")
_BASE_FOO_1 = uuid.UUID("b826c76e-d5da-5e84-b5de-310a332e1882")
_FEATURE_X_FOO_0 = uuid.UUID("49e64e01-d376-5099-97bf-753d44049e77")


def test_base_chunk_id_byte_identical_idx0() -> None:
    """work item：base 路径 chunk_id 与改造前字节级一致（idx 0，零漂移）。"""
    assert generate_chunk_id("repo-A", "src/foo.py", 0) == _BASE_FOO_0


def test_base_chunk_id_byte_identical_idx1() -> None:
    """work item：base 路径 chunk_id 与改造前字节级一致（idx 1，零漂移）。"""
    assert generate_chunk_id("repo-A", "src/foo.py", 1) == _BASE_FOO_1


def test_default_param_equals_explicit_empty_equals_legacy() -> None:
    """work item 向后兼容：默认形参 == 显式空串 == 旧三参调用，三者相等。"""
    legacy = generate_chunk_id("repo-A", "src/foo.py", 0)
    explicit_empty = generate_chunk_id("repo-A", "src/foo.py", 0, "")
    assert legacy == explicit_empty == _BASE_FOO_0


def test_feature_chunk_id_matches_golden_and_differs_from_base() -> None:
    """work item / Critical 1：feature 分支 chunk_id == golden 且与 base 必然不同。"""
    feature = generate_chunk_id("repo-A", "src/foo.py", 0, "feature/x")
    assert feature == _FEATURE_X_FOO_0
    assert feature != _BASE_FOO_0


def test_different_branches_produce_different_ids() -> None:
    """Critical 1：同 (repo, path, idx) 不同分支名产出不同 UUID（命名空间隔离）。"""
    a = generate_chunk_id("repo-A", "src/foo.py", 0, "feature/x")
    b = generate_chunk_id("repo-A", "src/foo.py", 0, "feature/y")
    base = generate_chunk_id("repo-A", "src/foo.py", 0)
    assert a != b
    assert a != base
    assert b != base
