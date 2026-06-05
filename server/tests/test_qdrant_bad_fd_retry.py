"""Qdrant client 坏 fd 后自动重建连接的回归测试。"""

from __future__ import annotations

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from services.qdrant_service import QdrantService


def test_upsert_vectors_retries_once_after_bad_file_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FlakyClient:
        def upsert(self, *, collection_name: str, points: list[object]) -> None:
            calls.append(collection_name)
            if len(calls) == 1:
                raise OSError(9, "Bad file descriptor")

    fake_client = FlakyClient()

    monkeypatch.setattr(
        QdrantService,
        "get_client",
        classmethod(lambda cls: fake_client),
    )

    ok = QdrantService.upsert_vectors(
        "repo-1",
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "vector": [0.1, 0.2],
                "payload": {"file_path": "a.py"},
            }
        ],
    )

    assert ok is True
    assert calls == ["code_index_repo-1", "code_index_repo-1"]


def test_upsert_vectors_reports_qdrant_response_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    logs: list[dict[str, object]] = []

    class CapturingLogger:
        def info(self, event: str, **kwargs: object) -> None:
            logs.append({"event": event, **kwargs})

        def warning(self, event: str, **kwargs: object) -> None:
            logs.append({"event": event, **kwargs})

        def error(self, event: str, **kwargs: object) -> None:
            logs.append({"event": event, **kwargs})

    class TimeoutClient:
        def upsert(self, *, collection_name: str, points: list[object]) -> None:
            raise ResponseHandlingException(httpx.ReadTimeout("timed out"))

    monkeypatch.setattr("services.qdrant_service.logger", CapturingLogger())
    monkeypatch.setattr(
        QdrantService,
        "get_client",
        classmethod(lambda cls: TimeoutClient()),
    )

    ok = QdrantService.upsert_vectors(
        "repo-1",
        [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "vector": [0.1, 0.2],
                "payload": {"file_path": "a.py"},
            }
        ],
    )

    assert ok is False
    failure = next(log for log in logs if log["event"] == "upsert_vectors_response_handling_failed")
    assert failure["reason"] == "timeout"
    assert failure["collection_name"] == "code_index_repo-1"
    assert failure["points_count"] == 1


def test_health_check_does_not_reset_cached_client_when_healthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """health_check 不能再无条件 reset_client：会切断在飞中的 upsert 连接，
    导致 60s ResponseHandlingException timeout（线上真实事故）。
    """
    closed: list[str] = []

    class FakeCollections:
        collections: list[object] = []

    class CountingClient:
        def __init__(self) -> None:
            self.collections_calls = 0

        def get_collections(self) -> FakeCollections:
            self.collections_calls += 1
            return FakeCollections()

        def close(self) -> None:
            closed.append("close")

    fake_client = CountingClient()

    QdrantService._client = fake_client  # type: ignore[assignment]
    try:
        result = QdrantService.health_check()
    finally:
        QdrantService._client = None

    assert result["status"] == "healthy"
    assert closed == [], (
        "health_check 不应关闭缓存的 client（这会切断正在进行的 upsert）"
    )
    assert fake_client.collections_calls == 1


def test_health_check_resets_cached_client_on_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """缓存的 client get_collections 抛连接错误时，health_check 必须 reset 并重新连。"""
    init_calls: list[str] = []

    class FakeCollections:
        collections: list[object] = []

    class StaleClient:
        def get_collections(self) -> FakeCollections:
            raise ConnectionResetError(54, "Connection reset by peer")

        def close(self) -> None:
            return None

    class FreshClient:
        def get_collections(self) -> FakeCollections:
            return FakeCollections()

        def close(self) -> None:
            return None

    QdrantService._client = StaleClient()  # type: ignore[assignment]

    def fake_get_client(cls: type) -> object:
        if QdrantService._client is None:
            init_calls.append("init")
            QdrantService._client = FreshClient()  # type: ignore[assignment]
        return QdrantService._client

    monkeypatch.setattr(
        QdrantService,
        "get_client",
        classmethod(fake_get_client),
    )

    try:
        result = QdrantService.health_check()
    finally:
        QdrantService._client = None

    assert result["status"] == "healthy"
    assert init_calls == ["init"], (
        "stale client 抛连接错误后必须 reset 并重建 client"
    )


def test_qdrant_setting_change_resets_cached_client(db, monkeypatch) -> None:
    """改 qdrant_url 设置时必须重置 QdrantService 的缓存 client，
    否则配置变更后还在用老连接。
    """
    from system.models import SettingKeys, SystemSetting

    closed: list[str] = []

    class StubClient:
        def close(self) -> None:
            closed.append("close")

    QdrantService._client = StubClient()  # type: ignore[assignment]
    try:
        SystemSetting.objects.update_or_create(
            key=SettingKeys.QDRANT_URL,
            defaults={"value": "http://127.0.0.1:6333"},
        )
    finally:
        try:
            QdrantService.reset_client()
        finally:
            QdrantService._client = None

    assert closed == ["close"], "qdrant_url 写入后应立刻重置 Qdrant client"


def test_non_qdrant_setting_change_does_not_reset_cached_client(db) -> None:
    from system.models import SettingKeys, SystemSetting

    closed: list[str] = []

    class StubClient:
        def close(self) -> None:
            closed.append("close")

    QdrantService._client = StubClient()  # type: ignore[assignment]
    try:
        SystemSetting.objects.update_or_create(
            key=SettingKeys.GIT_HTTP_PROXY,
            defaults={"value": ""},
        )
    finally:
        QdrantService._client = None

    assert closed == [], "无关设置不应触发 Qdrant client 重置"


def test_health_check_with_config_returns_message_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def get_collections(self) -> object:
            raise ConnectionResetError(54, "Connection reset by peer")

    monkeypatch.setattr("services.qdrant_service.QdrantClient", FailingClient)

    result = QdrantService.health_check_with_config("http://localhost:6333")

    assert result["status"] == "unhealthy"
    assert "ConnectionResetError" in result["message"]
    assert result["error"] == "[Errno 54] Connection reset by peer"
    assert result["reason"] == "connection_error"
