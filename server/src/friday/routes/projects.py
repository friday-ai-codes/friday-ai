"""Project management API routes."""
import shutil
from datetime import datetime
from pathlib import Path
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import (
 AuthType,
 GitCredential,
 GitCredentialCreate,
 GitCredentialRead,
 Project,
 ProjectCreate,
 ProjectRead,
 ProjectUpdate,
)
from ..services.crypto import encrypt_value
settings = get_settings
router = APIRouter(prefix="/api/projects", tags=["projects"])
@router.get("/", response_model=List[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
 """List all projects."""
 result = await db.execute(select(Project))
 projects = result.scalars.all
 response =
 for p in projects:
 # Check if credential exists
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == p.id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 response.append(
 ProjectRead(
 **p.model_dump,
 has_credential=has_cred,
 )
 )
 return response
@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
 project: ProjectCreate,
 db: AsyncSession = Depends(get_db),
):
 """Create a new project."""
 db_project = Project.model_validate(project)
 db.add(db_project)
 await db.commit
 await db.refresh(db_project)
 return ProjectRead(**db_project.model_dump, has_credential=False)
@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get a project by ID."""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Check credential
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 return ProjectRead(**project.model_dump, has_credential=has_cred)
@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
 project_id: str,
 project_update: ProjectUpdate,
 db: AsyncSession = Depends(get_db),
):
 """Update a project."""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 update_data = project_update.model_dump(exclude_unset=True)
 for key, value in update_data.items:
 setattr(project, key, value)
 project.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(project)
 # Check credential
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 return ProjectRead(**project.model_dump, has_credential=has_cred)
@router.delete("/{project_id}", status_code=204)
async def delete_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Delete a project and its credential."""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Delete credential if exists
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = cred_result.scalar_one_or_none
 if credential:
 # Delete SSH key file if exists
 if credential.ssh_key_path:
 key_path = Path(credential.ssh_key_path)
 if key_path.exists:
 key_path.unlink
 await db.delete(credential)
 await db.delete(project)
 await db.commit
 return None
# Credential Management
@router.get("/{project_id}/credential", response_model=GitCredentialRead)
async def get_credential(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Get credential for a project."""
 result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = result.scalar_one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="Credential not found")
 return GitCredentialRead(
 id=credential.id,
 project_id=credential.project_id,
 auth_type=credential.auth_type,
 git_user_name=credential.git_user_name,
 git_user_email=credential.git_user_email,
 created_at=credential.created_at,
 )
@router.post("/{project_id}/credential/ssh-key", response_model=GitCredentialRead)
async def upload_ssh_key(
 project_id: str,
 file: UploadFile = File(..., description="SSH private key file"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """Upload SSH private key for a project."""
 # Verify project exists
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Check if credential already exists
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 existing = cred_result.scalar_one_or_none
 if existing:
 raise HTTPException(
 status_code=400,
 detail="Credential already exists. Delete it first.",
 )
 # Save SSH key file
 cred_dir = settings.DATA_DIR / "credentials" / project_id
 cred_dir.mkdir(parents=True, exist_ok=True)
 key_path = cred_dir / "id_rsa"
 content = await file.read
 key_path.write_bytes(content)
 key_path.chmod(0o600) # Secure permissions
 # Create credential record
 credential = GitCredential(
 project_id=project_id,
 auth_type=AuthType.SSH_KEY,
 ssh_key_path=str(key_path),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 db.add(credential)
 await db.commit
 await db.refresh(credential)
 return GitCredentialRead(
 id=credential.id,
 project_id=credential.project_id,
 auth_type=credential.auth_type,
 git_user_name=credential.git_user_name,
 git_user_email=credential.git_user_email,
 created_at=credential.created_at,
 )
@router.post("/{project_id}/credential/access-token", response_model=GitCredentialRead)
async def set_access_token(
 project_id: str,
 token: str = Form(..., description="Git access token"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """Set access token for a project."""
 # Verify project exists
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="Project not found")
 # Check if credential already exists
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 existing = cred_result.scalar_one_or_none
 if existing:
 raise HTTPException(
 status_code=400,
 detail="Credential already exists. Delete it first.",
 )
 # Encrypt and store token
 encrypted = encrypt_value(token)
 credential = GitCredential(
 project_id=project_id,
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
 project_id=credential.project_id,
 auth_type=credential.auth_type,
 git_user_name=credential.git_user_name,
 git_user_email=credential.git_user_email,
 created_at=credential.created_at,
 )
@router.delete("/{project_id}/credential", status_code=204)
async def delete_credential(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """Delete credential for a project."""
 result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = result.scalar_one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="Credential not found")
 # Delete SSH key file if exists
 if credential.ssh_key_path:
 key_path = Path(credential.ssh_key_path)
 if key_path.exists:
 key_path.unlink
 # Remove directory if empty
 cred_dir = key_path.parent
 if cred_dir.exists and not list(cred_dir.iterdir):
 cred_dir.rmdir
 await db.delete(credential)
 await db.commit
 return None