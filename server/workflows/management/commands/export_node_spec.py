"""导出节点规范文档的管理命令。"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from typing import Any
import structlog
from django.core.management.base import BaseCommand
from workflows.nodes.registry import NodeRegistry
logger = structlog.get_logger
# 分类排序与中文映射
CATEGORY_ORDER: list[str] = ["trigger", "ai", "control", "action", "integration"]
CATEGORY_LABELS: dict[str, str] = {
 "trigger": "触发器节点",
 "ai": "AI 节点",
 "control": "控制流节点",
 "action": "操作节点",
 "integration": "集成节点",
}
EXPECTED_NODE_COUNT = 27
class Command(BaseCommand):
 help = "从 NodeRegistry 导出节点规范文档（Markdown）"
 def add_arguments(self, parser: Any) -> None:
 parser.add_argument(
 "--check",
 action="store_true",
 help="仅验证节点数量是否为 27",
 )
 def handle(self, *args: Any, **options: Any) -> None:
 schemas = NodeRegistry.get_all_schemas
 count = len(schemas)
 if options["check"]:
 if count == EXPECTED_NODE_COUNT:
 self.stdout.write(f"OK: {count} 个节点已注册")
 else:
 self.stderr.write(f"FAIL: 期望 {EXPECTED_NODE_COUNT} 个节点，实际 {count}")
 sys.exit(1)
 return
 logger.info("export_node_spec", node_count=count)
 grouped = _group_by_category(schemas)
 md = _render_markdown(grouped, schemas)
 self.stdout.write(md)
# ---------------------------------------------------------------------------
# 内部函数
# ---------------------------------------------------------------------------
def _group_by_category(schemas: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
 """按分类分组并排序。"""
 grouped: dict[str, list[dict[str, Any]]] = {c: for c in CATEGORY_ORDER}
 for s in schemas:
 cat = s["category"]
 if cat in grouped:
 grouped[cat].append(s)
 # 每组内按 node_type 排序
 for nodes in grouped.values:
 nodes.sort(key=lambda n: n["node_type"])
 return grouped
def _render_markdown(
 grouped: dict[str, list[dict[str, Any]]], schemas: list[dict[str, Any]]
) -> str:
 """渲染完整 Markdown 文档。"""
 today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
 lines: list[str] =
 w = lines.append
 # --- 文档头 ---
 w("# Friday 工作流节点规范")
 w("")
 w(f"> 由 `python manage.py export_node_spec` 自动生成于 {today}")
 w("")
 # --- 目录 ---
 w("## 目录")
 w("")
 w("- [节点速查表](#节点速查表)")
 for cat in CATEGORY_ORDER:
 label = CATEGORY_LABELS[cat]
 anchor = label.lower.replace(" ", "-")
 w(f"- [{label}](#{anchor})")
 w("")
 # --- 速查表 ---
 w("## 节点速查表")
 w("")
 w("| node_type | 显示名称 | 分类 | 执行模式 | 阻塞 |")
 w("|-----------|----------|------|----------|------|")
 for cat in CATEGORY_ORDER:
 for n in grouped[cat]:
 blocking = "是" if n.get("is_blocking") else ""
 w(
 f"| `{n['node_type']}` | {n['display_name']} "
 f"| {CATEGORY_LABELS.get(n['category'], n['category'])} "
 f"| {n['execution_mode']} | {blocking} |"
 )
 w("")
 # --- 按分类的详细节点卡片 ---
 for cat in CATEGORY_ORDER:
 nodes = grouped[cat]
 if not nodes:
 continue
 w(f"## {CATEGORY_LABELS[cat]}")
 w("")
 for n in nodes:
 _render_node_card(w, n)
 return "\n".join(lines)
def _render_node_card(w: Any, n: dict[str, Any]) -> None:
 """渲染单个节点的详细卡片。"""
 w(f"### {n['display_name']}（`{n['node_type']}`）")
 w("")
 w(f"- **分类：** {CATEGORY_LABELS.get(n['category'], n['category'])}")
 w(f"- **执行模式：** {n['execution_mode']}")
 if n.get("description"):
 w(f"- **描述：** {n['description']}")
 if n.get("is_blocking"):
 w("- **阻塞：** 是")
 w("")
 # 输入端口
 inputs = n.get("inputs", )
 if inputs:
 w("**输入端口**")
 w("")
 w("| 字段名 | 类型 | 必填 | 说明 |")
 w("|--------|------|------|------|")
 for p in inputs:
 req = "是" if p.get("required") else "否"
 w(f"| {p['name']} | {p.get('type', 'any')} | {req} | {p.get('description', '')} |")
 w("")
 # 输出端口
 outputs = n.get("outputs", )
 if outputs:
 w("**输出端口**")
 w("")
 w("| 字段名 | 类型 | 必填 | 说明 |")
 w("|--------|------|------|------|")
 for p in outputs:
 req = "是" if p.get("required") else "否"
 w(f"| {p['name']} | {p.get('type', 'any')} | {req} | {p.get('description', '')} |")
 w("")
 # 配置项
 config = n.get("config_schema", {})
 props = config.get("properties", {})
 if props:
 required_fields = config.get("required", )
 w("**配置项**")
 w("")
 w("| 字段名 | 类型 | 必填 | 说明 |")
 w("|--------|------|------|------|")
 for fname, fschema in props.items:
 ftype = fschema.get("type", "string")
 req = "是" if fname in required_fields else "否"
 desc = fschema.get("description", fschema.get("title", ""))
 w(f"| {fname} | {ftype} | {req} | {desc} |")
 w("")
 w("---")
 w("")
