"""凭证存储相关测试。
凭证现在与仓库（Repository）关联，而不是项目（Project）。
"""
import pytest
from httpx import AsyncClient
@pytest.mark.asyncio
async def test_create_access_token_credential(client: AsyncClient):
 """测试创建访问令牌凭证。"""
 # 创建仓库（同时创建凭证）
 repository_data = {
 "name": "Token Credential Test Repo",
 "git_url": "https://github.com/test/repo.git",
 "access_token": "GITHUB_TOKEN_PLACEHOLDER",
 "git_user_name": "Test User",
 "git_user_email": "test@example.com",
 }
 repository_response = await client.post("/api/repositories/", json=repository_data)
 assert repository_response.status_code == 201
 data = repository_response.json
 assert data["has_credential"] is True
 repository_id = data["id"]
 # 验证凭证存在
 response = await client.get(f"/api/repositories/{repository_id}/credential")
 assert response.status_code == 200
 cred_data = response.json
 assert cred_data["auth_type"] == "access_token"
 assert cred_data["git_user_name"] == "Test User"
 assert cred_data["git_user_email"] == "test@example.com"
 assert cred_data["repository_id"] == repository_id
@pytest.mark.asyncio
async def test_get_credential(client: AsyncClient):
 """测试获取凭证信息。"""
 # 创建仓库和凭证
 repository_data = {
 "name": "Get Credential Test Repo",
 "git_url": "https://github.com/test/repo2.git",
 "access_token": "GITHUB_TOKEN_PLACEHOLDER",
 "git_user_name": "Test User",
 "git_user_email": "test@example.com",
 }
 repository_response = await client.post("/api/repositories/", json=repository_data)
 repository_id = repository_response.json["id"]
 # 获取凭证
 response = await client.get(f"/api/repositories/{repository_id}/credential")
 assert response.status_code == 200
 data = response.json
 assert data["auth_type"] == "access_token"
 assert "encrypted_token" not in data # 加密的令牌不应返回
@pytest.mark.asyncio
async def test_credential_not_found(client: AsyncClient):
 """测试获取不存在的凭证。"""
 # 获取不存在的仓库凭证应返回 404
 response = await client.get("/api/repositories/nonexistent-id/credential")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_duplicate_credential(client: AsyncClient):
 """测试重复创建凭证。"""
 # 创建仓库和凭证
 repository_data = {
 "name": "Duplicate Credential Test Repo",
 "git_url": "https://github.com/test/repo3.git",
 "access_token": "token1",
 }
 repository_response = await client.post("/api/repositories/", json=repository_data)
 repository_id = repository_response.json["id"]
 # 尝试创建第二个凭证应失败
 response = await client.post(
 f"/api/repositories/{repository_id}/credential/access-token",
 data={"token": "token2"},
 )
 assert response.status_code == 400
@pytest.mark.asyncio
async def test_delete_credential(client: AsyncClient):
 """测试删除凭证。"""
 # 创建仓库和凭证
 repository_data = {
 "name": "Delete Credential Test Repo",
 "git_url": "https://github.com/test/repo4.git",
 "access_token": "token_to_delete",
 }
 repository_response = await client.post("/api/repositories/", json=repository_data)
 repository_id = repository_response.json["id"]
 # 删除凭证
 response = await client.delete(f"/api/repositories/{repository_id}/credential")
 assert response.status_code == 204
 # 验证凭证已删除
 response = await client.get(f"/api/repositories/{repository_id}/credential")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_set_access_token_after_creation(client: AsyncClient):
 """测试在删除凭证后重新设置访问令牌。"""
 # 创建仓库和凭证
 repository_data = {
 "name": "Reset Token Test Repo",
 "git_url": "https://github.com/test/repo5.git",
 "access_token": "initial_token",
 }
 repository_response = await client.post("/api/repositories/", json=repository_data)
 repository_id = repository_response.json["id"]
 # 删除凭证
 await client.delete(f"/api/repositories/{repository_id}/credential")
 # 重新设置凭证
 response = await client.post(
 f"/api/repositories/{repository_id}/credential/access-token",
 data={
 "token": "new_token",
 "git_user_name": "New User",
 "git_user_email": "new@example.com",
 },
 )
 assert response.status_code == 200
 data = response.json
 assert data["auth_type"] == "access_token"
 assert data["git_user_name"] == "New User"
