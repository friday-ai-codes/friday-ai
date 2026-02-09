"""SubAgent tools for delegating tasks to Claude Code.
Provides tools for:
- explore_repository: Explore repository structure
- ask_claude_code: Ask technical questions
- generate_tech_plan_section: Generate technical plan sections
- dispatch_coding_task: Dispatch coding tasks
"""
from agents.tools.subagent.ask import ask_claude_code
from agents.tools.subagent.coding import dispatch_coding_task
from agents.tools.subagent.explore import explore_repository
from agents.tools.subagent.plan import generate_tech_plan_section
__all__ = [
 "explore_repository",
 "ask_claude_code",
 "generate_tech_plan_section",
 "dispatch_coding_task",
]
