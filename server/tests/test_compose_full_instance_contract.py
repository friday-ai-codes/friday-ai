"""Docker Compose 完整体部署契约测试。"""
from pathlib import Path
from typing import Any
import yaml
ROOT = Path(__file__).resolve.parents[2]
def _compose -> dict[str, Any]:
 return yaml.safe_load((ROOT / "docker-compose.yaml").read_text)
def test_compose_defaults_to_full_instance_services -> None:
 """默认 `docker compose up -d` 应启动完整 Friday 实例。"""
 services = _compose["services"]
 assert {"redis", "postgres", "qdrant", "server", "web", "runner"} <= set(services)
 assert "profiles" not in services["postgres"]
 assert {"postgres", "redis", "qdrant"} <= set(services["server"]["depends_on"])
def test_compose_uses_host_data_dir_bind_mounts -> None:
 """所有持久化目录必须落到宿主机 FRIDAY_DATA_DIR 的独立子目录。"""
 services = _compose["services"]
 expected_mounts = {
 "postgres": "${FRIDAY_DATA_DIR:-~/.friday-ai}/postgres:/var/lib/postgresql/data",
 "redis": "${FRIDAY_DATA_DIR:-~/.friday-ai}/redis:/data",
 "qdrant": "${FRIDAY_DATA_DIR:-~/.friday-ai}/qdrant:/qdrant/storage",
 "server": "${FRIDAY_DATA_DIR:-~/.friday-ai}/server:/app/data",
 "runner": "${FRIDAY_DATA_DIR:-~/.friday-ai}/runner:/data",
 }
 for service, mount in expected_mounts.items:
 assert mount in services[service]["volumes"]
 assert "volumes" not in _compose
