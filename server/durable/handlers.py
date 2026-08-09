"""in-process fallback 下的业务任务 handler 注册（双后端入参对齐 adapter）。

in-process 后端的 ``_run_job`` 以 ``await handler(payload)`` 整传 dict，而 procrastinate
经 ``defer_async(**payload)`` 展开 kwargs。若直接把共用任务体（keyword-only 形参）注册到
in-process 后端会因"整传 dict vs 展开 kwargs"炸（研究 Pitfall 1）。本模块为每个任务名
注册一个 ``**payload`` 展开 adapter，使同一任务体在两后端入参一致。

本模块对 procrastinate 零直接依赖（仅经 ``durable.backends`` 的 in-process 注册表），
由 ``DurableConfig.ready()`` 在**两个后端路径都无条件调用** ``register_business_handlers()``，
保证 SQLite dev / pytest 也有业务 handler（否则 durable_index 会走 no-op）。
"""

from __future__ import annotations

from typing import Any

from durable.backends import register_handler


async def _index(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_index

    return await run_index(**payload)


async def _graph(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_graph

    return await run_graph(**payload)


async def _page_index(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_page_index

    return await run_page_index(**payload)


async def _crawl_ingest(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_crawl_ingest

    return await run_crawl_ingest(**payload)


async def _repo_summary(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_repo_summary

    return await run_repo_summary(**payload)


async def _doc_sync_pull(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_doc_sync_pull

    return await run_doc_sync_pull(**payload)


async def _doc_sync_push(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_doc_sync_push

    return await run_doc_sync_push(**payload)


async def _feature_list_parse_start(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_feature_list_parse_start

    return await run_feature_list_parse_start(**payload)


async def _feature_list_parse_module(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_feature_list_parse_module

    return await run_feature_list_parse_module(**payload)


async def _blueprint_resume(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_blueprint_resume

    return await run_blueprint_resume(**payload)


async def _runner_dispatch(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_runner_dispatch

    return await run_runner_dispatch(**payload)


async def _community_rebuild(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_community_rebuild

    return await run_community_rebuild(**payload)


async def _process_rebuild(payload: dict[str, Any]) -> Any:
    from durable.tasks_impl import run_process_rebuild

    return await run_process_rebuild(**payload)


def register_business_handlers() -> None:
    """把 index / graph / page_index 的 ``**payload`` 展开 adapter 注册到 in-process 后端。

    纯注册、无 IO，所有 role / 后端均安全调用。adapter 内 ``run_*(**payload)`` 与
    procrastinate ``defer_async(**payload)`` 入参完全对齐，消除双后端入参不一致。
    """
    register_handler("durable_index", _index)
    register_handler("durable_graph", _graph)
    register_handler("durable_page_index", _page_index)
    register_handler("durable_crawl_ingest", _crawl_ingest)
    register_handler("durable_repo_summary", _repo_summary)
    register_handler("durable_doc_sync_pull", _doc_sync_pull)
    register_handler("durable_doc_sync_push", _doc_sync_push)
    register_handler("feature_list_parse_start", _feature_list_parse_start)
    register_handler("feature_list_parse_module", _feature_list_parse_module)
    register_handler("durable_blueprint_resume", _blueprint_resume)
    register_handler("durable_runner_dispatch", _runner_dispatch)
    register_handler("durable_community_rebuild", _community_rebuild)
    register_handler("durable_process_rebuild", _process_rebuild)


__all__ = ["register_business_handlers"]
