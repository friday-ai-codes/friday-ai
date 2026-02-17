"""Runners app views - 注册/注销/验证/管理 API。"""
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from .authentication import RunnerTokenAuthentication
from .models import RegistrationToken, Runner, generate_token, hash_token
from .serializers import (
 RegistrationTokenCreateSerializer,
 RegistrationTokenSerializer,
 RunnerRegisterResponseSerializer,
 RunnerRegisterSerializer,
 RunnerSerializer,
)
class RegistrationTokenViewSet(ModelViewSet):
 """Registration token 管理（JWT 认证）。"""
 queryset = RegistrationToken.objects.all.order_by("-created_at")
 serializer_class = RegistrationTokenSerializer
 http_method_names = ["get", "post", "delete", "head", "options"]
 def create(self, request, *args, **kwargs):
 serializer = RegistrationTokenCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 token = generate_token
 reg_token = RegistrationToken.objects.create(
 token_hash=hash_token(token),
 description=data.get("description", ""),
 scope=data["scope"],
 project_id=data.get("project_id"),
 expires_at=timezone.now + timedelta(seconds=data["expires_in"]),
 created_by=request.user,
 )
 response_data = RegistrationTokenSerializer(reg_token).data
 response_data["token"] = token # 明文 token 仅返回一次
 return Response(response_data, status=status.HTTP_201_CREATED)
class RunnerRegisterView(APIView):
 """Runner 注册（无认证，用 registration token）。"""
 authentication_classes =
 permission_classes = [AllowAny]
 def post(self, request):
 serializer = RunnerRegisterSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 token_hashed = hash_token(data["token"])
 now = timezone.now
 # 原子操作：标记 token 已使用
 updated = RegistrationToken.objects.filter(
 token_hash=token_hashed, is_used=False, expires_at__gt=now
 ).update(is_used=True, used_at=now)
 if not updated:
 return Response(
 {"detail": "注册令牌无效或已过期"},
 status=status.HTTP_401_UNAUTHORIZED,
 )
 reg_token = RegistrationToken.objects.get(token_hash=token_hashed)
 # 生成 runner auth token
 runner_token = generate_token
 runner = Runner.objects.create(
 name=data["name"],
 token_hash=hash_token(runner_token),
 token_prefix=runner_token[:8],
 scope=data["scope"],
 concurrent=data["concurrent"],
 version=data.get("version", ""),
 ip_address=request.META.get("REMOTE_ADDR"),
 )
 # 绑定项目
 if reg_token.project:
 runner.projects.add(reg_token.project)
 # 回写 used_by_runner
 reg_token.used_by_runner = runner
 reg_token.save(update_fields=["used_by_runner"])
 return Response(
 RunnerRegisterResponseSerializer({
 "runner_id": runner.id,
 "runner_token": runner_token,
 "name": runner.name,
 "scope": runner.scope,
 }).data,
 status=status.HTTP_201_CREATED,
 )
class RunnerUnregisterView(APIView):
 """Runner 注销（Runner Token 认证）。"""
 authentication_classes = [RunnerTokenAuthentication]
 permission_classes = [AllowAny]
 def delete(self, request):
 runner = request.auth
 runner.is_active = False
 runner.save(update_fields=["is_active"])
 return Response(status=status.HTTP_204_NO_CONTENT)
class RunnerVerifyView(APIView):
 """Runner Token 验证（Runner Token 认证）。"""
 authentication_classes = [RunnerTokenAuthentication]
 permission_classes = [AllowAny]
 def get(self, request):
 runner = request.auth
 return Response({
 "id": str(runner.id),
 "name": runner.name,
 "scope": runner.scope,
 "status": runner.status,
 "concurrent": runner.concurrent,
 "version": runner.version,
 "last_heartbeat": runner.last_heartbeat,
 })
class RunnerViewSet(ModelViewSet):
 """Runner 管理（JWT 认证，只读 + 删除）。"""
 queryset = Runner.objects.all.order_by("-registered_at")
 serializer_class = RunnerSerializer
 http_method_names = ["get", "delete", "head", "options"]
