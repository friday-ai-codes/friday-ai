from __future__ import annotations
import re
from pathlib import Path
from mcp_tools.serializers import TOOL_SCHEMA_SNAPSHOT
REPO_ROOT = Path(__file__).resolve.parents[3]
SKILL_DIR = REPO_ROOT / ".codex" / "skills" / "friday-codebase-agent"
def _read(relative_path: str) -> str:
 return (SKILL_DIR / relative_path).read_text(encoding="utf-8")
def test_friday_codebase_agent_skill_metadata_and_workflows -> None:
 skill = _read("SKILL.md")
 assert "[TODO" not in skill
 assert "name: friday-codebase-agent" in skill
 assert "description:" in skill
 for workflow in ("discover", "analyze", "plan", "improve", "execute", "full_auto"):
 assert re.search(rf"`{workflow}`", skill)
 for reference in (
 "references/mcp-tools.md",
 "references/workflows.md",
 "references/examples.md",
 "references/uat.md",
 ):
 assert reference in skill
def test_friday_codebase_agent_documents_all_mcp_tools -> None:
 tool_reference = _read("references/mcp-tools.md")
 guide = (REPO_ROOT / "docs" / "guide" / "friday-codebase-agent.md").read_text(
 encoding="utf-8"
 )
 assert "[TODO" not in tool_reference
 for tool_name in TOOL_SCHEMA_SNAPSHOT:
 assert f"`{tool_name}`" in tool_reference
 assert f"`{tool_name}`" in guide
def test_full_auto_uat_requires_trace_reuse_and_end_to_end_path -> None:
 workflows = _read("references/workflows.md")
 uat = _read("references/uat.md")
 required_steps = [
 "route_repositories",
 "search_rag_chunks",
 "analyze_repository",
 "create_coding_plan",
 "execute_coding_plan",
 "get_coding_execution",
 "summarize_branch",
 "create_merge_request",
 ]
 for step in required_steps:
 assert f"`{step}`" in workflows
 assert f"`{step}`" in uat
 assert "X-Friday-Run-ID" in workflows
 assert "All tool calls in the workflow share one `run_id`." in uat
