# Friday AI Compose 完整体实例 Implementation Plan
> **For agentic workers:** REQUIRED work item: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- `) syntax for tracking.
**Goal:** 实现 `scripts/setup.sh && docker compose up -d` 启动 Friday AI 完整体实例，并把所有运行数据持久化到 `~/.friday-ai` 的独立子目录。
**Architecture:** `docker-compose.yaml` 成为默认完整体入口，基础设施服务默认启动。`scripts/setup.sh` 生成 `.env` 和宿主机数据目录；根目录 `setup.sh` 兼容转发。Server 启动后通过 management command 写入缺省 Qdrant 系统设置。
**Tech Stack:** Docker Compose V2、Bash、Django management command、pytest、PyYAML。
---
### Task 1: 部署契约测试
**Files:**
- Create: `server/tests/test_compose_full_instance_contract.py`
- Create: `server/tests/test_bootstrap_system_settings.py`
- **Step 1: 写 compose 契约失败测试**
```python
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve.parents[2]
def _compose -> dict:
 return yaml.safe_load((ROOT / "docker-compose.yaml").read_text)
def test_compose_defaults_to_full_instance_services -> None:
 services = _compose["services"]
 assert {"redis", "postgres", "qdrant", "server", "web", "runner"} <= set(services)
 assert "profiles" not in services["postgres"]
 assert {"postgres", "redis", "qdrant"} <= set(services["server"]["depends_on"])
def test_compose_uses_host_data_dir_bind_mounts -> None:
 services = _compose["services"]
 expected = {
 "postgres": "${FRIDAY_DATA_DIR:-~/.friday-ai}/postgres:/var/lib/postgresql/data",
 "redis": "${FRIDAY_DATA_DIR:-~/.friday-ai}/redis:/data",
 "qdrant": "${FRIDAY_DATA_DIR:-~/.friday-ai}/qdrant:/qdrant/storage",
 "server": "${FRIDAY_DATA_DIR:-~/.friday-ai}/server:/app/data",
 "runner": "${FRIDAY_DATA_DIR:-~/.friday-ai}/runner:/data",
 }
 for service, mount in expected.items:
 assert mount in services[service]["volumes"]
 assert "volumes" not in _compose
```
- **Step 2: 写系统设置 bootstrap 失败测试**
```python
from io import StringIO
import pytest
from django.core.management import call_command
from common.encryption import decrypt_value
from system.models import SettingKeys, SystemSetting
@pytest.mark.django_db
def test_bootstrap_system_settings_creates_qdrant_url(monkeypatch: pytest.MonkeyPatch) -> None:
 monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
 out = StringIO
 call_command("bootstrap_system_settings", stdout=out)
 setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_URL)
 assert setting.value == "http://qdrant:6333"
 assert setting.is_encrypted is False
@pytest.mark.django_db
def test_bootstrap_system_settings_preserves_existing_qdrant_url(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 SystemSetting.objects.create(
 key=SettingKeys.QDRANT_URL,
 value="http://external-qdrant:6333",
 is_encrypted=False,
 )
 monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
 call_command("bootstrap_system_settings")
 setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_URL)
 assert setting.value == "http://external-qdrant:6333"
@pytest.mark.django_db
def test_bootstrap_system_settings_encrypts_qdrant_api_key(
 monkeypatch: pytest.MonkeyPatch,
) -> None:
 monkeypatch.setenv("QDRANT_API_KEY", "secret-key")
 call_command("bootstrap_system_settings")
 setting = SystemSetting.objects.get(key=SettingKeys.QDRANT_API_KEY)
 assert setting.is_encrypted is True
 assert setting.value != "secret-key"
 assert decrypt_value(setting.value) == "secret-key"
```
- **Step 3: 运行测试确认失败**
Run:
```bash
cd server && uv run pytest tests/test_compose_full_instance_contract.py tests/test_bootstrap_system_settings.py -q
```
Expected: 失败，因为测试文件存在后，`postgres` 仍有 profile，host bind mounts 尚未配置，`bootstrap_system_settings` 命令尚不存在。
### Task 2: 实现 compose 和 setup
**Files:**
- Modify: `docker-compose.yaml`
- Create: `scripts/setup.sh`
- Modify: `setup.sh`
- Modify: `.env.example`
- **Step 1: 修改 compose**
删除 `postgres` 的 `profiles`，把 named volume 挂载改成 `${FRIDAY_DATA_DIR:-~/.friday-ai}/服务名:容器路径`，删除顶层 `volumes`。给 server 增加 `QDRANT_URL`、`QDRANT_API_KEY` 环境变量，并让 server 依赖 `postgres`、`redis`、`qdrant` 健康状态。
- **Step 2: 新建正式 setup 脚本**
把原根目录脚本主体移到 `scripts/setup.sh`，生成 `.env` 时写入 `FRIDAY_DATA_DIR`、`QDRANT_URL`、`QDRANT_API_KEY`，并创建 `postgres`、`redis`、`qdrant`、`server`、`runner` 子目录。
- **Step 3: 保留根目录兼容入口**
把 `setup.sh` 改为：
```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/scripts/setup.sh" "$@"
```
- **Step 4: 更新 `.env.example`**
加入 `FRIDAY_DATA_DIR=~/.friday-ai`，说明默认完整体包含 PostgreSQL、Redis、Qdrant，`COMPOSE_PROFILES=postgres` 不再需要。
### Task 3: 实现系统设置 bootstrap
**Files:**
- Create: `server/system/management/commands/bootstrap_system_settings.py`
- Modify: `server/entrypoint.sh`
- **Step 1: 新增 management command**
命令读取 `QDRANT_URL`，默认 `http://qdrant:6333`。不存在 `qdrant_url` 时创建；存在时不覆盖。读取 `QDRANT_API_KEY`，非空且不存在 `qdrant_api_key` 时使用 `encrypt_value` 加密写入。
- **Step 2: 接入 entrypoint**
在 `python manage.py migrate --noinput` 后执行：
```bash
python manage.py bootstrap_system_settings
```
### Task 4: 文档与验证
**Files:**
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/quick-start.md`
- Modify: `docs/guide/quick-start.md`
- **Step 1: 更新启动说明**
把 `cp .env.example .env` 的默认路径改成 `scripts/setup.sh`，说明数据默认写入 `~/.friday-ai`。
- **Step 2: 运行验证**
Run:
```bash
bash -n scripts/setup.sh setup.sh
cd server && uv run pytest tests/test_compose_full_instance_contract.py tests/test_bootstrap_system_settings.py -q
docker compose config
```
Expected: 三条命令退出码均为 0。
## 自检
本计划覆盖设计中的一键启动、默认完整体、宿主机持久化、Qdrant 系统设置初始化、文档更新和验证要求。无占位符或待补事项。
