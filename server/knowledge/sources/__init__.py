"""source_kind → normalizer 惰性注册表（Plan 13-02 / INGEST-07）。

normalizer 是 ``async def normalize(request: IngestionRequest) ->
list[IngestionEvent]`` 形态的协程函数，由各 source 模块提供
（``coding_plan`` / ``mcp_plan`` 模块在 Plan 13-03 落地）。

本注册表只做惰性 import 解耦：摄取核心对"一个触发产出几个实体几条边"
完全无感知，Phase 14 新触发点只需在此登记 + 新增 normalizer 模块。
"""

from __future__ import annotations

import importlib
from collections.abc import Callable

__all__ = ["get_normalizer"]

# source_kind → normalizer 模块路径（惰性 import，避免循环依赖与无谓加载）
_NORMALIZERS: dict[str, str] = {
    "coding_plan": "knowledge.sources.coding_plan",
    "mcp_technical_plan": "knowledge.sources.mcp_plan",
    # Phase 14 先注册（13-02 先例）：模块由 14-04/05/06 落地，
    # 落地前 get_normalizer 触发 ImportError 响亮失败，不静默。
    "workflow_plan": "knowledge.sources.workflow_plan",
    "task_result": "knowledge.sources.task_result",
    "feishu_work_item": "knowledge.sources.feishu_work_item",
    # Phase 30 DOC-02：飞书 docx（PRD/技术方案）→ Document + REFERENCES 边投影。
    "feishu_document": "knowledge.sources.feishu_document",
    # Phase 79 ARTIFACT-04：项目工件正文（飞书 doc/表格/md/repo_file）→ document 投影
    # + 工件→REFERENCES→项目图谱节点出边（KLINK-01）。
    "artifact": "knowledge.sources.artifact",
    # Phase 85 CTX-01/02：项目上下文物化（逻辑隔离于代码 RAG，复用 delivery_knowledge）。
    # 5 文件正文 / active 记忆 → document 投影 + REFERENCES→项目节点出边（写时增量 + 兜底重建）。
    "project_doc": "knowledge.sources.project_doc",
    "project_memory": "knowledge.sources.project_memory",
    # Phase 143 EVAL-03：中高价值 IDE 会话评估精华 → document 投影。
    "session_capture": "knowledge.sources.session_capture",
    # Phase 100 KNOW-01/03 先注册（13-02 先例）：learning_case 模块由 100-02 落地，
    # MCP 三类产物模块由 100-03 落地；落地前 get_normalizer 触发 ImportError 响亮失败，不静默。
    "learning_case": "knowledge.sources.learning_case",
    "mcp_coding_plan": "knowledge.sources.mcp_coding_plan",
    "mcp_repository_analysis": "knowledge.sources.mcp_repository_analysis",
    "mcp_execution_trace": "knowledge.sources.mcp_execution_trace",
    # Phase 116 VIEW-04：蓝图（delivery.Artifact 的 blueprint/v1 content）→ tech_plan 实体
    # + citations/项目关联物化（REFERENCES / RELATES_TO 出边），支撑「被谁引用」反查。
    "blueprint": "knowledge.sources.blueprint",
}


def get_normalizer(source_kind: str) -> Callable:
    """按 source_kind 返回对应 normalizer 协程函数。

    未知 source_kind 直接 raise ``KeyError``（响亮——触发点接错线 /
    配置漂移必须立刻暴露，不可静默吞掉）。
    """
    module_path = _NORMALIZERS[source_kind]
    module = importlib.import_module(module_path)
    return module.normalize
