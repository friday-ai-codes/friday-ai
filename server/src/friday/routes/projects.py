"""项目管理 API 路由。"""
from datetime import UTC, datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import (
 ClaudeConfigCreate,
 ClaudeConfigRead,
 FeishuConfigCreate,
 FeishuConfigRead,
 FeishuConfigTest,
 FeishuConfigTestResult,
 Project,
 ProjectCreate,
 ProjectRead,
 ProjectUpdate,
 WebhookTokenRead,
 WebhookTokenUpdate,
 generate_webhook_token,
)
from ..models.repository import ProjectRepository, Repository, RepositoryRead
from ..services.crypto import decrypt_value, encrypt_value
from ..services.feishu import FeishuClient
settings = get_settings
router = APIRouter(prefix="/api/projects", tags=["projects"])
# === 项目 CRUD ===
@router.get("/", response_model=List[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
 """列出所有项目。"""
 result = await db.exec(
 select(Project).options(
 selectinload(Project.repositories).selectinload(Repository.credential) # type: ignore[arg-type]
 )
 )
 projects = result.all
 response =
 for p in projects:
 repositories = [
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
 for repo in p.repositories
 ]
 response.append(
 ProjectRead(
 **p.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=p.has_feishu_config,
 webhook_token=p.feishu_webhook_token,
 repositories=repositories,
 )
 )
 return response
@router.post("/", response_model=ProjectRead, status_code=201)
async def create_project(
 project: ProjectCreate,
 db: AsyncSession = Depends(get_db),
):
 """创建新项目，自动生成 Webhook Token。"""
 db_project = Project.model_validate(project)
 # webhook_token 会通过 default_factory 自动生成
 db.add(db_project)
 await db.commit
 await db.refresh(db_project)
 return ProjectRead(
 **db_project.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=False,
 webhook_token=db_project.feishu_webhook_token,
 )
@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """根据 ID 获取项目。"""
 result = await db.exec(
 select(Project)
 .where(Project.id == project_id)
 .options(
 selectinload(Project.repositories).selectinload(Repository.credential) # type: ignore[arg-type]
 )
 )
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 repositories = [
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
 for repo in project.repositories
 ]
 return ProjectRead(
 **project.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=project.has_feishu_config,
 webhook_token=project.feishu_webhook_token,
 repositories=repositories,
 )
@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
 project_id: str,
 project_update: ProjectUpdate,
 db: AsyncSession = Depends(get_db),
):
 """更新项目。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 update_data = project_update.model_dump(exclude_unset=True)
 for key, value in update_data.items:
 setattr(project, key, value)
 project.updated_at = datetime.now(UTC)
 await db.commit
 await db.refresh(project)
 return ProjectRead(
 **project.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=project.has_feishu_config,
 webhook_token=project.feishu_webhook_token,
 )
@router.delete("/{project_id}", status_code=204)
async def delete_project(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """删除项目及其关联配置。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 手动删除关联记录
 await db.exec(
 delete(ProjectRepository).where(col(ProjectRepository.project_id) == project_id)
 )
 await db.delete(project)
 await db.commit
 return None
# === 仓库关联管理 ===
@router.post("/{project_id}/repositories/{repository_id}", status_code=201)
async def link_repository(
 project_id: str,
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """关联仓库到项目。"""
 # 验证项目
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 验证仓库
 result = await db.exec(select(Repository).where(Repository.id == repository_id))
 repository = result.one_or_none
 if not repository:
 raise HTTPException(status_code=404, detail="仓库未找到")
 # 检查是否已关联
 result = await db.exec(
 select(ProjectRepository).where(
 ProjectRepository.project_id == project_id,
 ProjectRepository.repository_id == repository_id,
 )
 )
 if result.one_or_none:
 return {"message": "Already linked"}
 # 创建关联
 link = ProjectRepository(project_id=project_id, repository_id=repository_id)
 db.add(link)
 await db.commit
 return {"message": "Linked successfully"}
@router.delete("/{project_id}/repositories/{repository_id}", status_code=204)
async def unlink_repository(
 project_id: str,
 repository_id: str,
 db: AsyncSession = Depends(get_db),
):
 """解除仓库与项目的关联。"""
 result = await db.exec(
 select(ProjectRepository).where(
 ProjectRepository.project_id == project_id,
 ProjectRepository.repository_id == repository_id,
 )
 )
 link = result.one_or_none
 if not link:
 raise HTTPException(status_code=404, detail="关联未找到")
 await db.delete(link)
 await db.commit
@router.get("/{project_id}/repositories")
async def list_project_repositories(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """列出项目关联的所有仓库。"""
 result = await db.exec(
 select(Repository)
 .join(ProjectRepository)
 .where(ProjectRepository.project_id == project_id)
 )
 return result.all
# === 飞书配置管理 ===
@router.get("/{project_id}/feishu-config", response_model=FeishuConfigRead)
async def get_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """获取项目的飞书配置（不返回敏感信息，Webhook Token 由项目接口返回）。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 return FeishuConfigRead(
 project_key=project.feishu_project_key,
 plugin_id=project.feishu_plugin_id,
 user_key=project.feishu_user_key,
 has_plugin_secret=bool(project.feishu_plugin_secret_encrypted),
 is_configured=project.has_feishu_config,
 )
@router.put("/{project_id}/feishu-config", response_model=FeishuConfigRead)
async def set_feishu_config(
 project_id: str,
 config: FeishuConfigCreate,
 db: AsyncSession = Depends(get_db),
):
 """设置项目的飞书配置（不包含 Webhook Token，它在项目级别独立管理）。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 加密敏感信息，不再处理 webhook_token
 project.feishu_plugin_id = config.plugin_id
 project.feishu_plugin_secret_encrypted = encrypt_value(config.plugin_secret)
 project.feishu_user_key = config.user_key
 project.updated_at = datetime.now(UTC)
 await db.commit
 await db.refresh(project)
 return FeishuConfigRead(
 project_key=project.feishu_project_key,
 plugin_id=project.feishu_plugin_id,
 user_key=project.feishu_user_key,
 has_plugin_secret=bool(project.feishu_plugin_secret_encrypted),
 is_configured=project.has_feishu_config,
 )
@router.delete("/{project_id}/feishu-config", status_code=204)
async def delete_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """删除项目的飞书配置（不影响 Webhook Token）。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 清除飞书插件配置，不清除 webhook_token（它独立于飞书配置）
 project.feishu_plugin_id = None
 project.feishu_plugin_secret_encrypted = None
 project.feishu_user_key = None
 project.updated_at = datetime.now(UTC)
 await db.commit
 return None
@router.post("/{project_id}/feishu-config/test", response_model=FeishuConfigTestResult)
async def test_feishu_config(
 project_id: str,
 test_config: Optional[FeishuConfigTest] = None,
 db: AsyncSession = Depends(get_db),
):
 """测试项目的飞书配置是否有效。
 支持两种模式：
 1. 不传 test_config：使用已保存的配置进行测试
 2. 传入 test_config：使用传入的临时配置进行测试（不保存）
 """
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 确定使用的配置：优先使用传入的临时配置，否则使用已保存的配置
 plugin_id = (
 test_config.plugin_id
 if test_config and test_config.plugin_id
 else project.feishu_plugin_id
 )
 plugin_secret = None
 if test_config and test_config.plugin_secret:
 # 使用传入的临时 secret
 plugin_secret = test_config.plugin_secret
 elif project.feishu_plugin_secret_encrypted:
 # 使用已保存的 secret
 plugin_secret = decrypt_value(project.feishu_plugin_secret_encrypted)
 user_key = (
 test_config.user_key
 if test_config and test_config.user_key
 else project.feishu_user_key
 )
 # 检查配置是否完整
 if not plugin_id or not plugin_secret:
 return FeishuConfigTestResult(
 success=False,
 message="飞书配置不完整，请填写插件 ID 和插件 Secret",
 plugin_token_valid=False,
 project_accessible=False,
 )
 try:
 # 创建客户端
 client = FeishuClient(
 plugin_id=plugin_id,
 plugin_secret=plugin_secret,
 project_key=project.feishu_project_key,
 user_key=user_key,
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
# === Webhook Token 管理 ===
@router.post("/{project_id}/refresh-webhook-token", response_model=WebhookTokenRead)
async def refresh_webhook_token(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """刷新项目的 Webhook Token，生成新的随机 Token。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 生成新的 Token
 project.feishu_webhook_token = generate_webhook_token
 project.updated_at = datetime.now(UTC)
 await db.commit
 await db.refresh(project)
 return WebhookTokenRead(webhook_token=project.feishu_webhook_token)
@router.put("/{project_id}/webhook-token", response_model=WebhookTokenRead)
async def update_webhook_token(
 project_id: str,
 token_update: WebhookTokenUpdate,
 db: AsyncSession = Depends(get_db),
):
 """自定义项目的 Webhook Token（最大 32 字符）。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 验证 Token 长度
 if len(token_update.token) > 32:
 raise HTTPException(status_code=400, detail="Token 长度不能超过 32 个字符")
 if len(token_update.token) == 0:
 raise HTTPException(status_code=400, detail="Token 不能为空")
 project.feishu_webhook_token = token_update.token
 project.updated_at = datetime.now(UTC)
 await db.commit
 await db.refresh(project)
 return WebhookTokenRead(webhook_token=project.feishu_webhook_token)
# === Claude 配置管理 ===
@router.get("/{project_id}/claude-config", response_model=ClaudeConfigRead)
async def get_claude_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """获取项目的 Claude 配置（不返回敏感信息）。
 配置优先级：项目级 > 系统级 > 环境变量
 """
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 确定配置来源
 has_project_api_key = bool(project.claude_api_key_encrypted)
 base_url = project.claude_base_url
 if has_project_api_key:
 source = "project"
 else:
 # 检查系统配置（这里先返回系统或环境变量来源，实际获取逻辑在 claude_config 服务中）
 source = "system" # 或 "environment"
 return ClaudeConfigRead(
 has_api_key=has_project_api_key,
 base_url=base_url,
 source=source,
 )
@router.put("/{project_id}/claude-config", response_model=ClaudeConfigRead)
async def set_claude_config(
 project_id: str,
 config: ClaudeConfigCreate,
 db: AsyncSession = Depends(get_db),
):
 """设置项目的 Claude 配置。
 可以只设置 api_key 或只设置 base_url，也可以同时设置。
 """
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 更新配置
 if config.api_key is not None:
 if config.api_key == "":
 # 空字符串表示清除 API Key
 project.claude_api_key_encrypted = None
 else:
 project.claude_api_key_encrypted = encrypt_value(config.api_key)
 if config.base_url is not None:
 if config.base_url == "":
 # 空字符串表示清除 Base URL
 project.claude_base_url = None
 else:
 project.claude_base_url = config.base_url
 project.updated_at = datetime.now(UTC)
 await db.commit
 await db.refresh(project)
 return ClaudeConfigRead(
 has_api_key=bool(project.claude_api_key_encrypted),
 base_url=project.claude_base_url,
 source="project" if project.claude_api_key_encrypted else "system",
 )
@router.delete("/{project_id}/claude-config", status_code=204)
async def delete_claude_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """删除项目的 Claude 配置，将使用系统级配置。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 # 清除项目级 Claude 配置
 project.claude_api_key_encrypted = None
 project.claude_base_url = None
 project.updated_at = datetime.now(UTC)
 await db.commit
 return None
