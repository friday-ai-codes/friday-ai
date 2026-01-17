"""系统设置 API 路由。"""
from datetime import UTC, datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..models import (
 SettingKeys,
 SystemSetting,
 SystemSettingCreate,
 SystemSettingRead,
 SystemSettingReadWithValue,
 SystemSettingUpdate,
)
from ..services.crypto import decrypt_value, encrypt_value
router = APIRouter(prefix="/api/settings", tags=["settings"])
# 需要加密存储的配置键
ENCRYPTED_KEYS = {
 SettingKeys.ANTHROPIC_API_KEY,
}
def _mask_api_key(value: str | None) -> str | None:
 """对 API Key 进行遮罩，显示前4位和后4位。"""
 if not value:
 return None
 if len(value) <= 8:
 return "*" * len(value)
 return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"
@router.get("/", response_model=List[SystemSettingReadWithValue])
async def list_settings(db: AsyncSession = Depends(get_db)):
 """列出所有系统设置。
 对于非加密设置，直接返回值；
 对于加密设置，返回遮罩后的值。
 """
 result = await db.exec(select(SystemSetting))
 settings = result.all
 items =
 for s in settings:
 if s.is_encrypted:
 # 加密设置：返回遮罩值
 decrypted = decrypt_value(s.value) if s.value else None
 masked = _mask_api_key(decrypted)
 items.append(
 SystemSettingReadWithValue(
 key=s.key,
 has_value=bool(s.value),
 is_encrypted=s.is_encrypted,
 description=s.description,
 updated_at=s.updated_at,
 value=None,
 masked_value=masked,
 )
 )
 else:
 # 非加密设置：直接返回值
 items.append(
 SystemSettingReadWithValue(
 key=s.key,
 has_value=bool(s.value),
 is_encrypted=s.is_encrypted,
 description=s.description,
 updated_at=s.updated_at,
 value=s.value,
 masked_value=None,
 )
 )
 return items
@router.get("/{key}", response_model=SystemSettingReadWithValue)
async def get_setting(
 key: str,
 db: AsyncSession = Depends(get_db),
):
 """获取单个系统设置。
 注意：加密的设置值不会返回，仅返回是否已配置。
 """
 result = await db.exec(select(SystemSetting).where(SystemSetting.key == key))
 setting = result.one_or_none
 if not setting:
 raise HTTPException(status_code=404, detail=f"设置 '{key}' 未找到")
 # 加密的值不返回实际内容
 value = None if setting.is_encrypted else setting.value
 return SystemSettingReadWithValue(
 key=setting.key,
 has_value=bool(setting.value),
 is_encrypted=setting.is_encrypted,
 description=setting.description,
 updated_at=setting.updated_at,
 value=value,
 )
@router.put("/{key}", response_model=SystemSettingRead)
async def update_setting(
 key: str,
 setting_update: SystemSettingUpdate,
 db: AsyncSession = Depends(get_db),
):
 """更新或创建系统设置。"""
 result = await db.exec(select(SystemSetting).where(SystemSetting.key == key))
 setting = result.one_or_none
 # 判断是否需要加密
 should_encrypt = setting_update.is_encrypted
 if should_encrypt is None:
 # 如果没有明确指定，检查是否是预定义的加密键
 should_encrypt = key in ENCRYPTED_KEYS
 # 处理值
 value = setting_update.value
 if should_encrypt and value:
 value = encrypt_value(value)
 if setting:
 # 更新现有设置
 setting.value = value
 setting.is_encrypted = should_encrypt
 if setting_update.description is not None:
 setting.description = setting_update.description
 setting.updated_at = datetime.now(UTC)
 else:
 # 创建新设置
 setting = SystemSetting(
 key=key,
 value=value,
 is_encrypted=should_encrypt,
 description=setting_update.description,
 )
 db.add(setting)
 await db.commit
 await db.refresh(setting)
 return SystemSettingRead(
 key=setting.key,
 has_value=bool(setting.value),
 is_encrypted=setting.is_encrypted,
 description=setting.description,
 updated_at=setting.updated_at,
 )
@router.post("/", response_model=SystemSettingRead, status_code=201)
async def create_setting(
 setting_create: SystemSettingCreate,
 db: AsyncSession = Depends(get_db),
):
 """创建新的系统设置。"""
 # 检查是否已存在
 result = await db.exec(
 select(SystemSetting).where(SystemSetting.key == setting_create.key)
 )
 if result.one_or_none:
 raise HTTPException(
 status_code=409, detail=f"设置 '{setting_create.key}' 已存在"
 )
 # 判断是否需要加密
 should_encrypt = setting_create.is_encrypted
 if not should_encrypt:
 # 检查是否是预定义的加密键
 should_encrypt = setting_create.key in ENCRYPTED_KEYS
 # 处理值
 value = setting_create.value
 if should_encrypt and value:
 value = encrypt_value(value)
 setting = SystemSetting(
 key=setting_create.key,
 value=value,
 is_encrypted=should_encrypt,
 description=setting_create.description,
 )
 db.add(setting)
 await db.commit
 await db.refresh(setting)
 return SystemSettingRead(
 key=setting.key,
 has_value=bool(setting.value),
 is_encrypted=setting.is_encrypted,
 description=setting.description,
 updated_at=setting.updated_at,
 )
@router.delete("/{key}", status_code=204)
async def delete_setting(
 key: str,
 db: AsyncSession = Depends(get_db),
):
 """删除系统设置。"""
 result = await db.exec(select(SystemSetting).where(SystemSetting.key == key))
 setting = result.one_or_none
 if not setting:
 raise HTTPException(status_code=404, detail=f"设置 '{key}' 未找到")
 await db.delete(setting)
 await db.commit
# === 便捷方法（供内部使用）===
async def get_setting_value(db: AsyncSession, key: str) -> str | None:
 """获取设置值（内部使用，自动解密）。"""
 result = await db.exec(select(SystemSetting).where(SystemSetting.key == key))
 setting = result.one_or_none
 if not setting or not setting.value:
 return None
 if setting.is_encrypted:
 return decrypt_value(setting.value)
 return setting.value
