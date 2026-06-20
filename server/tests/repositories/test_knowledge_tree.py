"""KnowledgeTreeRebuildView 收口到 durable defer 契约守护（PAGEIDX-01）。

锁定：

- POST knowledge-tree/rebuild/ 经 ``DurableTaskService.defer`` 入队，捕获入参契约
  （task=``durable_page_index``、queue=``page_index``、idempotency_key=
  ``page_index:corpus_tree``、payload 仅含 ``target_id``、**不含自我否定的 target_hash**，
  CR-01），返回 202 + job_id；
- 保持 ``IsAdminUser``：普通用户 / 未认证不放行；
- 源码契约：rebuild 路径无 ``run_in_background(`` 残留、文件内无 ``import procrastinate``。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from rest_framework.test import APIClient

pytestmark = [pytest.mark.django_db(transaction=True)]

_REBUILD_URL = "/api/repositories/knowledge-tree/rebuild/"


def _admin_client(admin_user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


def test_rebuild_defers_to_durable_page_index(admin_user) -> None:
    """admin POST rebuild → 202 + job_id；defer 入参契约（durable_page_index / page_index 队列 / 幂等键）。

    payload **仅含 ``target_id``、不含 target_hash**：run_page_index 在执行时以「上次构建快照
    的 source_hash」为基线自判（CR-01），入队点不再传同源恒等的当前指纹。
    """
    with patch(
        "durable.service.DurableTaskService.defer",
        new_callable=AsyncMock,
        return_value="page_index:corpus_tree",
    ) as mock_defer:
        response = _admin_client(admin_user).post(_REBUILD_URL)

    assert response.status_code == 202, getattr(response, "data", response)
    assert response.data.get("status") == "rebuild_started"
    assert response.data.get("job_id") == "page_index:corpus_tree"

    mock_defer.assert_awaited_once()
    args, kwargs = mock_defer.call_args
    assert args[0] == "durable_page_index"
    assert args[1] == {"target_id": "corpus_tree"}
    assert "target_hash" not in args[1]
    assert kwargs.get("queue") == "page_index"
    assert kwargs.get("idempotency_key") == "page_index:corpus_tree"


def test_rebuild_forbidden_for_non_admin(user) -> None:
    """普通用户（非 admin）→ 403，保持 IsAdminUser 不放宽。"""
    client = APIClient()
    client.force_authenticate(user=user)
    with patch(
        "durable.service.DurableTaskService.defer",
        new_callable=AsyncMock,
    ) as mock_defer:
        response = client.post(_REBUILD_URL)

    assert response.status_code == 403
    mock_defer.assert_not_awaited()


def test_rebuild_unauthenticated_rejected() -> None:
    """未认证 → 401/403（IsAdminUser 强制）。"""
    response = APIClient().post(_REBUILD_URL)
    assert response.status_code in (401, 403)


def test_rebuild_path_has_no_bare_background_runner_or_procrastinate() -> None:
    """源码契约：tree_views.py 无裸 run_in_background( 与直接 import procrastinate。"""
    source = (
        Path(__file__).resolve().parents[2]
        / "repositories"
        / "tree_views.py"
    ).read_text(encoding="utf-8")
    assert "run_in_background(" not in source
    assert "import procrastinate" not in source
    # 正面契约：经 durable 门面入队。
    assert "DurableTaskService" in source
    assert "QUEUE_PAGE_INDEX" in source
