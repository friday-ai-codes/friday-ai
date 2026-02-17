"""Tests for RepoCacheManager."""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from docker.errors import APIError, NotFound
from services.repo_cache_manager import RepoCacheManager
class TestGetVolumeName:
 """Tests for get_volume_name method."""
 def test_get_volume_name_deterministic(self) -> None:
 """Same URL returns same volume name."""
 with patch("docker.from_env"):
 manager = RepoCacheManager
 url = "https://github.com/example/repo.git"
 name1 = manager.get_volume_name(url)
 name2 = manager.get_volume_name(url)
 assert name1 == name2
 assert name1.startswith("friday-repo-")
 assert len(name1) == len("friday-repo-") + 12 # 12 char hash
 def test_get_volume_name_different_urls(self) -> None:
 """Different URLs return different volume names."""
 with patch("docker.from_env"):
 manager = RepoCacheManager
 url1 = "https://github.com/example/repo1.git"
 url2 = "https://github.com/example/repo2.git"
 name1 = manager.get_volume_name(url1)
 name2 = manager.get_volume_name(url2)
 assert name1 != name2
@pytest.mark.django_db
class TestEnsureRepoCache:
 """Tests for ensure_repo_cache method."""
 @pytest.mark.asyncio
 async def test_ensure_repo_cache_returns_existing(self) -> None:
 """Returns existing volume name when volume exists."""
 mock_client = MagicMock
 mock_volume = MagicMock
 mock_client.volumes.get.return_value = mock_volume
 with patch("docker.from_env", return_value=mock_client):
 manager = RepoCacheManager
 result = await manager.ensure_repo_cache(
 repo_url="https://github.com/example/repo.git",
 repo_id="repo-123",
 )
 assert result is not None
 assert result.startswith("friday-repo-")
 # Volume.get was called, containers.run was NOT called
 mock_client.volumes.get.assert_called_once
 mock_client.containers.run.assert_not_called
 @pytest.mark.asyncio
 async def test_ensure_repo_cache_creates_volume(self) -> None:
 """Creates volume and runs bare clone when volume doesn't exist."""
 mock_client = MagicMock
 mock_client.volumes.get.side_effect = NotFound("Volume not found")
 mock_client.volumes.create.return_value = MagicMock
 mock_client.containers.run.return_value = b""
 with patch("docker.from_env", return_value=mock_client):
 manager = RepoCacheManager
 result = await manager.ensure_repo_cache(
 repo_url="https://github.com/example/repo.git",
 repo_id="repo-123",
 )
 assert result is not None
 assert result.startswith("friday-repo-")
 mock_client.volumes.create.assert_called_once
 mock_client.containers.run.assert_called_once
 # Verify volume labels
 create_call = mock_client.volumes.create.call_args
 labels = create_call.kwargs["labels"]
 assert labels["friday.type"] == "repo-cache"
 assert labels["friday.repo_id"] == "repo-123"
 @pytest.mark.asyncio
 async def test_ensure_repo_cache_handles_race_condition(self) -> None:
 """Handles race condition when volume is created by another process."""
 mock_client = MagicMock
 mock_client.volumes.get.side_effect = NotFound("Volume not found")
 mock_client.volumes.create.side_effect = APIError("volume already exists")
 with patch("docker.from_env", return_value=mock_client):
 manager = RepoCacheManager
 result = await manager.ensure_repo_cache(
 repo_url="https://github.com/example/repo.git",
 repo_id="repo-123",
 )
 # Should return volume name even with race condition
 assert result is not None
 assert result.startswith("friday-repo-")
class TestRefreshCache:
 """Tests for refresh_cache method."""
 @pytest.mark.asyncio
 async def test_refresh_cache_runs_fetch(self) -> None:
 """Runs git fetch in container."""
 mock_client = MagicMock
 mock_client.volumes.get.return_value = MagicMock
 mock_client.containers.run.return_value = b""
 with patch("docker.from_env", return_value=mock_client):
 manager = RepoCacheManager
 result = await manager.refresh_cache("friday-repo-abc123")
 assert result is True
 mock_client.containers.run.assert_called_once
 # Verify fetch command
 run_call = mock_client.containers.run.call_args
 command = run_call.kwargs["command"]
 assert "git fetch" in " ".join(command)
class TestListCacheVolumes:
 """Tests for list_cache_volumes method."""
 @pytest.mark.asyncio
 async def test_list_cache_volumes_filters_prefix(self) -> None:
 """Only returns volumes with friday-repo- prefix."""
 mock_volume1 = MagicMock
 mock_volume1.name = "friday-repo-abc123"
 mock_volume1.attrs = {
 "Labels": {"friday.type": "repo-cache"},
 "CreatedAt": "2024-01-01T00:00:00Z",
 }
 mock_volume2 = MagicMock
 mock_volume2.name = "other-volume"
 mock_volume2.attrs = {}
 mock_volume3 = MagicMock
 mock_volume3.name = "friday-repo-def456"
 mock_volume3.attrs = {
 "Labels": {"friday.type": "repo-cache"},
 "CreatedAt": "2024-01-02T00:00:00Z",
 }
 mock_client = MagicMock
 mock_client.volumes.list.return_value = [mock_volume1, mock_volume2, mock_volume3]
 with patch("docker.from_env", return_value=mock_client):
 manager = RepoCacheManager
 result = await manager.list_cache_volumes
 # Should only include friday-repo- volumes
 assert len(result) == 2
 names = [v["name"] for v in result]
 assert "friday-repo-abc123" in names
 assert "friday-repo-def456" in names
 assert "other-volume" not in names
