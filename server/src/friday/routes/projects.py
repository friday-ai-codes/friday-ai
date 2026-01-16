"""项目管理 API 路由。"""
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..config import get_settings
from ..database import get_db
from ..models import (
 FeishuConfigCreate,
 FeishuConfigRead,
 FeishuConfigTestResult,
 Project,
 ProjectCreate,
 ProjectRead,
 ProjectUpdate,
 WebhookTokenRead,
 WebhookTokenUpdate,
 generate_webhook_token,
)
from ..models.repository import ProjectRepository, Repository
from ..services.crypto import decrypt_value, encrypt_value
from ..services.feishu import FeishuClient
settings = get_settings
router = APIRouter(prefix="/api/projects", tags=["projects"])
# === 项目 CRUD ===
@router.get("/", response_model=List[ProjectRead])
async def list_projects(db: AsyncSession = Depends(get_db)):
 """列出所有项目。"""
 result = await db.exec(select(Project))
 projects = result.all
 response =
 for p in projects:
 response.append(
 ProjectRead(
 **p.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=p.has_feishu_config,
 webhook_token=p.feishu_webhook_token,
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
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise HTTPException(status_code=404, detail="项目未找到")
 return ProjectRead(
 **project.model_dump(exclude={"feishu_plugin_secret_encrypted"}),
 has_feishu_config=project.has_feishu_config,
 webhook_token=project.feishu_webhook_token,
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
 project.updated_at = datetime.utcnow
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
 project.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(project)
 return FeishuConfigRead(
 project_key=project.feishu_project_key,
 plugin_id=project.feishu_plugin_id,
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
 project.updated_at = datetime.utcnow
 await db.commit
 return None
@router.post("/{project_id}/feishu-config/test", response_model=FeishuConfigTestResult)
async def test_feishu_config(
 project_id: str,
 db: AsyncSession = Depends(get_db),
):
 """测试项目的飞书配置是否有效。"""
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
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
 # has_feishu_config 已确保 feishu_plugin_secret_encrypted 不为 None
 assert project.feishu_plugin_secret_encrypted is not None
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
 project.updated_at = datetime.utcnow
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
 project.updated_at = datetime.utcnow
 await db.commit
 await db.refresh(project)
 return WebhookTokenRead(webhook_token=project.feishu_webhook_token)
