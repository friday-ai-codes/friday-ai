"""系统设置 API 测试。"""
import pytest
from httpx import AsyncClient
@pytest.mark.asyncio
async def test_list_settings_returns_list(client: AsyncClient):
 """测试列出系统设置返回列表。"""
 response = await client.get("/api/settings/")
 assert response.status_code == 200
 data = response.json
 assert isinstance(data, list)
 # 列表可能为空或包含其他测试创建的项目
@pytest.mark.asyncio
async def test_create_setting(client: AsyncClient):
 """测试创建系统设置。"""
 setting_data = {
 "key": "test_setting",
 "value": "test_value",
 "description": "测试设置描述",
 "is_encrypted": False,
 }
 response = await client.post("/api/settings/", json=setting_data)
 assert response.status_code == 201
 data = response.json
 assert data["key"] == "test_setting"
 assert data["has_value"] is True
 assert data["is_encrypted"] is False
 assert data["description"] == "测试设置描述"
@pytest.mark.asyncio
async def test_create_encrypted_setting(client: AsyncClient):
 """测试创建加密的系统设置。"""
 setting_data = {
 "key": "anthropic_api_key",
 "value": "sk-ant-test-key-12345",
 "description": "Anthropic API Key",
 "is_encrypted": True,
 }
 response = await client.post("/api/settings/", json=setting_data)
 assert response.status_code == 201
 data = response.json
 assert data["key"] == "anthropic_api_key"
 assert data["has_value"] is True
 assert data["is_encrypted"] is True
@pytest.mark.asyncio
async def test_get_setting(client: AsyncClient):
 """测试获取单个系统设置。"""
 # 先创建
 setting_data = {
 "key": "get_test_setting",
 "value": "get_test_value",
 "is_encrypted": False,
 }
 create_response = await client.post("/api/settings/", json=setting_data)
 assert create_response.status_code == 201
 # 获取
 response = await client.get("/api/settings/get_test_setting")
 assert response.status_code == 200
 data = response.json
 assert data["key"] == "get_test_setting"
 assert data["has_value"] is True
@pytest.mark.asyncio
async def test_get_nonexistent_setting(client: AsyncClient):
 """测试获取不存在的系统设置。"""
 response = await client.get("/api/settings/nonexistent_key")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_update_setting(client: AsyncClient):
 """测试更新系统设置。"""
 # 先创建
 setting_data = {
 "key": "update_test_setting",
 "value": "original_value",
 "is_encrypted": False,
 }
 create_response = await client.post("/api/settings/", json=setting_data)
 assert create_response.status_code == 201
 # 更新
 update_data = {
 "value": "updated_value",
 "description": "新描述",
 }
 response = await client.put("/api/settings/update_test_setting", json=update_data)
 assert response.status_code == 200
 data = response.json
 assert data["key"] == "update_test_setting"
 assert data["description"] == "新描述"
@pytest.mark.asyncio
async def test_update_creates_setting_if_not_exists(client: AsyncClient):
 """测试 PUT 方法可以创建不存在的设置。"""
 update_data = {
 "value": "new_value",
 "description": "动态创建的设置",
 }
 response = await client.put("/api/settings/new_created_setting", json=update_data)
 assert response.status_code == 200
 data = response.json
 assert data["key"] == "new_created_setting"
 assert data["has_value"] is True
@pytest.mark.asyncio
async def test_delete_setting(client: AsyncClient):
 """测试删除系统设置。"""
 # 先创建
 setting_data = {
 "key": "delete_test_setting",
 "value": "to_be_deleted",
 "is_encrypted": False,
 }
 create_response = await client.post("/api/settings/", json=setting_data)
 assert create_response.status_code == 201
 # 删除
 response = await client.delete("/api/settings/delete_test_setting")
 assert response.status_code == 204
 # 确认已删除
 get_response = await client.get("/api/settings/delete_test_setting")
 assert get_response.status_code == 404
@pytest.mark.asyncio
async def test_delete_nonexistent_setting(client: AsyncClient):
 """测试删除不存在的系统设置。"""
 response = await client.delete("/api/settings/nonexistent_key")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_create_duplicate_setting(client: AsyncClient):
 """测试创建重复的设置键返回错误。"""
 setting_data = {
 "key": "duplicate_test",
 "value": "first_value",
 "is_encrypted": False,
 }
 # 创建第一个
 response1 = await client.post("/api/settings/", json=setting_data)
 assert response1.status_code == 201
 # 尝试创建重复的
 response2 = await client.post("/api/settings/", json=setting_data)
 assert response2.status_code == 409
@pytest.mark.asyncio
async def test_list_settings_with_items(client: AsyncClient):
 """测试列出系统设置包含已创建的项目。"""
 # 创建几个设置
 settings = [
 {"key": "list_test_1", "value": "value1", "is_encrypted": False},
 {"key": "list_test_2", "value": "value2", "is_encrypted": False},
 ]
 for s in settings:
 response = await client.post("/api/settings/", json=s)
 assert response.status_code == 201
 # 列出
 response = await client.get("/api/settings/")
 assert response.status_code == 200
 data = response.json
 assert len(data) >= 2
 keys = [item["key"] for item in data]
 assert "list_test_1" in keys
 assert "list_test_2" in keys
@pytest.mark.asyncio
async def test_encrypted_setting_masked_in_list(client: AsyncClient):
 """测试加密设置在列表中返回遮罩值。"""
 # 创建加密设置
 setting_data = {
 "key": "masked_api_key",
 "value": "sk-test-placeholder",
 "is_encrypted": True,
 }
 response = await client.post("/api/settings/", json=setting_data)
 assert response.status_code == 201
 # 列出设置，检查遮罩值
 list_response = await client.get("/api/settings/")
 assert list_response.status_code == 200
 data = list_response.json
 masked_setting = next((s for s in data if s["key"] == "masked_api_key"), None)
 assert masked_setting is not None
 assert masked_setting["has_value"] is True
 assert masked_setting["is_encrypted"] is True
 assert masked_setting["value"] is None # 加密设置不返回实际值
 assert masked_setting["masked_value"] is not None # 但返回遮罩值
 # 遮罩格式：前4位 + 星号 + 后4位
 assert masked_setting["masked_value"].startswith("sk-t")
 assert masked_setting["masked_value"].endswith("cdef")
