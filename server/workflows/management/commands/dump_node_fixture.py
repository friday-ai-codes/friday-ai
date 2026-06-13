"""从 NodeRegistry dump 精简节点 fixture 到前端版本库。

⚠️ 改后端节点（新增/删除节点、改 node_type/category/端口）后须重跑：
    uv run python manage.py dump_node_fixture
否则前端离线漂移守护（19-05 node-sync 对账）会与后端事实源失配。

精简集字段：{node_type, category, inputs:[{name}], outputs:[{name}]}，
按 node_type 排序保证 diff 稳定。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from django.core.management.base import BaseCommand

from workflows.nodes.registry import NodeRegistry

logger = structlog.get_logger()

# 仓库根 = .../server/workflows/management/commands/dump_node_fixture.py 的第 4 层父目录
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPO_ROOT / "web" / "src" / "types" / "workflow" / "__fixtures__" / "node-types.fixture.json"
)


class Command(BaseCommand):
    help = "从 NodeRegistry dump 精简节点定义快照到前端 __fixtures__（离线漂移守护基准）"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--output",
            default=str(DEFAULT_OUTPUT),
            help="fixture 输出路径（默认 web/src/types/workflow/__fixtures__/node-types.fixture.json）",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        schemas = NodeRegistry.get_all_schemas()
        nodes = sorted(
            (_to_fixture_node(s) for s in schemas),
            key=lambda n: n["node_type"],
        )
        payload = {"node_count": len(nodes), "nodes": nodes}

        output_path = Path(options["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        logger.info("dump_node_fixture", node_count=len(nodes), output=str(output_path))
        self.stdout.write(f"OK: 已写入 {len(nodes)} 个节点 -> {output_path}")


def _to_fixture_node(schema: dict[str, Any]) -> dict[str, Any]:
    """映射后端 schema 为精简 fixture 节点。"""
    return {
        "node_type": schema["node_type"],
        "category": schema["category"],
        "inputs": [{"name": p["name"]} for p in schema.get("inputs", [])],
        "outputs": [{"name": p["name"]} for p in schema.get("outputs", [])],
    }
