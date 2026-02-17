"""Tests for TechnicalPlanSchema validation."""
from workflows.schemas import (
 TECHNICAL_PLAN_JSON_SCHEMA,
 ExecutionTask,
 TaskFile,
 TechnicalPlan,
 dict_to_technical_plan,
 validate_technical_plan,
)
class TestValidateTechnicalPlan:
 """Tests for validate_technical_plan function."""
 def test_valid_plan_passes(self) -> None:
 """Valid plan with all required fields passes validation."""
 valid_plan = {
 "title": "Test Plan",
 "summary": "Test summary for the plan",
 "created_at": "2026-02-03",
 "projects": [{"id": "1", "name": "test-project", "repository_count": 2}],
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "description": "Do something",
 "repository_id": "repo-1",
 "repository_name": "test-repo",
 "branch_strategy": "feature",
 }
 ],
 }
 is_valid, error = validate_technical_plan(valid_plan)
 assert is_valid is True
 assert error is None
 def test_valid_plan_with_all_optional_fields(self) -> None:
 """Valid plan with all optional fields passes validation."""
 valid_plan = {
 "title": "Complete Plan",
 "summary": "A complete test plan",
 "created_at": "2026-02-03T10:00:00Z",
 "projects": [{"id": "proj-1", "name": "my-project"}],
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Implement feature",
 "description": "Detailed description",
 "repository_id": "repo-123",
 "repository_name": "backend-service",
 "branch_strategy": "feature",
 "coding_instruction": "Use the existing pattern in utils.py",
 "files": [
 {
 "path": "src/feature.py",
 "action": "create",
 "description": "New feature module",
 },
 {
 "path": "src/utils.py",
 "action": "modify",
 "description": "Add helper function",
 },
 ],
 "dependencies":,
 "estimated_hours": 4.5,
 "priority": 1,
 }
 ],
 "total_tasks": 1,
 "estimated_total_hours": 4.5,
 "risks": ["API might change", "Dependency conflicts"],
 "assumptions": ["Python 3.14 available"],
 "global_context": "This is a refactoring project",
 }
 is_valid, error = validate_technical_plan(valid_plan)
 assert is_valid is True
 assert error is None
 def test_missing_title_fails(self) -> None:
 """Plan missing required 'title' field fails validation."""
 invalid_plan = {
 "summary": "Test summary",
 "execution_plan":,
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "title" in error
 def test_missing_summary_fails(self) -> None:
 """Plan missing required 'summary' field fails validation."""
 invalid_plan = {
 "title": "Test",
 "execution_plan":,
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "summary" in error
 def test_missing_execution_plan_fails(self) -> None:
 """Plan missing required 'execution_plan' field fails validation."""
 invalid_plan = {
 "title": "Test",
 "summary": "Test summary",
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "execution_plan" in error
 def test_missing_repository_id_fails(self) -> None:
 """Task missing required 'repository_id' field fails validation."""
 invalid_plan = {
 "title": "Test",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "repository_name": "test-repo",
 "branch_strategy": "feature",
 # Missing repository_id
 }
 ],
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "repository_id" in error
 def test_missing_branch_strategy_fails(self) -> None:
 """Task missing required 'branch_strategy' field fails validation."""
 invalid_plan = {
 "title": "Test",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "repository_id": "repo-1",
 "repository_name": "test-repo",
 # Missing branch_strategy
 }
 ],
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "branch_strategy" in error
 def test_invalid_branch_strategy_fails(self) -> None:
 """Task with invalid 'branch_strategy' value fails validation."""
 invalid_plan = {
 "title": "Test",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "repository_id": "repo-1",
 "repository_name": "test-repo",
 "branch_strategy": "invalid-strategy", # Not in enum
 }
 ],
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 assert "invalid-strategy" in error or "branch_strategy" in error
 def test_empty_execution_plan_allowed(self) -> None:
 """Empty execution_plan is allowed (outline mode)."""
 valid_plan = {
 "title": "Outline Plan",
 "summary": "Just an outline, no tasks yet",
 "execution_plan":,
 }
 is_valid, error = validate_technical_plan(valid_plan)
 assert is_valid is True
 assert error is None
 def test_invalid_file_action_fails(self) -> None:
 """File with invalid 'action' value fails validation."""
 invalid_plan = {
 "title": "Test",
 "summary": "Test summary",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "repository_id": "repo-1",
 "repository_name": "test-repo",
 "branch_strategy": "feature",
 "files": [
 {
 "path": "src/file.py",
 "action": "rename", # Not in enum
 }
 ],
 }
 ],
 }
 is_valid, error = validate_technical_plan(invalid_plan)
 assert is_valid is False
 assert error is not None
 def test_all_branch_strategies_valid(self) -> None:
 """All valid branch_strategy values pass validation."""
 for strategy in ["feature", "hotfix", "release"]:
 valid_plan = {
 "title": "Test",
 "summary": "Test",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task 1",
 "repository_id": "repo-1",
 "repository_name": "test-repo",
 "branch_strategy": strategy,
 }
 ],
 }
 is_valid, error = validate_technical_plan(valid_plan)
 assert is_valid is True, f"Strategy '{strategy}' should be valid"
