"""认证服务 - JWT Token 和密码处理。"""
from datetime import datetime, timedelta
from typing import Literal
from fastapi import Response
from jose import JWTError, jwt
from passlib.context import CryptContext
from ..config import get_settings
settings = get_settings
# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# Token 类型
TokenType = Literal["access", "refresh"]
# Refresh Token Cookie 名称
REFRESH_TOKEN_COOKIE_NAME = "refresh_token"
def verify_password(plain_password: str, hashed_password: str) -> bool:
 """验证密码。
 Args:
 plain_password: 明文密码
 hashed_password: 哈希后的密码
 Returns:
 密码是否匹配
 """
 return pwd_context.verify(plain_password, hashed_password)
def get_password_hash(password: str) -> str:
 """获取密码哈希。
 Args:
 password: 明文密码
 Returns:
 哈希后的密码
 """
 return pwd_context.hash(password)
def create_access_token(
 data: dict,
 expires_delta: timedelta | None = None,
) -> str:
 """创建 Access Token。
 Args:
 data: 要编码的数据
 expires_delta: 过期时间增量，默认使用配置中的值
 Returns:
 JWT Token 字符串
 """
 to_encode = data.copy
 if expires_delta:
 expire = datetime.utcnow + expires_delta
 else:
 expire = datetime.utcnow + timedelta(
 minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
 )
 to_encode.update({"exp": expire, "type": "access"})
 encoded_jwt = jwt.encode(
 to_encode,
 settings.JWT_SECRET_KEY,
 algorithm=settings.JWT_ALGORITHM,
 )
 return encoded_jwt
def create_refresh_token(data: dict) -> str:
 """创建 Refresh Token。
 Args:
 data: 要编码的数据
 Returns:
 JWT Token 字符串
 """
 to_encode = data.copy
 expire = datetime.utcnow + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
 to_encode.update({"exp": expire, "type": "refresh"})
 encoded_jwt = jwt.encode(
 to_encode,
 settings.JWT_SECRET_KEY,
 algorithm=settings.JWT_ALGORITHM,
 )
 return encoded_jwt
def decode_token(token: str, expected_type: TokenType | None = None) -> dict | None:
 """解码并验证 JWT Token。
 Args:
 token: JWT Token 字符串
 expected_type: 期望的 token 类型 ("access" 或 "refresh")
 Returns:
 解码后的数据，如果验证失败返回 None
 """
 try:
 payload = jwt.decode(
 token,
 settings.JWT_SECRET_KEY,
 algorithms=[settings.JWT_ALGORITHM],
 )
 # 验证 token 类型
 if expected_type and payload.get("type") != expected_type:
 return None
 return payload
 except JWTError:
 return None
def set_refresh_token_cookie(response: Response, token: str) -> None:
 """设置 Refresh Token Cookie。
 Args:
 response: FastAPI Response 对象
 token: Refresh Token
 """
 max_age = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60 # 转换为秒
 response.set_cookie(
 key=REFRESH_TOKEN_COOKIE_NAME,
 value=token,
 max_age=max_age,
 httponly=settings.COOKIE_HTTPONLY,
 secure=settings.COOKIE_SECURE,
 samesite=settings.COOKIE_SAMESITE,
 path="/api/auth", # 只在认证路由下发送
 )
def clear_refresh_token_cookie(response: Response) -> None:
 """清除 Refresh Token Cookie。
 Args:
 response: FastAPI Response 对象
 """
 response.delete_cookie(
 key=REFRESH_TOKEN_COOKIE_NAME,
 path="/api/auth",
 httponly=settings.COOKIE_HTTPONLY,
 secure=settings.COOKIE_SECURE,
 samesite=settings.COOKIE_SAMESITE,
 )
