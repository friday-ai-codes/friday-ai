"""Repository management routes."""
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..models import AuthType, GitCredential, GitCredentialRead
from ..models.repository import (
 ProjectSummary,
 Repository,
 RepositoryCreate,
 RepositoryRead,
 RepositoryUpdate,
 RepositoryWithProjectsRead,
)
from ..services.crypto import encrypt_value
router = APIRouter(prefix="/api/repositories", tags=["repositories"])
@router.get("/", response_model=List[RepositoryRead])
async def list_repositories(db: AsyncSession = Depends(get_db)):
 """List all repositories."""
 result = await db.exec(select(Repository))
 return result.all
@router.post("/", response_model=RepositoryRead, status_code=201)
async def create_repository(
 repository: RepositoryCreate,
 db: AsyncSession = Depends(get_db),
):
 """Create a new repository."""
 db_repository = Repository.model_validate(repository)
 db.add(db_repository)
 await db.commit
 await db.refresh(db_repository)
 return db_repository
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
 )
@router.post("/{repository_id}/credential/ssh-key", response_model=GitCredentialRead)
async def upload_ssh_key(
 repository_id: str,
 file: UploadFile = File(..., description="SSH Private Key File"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """Upload SSH private key for the repository."""
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
 # Read and encrypt SSH key content
 content = await file.read
 ssh_key_content = content.decode("utf-8")
 encrypted_ssh_key = encrypt_value(ssh_key_content)
 # Create credential record
 credential = GitCredential(
 repository_id=repository_id,
 auth_type=AuthType.SSH_KEY,
 ssh_key_encrypted=encrypted_ssh_key,
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
