"""Resolve runtime project ownership for inbound Feishu bot messages."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from feishu.models import FeishuBotMessage, FeishuBotThread
from projects.models import Project
@dataclass(slots=True)
class ProjectResolution:
 status: str
 project: Project | None
 candidates: list[str]
 reason: str
class ProjectResolver:
 """Resolve the project that should answer a bot question."""
 async def resolve(
 self,
 message: FeishuBotMessage,
 thread: FeishuBotThread | None = None,
 ) -> ProjectResolution:
 haystack = self._build_haystack(message).lower
 query_terms = [term for term in haystack.replace("：", " ").replace(":", " ").split if term]
 matches: list[Project] =
 projects = [
 project async for project in Project.objects.prefetch_related("repositories").all
 ]
 for project in projects:
 aliases = {project.name, project.feishu_project_key or ""}
 aliases.update(repo.name for repo in project.repositories.all)
 alias_hits = {
 alias for alias in aliases
 if alias and self._alias_matches(alias.lower, haystack, query_terms)
 }
 if alias_hits:
 matches.append(project)
 unique_matches = {project.id: project for project in matches}
 if len(unique_matches) == 1:
 project = next(iter(unique_matches.values))
 return ProjectResolution(
 status="resolved",
 project=project,
 candidates=[project.name],
 reason="explicit_alias_match",
 )
 if len(unique_matches) > 1:
 return ProjectResolution(
 status="awaiting_project_clarification",
 project=None,
 candidates=[project.name for project in unique_matches.values][:5],
 reason="ambiguous_alias_match",
 )
 if thread and thread.project_id:
 return ProjectResolution(
 status="resolved",
 project=thread.project,
 candidates=[thread.project.name] if thread.project else,
 reason="thread_project_reuse",
 )
 recent_projects = await self._recent_project_preference(message)
 if recent_projects is not None:
 return ProjectResolution(
 status="resolved",
 project=recent_projects,
 candidates=[recent_projects.name],
 reason="recent_project_preference",
 )
 candidates = [project.name for project in projects[:5]]
 return ProjectResolution(
 status="awaiting_project_clarification",
 project=None,
 candidates=candidates,
 reason="no_project_match",
 )
 @staticmethod
 def _build_haystack(message: FeishuBotMessage) -> str:
 payload = message.raw_payload or {}
 attachments: list[str] =
 content = payload.get("event", {}).get("message", {}).get("content")
 if isinstance(content, str):
 attachments.append(content)
 elif isinstance(content, dict):
 attachments.extend(str(value) for value in content.values)
 return " ".join(filter(None, [message.normalized_text, *attachments]))
 @staticmethod
 async def _recent_project_preference(message: FeishuBotMessage) -> Project | None:
 threads = [
 thread async for thread in FeishuBotThread.objects.select_related("project").filter(
 chat_id=message.chat_id,
 project__isnull=False,
 ).order_by("-updated_at")[:3]
 ]
 if not threads:
 return None
 counts: dict[Any, int] = {}
 latest: dict[Any, Project] = {}
 for thread in threads:
 if thread.project_id is None or thread.project is None:
 continue
 counts[thread.project_id] = counts.get(thread.project_id, 0) + 1
 latest[thread.project_id] = thread.project
 if len(counts) == 1:
 return next(iter(latest.values))
 top_project_id = max(counts, key=counts.get)
 if counts[top_project_id] >= 2:
 return latest[top_project_id]
 return None
 @staticmethod
 def _alias_matches(alias: str, haystack: str, query_terms: list[str]) -> bool:
 if alias in haystack:
 return True
 return any(
 min(len(term), len(alias)) >= 6 and (alias.startswith(term) or term.startswith(alias))
 for term in query_terms
 )
