"""Tests for DependencyCacheManager."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from docker.errors import NotFound

from services.dependency_cache import (
    DependencyCacheManager,
    LockFileInfo,
    PackageManager,
)


class TestGetVolumeName:
    """Tests for get_volume_name method."""

    def test_get_volume_name_format(self) -> None:
        """Volume name follows expected format."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        name = manager.get_volume_name("repo-12345678", "abcdef1234567890")

        # friday-deps-{repo_id[:8]}-{lock_hash[:8]}
        assert name == "friday-deps-repo-123-abcdef12"
        assert name.startswith("friday-deps-")


class TestComputeLockHash:
    """Tests for compute_lock_hash method."""

    def test_compute_lock_hash_deterministic(self) -> None:
        """Same content returns same hash."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content\n")
            temp_path = f.name

        try:
            hash1 = manager.compute_lock_hash(temp_path)
            hash2 = manager.compute_lock_hash(temp_path)

            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex length
        finally:
            os.unlink(temp_path)


class TestDetectLockFile:
    """Tests for detect_lock_file method."""

    def test_detect_lock_file_priority_pnpm(self) -> None:
        """pnpm-lock.yaml has highest priority."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create all lock files
            for filename in ["requirements.txt", "package-lock.json", "pnpm-lock.yaml"]:
                with open(os.path.join(tmpdir, filename), "w") as f:
                    f.write("content")

            result = manager.detect_lock_file(tmpdir)

            assert result is not None
            assert result.manager == PackageManager.PNPM
            assert "pnpm-lock.yaml" in result.file_path

    def test_detect_lock_file_priority_npm(self) -> None:
        """package-lock.json has second priority."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create npm and pip lock files
            for filename in ["requirements.txt", "package-lock.json"]:
                with open(os.path.join(tmpdir, filename), "w") as f:
                    f.write("content")

            result = manager.detect_lock_file(tmpdir)

            assert result is not None
            assert result.manager == PackageManager.NPM

    def test_detect_lock_file_none(self) -> None:
        """Returns None when no lock file exists."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = manager.detect_lock_file(tmpdir)
            assert result is None


@pytest.mark.django_db
class TestEnsureDepsCache:
    """Tests for ensure_deps_cache method."""

    @pytest.mark.asyncio
    async def test_ensure_deps_cache_returns_existing(self) -> None:
        """Returns existing volume name when volume exists."""
        mock_client = MagicMock()
        mock_client.volumes.get.return_value = MagicMock()

        with patch("docker.from_env", return_value=mock_client):
            manager = DependencyCacheManager()

        lock_info = LockFileInfo(
            manager=PackageManager.PIP,
            content_hash="abcdef1234567890",
            file_path="/tmp/requirements.txt",
        )

        result = await manager.ensure_deps_cache(
            repo_id="repo-123",
            lock_info=lock_info,
        )

        assert result is not None
        mock_client.volumes.get.assert_called_once()
        mock_client.containers.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_deps_cache_creates_volume(self) -> None:
        """Creates volume and runs install when volume doesn't exist."""
        mock_client = MagicMock()
        mock_client.volumes.get.side_effect = NotFound("Volume not found")
        mock_client.volumes.create.return_value = MagicMock()
        mock_client.containers.run.return_value = b""

        with patch("docker.from_env", return_value=mock_client):
            manager = DependencyCacheManager()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("django>=4.0\n")
            temp_path = f.name

        try:
            lock_info = LockFileInfo(
                manager=PackageManager.PIP,
                content_hash="abcdef1234567890",
                file_path=temp_path,
            )

            result = await manager.ensure_deps_cache(
                repo_id="repo-123",
                lock_info=lock_info,
            )

            assert result is not None
            mock_client.volumes.create.assert_called_once()
            mock_client.containers.run.assert_called_once()

            # Verify volume labels
            create_call = mock_client.volumes.create.call_args
            labels = create_call.kwargs["labels"]
            assert labels["friday.type"] == "deps-cache"
            assert labels["friday.manager"] == "pip"
        finally:
            os.unlink(temp_path)


class TestGetInstallCommand:
    """Tests for _get_install_command method."""

    def test_get_install_command_pip(self) -> None:
        """pip install command is correct."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        command = manager._get_install_command(
            PackageManager.PIP,
            "/workspace/requirements.txt",
        )

        assert "pip install" in command
        assert "--target /deps/site-packages" in command

    def test_get_install_command_npm(self) -> None:
        """npm install command is correct."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        command = manager._get_install_command(
            PackageManager.NPM,
            "/workspace/package-lock.json",
        )

        assert "npm ci" in command
        assert "--prefix /deps" in command

    def test_get_install_command_pnpm(self) -> None:
        """pnpm install command is correct."""
        with patch("docker.from_env"):
            manager = DependencyCacheManager()

        command = manager._get_install_command(
            PackageManager.PNPM,
            "/workspace/pnpm-lock.yaml",
        )

        assert "pnpm install" in command
        assert "--frozen-lockfile" in command
