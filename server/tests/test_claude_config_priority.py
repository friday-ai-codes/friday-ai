"""Claude 配置优先级测试。
测试配置优先级逻辑：项目级 > 系统级 > 环境变量
"""
import os
import pytest
from friday.models import Project
from friday.services.claude_config import get_claude_config, get_claude_config_for_task
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession
@pytest.mark.asyncio
async def test_get_claude_config_from_environment(db_session: AsyncSession):
 """测试从环境变量获取 Claude 配置。"""
 # 确保没有系统设置和项目配置
 os.environ["ANTHROPIC_API_KEY"] = "env-api-key-123"
 os.environ["ANTHROPIC_BASE_URL"] = "https://env.example.com/v1"
 try:
 config = await get_claude_config(db_session, project=None)
 assert config.api_key == "env-api-key-123"
 assert config.base_url == "https://env.example.com/v1"
 assert config.source == "environment"
 finally:
 # 清理环境变量
 os.environ.pop("ANTHROPIC_API_KEY", None)
 os.environ.pop("ANTHROPIC_BASE_URL", None)
@pytest.mark.asyncio
async def test_get_claude_config_system_overrides_environment(
 db_session: AsyncSession, client: AsyncClient
):
 """测试系统配置覆盖环境变量。"""
 # 设置环境变量
 os.environ["ANTHROPIC_API_KEY"] = "env-api-key-overridden"
 os.environ["ANTHROPIC_BASE_URL"] = "https://env.example.com/v1"
 try:
 # 创建系统设置
 setting_data = {
 "key": "anthropic_api_key",
 "value": "system-api-key-456",
 "is_encrypted": True,
 }
 response = await client.post("/api/settings/", json=setting_data)
 assert response.status_code == 201
 base_url_data = {
 "key": "anthropic_base_url",
 "value": "https://system.example.com/v1",
 "is_encrypted": False,
 }
 response = await client.post("/api/settings/", json=base_url_data)
 assert response.status_code == 201
 # 获取配置
 config = await get_claude_config(db_session, project=None)
 assert config.api_key == "system-api-key-456"
 assert config.base_url == "https://system.example.com/v1"
 assert config.source == "system"
 finally:
 os.environ.pop("ANTHROPIC_API_KEY", None)
 os.environ.pop("ANTHROPIC_BASE_URL", None)
@pytest.mark.asyncio
async def test_get_claude_config_project_overrides_system(
 db_session: AsyncSession, client: AsyncClient
):
 """测试项目配置覆盖系统配置。"""
 # 设置环境变量
 os.environ["ANTHROPIC_API_KEY"] = "env-api-key"
 try:
 # 创建系统设置
 setting_data = {
 "key": "anthropic_api_key",
 "value": "system-api-key",
 "is_encrypted": True,
 }
 await client.post("/api/settings/", json=setting_data)
 # 创建项目
 project_data = {
 "name": "Priority Test Project",
 "repo_url": "https://github.com/test/repo.git",
 }
 response = await client.post("/api/projects/", json=project_data)
 assert response.status_code == 201
 project_id = response.json["id"]
 # 设置项目级配置
 config_data = {
 "api_key": "project-api-key-789",
 "base_url": "https://project.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 # 从数据库获取项目（模拟内部服务调用）
 from sqlmodel import select
 result = await db_session.exec(select(Project).where(Project.id == project_id))
 project = result.one
 # 获取配置
 config = await get_claude_config(db_session, project=project)
 assert config.api_key == "project-api-key-789"
 assert config.base_url == "https://project.example.com/v1"
 assert config.source == "project"
 finally:
 os.environ.pop("ANTHROPIC_API_KEY", None)
@pytest.mark.asyncio
async def test_get_claude_config_for_task_success(
 db_session: AsyncSession, client: AsyncClient
):
 """测试 get_claude_config_for_task 成功获取配置。"""
 # 创建项目
 project_data = {
 "name": "Task Config Test Project",
 "repo_url": "https://github.com/test/repo.git",
 }
 response = await client.post("/api/projects/", json=project_data)
 assert response.status_code == 201
 project_id = response.json["id"]
 # 设置项目级配置
 config_data = {
 "api_key": "task-api-key",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 # 获取任务配置
 config = await get_claude_config_for_task(db_session, project_id)
 assert config.api_key == "task-api-key"
 assert config.source == "project"
@pytest.mark.asyncio
async def test_get_claude_config_for_task_no_api_key(
 db_session: AsyncSession, client: AsyncClient
):
 """测试 get_claude_config_for_task 没有配置 API Key 时抛出错误。"""
 # 确保没有环境变量
 os.environ.pop("ANTHROPIC_API_KEY", None)
 # 创建项目（不配置 API Key）
 project_data = {
 "name": "No Config Project",
 "repo_url": "https://github.com/test/repo.git",
 }
 response = await client.post("/api/projects/", json=project_data)
 assert response.status_code == 201
 project_id = response.json["id"]
 # 应该抛出 ValueError
 with pytest.raises(ValueError) as exc_info:
 await get_claude_config_for_task(db_session, project_id)
 assert "未配置 Claude API Key" in str(exc_info.value)
@pytest.mark.asyncio
async def test_get_claude_config_for_task_nonexistent_project(
 db_session: AsyncSession,
):
 """测试 get_claude_config_for_task 项目不存在时抛出错误。"""
 with pytest.raises(ValueError) as exc_info:
 await get_claude_config_for_task(db_session, "nonexistent-project-id")
 assert "找不到项目" in str(exc_info.value)
@pytest.mark.asyncio
async def test_get_claude_config_mixed_sources(
 db_session: AsyncSession, client: AsyncClient
):
 """测试混合配置源：项目 API Key + 系统 Base URL。"""
 os.environ.pop("ANTHROPIC_API_KEY", None)
 os.environ.pop("ANTHROPIC_BASE_URL", None)
 try:
 # 创建系统 Base URL 配置（没有 API Key）
 base_url_data = {
 "key": "anthropic_base_url",
 "value": "https://system-base-url.example.com/v1",
 "is_encrypted": False,
 }
 await client.post("/api/settings/", json=base_url_data)
 # 创建项目并只设置 API Key
 project_data = {
 "name": "Mixed Source Project",
 "repo_url": "https://github.com/test/repo.git",
 }
 response = await client.post("/api/projects/", json=project_data)
 project_id = response.json["id"]
 config_data = {
 "api_key": "project-only-api-key",
 }
 await client.put(f"/api/projects/{project_id}/claude-config", json=config_data)
 # 获取项目
 from sqlmodel import select
 result = await db_session.exec(select(Project).where(Project.id == project_id))
 project = result.one
 # 获取配置
 config = await get_claude_config(db_session, project=project)
 # API Key 来自项目
 assert config.api_key == "project-only-api-key"
 # Base URL 来自系统
 assert config.base_url == "https://system-base-url.example.com/v1"
 # 来源是项目（因为 API Key 来自项目）
 assert config.source == "project"
 finally:
 os.environ.pop("ANTHROPIC_API_KEY", None)
 os.environ.pop("ANTHROPIC_BASE_URL", None)
