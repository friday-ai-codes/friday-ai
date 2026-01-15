"""凭证存储相关测试。"""
import pytest
from httpx import AsyncClient
@pytest.mark.asyncio
async def test_create_access_token_credential(client: AsyncClient):
 """测试创建访问令牌凭证。"""
 # 创建项目
 project_data = {
 "name": "Token Credential Test",
 "repo_url": "https://github.com/test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 assert project_response.status_code == 201
 project_id = project_response.json["id"]
 # 创建访问令牌凭证
 response = await client.post(
 f"/api/projects/{project_id}/credential/access-token",
 data={
 "token": "GITHUB_TOKEN_PLACEHOLDER",
 "git_user_name": "Test User",
 "git_user_email": "test@example.com",
 },
 )
 assert response.status_code == 200
 data = response.json
 assert data["auth_type"] == "access_token"
 assert data["git_user_name"] == "Test User"
 assert data["git_user_email"] == "test@example.com"
 assert data["project_id"] == project_id
@pytest.mark.asyncio
async def test_get_credential(client: AsyncClient):
 """测试获取凭证信息。"""
 # 创建项目和凭证
 project_data = {
 "name": "Get Credential Test",
 "repo_url": "https://github.com/test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 project_id = project_response.json["id"]
 await client.post(
 f"/api/projects/{project_id}/credential/access-token",
 data={
 "token": "GITHUB_TOKEN_PLACEHOLDER",
 "git_user_name": "Test User",
 "git_user_email": "test@example.com",
 },
 )
 # 获取凭证
 response = await client.get(f"/api/projects/{project_id}/credential")
 assert response.status_code == 200
 data = response.json
 assert data["auth_type"] == "access_token"
 assert "encrypted_token" not in data # 加密的令牌不应返回
@pytest.mark.asyncio
async def test_credential_not_found(client: AsyncClient):
 """测试获取不存在的凭证。"""
 # 创建项目但不创建凭证
 project_data = {
 "name": "No Credential Project",
 "repo_url": "https://github.com/test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 project_id = project_response.json["id"]
 # 获取凭证应返回 404
 response = await client.get(f"/api/projects/{project_id}/credential")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_duplicate_credential(client: AsyncClient):
 """测试重复创建凭证。"""
 # 创建项目和凭证
 project_data = {
 "name": "Duplicate Credential Test",
 "repo_url": "https://github.com/test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 project_id = project_response.json["id"]
 # 创建第一个凭证
 response = await client.post(
 f"/api/projects/{project_id}/credential/access-token",
 data={"token": "token1"},
 )
 assert response.status_code == 200
 # 尝试创建第二个凭证应失败
 response = await client.post(
 f"/api/projects/{project_id}/credential/access-token",
 data={"token": "token2"},
 )
 assert response.status_code == 400
@pytest.mark.asyncio
async def test_delete_credential(client: AsyncClient):
 """测试删除凭证。"""
 # 创建项目和凭证
 project_data = {
 "name": "Delete Credential Test",
 "repo_url": "https://github.com/test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 project_id = project_response.json["id"]
 await client.post(
 f"/api/projects/{project_id}/credential/access-token",
 data={"token": "token_to_delete"},
 )
 # 删除凭证
 response = await client.delete(f"/api/projects/{project_id}/credential")
 assert response.status_code == 204
 # 验证凭证已删除
 response = await client.get(f"/api/projects/{project_id}/credential")
 assert response.status_code == 404
@pytest.mark.asyncio
async def test_ssh_key_credential(client: AsyncClient):
 """测试上传 SSH 密钥凭证。"""
 # 创建项目
 project_data = {
 "name": "SSH Key Test",
 "repo_url": "git@github.com:test/repo.git",
 }
 project_response = await client.post("/api/projects/", json=project_data)
 project_id = project_response.json["id"]
 # 创建一个模拟的 SSH 私钥文件
 ssh_key_content = b"""-----BEGIN REDACTED TEST KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACBZJ5O5RBxz9U+Xk1z1VkZmZ2p1a25hbmVAZXhhbXBsZS5jb20AAAAJdGVz
dC1rZXk=
-----END REDACTED TEST KEY-----
"""
 # 上传 SSH 密钥
 response = await client.post(
 f"/api/projects/{project_id}/credential/ssh-key",
 files={"file": ("id_rsa", ssh_key_content, "application/octet-stream")},
 data={
 "git_user_name": "SSH User",
 "git_user_email": "ssh@example.com",
 },
 )
 assert response.status_code == 200
 data = response.json
 assert data["auth_type"] == "ssh_key"
 assert data["git_user_name"] == "SSH User"
