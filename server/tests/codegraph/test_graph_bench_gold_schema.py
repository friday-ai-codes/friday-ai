"""BENCH-02：gold 冻结数据集 schema 校验（纯函数，内存 dict 即可测）。

覆盖：manifest 必填键与三切分、case 必填分桶维度与闭集、空白 query 拒绝、
edge_golds 的 call_shape 闭集与 evidence_file_line 防反导锚点必填。
"""

from __future__ import annotations

import pytest

from codegraph.services.graph_bench_eval import (
    GoldDataset,
    validate_gold_case,
    validate_gold_dataset,
)


def _valid_manifest() -> dict:
    return {
        "gold_version": "1",
        "annotated_at_sha": "abc123",
        "repository": "friday-ai",
        "branch": "main",
        "splits": {"dev": "dev.json", "locked_test": "locked_test.json", "holdout": "holdout.json"},
    }


def _valid_case() -> dict:
    return {
        "case_id": "dev-0001",
        "split": "dev",
        "query": "登录接口在哪里？",
        "language": "python",
        "framework": "django",
        "entry_type": "http_endpoint",
    }


class TestManifestValidation:
    @pytest.mark.parametrize("missing", ["gold_version", "annotated_at_sha", "splits"])
    def test_missing_required_key_raises(self, missing: str) -> None:
        manifest = _valid_manifest()
        del manifest[missing]
        with pytest.raises(ValueError, match=missing):
            validate_gold_dataset(manifest, [_valid_case()])

    @pytest.mark.parametrize("missing_split", ["dev", "locked_test", "holdout"])
    def test_missing_split_raises(self, missing_split: str) -> None:
        manifest = _valid_manifest()
        del manifest["splits"][missing_split]
        with pytest.raises(ValueError, match=missing_split):
            validate_gold_dataset(manifest, [_valid_case()])

    def test_valid_minimal_dataset_passes(self) -> None:
        dataset = validate_gold_dataset(_valid_manifest(), [_valid_case()])
        assert isinstance(dataset, GoldDataset)
        assert dataset.gold_version == "1"
        assert len(dataset.cases) == 1
        assert dataset.cases[0].case_id == "dev-0001"
        # 缺省 expected_* 给空列表
        assert dataset.cases[0].expected_symbols == []


class TestCaseValidation:
    @pytest.mark.parametrize("field_name", ["language", "framework", "entry_type"])
    def test_missing_bucket_dimension_raises(self, field_name: str) -> None:
        case = _valid_case()
        del case[field_name]
        with pytest.raises(ValueError, match=field_name):
            validate_gold_case(case)

    @pytest.mark.parametrize(
        ("field_name", "bad_value"),
        [
            ("language", "rust"),
            ("framework", "flask"),
            ("entry_type", "cron_job"),
        ],
    )
    def test_out_of_closed_set_raises(self, field_name: str, bad_value: str) -> None:
        case = _valid_case()
        case[field_name] = bad_value
        with pytest.raises(ValueError, match=field_name):
            validate_gold_case(case)

    def test_blank_query_raises(self) -> None:
        case = _valid_case()
        case["query"] = "   "
        with pytest.raises(ValueError, match="query"):
            validate_gold_case(case)

    def test_edge_call_shape_out_of_closed_set_raises(self) -> None:
        case = _valid_case()
        case["edge_golds"] = [
            {"caller_uid": "u1", "callee_uid": "u2", "call_shape": "dynamic_dispatch"},
        ]
        with pytest.raises(ValueError, match="call_shape"):
            validate_gold_case(case)

    def test_edge_callee_uid_requires_evidence_file_line(self) -> None:
        case = _valid_case()
        case["edge_golds"] = [
            {"caller_uid": "u1", "callee_uid": "u2", "call_shape": "direct"},
        ]
        with pytest.raises(ValueError, match="evidence_file_line"):
            validate_gold_case(case)

    def test_edge_with_evidence_passes(self) -> None:
        case = _valid_case()
        case["edge_golds"] = [
            {
                "caller_uid": "u1",
                "callee_uid": "u2",
                "call_shape": "direct",
                "evidence_file_line": "server/app/views.py:42",
            },
        ]
        gold = validate_gold_case(case)
        assert gold.edge_golds[0]["evidence_file_line"] == "server/app/views.py:42"

    def test_error_message_contains_case_id(self) -> None:
        case = _valid_case()
        del case["language"]
        with pytest.raises(ValueError, match="dev-0001"):
            validate_gold_case(case)
