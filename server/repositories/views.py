"""Repositories views."""
import subprocess
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from common.encryption import decrypt_value, encrypt_value
from .models import AuthType, GitCredential, Repository
from .serializers import (
 GitCredentialSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
)
class RepositoryViewSet(ModelViewSet):
 """ViewSet for Repository CRUD operations."""
 serializer_class = RepositorySerializer
 def get_queryset(self):
 """Filter out soft-deleted repositories."""
 return (
 Repository.objects.filter(is_deleted=False)
 .select_related("credential")
 .prefetch_related("projects")
 )
 def get_serializer_class(self):
 if self.action == "create":
 return RepositoryCreateSerializer
 if self.action == "retrieve":
 return RepositoryWithProjectsSerializer
 return RepositorySerializer
 def create(self, request, *args, **kwargs):
 serializer = RepositoryCreateSerializer(data=request.data)
 serializer.is_valid(raise_exception=True)
 data = serializer.validated_data
 access_token = data.pop("access_token")
 git_user_name = data.pop("git_user_name", "Friday Codes AI Agent")
 git_user_email = data.pop("git_user_email", "ai@friday.codes")
 if not access_token.strip:
 return Response(
 {"detail": "Access Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Create repository
 repository = Repository.objects.create(**data)
 # Create credential
 GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(access_token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 return Response(
 RepositorySerializer(repository).data,
 status=status.HTTP_201_CREATED,
 )
 @action(detail=True, methods=["get", "delete"], url_path="credential")
 def credential(self, request, pk=None):
 """Get or delete credential for repository."""
 repository = self.get_object
 if request.method == "GET":
 credential = GitCredential.objects.filter(repository=repository).first
 if credential:
 return Response(GitCredentialSerializer(credential).data)
 return Response(None)
 elif request.method == "DELETE":
 credential = GitCredential.objects.filter(repository=repository).first
 if credential:
 credential.delete
 return Response(status=status.HTTP_204_NO_CONTENT)
 else:
 return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
 def destroy(self, request, *args, **kwargs):
 """Soft delete the repository instead of hard delete."""
 repository = self.get_object
 repository.soft_delete
 return Response(status=status.HTTP_204_NO_CONTENT)
class SetAccessTokenView(APIView):
 """View for setting or updating access token."""
 def post(self, request, repository_id):
 repository = get_object_or_404(Repository, id=repository_id, is_deleted=False)
 token = request.data.get("token")
 if not token:
 return Response(
 {"detail": "Token 不能为空"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 git_user_name = request.data.get("git_user_name", "Friday Codes AI Agent")
 git_user_email = request.data.get("git_user_email", "ai@friday.codes")
 existing_credential = GitCredential.objects.filter(repository=repository).first
 if existing_credential:
 existing_credential.auth_type = AuthType.ACCESS_TOKEN
 existing_credential.encrypted_token = encrypt_value(token)
 existing_credential.git_user_name = git_user_name
 existing_credential.git_user_email = git_user_email
 existing_credential.save
 return Response(GitCredentialSerializer(existing_credential).data)
 else:
 credential = GitCredential.objects.create(
 repository=repository,
 auth_type=AuthType.ACCESS_TOKEN,
 encrypted_token=encrypt_value(token),
 git_user_name=git_user_name,
 git_user_email=git_user_email,
 )
 return Response(
 GitCredentialSerializer(credential).data, status=status.HTTP_201_CREATED
 )
class TestConnectionView(APIView):
 """View for testing Git repository connection."""
 def post(self, request, repository_id=None):
 """Test connection to a Git repository.
 Can be used in two ways:
 1. With repository_id: Test existing repository's connection
 2. Without repository_id: Test connection with provided git_url and access_token
 """
 if repository_id:
 # Test existing repository
 repository = get_object_or_404(Repository, id=repository_id, is_deleted=False)
 git_url = repository.git_url
 proxy_url = repository.proxy_url
 # Get token from credential
 credential = getattr(repository, "credential", None)
 if not credential or not credential.encrypted_token:
 return Response(
 {"success": False, "error": "仓库未配置访问凭证"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 token = decrypt_value(credential.encrypted_token)
 else:
 # Test with provided data
 git_url = request.data.get("git_url")
 token = request.data.get("access_token")
 proxy_url = request.data.get("proxy_url")
 if not git_url:
 return Response(
 {"success": False, "error": "请提供仓库 URL"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 if not token:
 return Response(
 {"success": False, "error": "请提供 Access Token"},
 status=status.HTTP_400_BAD_REQUEST,
 )
 # Build authenticated URL
 auth_url = git_url
 if token and git_url.startswith("https://"):
 auth_url = git_url.replace("https://", f"https://{token}@")
 # Test connection using git ls-remote
 try:
 cmd = ["git", "ls-remote", "--heads", auth_url]
 # Add proxy if configured
 env = None
 if proxy_url:
 import os
 env = os.environ.copy
 env["http_proxy"] = proxy_url
 env["https_proxy"] = proxy_url
 result = subprocess.run(
 cmd,
 capture_output=True,
 text=True,
 timeout=30,
 env=env,
 )
 if result.returncode == 0:
 # Parse branches from output
 branches =
 for line in result.stdout.strip.split("\n"):
 if line and "\t" in line:
 ref = line.split("\t")[1]
 if ref.startswith("refs/heads/"):
 branches.append(ref.replace("refs/heads/", ""))
 return Response(
 {
 "success": True,
 "message": "连接成功",
 "branches": branches[:10], # Limit to first 10 branches
 }
 )
 else:
 error_msg = result.stderr.strip
 # Clean up token from error message
 if token:
 error_msg = error_msg.replace(token, "***")
 return Response(
 {
 "success": False,
 "error": f"连接失败: {error_msg}",
 }
 )
 except subprocess.TimeoutExpired:
 return Response(
 {
 "success": False,
 "error": "连接超时，请检查网络或代理配置",
 }
 )
 except Exception as e:
 return Response(
 {
 "success": False,
 "error": f"连接测试失败: {e!s}",
 }
 )
