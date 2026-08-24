"""真仓 graph benchmark 集成验收。

运行方式：

```
GRAPH_BENCH_REPOSITORY_ID=<uuid> \
GRAPH_BENCH_BRANCH=<branch> \
GRAPH_BENCH_COMMIT_SHA=<sha> \
uv run pytest tests/codegraph/test_graph_bench_integration.py -m integration -q
```

需要目标仓已完成 Symbol/CallEdge/ProcessTrace 与 Qdrant 索引，且三方水位与
``GRAPH_BENCH_COMMIT_SHA`` 完全一致。默认测试套件排除此标记。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from django.core.management import call_command

from codegraph.management.commands.evaluate_graph_bench import _benchmark_environment_preflight


@pytest.mark.integration
@pytest.mark.django_db(transaction=True)
def test_graph_bench_real_repository_ok_path(tmp_path: Path) -> None:
    """真仓 OK 路径应同时产出可关联 manifest 与无阈值 baseline。"""
    repository_id = os.getenv("GRAPH_BENCH_REPOSITORY_ID")
    commit_sha = os.getenv("GRAPH_BENCH_COMMIT_SHA")
    qdrant_url = os.getenv("GRAPH_BENCH_QDRANT_URL")
    baseline_artifact = os.getenv("GRAPH_BENCH_V022_BASELINE_ARTIFACT")
    preflight = _benchmark_environment_preflight(
        repository_id=repository_id or "",
        commit_sha=commit_sha or "",
        qdrant_url=qdrant_url or "",
        baseline_artifact=baseline_artifact or "",
    )
    if preflight["status"] == "human_needed":
        assert preflight["reproduce_command"]
        assert preflight["missing"]
        assert "metrics" not in preflight
        return

    manifest_path = tmp_path / "run-manifest.json"
    baseline_path = tmp_path / "baseline.json"
    call_command(
        "evaluate_graph_bench",
        repo=repository_id,
        branch=os.getenv("GRAPH_BENCH_BRANCH", ""),
        commit_sha=commit_sha,
        split="dev",
        output_manifest=str(manifest_path),
        output_json=str(baseline_path),
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert manifest["watermark"] == "OK"
    assert manifest["run_id"]
    assert baseline["run_id"] == manifest["run_id"]
    assert isinstance(baseline["per_case"], list)
    assert isinstance(baseline["per_bucket"], list)
    assert isinstance(baseline["overall"], dict)
