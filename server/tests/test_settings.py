"""系统设置 API 测试。
使用 pytest + pytest-django 风格，提供更好的表达力和可维护性。
"""
import pytest
from rest_framework import status
# ============================================================================
# 系统设置列表和创建测试
# ============================================================================
@pytest.mark.django_db
class TestSettingsListCreate:
 """系统设置列表和创建接口测试。"""
 def test_list_settings_returns_list(self, authenticated_client, urls):
 """测试列出系统设置返回列表。"""
 response = authenticated_client.get(urls.settings_list)
 assert response.status_code == status.HTTP_200_OK
 assert isinstance(response.data, list)
 def test_create_setting(self, authenticated_client, urls):
 """测试创建系统设置。"""
 setting_data = {
 "key": "test_setting",
 "value": "test_value",
 "description": "测试设置描述",
 "is_encrypted": False,
 }
 response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["key"] == "test_setting"
 assert response.data["has_value"] is True
 assert response.data["is_encrypted"] is False
 assert response.data["description"] == "测试设置描述"
 def test_create_encrypted_setting(self, authenticated_client, urls):
 """测试创建加密的系统设置。"""
 setting_data = {
 "key": "anthropic_api_key",
 "value": "sk-ant-test-key-12345",
 "description": "Anthropic API Key",
 "is_encrypted": True,
 }
 response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert response.status_code == status.HTTP_201_CREATED
 assert response.data["key"] == "anthropic_api_key"
 assert response.data["has_value"] is True
 assert response.data["is_encrypted"] is True
 def test_create_duplicate_setting(self, authenticated_client, urls):
 """测试创建重复的设置键返回错误。"""
 setting_data = {
 "key": "duplicate_test",
 "value": "first_value",
 "is_encrypted": False,
 }
 # 创建第一个
 response1 = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert response1.status_code == status.HTTP_201_CREATED
 # 尝试创建重复的
 response2 = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert response2.status_code == status.HTTP_400_BAD_REQUEST
# ============================================================================
# 系统设置详情测试
# ============================================================================
@pytest.mark.django_db
class TestSettingsDetail:
 """系统设置详情接口测试。"""
 def test_get_setting(self, authenticated_client, urls):
 """测试获取单个系统设置。"""
 # 先创建
 setting_data = {
 "key": "get_test_setting",
 "value": "get_test_value",
 "is_encrypted": False,
 }
 create_response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert create_response.status_code == status.HTTP_201_CREATED
 # 获取
 response = authenticated_client.get(urls.settings_detail("get_test_setting"))
 assert response.status_code == status.HTTP_200_OK
 assert response.data["key"] == "get_test_setting"
 assert response.data["has_value"] is True
 def test_get_nonexistent_setting(self, authenticated_client, urls):
 """测试获取不存在的系统设置。"""
 response = authenticated_client.get(urls.settings_detail("nonexistent_key"))
 assert response.status_code == status.HTTP_404_NOT_FOUND
 def test_update_setting(self, authenticated_client, urls):
 """测试更新系统设置。"""
 # 先创建
 setting_data = {
 "key": "update_test_setting",
 "value": "original_value",
 "is_encrypted": False,
 }
 create_response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert create_response.status_code == status.HTTP_201_CREATED
 # 更新
 update_data = {
 "value": "updated_value",
 "description": "新描述",
 }
 response = authenticated_client.put(
 urls.settings_detail("update_test_setting"), update_data, format="json"
 )
 assert response.status_code == status.HTTP_200_OK
 assert response.data["key"] == "update_test_setting"
 assert response.data["description"] == "新描述"
 def test_delete_setting(self, authenticated_client, urls):
 """测试删除系统设置。"""
 # 先创建
 setting_data = {
 "key": "delete_test_setting",
 "value": "to_be_deleted",
 "is_encrypted": False,
 }
 create_response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert create_response.status_code == status.HTTP_201_CREATED
 # 删除
 response = authenticated_client.delete(urls.settings_detail("delete_test_setting"))
 assert response.status_code == status.HTTP_204_NO_CONTENT
 # 确认已删除
 get_response = authenticated_client.get(urls.settings_detail("delete_test_setting"))
 assert get_response.status_code == status.HTTP_404_NOT_FOUND
 def test_delete_nonexistent_setting(self, authenticated_client, urls):
 """测试删除不存在的系统设置。"""
 response = authenticated_client.delete(urls.settings_detail("nonexistent_key"))
 assert response.status_code == status.HTTP_404_NOT_FOUND
# ============================================================================
# 加密设置测试
# ============================================================================
@pytest.mark.django_db
class TestSettingsEncryption:
 """加密设置测试。"""
 def test_encrypted_setting_masked_in_list(self, authenticated_client, urls):
 """测试加密设置在列表中返回遮罩值。"""
 # 创建加密设置
 setting_data = {
 "key": "masked_api_key",
 "value": "sk-test-placeholder",
 "is_encrypted": True,
 }
 response = authenticated_client.post(urls.settings_list, setting_data, format="json")
 assert response.status_code == status.HTTP_201_CREATED
 # 列出设置，检查遮罩值
 list_response = authenticated_client.get(urls.settings_list)
 assert list_response.status_code == status.HTTP_200_OK
 masked_setting = next((s for s in list_response.data if s["key"] == "masked_api_key"), None)
 assert masked_setting is not None
 assert masked_setting["has_value"] is True
 assert masked_setting["is_encrypted"] is True
 # 加密设置返回遮罩值
 assert masked_setting.get("masked_value") is not None or masked_setting.get("value") is None
