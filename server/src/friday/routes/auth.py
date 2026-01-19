"""认证路由 - 登录、登出、刷新 Token 等。"""
from datetime import datetime
from typing import Annotated
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from ..database import get_db
from ..dependencies import CurrentUser, RefreshToken
from ..models.user import (
 ChangePasswordRequest,
 LoginRequest,
 LoginResponse,
 TokenResponse,
 User,
 UserRead,
)
from ..services.auth import (
 clear_refresh_token_cookie,
 create_access_token,
 create_refresh_token,
 decode_token,
 get_password_hash,
 set_refresh_token_cookie,
 verify_password,
)
logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["认证"])
@router.post("/login", response_model=LoginResponse)
async def login(
 request: LoginRequest,
 response: Response,
 db: Annotated[AsyncSession, Depends(get_db)],
) -> LoginResponse:
 """用户登录。
 验证用户名和密码，返回 Access Token 并设置 Refresh Token Cookie。
 """
 # 查询用户
 result = await db.execute(select(User).where(User.username == request.username))
 user = result.scalar_one_or_none
 if not user or not verify_password(request.password, user.hashed_password):
 logger.warning("登录失败", username=request.username)
 raise HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="用户名或密码错误",
 )
 if not user.is_active:
 logger.warning("用户已被禁用", username=request.username)
 raise HTTPException(
 status_code=status.HTTP_403_FORBIDDEN,
 detail="用户已被禁用",
 )
 # 创建 tokens
 token_data = {"sub": user.id}
 access_token = create_access_token(token_data)
 refresh_token = create_refresh_token(token_data)
 # 设置 Refresh Token Cookie
 set_refresh_token_cookie(response, refresh_token)
 logger.info("用户登录成功", username=request.username, user_id=user.id)
 return LoginResponse(
 access_token=access_token,
 user=UserRead.model_validate(user),
 )
@router.post("/logout")
async def logout(response: Response) -> dict:
 """用户登出。
 清除 Refresh Token Cookie。
 """
 clear_refresh_token_cookie(response)
 return {"message": "登出成功"}
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
 refresh_token: RefreshToken,
 response: Response,
 db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
 """刷新 Access Token。
 使用 Cookie 中的 Refresh Token 获取新的 Access Token。
 """
 # 解码 Refresh Token
 payload = decode_token(refresh_token, expected_type="refresh")
 if payload is None:
 clear_refresh_token_cookie(response)
 raise HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="Refresh Token 无效或已过期",
 )
 user_id = payload.get("sub")
 if not user_id:
 clear_refresh_token_cookie(response)
 raise HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="无效的 Token",
 )
 # 验证用户是否存在且激活
 result = await db.execute(select(User).where(User.id == user_id))
 user = result.scalar_one_or_none
 if not user or not user.is_active:
 clear_refresh_token_cookie(response)
 raise HTTPException(
 status_code=status.HTTP_401_UNAUTHORIZED,
 detail="用户不存在或已被禁用",
 )
 # 创建新的 Access Token
 access_token = create_access_token({"sub": user.id})
 # 可选：滚动刷新 Refresh Token（延长有效期）
 new_refresh_token = create_refresh_token({"sub": user.id})
 set_refresh_token_cookie(response, new_refresh_token)
 return TokenResponse(access_token=access_token)
@router.get("/me", response_model=UserRead)
async def get_current_user_info(current_user: CurrentUser) -> UserRead:
 """获取当前用户信息。"""
 return UserRead.model_validate(current_user)
@router.post("/change-password")
async def change_password(
 request: ChangePasswordRequest,
 current_user: CurrentUser,
 db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
 """修改密码。"""
 # 验证旧密码
 if not verify_password(request.old_password, current_user.hashed_password):
 raise HTTPException(
 status_code=status.HTTP_400_BAD_REQUEST,
 detail="旧密码错误",
 )
 # 更新密码
 current_user.hashed_password = get_password_hash(request.new_password)
 current_user.updated_at = datetime.utcnow
 db.add(current_user)
 await db.commit
 logger.info("用户修改密码成功", user_id=current_user.id)
 return {"message": "密码修改成功"}
