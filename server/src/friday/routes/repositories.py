"""Repository management routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..models import AuthType, GitCredential, GitCredentialRead
from ..models.repository import (
 GitPlatform,
 ProjectSummary,
 Repository,
 RepositoryRead,
 RepositoryUpdate,
 RepositoryWithProjectsRead,
)
from ..services.crypto import encrypt_value
router = APIRouter(prefix="/api/repositories", tags=["repositories"])
# === 请求模型 ===
class RepositoryCreateWithCredential(BaseModel):
 """创建仓库请求，包含必填的 Access Token 凭证。"""
 # 仓库基本信息
 name: str = Field(description="仓库显示名称")
 git_url: str = Field(description="Git 仓库 URL")
 git_platform: GitPlatform = Field(
 default=GitPlatform.GITHUB,
 description="Git 平台类型",
 )
 default_branch: str = Field(
 default="main",
 description="默认分支名称",
 )
 claude_md_path: str = Field(
 default="developer-notes.md",
 description="仓库中 developer-notes.md 文件的路径",
 )
 description: Optional[str] = Field(
 default=None,
 description="仓库描述",
 )
 # 凭证信息（必填）
 access_token: str = Field(description="Git Access Token（必填）")
 git_user_name: str = Field(
 default="Friday AI Agent",
 description="Git 提交用户名",
 )
 git_user_email: str = Field(
 default="ai-agent@friday.dev",
 description="Git 提交邮箱",
 )
@router.get("/", response_model=List[RepositoryRead])
async def list_repositories(db: AsyncSession = Depends(get_db)):
 """List all repositories."""
 result = await db.exec(
 select(Repository).options(selectinload(Repository.credential)) # type: ignore[arg-type]
 )
 repositories = result.all
 return [
 RepositoryRead(
 id=repo.id,
 name=repo.name,
 git_url=repo.git_url,
 git_platform=repo.git_platform,
 default_branch=repo.default_branch,
 claude_md_path=repo.claude_md_path,
 description=repo.description,
 created_at=repo.created_at,
 updated_at=repo.updated_at,
 has_credential=repo.credential is not None,
 )
 for repo in repositories
 ]
@router.post("/", response_model=RepositoryRead, status_code=201)
async def create_repository(
 data: RepositoryCreateWithCredential,
 db: AsyncSession = Depends(get_db),
):
 """创建仓库，同时创建 Access Token 凭证（凭证必填）。"""
 # 验证 Access Token 不为空
 if not data.access_token.strip:
 raise HTTPException(status_code=400, detail="Access Token 不能为空")
 # 创建仓库
 db_repository = Repository(
 name=data.name,
 git_url=data.git_url,
 git_platform=data.git_platform,
 default_branch=data.default_branch,
 claude_md_path=data.claude_md_path,
 description=data.description,
 )
 db.add(db_repository)
 await db.flush # 刷新以获取仓库 ID
 # 创建凭证
 encrypted_token = encrypt_value(data.access_token)
 credential = GitCredential(
 repository_id=db_repository.id,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypted_token,
 git_user_name=data.git_user_name,
 git_user_email=data.git_user_email,
 )
 db.add(credential)
 await db.commit
 await db.refresh(db_repository)
 return RepositoryRead(
 id=db_repository.id,
 name=db_repository.name,
 git_url=db_repository.git_url,
 git_platform=db_repository.git_platform,
 default_branch=db_repository.default_branch,
 claude_md_path=db_repository.claude_md_path,
 description=db_repository.description,
 created_at=db_repository.created_at,
 updated_at=db_repository.updated_at,
 has_credential=True, # 同时创建了凭证
 )
@router.get("/{repository_id}", response_model=RepositoryWithProjectsRead)
async def get_repository(
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get repository by ID with associated projects."""
 result = await db.exec(
 select(Repository)
 .where(Repository.id == repository_id)
 .options(selectinload(Repository.projects)) # type: ignore[arg-type]
 )
 repository = result.one_or_none
 if not repository:
 raise HTTPException(status_code=404, detail="Repository not found")
 # 检查是否有凭证
 cred_result = await db.exec(
 select(GitCredential).where(GitCredential.repository_id == repository_id)
 )
 has_credential = cred_result.one_or_none is not None
 # 构建项目摘要列表
 project_summaries = [
 ProjectSummary(id=p.id, name=p.name) for p in repository.projects
 ]
 return RepositoryWithProjectsRead(
 id=repository.id,
 name=repository.name,
 git_url=repository.git_url,
 git_platform=repository.git_platform,
 default_branch=repository.default_branch,
 claude_md_path=repository.claude_md_path,
 description=repository.description,
 created_at=repository.created_at,
 updated_at=repository.updated_at,
 has_credential=has_credential,
 projects=project_summaries,
 )
