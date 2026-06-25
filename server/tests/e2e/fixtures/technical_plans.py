"""Technical plan test data for E2E testing.

Provides valid technical plan fixtures that match TechnicalPlanSchema
for testing the full workflow from plan generation to task dispatch.
"""

from typing import Any

# A complete valid technical plan matching TechnicalPlanSchema
VALID_TECHNICAL_PLAN: dict[str, Any] = {
    "title": "用户认证模块重构",
    "summary": "重构现有用户认证模块，添加 JWT 刷新令牌支持和多因素认证功能",
    "created_at": "2026-02-03",
    "projects": [
        {
            "id": "proj-001",
            "name": "Friday Backend",
            "repository_count": 1,
        }
    ],
    "execution_plan": [
        {
            "id": "task-001",
            "name": "添加 JWT 刷新令牌支持",
            "description": "实现 JWT 刷新令牌的生成、存储和验证逻辑",
            "repository_id": "repo-001",
            "repository_name": "friday-backend",
            "branch_strategy": "feature",
            "coding_instruction": """实现 JWT 刷新令牌功能：

1. 在 accounts/models.py 中添加 RefreshToken 模型
2. 在 accounts/views.py 中添加 /api/auth/refresh/ 端点
3. 添加令牌轮换逻辑，每次刷新时失效旧令牌
4. 设置刷新令牌 7 天有效期

注意：确保令牌存储使用加密字段""",
            "files": [
                {
                    "path": "accounts/models.py",
                    "action": "modify",
                    "description": "添加 RefreshToken 模型",
                },
                {
                    "path": "accounts/views.py",
                    "action": "modify",
                    "description": "添加刷新令牌端点",
                },
                {
                    "path": "accounts/serializers.py",
                    "action": "modify",
                    "description": "添加刷新令牌序列化器",
                },
            ],
            "dependencies": [],
            "estimated_hours": 4,
            "priority": 1,
        },
        {
            "id": "task-002",
            "name": "实现多因素认证",
            "description": "添加 TOTP 多因素认证支持",
            "repository_id": "repo-001",
            "repository_name": "friday-backend",
            "branch_strategy": "feature",
            "coding_instruction": """实现 TOTP 多因素认证：

1. 添加 pyotp 依赖
2. 在 accounts/models.py 添加 MFADevice 模型
3. 实现 /api/auth/mfa/setup/ 端点生成密钥和二维码
4. 实现 /api/auth/mfa/verify/ 端点验证 TOTP 码
5. 修改登录流程支持 MFA 验证

安全注意：密钥必须加密存储""",
            "files": [
                {
                    "path": "accounts/models.py",
                    "action": "modify",
                    "description": "添加 MFADevice 模型",
                },
                {
                    "path": "accounts/views.py",
                    "action": "modify",
                    "description": "添加 MFA 相关端点",
                },
                {
                    "path": "requirements.txt",
                    "action": "modify",
                    "description": "添加 pyotp 依赖",
                },
            ],
            "dependencies": ["task-001"],
            "estimated_hours": 6,
            "priority": 2,
        },
    ],
    "total_tasks": 2,
    "estimated_total_hours": 10,
    "risks": [
        "刷新令牌泄露可能导致长期会话劫持",
        "MFA 密钥丢失可能导致用户无法登录",
    ],
    "assumptions": [
        "用户已有基本的认证系统",
        "数据库支持加密字段存储",
    ],
    "global_context": "这是 Friday 项目的认证模块重构，目标是提升安全性和用户体验。",
}


def create_technical_plan(
    repository_id: str,
    repository_name: str,
    task_count: int = 1,
    branch_strategy: str = "feature",
    **overrides: Any,
) -> dict[str, Any]:
    """Create a valid technical plan with customizable parameters.

    Args:
        repository_id: Target repository ID for tasks
        repository_name: Target repository name
        task_count: Number of tasks to generate
        branch_strategy: Branch strategy for all tasks
        **overrides: Override any top-level plan fields

    Returns:
        Dictionary matching TechnicalPlanSchema
    """
    # Generate tasks
    tasks = []
    for i in range(task_count):
        task_id = f"task-{i + 1:03d}"
        tasks.append(
            {
                "id": task_id,
                "name": f"任务 {i + 1}",
                "description": f"测试任务 {i + 1} 的详细描述",
                "repository_id": repository_id,
                "repository_name": repository_name,
                "branch_strategy": branch_strategy,
                "coding_instruction": f"完成任务 {i + 1} 的具体编码指令",
                "files": [
                    {
                        "path": f"src/module_{i + 1}/main.py",
                        "action": "create",
                        "description": f"模块 {i + 1} 主文件",
                    },
                    {
                        "path": f"tests/test_module_{i + 1}.py",
                        "action": "create",
                        "description": f"模块 {i + 1} 测试文件",
                    },
                ],
                "dependencies": [f"task-{i:03d}"] if i > 0 else [],
                "estimated_hours": 2,
                "priority": i + 1,
            }
        )

    plan: dict[str, Any] = {
        "title": "测试技术方案",
        "summary": f"包含 {task_count} 个任务的测试技术方案",
        "created_at": "2026-02-03",
        "projects": [
            {
                "id": "test-project",
                "name": "Test Space",
                "repository_count": 1,
            }
        ],
        "execution_plan": tasks,
        "total_tasks": task_count,
        "estimated_total_hours": task_count * 2,
        "risks": ["测试风险"],
        "assumptions": ["测试假设"],
        "global_context": "测试项目上下文",
    }

    # Apply overrides
    plan.update(overrides)

    return plan


def create_multi_repo_plan(
    repositories: list[tuple[str, str]],
    tasks_per_repo: int = 1,
) -> dict[str, Any]:
    """Create a technical plan spanning multiple repositories.

    Args:
        repositories: List of (repository_id, repository_name) tuples
        tasks_per_repo: Number of tasks per repository

    Returns:
        Dictionary matching TechnicalPlanSchema with multi-repo tasks
    """
    tasks = []
    task_num = 1

    for repo_id, repo_name in repositories:
        for i in range(tasks_per_repo):
            tasks.append(
                {
                    "id": f"task-{task_num:03d}",
                    "name": f"{repo_name} 任务 {i + 1}",
                    "description": f"针对 {repo_name} 的任务 {i + 1}",
                    "repository_id": repo_id,
                    "repository_name": repo_name,
                    "branch_strategy": "feature",
                    "coding_instruction": f"在 {repo_name} 中完成任务 {i + 1}",
                    "files": [
                        {
                            "path": f"src/feature_{task_num}.py",
                            "action": "create",
                            "description": f"功能 {task_num}",
                        }
                    ],
                    "dependencies": [],
                    "estimated_hours": 2,
                    "priority": task_num,
                }
            )
            task_num += 1

    total_tasks = len(tasks)

    return {
        "title": "多仓库技术方案",
        "summary": f"跨 {len(repositories)} 个仓库的技术方案，共 {total_tasks} 个任务",
        "created_at": "2026-02-03",
        "projects": [
            {
                "id": "multi-repo-project",
                "name": "Multi-Repo Space",
                "repository_count": len(repositories),
            }
        ],
        "execution_plan": tasks,
        "total_tasks": total_tasks,
        "estimated_total_hours": total_tasks * 2,
        "risks": [],
        "assumptions": [],
        "global_context": "多仓库项目上下文",
    }
