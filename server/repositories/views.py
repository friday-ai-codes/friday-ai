"""Repositories views."""
from common.encryption import encrypt_value
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from .models import AuthType, GitCredential, Repository
from .serializers import (
 GitCredentialSerializer,
 RepositoryCreateSerializer,
 RepositorySerializer,
 RepositoryWithProjectsSerializer,
)
class RepositoryViewSet(ModelViewSet):
 """ViewSet for Repository CRUD operations."""
 queryset = Repository.objects.select_related("credential").prefetch_related("projects").all
 serializer_class = RepositorySerializer
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
class SetAccessTokenView(APIView):
 """View for setting or updating access token."""
 def post(self, request, repository_id):
 repository = get_object_or_404(Repository, id=repository_id)
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
