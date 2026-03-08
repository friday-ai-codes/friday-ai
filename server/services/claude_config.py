"""Claude 配置服务，实现配置优先级获取逻辑。
配置优先级：项目级 > 系统级
同步版本供同步代码使用，async 版本（aget_* 前缀）供 async 代码使用。
"""
from dataclasses import dataclass
from typing import Literal, Optional
from common.encryption import decrypt_value
from projects.models import Project
from system.models import SettingKeys, SystemSetting
@dataclass
class ClaudeConfig:
 """Claude 配置数据类。"""
 api_key: Optional[str]
 base_url: Optional[str]
 model: Optional[str]
 source: Literal["project", "system"]
 provider_type: str = "anthropic"
def get_setting_value(key: str) -> Optional[str]:
 """获取系统设置值（自动解密）。"""
 try:
 setting = SystemSetting.objects.get(key=key)
 if not setting.value:
 return None
 if setting.is_encrypted:
 return decrypt_value(setting.value)
 return setting.value
 except SystemSetting.DoesNotExist:
 return None
async def aget_setting_value(key: str) -> Optional[str]:
 """获取系统设置值（自动解密）— async 版本。"""
 try:
 setting = await SystemSetting.objects.aget(key=key)
 if not setting.value:
 return None
 if setting.is_encrypted:
 return decrypt_value(setting.value)
 return setting.value
 except SystemSetting.DoesNotExist:
 return None
def get_claude_config(project: Optional[Project] = None) -> ClaudeConfig:
 """获取 Claude 配置，按优先级依次查找。
 配置优先级：
 1. 项目级配置（如果提供了 project）
 2. 系统级配置（从 system_settings 表读取）
 Args:
 project: 项目对象（可选）
 Returns:
 ClaudeConfig: 配置对象
 """
 api_key: Optional[str] = None
 base_url: Optional[str] = None
 source: Literal["project", "system"] = "system"
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
 system_api_key = get_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 if system_api_key:
 api_key = system_api_key
 source = "system"
 # 如果没有项目级 Base URL，检查系统级
 if not base_url:
 system_base_url = get_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 if system_base_url:
 base_url = system_base_url
 # 获取模型配置（项目级 > 系统级）
 model = (
 (project.claude_default_model if project else None)
 or get_setting_value(SettingKeys.ANTHROPIC_MODEL)
 or None
 )
 return ClaudeConfig(
 api_key=api_key,
 base_url=base_url,
 model=model,
 source=source,
 provider_type=get_setting_value(SettingKeys.DEFAULT_PROVIDER_TYPE) or "anthropic",
 )
async def aget_claude_config(project: Optional[Project] = None) -> ClaudeConfig:
 """获取 Claude 配置，按优先级依次查找 — async 版本。"""
 api_key: Optional[str] = None
 base_url: Optional[str] = None
 source: Literal["project", "system"] = "system"
 if project:
 if project.claude_api_key_encrypted:
 api_key = decrypt_value(project.claude_api_key_encrypted)
 source = "project"
 if project.claude_base_url:
 base_url = project.claude_base_url
 if source != "project":
 source = "project"
 if not api_key:
 system_api_key = await aget_setting_value(SettingKeys.ANTHROPIC_API_KEY)
 if system_api_key:
 api_key = system_api_key
 source = "system"
 if not base_url:
 system_base_url = await aget_setting_value(SettingKeys.ANTHROPIC_BASE_URL)
 if system_base_url:
 base_url = system_base_url
 model = (
 (project.claude_default_model if project else None)
 or await aget_setting_value(SettingKeys.ANTHROPIC_MODEL)
 or None
 )
 return ClaudeConfig(
 api_key=api_key,
 base_url=base_url,
 model=model,
 source=source,
 provider_type=await aget_setting_value(SettingKeys.DEFAULT_PROVIDER_TYPE) or "anthropic",
 )
def get_claude_config_for_task(project_id: str) -> ClaudeConfig:
 """为任务执行获取 Claude 配置。
 Args:
 project_id: 项目 ID
 Returns:
 ClaudeConfig: 配置对象
 Raises:
 ValueError: 如果找不到项目或没有配置 API Key
 """
 # 获取项目
 try:
 project = Project.objects.get(id=project_id)
 except Project.DoesNotExist:
 raise ValueError(f"找不到项目: {project_id}")
 # 获取配置
 config = get_claude_config(project)
 if not config.api_key:
 raise ValueError("未配置 Claude API Key，请在系统设置或项目设置中配置")
 if not config.model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 return config
async def aget_claude_config_for_task(project_id: str) -> ClaudeConfig:
 """为任务执行获取 Claude 配置 — async 版本。"""
 try:
 project = await Project.objects.aget(id=project_id)
 except Project.DoesNotExist:
 raise ValueError(f"找不到项目: {project_id}")
 config = await aget_claude_config(project)
 if not config.api_key:
 raise ValueError("未配置 Claude API Key，请在系统设置或项目设置中配置")
 if not config.model:
 raise ValueError("未配置默认模型，请在系统设置或项目设置中配置默认模型")
 return config
