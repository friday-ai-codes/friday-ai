"""项目管理 API 路由。"""
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
 FeishuConfigCreate,
 FeishuConfigRead,
 FeishuConfigTestResult,
 GitCredential,
 GitCredentialRead,
 Project,
 ProjectCreate,
 ProjectRead,
 ProjectUpdate,
)
from ..services.crypto import decrypt_value, encrypt_value
from ..services.feishu import FeishuClient
settings = get_settings
router = APIRouter(prefix="/api/projects", tags=["projects"])
# === 项目 CRUD ===
@router.get("/", response_model=List[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
 """列出所有项目。"""
 result = await db.execute(select(Project))
 projects = result.scalars.all
 response =
 for p in projects:
 # 检查凭证是否存在
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == p.id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 response.append(
 ProjectRead(
 **p.model_dump(
 exclude={"feishu_plugin_secret_encrypted", "feishu_webhook_token"}
 ),
 has_credential=has_cred,
 has_feishu_config=p.has_feishu_config,
 )
 )
 return response
@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
 project: ProjectCreate,
 db: AsyncSession = Depends(get_db),
):
 """创建新项目。"""
 db_project = Project.model_validate(project)
 db.add(db_project)
 await db.commit
 await db.refresh(db_project)
 return ProjectRead(
 **db_project.model_dump(
 exclude={"feishu_plugin_secret_encrypted", "feishu_webhook_token"}
 ),
 has_credential=False,
 has_feishu_config=False,
 )
@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """根据 ID 获取项目。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 检查凭证
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 return ProjectRead(
 **project.model_dump(
 exclude={"feishu_plugin_secret_encrypted", "feishu_webhook_token"}
 ),
 has_credential=has_cred,
 has_feishu_config=project.has_feishu_config,
 )
@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
 project_id: str,
 project_update: ProjectUpdate,
 db: AsyncSession = Depends(get_db),
):
 """更新项目。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 update_data = project_update.model_dump(exclude_unset=True)
 for key, value in update_data.items:
 setattr(project, key, value)
 project.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(project)
 # 检查凭证
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 has_cred = cred_result.scalar_one_or_none is not None
 return ProjectRead(
 **project.model_dump(
 exclude={"feishu_plugin_secret_encrypted", "feishu_webhook_token"}
 ),
 has_credential=has_cred,
 has_feishu_config=project.has_feishu_config,
 )
@router.delete("/{project_id}", status_code=204)
async def delete_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """删除项目及其凭证。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 删除凭证（如果存在）
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = cred_result.scalar_one_or_none
 if credential:
 # 删除 SSH 密钥文件（如果存在）
 if credential.ssh_key_path:
 key_path = Path(credential.ssh_key_path)
 if key_path.exists:
 key_path.unlink
 await db.delete(credential)
 await db.delete(project)
 await db.commit
 return None
# === Git 凭证管理 ===
@router.get("/{project_id}/credential", response_model=GitCredentialRead)
async def get_credential(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """获取项目的 Git 凭证。"""
 result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = result.scalar_one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="凭证未找到")
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
 file: UploadFile = File(..., description="SSH 私钥文件"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """上传项目的 SSH 私钥。"""
 # 验证项目存在
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 检查凭证是否已存在
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 existing = cred_result.scalar_one_or_none
 if existing:
 raise HTTPException(
 status_code=400,
 detail="凭证已存在，请先删除现有凭证。",
 )
 # 保存 SSH 密钥文件
 cred_dir = settings.DATA_DIR / "credentials" / project_id
 cred_dir.mkdir(parents=True, exist_ok=True)
 key_path = cred_dir / "id_rsa"
 content = await file.read
 key_path.write_bytes(content)
 key_path.chmod(0o600) # 设置安全权限
 # 创建凭证记录
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
 token: str = Form(..., description="Git 访问令牌"),
 git_user_name: str = Form(default="Friday AI Agent"),
 git_user_email: str = Form(default="ai-agent@friday.dev"),
 db: AsyncSession = Depends(get_db),
):
 """设置项目的 Git 访问令牌。"""
 # 验证项目存在
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 检查凭证是否已存在
 cred_result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 existing = cred_result.scalar_one_or_none
 if existing:
 raise HTTPException(
 status_code=400,
 detail="凭证已存在，请先删除现有凭证。",
 )
 # 加密并存储令牌
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
 """删除项目的 Git 凭证。"""
 result = await db.execute(
 select(GitCredential).where(GitCredential.project_id == project_id)
 )
 credential = result.scalar_one_or_none
 if not credential:
 raise HTTPException(status_code=404, detail="凭证未找到")
 # 删除 SSH 密钥文件（如果存在）
 if credential.ssh_key_path:
 key_path = Path(credential.ssh_key_path)
 if key_path.exists:
 key_path.unlink
 # 如果目录为空则删除
 cred_dir = key_path.parent
 if cred_dir.exists and not list(cred_dir.iterdir):
 cred_dir.rmdir
 await db.delete(credential)
 await db.commit
 return None
# === 飞书配置管理 ===
@router.get("/{project_id}/feishu-config", response_model=FeishuConfigRead)
async def get_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """获取项目的飞书配置（不返回敏感信息）。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 return FeishuConfigRead(
 project_key=project.feishu_project_key,
 plugin_id=project.feishu_plugin_id,
 has_plugin_secret=bool(project.feishu_plugin_secret_encrypted),
 has_webhook_token=bool(project.feishu_webhook_token),
 is_configured=project.has_feishu_config,
 )
@router.put("/{project_id}/feishu-config", response_model=FeishuConfigRead)
async def set_feishu_config(
 project_id: str,
 config: FeishuConfigCreate,
 db: AsyncSession = Depends(get_db),
):
 """设置项目的飞书配置。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 加密敏感信息
 project.feishu_plugin_id = config.plugin_id
 project.feishu_plugin_secret_encrypted = encrypt_value(config.plugin_secret)
 if config.webhook_token:
 project.feishu_webhook_token = config.webhook_token
 project.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(project)
 return FeishuConfigRead(
 project_key=project.feishu_project_key,
 plugin_id=project.feishu_plugin_id,
 has_plugin_secret=bool(project.feishu_plugin_secret_encrypted),
 has_webhook_token=bool(project.feishu_webhook_token),
 is_configured=project.has_feishu_config,
 )
@router.delete("/{project_id}/feishu-config", status_code=204)
async def delete_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """删除项目的飞书配置。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 清除飞书配置
 project.feishu_plugin_id = None
 project.feishu_plugin_secret_encrypted = None
 project.feishu_webhook_token = None
 project.updated_at = datetime.utcnow
 await db.commit
 return None
@router.post("/{project_id}/feishu-config/test", response_model=FeishuConfigTestResult)
async def test_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """测试项目的飞书配置是否有效。"""
 result = await db.execute(select(Project).where(Project.id == project_id))
 project = result.scalar_one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 if not project.has_feishu_config:
 return FeishuConfigTestResult(
 success=False,
 message="飞书配置不完整，请先完成配置",
 plugin_token_valid=False,
 project_accessible=False,
 )
 try:
 # 解密并创建客户端
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 client = FeishuClient(
 plugin_id=project.feishu_plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 )
 # 执行测试
 test_result = await client.test_connection(project.feishu_project_key)
 return FeishuConfigTestResult(
 success=test_result["success"],
 message=test_result["message"],
 plugin_token_valid=test_result["plugin_token_valid"],
 project_accessible=test_result["project_accessible"],
 )
 except Exception as e:
 return FeishuConfigTestResult(
 success=False,
 message=f"测试失败: {str(e)}",
 plugin_token_valid=False,
 project_accessible=False,
 )