@router.patch("/{repository_id}", response_model=RepositoryRead)
async def update_repository(
 repository_id: str,
 repository_update: RepositoryUpdate,
 db: AsyncSession = Depends(get_db),
):
 """Update repository."""
 result = await db.exec(select(Repository).where(Repository.id == repository_id))
 repository = result.one_or_none
 if not repository:
 raise HTTPException(status_code=404, detail="Repository not found")
 update_data = repository_update.model_dump(exclude_unset=True)
 for key, value in update_data.items:
 setattr(repository, key, value)
 db.add(repository)
 await db.commit
 await db.refresh(repository)
 return repository
@router.delete("/{repository_id}", status_code=204)
async def delete_repository(
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Delete repository."""
 result = await db.exec(select(Repository).where(Repository.id == repository_id))
 repository = result.one_or_none
 if not repository:
 raise HTTPException(status_code=404, detail="Repository not found")
 await db.delete(repository)
 await db.commit
# === Git Credential Management ===
@router.get("/{repository_id}/credential", response_model=GitCredentialRead)
async def get_credential(
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get Git credential for the repository."""
 result = await db.exec(
 select(GitCredential).where(GitCredential.repository_id == repository_id)
 )
 credential = result.one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="Credential not found")
 return GitCredentialRead(
 id=credential.id,
 repository_id=credential.repository_id,
 auth_type=credential.auth_type,
 git_user_name=credential.git_user_name,
 git_user_email=credential.git_user_email,
 created_at=credential.created_at,
 has_ssh_key=credential.ssh_key_encrypted is not None,
 has_access_token=credential.encrypted_token is not None,
 )
@router.post(
 "/{repository_id}/credential/access-token", response_model=GitCredentialRead
)
async def set_access_token(
 repository_id: str,
 token: str = Form(..., description="Git Access Token"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """Set Git access token for the repository."""
 # Verify repository exists
 result = await db.exec(select(Repository).where(Repository.id == repository_id))
 repository = result.one_or_none
 if not repository:
 raise HTTPException(status_code=404, detail="Repository not found")
 # Check if credential already exists
 cred_result = await db.exec(
 select(GitCredential).where(GitCredential.repository_id == repository_id)
 )
 existing = cred_result.one_or_none
 if existing:
 raise HTTPException(
 status_code=400,
 detail="Credential already exists. Please delete the existing one first.",
 )
 # Encrypt and store token
 encrypted = encrypt_value(token)
 credential = GitCredential(
 repository_id=repository_id,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypted,
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 db.add(credential)
 await db.commit
 await db.refresh(credential)
 return GitCredentialRead(
 id=credential.id,
 repository_id=credential.repository_id,
 auth_type=credential.auth_type,
 git_user_name=credential.git_user_name,
 git_user_email=credential.git_user_email,
 created_at=credential.created_at,
 has_ssh_key=credential.ssh_key_encrypted is not None,
 has_access_token=credential.encrypted_token is not None,
 )
@router.delete("/{repository_id}/credential", status_code=204)
async def delete_credential(
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Delete Git credential for the repository."""
 result = await db.exec(
 select(GitCredential).where(GitCredential.repository_id == repository_id)
 )
 credential = result.one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="Credential not found")
 await db.delete(credential)
 await db.commit
 return None
