"""Phase GRAPH- — 顶层 Graph 构建服务。
将"图谱构建"从 indexer 内部 private method 抽出为一等公民 service：
- 入口：``build_graph_for_repository(repository_id, *, trigger, history_id=None) -> GraphBuildResult``
- 串行流程：锁 Repository → 取/建 ``GraphBuildHistory(RUNNING)`` →
 ``GraphWriter.adelete_for_files`` 前置删除孤儿 → 复用 ``IndexerService._extract_and_write_graph``
 薄壳 → 转 ``COMPLETED`` 落计数 / ``FAILED`` 落 error_message。
- 不读 ``settings.ENABLE_CODEGRAPH``（view 层 403 拦截，service 假定调用方已通过 flag）。
- 不读 ``Repository.auto_build_graph_enabled``（手动 REST 是用户 explicit intent，
 per-repo 开关只控 indexer 自动衔接路径）。
- 三 trigger 一视同仁（manual / auto_after_index / webhook），全部写
 ``GraphBuildHistory`` 供 list endpoint 审计。
设计动机详见 ``project-docs/phases/work-item/work-item.md`` 与 Plan。
"""
from __future__ import annotations
from dataclasses import dataclass
import structlog
__all__ = ["GraphBuildResult", "build_graph_for_repository"]
logger = structlog.get_logger(__name__)
@dataclass(frozen=True)
class GraphBuildResult:
 """``build_graph_for_repository`` 返回值——与 ``GraphBuildHistory`` 字段口径对齐。
 末位追加新字段保字段位置兼容（CONTEXT decisions：与 ``CleanupReport`` 同模式）。
 完成时调用方可一次性 ``asdict(result)`` 写 history 行。
 """
 status: str
 files_total: int = 0
 files_processed: int = 0
 files_failed: int = 0
 symbols_count: int = 0
 imports_count: int = 0
 calls_count: int = 0
 endpoints_count: int = 0
 duration_seconds: float = 0.0
 error_message: str = ""
async def build_graph_for_repository(
 repository_id: str,
 *,
 trigger: str,
 history_id: str | None = None,
) -> GraphBuildResult:
 """顶层 graph 构建入口（GRAPH-）。
 Args:
 repository_id: 仓库 UUID 字符串。
 trigger: 触发来源（``manual`` / ``auto_after_index`` / ``webhook``）。
 history_id: 可选 ``GraphBuildHistory`` 行 ID；为 ``None`` 时 service 自创建
 RUNNING 行（manual REST 路径），非 ``None`` 时复用调用方已创建的 RUNNING
 行（``auto_after_index`` 路径——indexer 主流程协议）。
 Returns:
 ``GraphBuildResult``：含 status / counts / duration / error_message 全字段。
 Raises:
 异常时已写 ``history.status=FAILED + error_message`` 后透传，让
 ``background_runner`` worker 拿到异常以便外层观测。
 """
 # T- 将填入完整实现；当前骨架仅满足 dataclass 形态 + API 签名两类断言。
 _ = (repository_id, trigger, history_id)
 raise NotImplementedError(
 "build_graph_for_repository 主体实现见 T-"
 )
