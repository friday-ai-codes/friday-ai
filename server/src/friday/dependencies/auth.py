"""认证依赖 - FastAPI 依赖注入。"""
from typing import Annotated
from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..models.user import User
from .auth import REFRESH_TOKEN_COOKIE_NAME, decode_token
# HTTP Bearer 认证方案
security = HTTPBearer(auto_error=False)
async def get_current_user(
 credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
 db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
 """从 Access Token 获取当前用户。
 Args:
 credentials: HTTP Bearer 凭证
 db: 数据库会话
 Returns:
 当前用户对象
 Raises:
 HTTPException: 认证失败
 """
 credentials_exception = HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="无效的认证凭证",
 headers={"WWW-Authenticate": "Bearer"},
 )
 if not credentials:
 raise credentials_exception
 # 解码并验证 token
 payload = decode_token(credentials.credentials, expected_type="access")
 if payload is None:
 raise credentials_exception
 user_id: str | None = payload.get("sub")
 if user_id is None:
 raise credentials_exception
 # 查询用户
 result = await db.execute(select(User).where(User.id == user_id))
 user = result.scalar_one_or_none
 if user is None:
 raise credentials_exception
 return user
async def get_current_active_user(
 current_user: Annotated[User, Depends(get_current_user)],
) -> User:
 """确保当前用户是激活状态。
 Args:
 current_user: 当前用户
 Returns:
 当前激活的用户
 Raises:
 HTTPException: 用户未激活
 """
 if not current_user.is_active:
 raise HTTPException(
 status_code=status.HTTP_403_FORBIDDEN,
 detail="用户已被禁用",
 )
 return current_user
async def get_refresh_token_from_cookie(
 refresh_token: Annotated[str | None, Cookie(alias=REFRESH_TOKEN_COOKIE_NAME)] = None,
) -> str:
 """从 Cookie 获取 Refresh Token。
 Args:
 refresh_token: Cookie 中的 Refresh Token
 Returns:
 Refresh Token 字符串
 Raises:
 HTTPException: 未找到 Refresh Token
 """
 if not refresh_token:
 raise HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="未找到 Refresh Token",
 )
 return refresh_token
# 类型别名，方便使用
CurrentUser = Annotated[User, Depends(get_current_active_user)]
RefreshToken = Annotated[str, Depends(get_refresh_token_from_cookie)]
