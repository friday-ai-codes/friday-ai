"""BENCH-01：run identity 五元组与三方水位一致性校验（纯函数，默认套件可跑）。

覆盖：三方水位 fail-closed（任一为空/不全相等 → INVALID）、可选第四参
process_built_at_sha、RunIdentity.to_dict 含 index_key_source、空身份必填校验。
"""

from __future__ import annotations

import pytest

from codegraph.services.graph_bench_eval import (
    RunIdentity,
    build_run_identity,
    validate_watermark,
)


class TestValidateWatermark:
    def test_any_empty_is_invalid(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha="",
                gold_annotated_at_sha="x",
                source_checkout_sha="x",
            )
            == "INVALID"
        )

    def test_mismatch_is_invalid(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha="a",
                gold_annotated_at_sha="a",
                source_checkout_sha="b",
            )
            == "INVALID"
        )

    def test_all_equal_is_ok(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha="a",
                gold_annotated_at_sha="a",
                source_checkout_sha="a",
            )
            == "OK"
        )

    def test_process_sha_mismatch_is_invalid(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha="a",
                gold_annotated_at_sha="a",
                source_checkout_sha="a",
                process_built_at_sha="b",
            )
            == "INVALID"
        )

    def test_process_sha_omitted_not_checked(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha="a",
                gold_annotated_at_sha="a",
                source_checkout_sha="a",
                process_built_at_sha=None,
            )
            == "OK"
        )

    def test_none_sha_is_invalid(self) -> None:
        assert (
            validate_watermark(
                index_built_at_sha=None,
                gold_annotated_at_sha="a",
                source_checkout_sha="a",
            )
            == "INVALID"
        )


class TestBuildRunIdentity:
    def test_to_dict_contains_five_keys_and_index_key_source(self) -> None:
        identity = build_run_identity(
            repository="r",
            branch="b",
            commit_sha="a",
            index_key="a",
            gold_version="1",
        )
        assert isinstance(identity, RunIdentity)
        d = identity.to_dict()
        assert d["repository"] == "r"
        assert d["branch"] == "b"
        assert d["commit_sha"] == "a"
        assert d["index_key"] == "a"
        assert d["gold_version"] == "1"
        assert d["index_key_source"] == "last_indexed_commit_sha"

    def test_empty_repository_raises(self) -> None:
        with pytest.raises(ValueError):
            build_run_identity(
                repository="",
                branch="b",
                commit_sha="a",
                index_key="a",
                gold_version="1",
            )

    def test_empty_gold_version_raises(self) -> None:
        with pytest.raises(ValueError):
            build_run_identity(
                repository="r",
                branch="b",
                commit_sha="a",
                index_key="a",
                gold_version="",
            )

    def test_empty_branch_allowed(self) -> None:
        identity = build_run_identity(
            repository="r",
            branch="",
            commit_sha="a",
            index_key="a",
            gold_version="1",
        )
        assert identity.branch == ""
