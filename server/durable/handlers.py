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


def register_business_handlers() -> None:
    """把 index / graph / page_index 的 ``**payload`` 展开 adapter 注册到 in-process 后端。

    纯注册、无 IO，所有 role / 后端均安全调用。adapter 内 ``run_*(**payload)`` 与
    procrastinate ``defer_async(**payload)`` 入参完全对齐，消除双后端入参不一致。
    """
    register_handler("durable_index", _index)
    register_handler("durable_graph", _graph)
    register_handler("durable_page_index", _page_index)
    register_handler("durable_crawl_ingest", _crawl_ingest)


__all__ = ["register_business_handlers"]
