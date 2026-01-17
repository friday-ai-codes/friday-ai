"""项目 Claude 配置 API 测试。"""
import pytest
from httpx import AsyncClient
async def create_test_project(
 client: AsyncClient, name: str = "Claude Config Test"
) -> str:
 """辅助函数：创建测试项目。"""
 project_data = {
 "name": name,
 "repo_url": "https://github.com/test/repo.git",
 }
 response = await client.post("/api/projects/", json=project_data)
 assert response.status_code == 201
 return response.json["id"]
@pytest.mark.asyncio
async def test_get_claude_config_default(client: AsyncClient):
 """测试获取项目的默认 Claude 配置。"""
 project_id = await create_test_project(client, "Get Claude Config Default")
 response = await client.get(f"/api/projects/{project_id}/claude-config")
 assert response.status_code == 200
 data = response.json
 assert data["has_api_key"] is False
 assert data["base_url"] is None
 # 没有项目级 API Key，使用系统或环境变量来源
 assert data["source"] in ["system", "environment"]
@pytest.mark.asyncio
async def test_set_claude_config_api_key(client: AsyncClient):
 """测试设置项目的 Claude API Key。"""
 project_id = await create_test_project(client, "Set Claude API Key")
 config_data = {
 "api_key": "sk-ant-test-key-12345",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 data = response.json
 assert data["has_api_key"] is True
 assert data["source"] == "project"
@pytest.mark.asyncio
async def test_set_claude_config_base_url(client: AsyncClient):
 """测试设置项目的 Claude Base URL。"""
 project_id = await create_test_project(client, "Set Claude Base URL")
 config_data = {
 "base_url": "https://proxy.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 data = response.json
 assert data["base_url"] == "https://proxy.example.com/v1"
@pytest.mark.asyncio
async def test_set_claude_config_both(client: AsyncClient):
 """测试同时设置 API Key 和 Base URL。"""
 project_id = await create_test_project(client, "Set Both Config")
 config_data = {
 "api_key": "sk-ant-test-key-full",
 "base_url": "https://proxy.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 data = response.json
 assert data["has_api_key"] is True
 assert data["base_url"] == "https://proxy.example.com/v1"
 assert data["source"] == "project"
@pytest.mark.asyncio
async def test_update_claude_config(client: AsyncClient):
 """测试更新项目的 Claude 配置。"""
 project_id = await create_test_project(client, "Update Claude Config")
 # 初始设置
 config_data = {
 "api_key": "sk-ant-original-key",
 "base_url": "https://original.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 # 只更新 base_url
 update_data = {
 "base_url": "https://updated.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=update_data
 )
 assert response.status_code == 200
 data = response.json
 assert data["has_api_key"] is True # API Key 保持不变
 assert data["base_url"] == "https://updated.example.com/v1"
@pytest.mark.asyncio
async def test_clear_claude_api_key(client: AsyncClient):
 """测试清除项目的 Claude API Key（使用空字符串）。"""
 project_id = await create_test_project(client, "Clear Claude API Key")
 # 先设置
 config_data = {
 "api_key": "sk-ant-to-be-cleared",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 assert response.json["has_api_key"] is True
 # 清除（使用空字符串）
 clear_data = {
 "api_key": "",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=clear_data
 )
 assert response.status_code == 200
 assert response.json["has_api_key"] is False
@pytest.mark.asyncio
async def test_delete_claude_config(client: AsyncClient):
 """测试删除项目的全部 Claude 配置。"""
 project_id = await create_test_project(client, "Delete Claude Config")
 # 先设置
 config_data = {
 "api_key": "sk-ant-to-be-deleted",
 "base_url": "https://delete.example.com/v1",
 }
 response = await client.put(
 f"/api/projects/{project_id}/claude-config", json=config_data
 )
 assert response.status_code == 200
 # 删除
 response = await client.delete(f"/api/projects/{project_id}/claude-config")
 assert response.status_code == 204
 # 确认已删除
 response = await client.get(f"/api/projects/{project_id}/claude-config")
 assert response.status_code == 200
 data = response.json
 assert data["has_api_key"] is False
 assert data["base_url"] is None
@pytest.mark.asyncio
async def test_get_claude_config_nonexistent_project(client: AsyncClient):
 """测试获取不存在项目的 Claude 配置。"""
 response = await client.get("/api/projects/nonexistent-id/claude-config")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_set_claude_config_nonexistent_project(client: AsyncClient):
 """测试设置不存在项目的 Claude 配置。"""
 config_data = {
 "api_key": "sk-ant-test",
 }
 response = await client.put(
 "/api/projects/nonexistent-id/claude-config", json=config_data
 )
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_delete_claude_config_nonexistent_project(client: AsyncClient):
 """测试删除不存在项目的 Claude 配置。"""
 response = await client.delete("/api/projects/nonexistent-id/claude-config")
 assert response.status_code == 404
