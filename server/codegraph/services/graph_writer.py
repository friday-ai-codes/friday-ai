"""GraphWriter —— 将 ExtractionBundle 的四维图谱数据批量写入 Django ORM。

per contract: 图谱写入失败时不阻塞向量轨。调用方负责 try/except。
per contract: 图谱写入共享索引管线的事务锁（复用 _acquire_index_lock）。
per RESEARCH.md §E.2: 两阶段写入 —— Symbols → ImportEdges/Endpoints → CallEdges (FK resolution)。
per RESEARCH.md §H.4: 重新索引幂等性 —— per-file delete 再 bulk_create。

线程模型说明（线上事故修复）：
- Django ORM 的 async 方法（aget/abulk_create/adelete）默认通过
  ``sync_to_async(thread_sensitive=True)`` 调度，整个 ASGI 进程的 thread
  sensitive sync_to_async 调用共享同一根线程串行执行。
- graph 阶段一个仓库 4000+ 文件 × 多次 ORM 写入会把这根线程占满，
  HTTP 接口的 ORM 调用全部排队 → "接口都待处理"假死。
- 修复：``write_bundle`` 是 async 包装器，把整文件的 4 张表写入打包成
  ``write_bundle_sync`` 一次性 sync 调用，并通过
  ``sync_to_async(..., thread_sensitive=False)`` 调度到独立线程池，
  与 ASGI 请求线程完全隔离。

事务策略（contract）：
- ``write_bundle_sync`` 单文件内 3 次 delete + 4 次 bulk_create 用
  ``transaction.atomic()`` 合并为 **1 个事务**。每文件 1 次 commit + 1 次
  fsync，而不是 7 次。4000 文件场景下 SQLite 写锁/WAL 压力下降一个量级，
  显著缓解图谱阶段"接口都待处理"假死。
- atomic 还顺带保证幂等：单文件失败回滚整批，不会留下"Symbol 删了但
  ImportEdge 残留"的中间态。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from asgiref.sync import sync_to_async
from django.db import transaction

from codegraph.models import ApiCallSite, ApiWrapper, CallEdge, Endpoint, ImportEdge, Symbol

if TYPE_CHECKING:
    from codegraph.extractors.api_resolver.base import ApiCallSiteData, ApiWrapperData

logger = structlog.get_logger(__name__)


class GraphWriter:
    """将 ExtractionBundle 的四维图谱数据批量写入 Django ORM。

    单次调用 write_bundle() 处理一个文件的完整图谱数据。
    由 IndexerService（plan）在每个索引文件后调用，或批量处理。
    """

    async def write_bundle(
        self, repository_id: str, bundle: Any, *, branch_name: str = "",
    ) -> dict[str, int]:
        """将单文件的 ExtractionBundle 批量写入 Django ORM（async 包装器）。

        实际写入由 ``write_bundle_sync`` 承担，通过
        ``sync_to_async(thread_sensitive=False)`` 调度到独立线程池：
        Django ORM async API 默认 thread_sensitive=True，会与 ASGI 请求线程
        共享同一根 SingleThreadExecutor，graph 阶段大批写入时所有 HTTP 接口
        会被排队"待处理"。把整文件的 4 张表写入打包到独立线程，彻底切断
        与 ASGI 请求线程的争用。

        branch_name（contract）：分支维度透传给 write_bundle_sync。默认 ""=base，
        保证现有 full/incremental 调用方行为字节不变（向后兼容红线）。
        """
        return await sync_to_async(
            self.write_bundle_sync, thread_sensitive=False,
        )(repository_id, bundle, branch_name=branch_name)

    def write_bundle_sync(
        self, repository_id: str, bundle: Any, *, branch_name: str = "",
    ) -> dict[str, int]:
        """同步版本的 write_bundle，使用 sync ORM 一次性完成 4 张表写入。

        写入策略（per-file 幂等性）：
        1. 删除该文件旧记录：Symbol/ImportEdge/Endpoint 按 file_path 过滤 delete；
           CallEdge 统一按 caller_file=file_path 显式删除（函数内边与模块级边的
           caller_file 都等于本文件，是唯一清理路径）。caller_symbol 已改
           SET_NULL，Symbol delete 仅把边的 caller_symbol 置 NULL、不负责删边
        2. 先 bulk_create Symbol → 构建 symbol_id_map
        3. bulk_create ImportEdge 和 Endpoint（无 FK 依赖）
        4. bulk_create CallEdge：caller 查到则填 caller_symbol FK，查不到则写
           模块级边（caller_symbol=NULL）；所有边恒填 caller_file（work item）

        contract：整个流程包在 ``transaction.atomic()`` 内 —— 每文件 1 次 commit
        而不是 7 次（3 delete + 4 bulk_create），SQLite WAL/写锁压力下降一个
        量级；同时保证 per-file 原子性（中途失败完全回滚，无中间态）。

        Args:
            repository_id: 仓库 UUID 字符串
            bundle: ExtractionBundle dataclass 实例

        Returns:
            dict: {"symbols": N, "imports": N, "calls": N, "endpoints": N}
        """
        file_path = bundle.file_path
        stats: dict[str, int] = {"symbols": 0, "imports": 0, "calls": 0, "endpoints": 0}
        # 模块级边计数（caller_symbol_id=None）——仅用于可观测性日志，不影响写入。
        module_level_calls = 0

        with transaction.atomic():
            # =================================================================
            # 第一步：删除该文件的旧图谱记录（幂等性保证）
            # =================================================================
            # CallEdge 统一删除路径（Pitfall 2 / work item / work item）：
            # caller_symbol 现为 SET_NULL —— 删除 Symbol 只会把函数内边的
            # caller_symbol 置 NULL，**不**级联删边（CASCADE 才级联，本字段已非
            # CASCADE）。函数内边与模块级边的 caller_file 都恒填 == 本文件，统一由
            # caller_file=file_path 显式删除，是**唯一**清理路径，不可移除——
            # 移除将导致本文件全部 CallEdge 泄漏无法清理。
            # work item：**必须在 Symbol delete 之前**先删边——否则 Symbol delete 会对
            # 即将被删的函数内边先触发一次 SET_NULL UPDATE（写放大）；先删边后这些
            # 行已不存在，Symbol delete 不再产生无谓 UPDATE，删除职责也单一化。
            # contract：4 个 per-file 删除 filter 全部带 branch_name —— feature
            # per-file 删除加 branch_name=<feature> 过滤后绝不会删到 base 行
            # （base 行 branch_name=""），杜绝 feature 写入污染 base（Pitfall 1/4）。
            CallEdge.objects.filter(
                repository_id=repository_id, caller_file=file_path,
                branch_name=branch_name,
            ).delete()
            Symbol.objects.filter(
                repository_id=repository_id, file_path=file_path,
                branch_name=branch_name,
            ).delete()
            ImportEdge.objects.filter(
                repository_id=repository_id, source_file=file_path,
                branch_name=branch_name,
            ).delete()
            Endpoint.objects.filter(
                repository_id=repository_id, file_path=file_path,
                branch_name=branch_name,
            ).delete()

            # =================================================================
            # 第二步：批量创建 Symbol（必须先于 CallEdge）
            # =================================================================
            symbol_objs: list[Symbol] = []
            for s in bundle.symbols:
                symbol_objs.append(Symbol(
                    repository_id=repository_id,
                    branch_name=branch_name,
                    name=s.name,
                    symbol_type=s.symbol_type,
                    file_path=s.file_path,
                    start_line=s.start_line,
                    end_line=s.end_line,
                    signature=s.signature,
                    is_async=s.is_async,
                ))

            if symbol_objs:
                created_symbols = Symbol.objects.bulk_create(symbol_objs)
                stats["symbols"] = len(created_symbols)
                # 构建 symbol_id_map: (file_path, name, start_line) -> Symbol.id
                # 用于 CallEdge 的 caller_symbol FK 解析
                symbol_id_map: dict[tuple[str, str, int], str] = {}
                # 兜底：(file_path, name) -> Symbol.id。calls extractor 写的 caller_key
                # 是 (file_path, ancestor_function_name, 0)（start_line 用 0 表示 unknown），
                # 精确三元组永远查不到 → 必须通过 (file_path, name) 兜底。
                # 同名情况下取第一个（同文件内同名函数极罕见，且文件级抽取已隔离）。
                symbol_name_index: dict[tuple[str, str], str] = {}
                for sym in created_symbols:
                    key = (sym.file_path, sym.name, sym.start_line)
                    symbol_id_map[key] = str(sym.id)
                    name_key = (sym.file_path, sym.name)
                    symbol_name_index.setdefault(name_key, str(sym.id))
            else:
                symbol_id_map = {}
                symbol_name_index = {}

            # =================================================================
            # 第三步：批量创建 ImportEdge（无 FK 依赖）
            # =================================================================
            import_objs: list[ImportEdge] = []
            for imp in bundle.imports:
                import_objs.append(ImportEdge(
                    repository_id=repository_id,
                    branch_name=branch_name,
                    source_file=imp.source_file,
                    target_module=imp.target_module,
                    imported_names=imp.imported_names,
                    is_relative=imp.is_relative,
                ))

            if import_objs:
                ImportEdge.objects.bulk_create(import_objs)
                stats["imports"] = len(import_objs)

            # =================================================================
            # 第四步：批量创建 Endpoint（无 FK 依赖）
            # =================================================================
            endpoint_objs: list[Endpoint] = []
            for ep in bundle.endpoints:
                # url_path 可能为 None（Layer 1 装饰器扫描结果未关联 URL）
                endpoint_objs.append(Endpoint(
                    repository_id=repository_id,
                    branch_name=branch_name,
                    http_method=ep.http_method,
                    url_path=ep.url_path or "",
                    handler_name=ep.handler_name,
                    view_type=ep.view_type,
                    file_path=ep.file_path,
                    line_number=ep.line_number,
                    metadata=ep.metadata,
                ))

            if endpoint_objs:
                Endpoint.objects.bulk_create(endpoint_objs)
                stats["endpoints"] = len(endpoint_objs)

            # =================================================================
            # 第五步：批量创建 CallEdge（依赖 symbol_id_map 解析 FK）
            # =================================================================
            call_objs: list[CallEdge] = []
            for call in bundle.calls:
                caller_key = (
                    call.caller_key[0],  # file_path
                    call.caller_key[1],  # name
                    call.caller_key[2],  # start_line
                )
                caller_id = symbol_id_map.get(caller_key)
                if caller_id is None:
                    # 兜底：calls extractor 默认 start_line=0，三元组查不到 →
                    # 用 (file_path, name) 命中同文件同名 caller。
                    caller_id = symbol_name_index.get((caller_key[0], caller_key[1]))
                # work item / Pitfall 3：caller 查不到不再 skip，而是判定为模块级边——
                # caller_symbol_id=None（caller_key[1]=="<module>" 等 sentinel 或动态
                # 分派）。所有边恒填 caller_file=call.caller_key[0]（函数内边
                # caller_file == caller 所在文件 == caller_key[0]，模块级边同样取
                # caller_key[0]）。callee_symbol/callee_file/is_cross_file 留模型默认
                # （NULL/NULL/False），跨文件解析属 288+ 回填。
                if caller_id is None:
                    module_level_calls += 1
                call_objs.append(CallEdge(
                    repository_id=repository_id,
                    branch_name=branch_name,
                    caller_symbol_id=caller_id,
                    caller_file=call.caller_key[0],
                    callee_name=call.callee_name,
                    call_type=call.call_type,
                    line_number=call.line_number,
                    callee_qualifier=call.callee_qualifier,
                ))

            if call_objs:
                CallEdge.objects.bulk_create(call_objs)
                stats["calls"] = len(call_objs)

        # 大型仓库 4000+ 文件每个都 info 级会刷屏 + 拖累 stdout/structlog；
        # 降到 debug，索引完成后由 _extract_and_write_graph 汇总一条 info。
        logger.debug(
            "graph_bundle_written",
            file_path=file_path,
            symbols=stats["symbols"],
            imports=stats["imports"],
            calls=stats["calls"],
            endpoints=stats["endpoints"],
            module_level_calls=module_level_calls,
        )

        return stats

    # =========================================================================
    # initial implementation plan（work item-01）：批量按文件删除图谱孤儿数据
    #
    # 增量索引检测到文件被删除时，indexer 在 _extract_and_write_graph 之前
    # 调用 delete_for_files(deleted_file_paths) 把对应的 Symbol / ImportEdge /
    # Endpoint 三件套清理掉，避免 file_path 已不存在但图谱里还残留行（孤儿数据 bug）。
    #
    # 设计要点：
    # - 整体 transaction.atomic() 包装：单步失败回滚整批，不留中间态。
    # - 三表字段差异显式处理：Symbol.file_path / Endpoint.file_path /
    #   ImportEdge.source_file（注意 ImportEdge 字段名不同）。
    # - file_paths == [] 短路返回 0，不进 transaction、不写 log——避免空调用
    #   产生无意义的事务开销 + 日志噪音。
    # - 异步版通过 sync_to_async(thread_sensitive=False) 调度到独立线程池，
    #   与 write_bundle 同模式，避免与 ASGI 请求线程争用。
    # - 异常不在内部 catch——按调用方（indexer）决定降级策略，配合
    #   transaction.atomic 自动 rollback。
    # =========================================================================

    def delete_for_files(
        self, repository_id: str, file_paths: list[str], *, branch_name: str = "",
    ) -> int:
        """按文件批量删除 Symbol / ImportEdge / Endpoint / 模块级 CallEdge（同步版）。

        CallEdge.caller_symbol 现为 SET_NULL —— 删除 Symbol 只把边的 caller_symbol
        置 NULL、**不**级联删边（Pitfall 2）。函数内边与模块级边的 caller_file 都
        等于其所在文件，统一按 caller_file__in 显式删除，是唯一清理路径，与 Symbol
        删除无耦合（不依赖任何 FK 级联）。

        contract：4 个 __in 删除 filter 全部带 branch_name —— feature 孤儿清理
        加 branch_name=<feature> 过滤后只清本分支行，base 行（branch_name=""）绝不
        被删（Pitfall 1）。默认 ""=base，现有调用方行为字节不变。

        Args:
            repository_id: 仓库 UUID 字符串
            file_paths: 要清理的文件路径列表
            branch_name: 分支维度（""=base）。仅删除该分支的图谱行。

        Returns:
            四表删除行数总和（int）。空 file_paths 直接返回 0。

        Raises:
            原样向上抛任何 ORM 异常；transaction.atomic 自动回滚已删除行。
        """
        if not file_paths:
            return 0

        with transaction.atomic():
            symbols_deleted, _ = Symbol.objects.filter(
                repository_id=repository_id, file_path__in=file_paths,
                branch_name=branch_name,
            ).delete()
            imports_deleted, _ = ImportEdge.objects.filter(
                repository_id=repository_id, source_file__in=file_paths,
                branch_name=branch_name,
            ).delete()
            endpoints_deleted, _ = Endpoint.objects.filter(
                repository_id=repository_id, file_path__in=file_paths,
                branch_name=branch_name,
            ).delete()
            call_edges_deleted, _ = CallEdge.objects.filter(
                repository_id=repository_id, caller_file__in=file_paths,
                branch_name=branch_name,
            ).delete()

        total = (
            int(symbols_deleted) + int(imports_deleted)
            + int(endpoints_deleted) + int(call_edges_deleted)
        )
        logger.info(
            "graph_orphan_cleanup",
            repository_id=repository_id,
            branch_name=branch_name,
            file_count=len(file_paths),
            symbols_deleted=int(symbols_deleted),
            import_edges_deleted=int(imports_deleted),
            endpoints_deleted=int(endpoints_deleted),
            call_edges_deleted=int(call_edges_deleted),
            total_deleted=total,
        )
        return total

    async def adelete_for_files(
        self, repository_id: str, file_paths: list[str], *, branch_name: str = "",
    ) -> int:
        """delete_for_files 的 async 包装器（work item-01）。

        通过 sync_to_async(thread_sensitive=False) 调度到独立线程池，与
        write_bundle 同模式，避免与 ASGI 请求线程共享 SingleThreadExecutor。

        contract：branch_name 透传给 sync 实现，feature 孤儿清理只清本分支行。

        Args:
            repository_id: 仓库 UUID 字符串
            file_paths: 要清理的文件路径列表
            branch_name: 分支维度（""=base）。

        Returns:
            三表删除行数总和（int）。空 file_paths 直接返回 0，不调度到线程池。
        """
        if not file_paths:
            return 0
        return await sync_to_async(
            self.delete_for_files, thread_sensitive=False,
        )(repository_id, file_paths, branch_name=branch_name)

    # =========================================================================
    # initial implementation: ApiWrapper + ApiCallSite 写入（work item）
    # =========================================================================

    def write_api_wrappers_for_file(
        self,
        repository_id: str,
        file_path: str,
        wrappers: "list[ApiWrapperData]",
        *,
        branch_name: str = "",
    ) -> int:
        """Per-file 幂等写入 ApiWrapper（先 delete 再 bulk_create）。

        与 write_bundle_sync 的 per-file 幂等策略一致：先删除该文件旧记录，
        再 bulk_create 新记录，保证重复运行不重复插入。

        contract：293 已给 ApiWrapper 加 branch_name 字段 + unique 含 branch_name，
        故 filter/构造同步带 branch_name，避免 base+feature 双写撞 unique（Pitfall 1）。
        **ApiCallSite 不动**：293 未给 ApiCallSite 加 branch 维度，per-wrapper 删除
        已隔离（write_api_call_sites_for_wrapper 保持原样）。调用入口在 checkpoint/04 透传。

        Args:
            repository_id: 仓库 UUID 字符串
            file_path: 源文件路径（ApiWrapper 所在文件）
            wrappers: ApiWrapperData 列表
            branch_name: 分支维度（""=base）。

        Returns:
            写入的 ApiWrapper 数量
        """
        with transaction.atomic():
            ApiWrapper.objects.filter(
                repository_id=repository_id, file_path=file_path,
                branch_name=branch_name,
            ).delete()
            objs = [
                ApiWrapper(
                    repository_id=repository_id,
                    branch_name=branch_name,
                    file_path=w.file_path,
                    function_symbol=w.function_symbol,
                    http_method=w.http_method,
                    url_path_raw=w.url_path_raw,
                    url_path_pattern=w.url_path_pattern,
                    detected_via=w.detected_via,
                    line_number=w.line_number,
                    metadata=w.metadata,
                )
                for w in wrappers
            ]
            if objs:
                ApiWrapper.objects.bulk_create(objs, ignore_conflicts=True)

        logger.debug(
            "api_wrapper_written",
            file_path=file_path,
            count=len(objs),
        )
        return len(objs)

    def write_api_call_sites_for_wrapper(
        self,
        repository_id: str,
        api_wrapper_id: str,
        sites: "list[ApiCallSiteData]",
    ) -> int:
        """Per-wrapper 幂等写入 ApiCallSite（先 delete 再 bulk_create）。

        Args:
            repository_id: 仓库 UUID 字符串
            api_wrapper_id: ApiWrapper.id（UUID 字符串）
            sites: ApiCallSiteData 列表

        Returns:
            写入的 ApiCallSite 数量
        """
        import uuid as _uuid

        wrapper_uuid = _uuid.UUID(api_wrapper_id) if isinstance(api_wrapper_id, str) else api_wrapper_id
        with transaction.atomic():
            ApiCallSite.objects.filter(api_wrapper_id=wrapper_uuid).delete()
            objs = [
                ApiCallSite(
                    repository_id=repository_id,
                    api_wrapper_id=wrapper_uuid,
                    caller_file=s.caller_file,
                    caller_function=s.caller_function,
                    line_number=s.line_number,
                )
                for s in sites
            ]
            if objs:
                ApiCallSite.objects.bulk_create(objs)

        logger.debug(
            "api_call_site_written",
            api_wrapper_id=str(wrapper_uuid),
            count=len(objs),
        )
        return len(objs)
