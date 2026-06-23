"""LLM 凭证级并发限流守护（CONC-02，进程内 fallback 路径）。

测试默认走进程内 asyncio.Semaphore（test settings 未配 Redis →
LLM_CONCURRENCY_REDIS_URL 为空）。Redis 租约路径需真实 Redis，留集成验收。
"""

from __future__ import annotations

import uuid

import pytest

from agents.llm_concurrency import LLMBusyError, acquire_llm_slot


def _cid() -> str:
    return f"cred-{uuid.uuid4().hex[:8]}"


async def test_noop_when_max_concurrency_zero() -> None:
    """max_concurrency=0（不限）→ 同凭证可任意并发，不抛。"""
    cid = _cid()
    async with acquire_llm_slot(cid, 0, timeout=0.2):
        async with acquire_llm_slot(cid, 0, timeout=0.2):
            pass  # 不限流：两层嵌套均放行


async def test_noop_when_credential_none() -> None:
    """credential_id 为空 → 不限流。"""
    async with acquire_llm_slot(None, 5, timeout=0.2):
        pass


async def test_inprocess_limits_to_capacity() -> None:
    """max_concurrency=1：持有一个槽位时再申请同凭证 → 等待超时抛 LLMBusyError。"""
    cid = _cid()
    async with acquire_llm_slot(cid, 1, timeout=0.2):
        with pytest.raises(LLMBusyError):
            async with acquire_llm_slot(cid, 1, timeout=0.2):
                pass


async def test_inprocess_releases_slot_after_use() -> None:
    """释放后同凭证可再次申请（不抛）。"""
    cid = _cid()
    async with acquire_llm_slot(cid, 1, timeout=0.2):
        pass
    # 第一次已释放 → 第二次应成功
    async with acquire_llm_slot(cid, 1, timeout=0.2):
        pass


async def test_inprocess_allows_up_to_capacity_concurrently() -> None:
    """容量=2：可同时持有 2 个槽位，第 3 个超时。"""
    cid = _cid()
    async with acquire_llm_slot(cid, 2, timeout=0.2):
        async with acquire_llm_slot(cid, 2, timeout=0.2):
            with pytest.raises(LLMBusyError):
                async with acquire_llm_slot(cid, 2, timeout=0.2):
                    pass


async def test_different_credentials_isolated() -> None:
    """不同凭证各自独立计数，互不阻塞。"""
    a, b = _cid(), _cid()
    async with acquire_llm_slot(a, 1, timeout=0.2):
        # 另一凭证容量 1 仍可申请
        async with acquire_llm_slot(b, 1, timeout=0.2):
            pass


@pytest.mark.django_db
def test_provider_credential_max_concurrency_default() -> None:
    """ProviderCredential.max_concurrency 默认 50（开箱即用）。"""
    from system.models import ProviderCredential

    cred = ProviderCredential.objects.create(
        provider_type="anthropic",
        name="conc-default",
        encrypted_config="x",
    )
    assert cred.max_concurrency == 50
