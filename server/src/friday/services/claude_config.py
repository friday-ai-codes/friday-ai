"""Claude 配置服务，实现配置优先级获取逻辑。
配置优先级：项目级 > 系统级 > 环境变量
"""
import os
from dataclasses import dataclass
from typing import Literal, Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from ..models import Project, SettingKeys
from .crypto import decrypt_value
@dataclass
class ClaudeConfig:
 """Claude 配置数据类。"""
 api_key: Optional[str]
 base_url: Optional[str]
 source: Literal["project", "system", "environment"]
async def get_claude_config(
 db: AsyncSession,
 project: Optional[Project] = None,
) -> ClaudeConfig:
 """获取 Claude 配置，按优先级依次查找。
 配置优先级：
 1. 项目级配置（如果提供了 project）
 2. 系统级配置（从 system_settings 表读取）
 3. 环境变量
 Args:
 db: 数据库会话
 project: 项目对象（可选）
 Returns:
 ClaudeConfig: 配置对象
 """
 from ..routes.settings import get_setting_value
 api_key: Optional[str] = None
 base_url: Optional[str] = None
 source: Literal["project", "system", "environment"] = "environment"
 # 1. 检查项目级配置
 if project:
 if project.claude_api_key_encrypted:
 api_key = decrypt_value(project.claude_api_key_encrypted)
 source = "project"
 if project.claude_base_url:
 base_url = project.claude_base_url
 if source != "project":
 source = "project"
 # 2. 如果没有项目级 API Key，检查系统级配置
 if not api_key:
 system_api_key = await get_setting_value(db, SettingKeys.ANTHROPIC_API_KEY)
 if system_api_key:
 api_key = system_api_key
 source = "system"
 # 如果没有项目级 Base URL，检查系统级
 if not base_url:
 system_base_url = await get_setting_value(db, SettingKeys.ANTHROPIC_BASE_URL)
 if system_base_url:
 base_url = system_base_url
 # 3. 如果没有系统级 API Key，检查环境变量
 if not api_key:
 api_key = os.environ.get("ANTHROPIC_API_KEY")
 if api_key:
 source = "environment"
 # 环境变量 Base URL
 if not base_url:
 base_url = os.environ.get("ANTHROPIC_BASE_URL")
 return ClaudeConfig(
 api_key=api_key,
 base_url=base_url,
 source=source,
 )
async def get_claude_config_for_task(
 db: AsyncSession,
 project_id: str,
) -> ClaudeConfig:
 """为任务执行获取 Claude 配置。
 Args:
 db: 数据库会话
 project_id: 项目 ID
 Returns:
 ClaudeConfig: 配置对象
 Raises:
 ValueError: 如果找不到项目或没有配置 API Key
 """
 from sqlmodel import select
 # 获取项目
 result = await db.exec(select(Project).where(Project.id == project_id))
 project = result.one_or_none
 if not project:
 raise ValueError(f"找不到项目: {project_id}")
 # 获取配置
 config = await get_claude_config(db, project)
 if not config.api_key:
 raise ValueError("未配置 Claude API Key，请在系统设置或项目设置中配置")
 return config