class TestDictToTechnicalPlan:
 """Tests for dict_to_technical_plan conversion function."""
 def test_converts_minimal_plan(self) -> None:
 """Converts minimal valid plan to TechnicalPlan dataclass."""
 data = {
 "title": "Minimal Plan",
 "summary": "A minimal plan",
 "execution_plan":,
 }
 plan = dict_to_technical_plan(data)
 assert isinstance(plan, TechnicalPlan)
 assert plan.title == "Minimal Plan"
 assert plan.summary == "A minimal plan"
 assert plan.execution_plan ==
 assert plan.total_tasks == 0
 assert plan.risks ==
 assert plan.assumptions ==
 def test_converts_full_plan(self) -> None:
 """Converts full plan with all fields to TechnicalPlan dataclass."""
 data = {
 "title": "Full Plan",
 "summary": "A complete plan",
 "created_at": "2026-02-03",
 "projects": [{"id": "1", "name": "project-a"}],
 "execution_plan": [
 {
 "id": "task-1",
 "name": "First Task",
 "description": "Do the first thing",
 "repository_id": "repo-1",
 "repository_name": "backend",
 "branch_strategy": "feature",
 "coding_instruction": "Follow TDD",
 "files": [
 {"path": "src/main.py", "action": "create", "description": "Main module"}
 ],
 "dependencies":,
 "estimated_hours": 2.0,
 "priority": 1,
 }
 ],
 "total_tasks": 1,
 "estimated_total_hours": 2.0,
 "risks": ["Tight deadline"],
 "assumptions": ["API stable"],
 "global_context": "Greenfield project",
 }
 plan = dict_to_technical_plan(data)
 assert plan.title == "Full Plan"
 assert plan.created_at == "2026-02-03"
 assert len(plan.projects) == 1
 assert plan.projects[0]["name"] == "project-a"
 assert len(plan.execution_plan) == 1
 task = plan.execution_plan[0]
 assert isinstance(task, ExecutionTask)
 assert task.id == "task-1"
 assert task.name == "First Task"
 assert task.repository_id == "repo-1"
 assert task.branch_strategy == "feature"
 assert task.coding_instruction == "Follow TDD"
 assert len(task.files) == 1
 file = task.files[0]
 assert isinstance(file, TaskFile)
 assert file.path == "src/main.py"
 assert file.action == "create"
 assert file.description == "Main module"
 assert plan.risks == ["Tight deadline"]
 assert plan.assumptions == ["API stable"]
 assert plan.global_context == "Greenfield project"
 def test_handles_missing_optional_fields(self) -> None:
 """Handles missing optional fields with defaults."""
 data = {
 "title": "Sparse Plan",
 "summary": "Plan with minimal data",
 "execution_plan": [
 {
 "id": "task-1",
 "name": "Task",
 "repository_id": "repo-1",
 "repository_name": "repo",
 "branch_strategy": "hotfix",
 }
 ],
 }
 plan = dict_to_technical_plan(data)
 assert plan.created_at == ""
 assert plan.projects ==
 assert plan.global_context == ""
 task = plan.execution_plan[0]
 assert task.description == ""
 assert task.coding_instruction == ""
 assert task.files ==
 assert task.dependencies ==
 assert task.estimated_hours == 0
 assert task.priority == 1
class TestJsonSchema:
 """Tests for TECHNICAL_PLAN_JSON_SCHEMA constant."""
 def test_schema_has_required_structure(self) -> None:
 """Schema has expected top-level structure."""
 assert "$schema" in TECHNICAL_PLAN_JSON_SCHEMA
 assert "title" in TECHNICAL_PLAN_JSON_SCHEMA
 assert "type" in TECHNICAL_PLAN_JSON_SCHEMA
 assert TECHNICAL_PLAN_JSON_SCHEMA["type"] == "object"
 def test_schema_defines_required_fields(self) -> None:
 """Schema defines required fields correctly."""
 required = TECHNICAL_PLAN_JSON_SCHEMA["required"]
 assert "title" in required
 assert "summary" in required
 assert "execution_plan" in required
 def test_execution_task_schema_has_branch_strategy_enum(self) -> None:
 """Execution task schema includes branch_strategy enum."""
 task_schema = TECHNICAL_PLAN_JSON_SCHEMA["properties"]["execution_plan"]["items"]
 branch_strategy = task_schema["properties"]["branch_strategy"]
 assert "enum" in branch_strategy
 assert set(branch_strategy["enum"]) == {"feature", "hotfix", "release"}
