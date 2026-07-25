"""Git Pull Request operations nodes."""

import asyncio
from typing import Any, TypedDict

import structlog

from repositories.models import Repository
from services.git_credentials import aresolve_git_token
from services.git_platform import MRCreateRequest, MRCreateResult, get_git_platform_client
from services.git_platform.models import MergeRequestLookupFailed
from workflows.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeCategory,
    NodePort,
    NodeResult,
    PortType,
    normalize_repositories,
)
from workflows.nodes.registry import register_node

logger = structlog.get_logger()


class PRSuccessResult(TypedDict):
    """Successful PR creation result."""

    repository_id: str
    repository_name: str
    pr_url: str
    pr_id: str
    has_conflicts: bool
    cross_referenced: bool


class PRFailureResult(TypedDict):
    """Failed PR creation result."""

    repository_id: str
    repository_name: str
    error: str


class PRCreateResult(TypedDict, total=False):
    """Internal PR creation result for parallel processing."""

    repository_id: str
    repository_name: str
    pr_url: str
    pr_id: str
    has_conflicts: bool
    success: bool
    error: str


@register_node
class CreatePRNode(BaseNode):
    """创建 Pull Request 节点

    支持多仓库并行创建 PR/MR，并添加交叉引用链接。
    """

    node_type = "create_pr"
    display_name = "创建 PR"
    description = "创建 GitHub/GitLab Pull Request（支持多仓库）"
    icon = "git-pull-request"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "repositories": {
                "oneOf": [
                    {"type": "array", "items": {"type": ["string", "object"]}},
                    {"type": "string"},
                ],
                "title": "仓库列表",
                "description": "要创建 PR 的仓库列表，支持模板变量",
            },
            "repository_path": {
                "type": "string",
                "title": "仓库路径（已废弃）",
                "description": "Git 仓库的本地路径，向后兼容",
            },
            "title": {
                "type": "string",
                "title": "PR 标题",
                "description": "Pull Request 标题，支持模板变量",
            },
            "body": {
                "type": "string",
                "title": "PR 描述",
                "description": "Pull Request 描述内容，支持模板变量",
                "default": "",
            },
            "base_branch": {
                "type": "string",
                "title": "目标分支",
                "description": "合并到哪个分支",
                "default": "main",
            },
            "head_branch": {
                "type": "string",
                "title": "源分支",
                "description": "从哪个分支合并",
            },
            "draft": {
                "type": "boolean",
                "title": "草稿 PR",
                "default": False,
            },
            "labels": {
                "type": "array",
                "title": "标签",
                "items": {"type": "string"},
                "default": [],
            },
            "reviewers": {
                "type": "array",
                "title": "审核人",
                "items": {"type": "string"},
                "default": [],
            },
            "add_cross_references": {
                "type": "boolean",
                "title": "添加交叉引用",
                "description": "在 PR 描述中添加关联 PR 链接",
                "default": True,
            },
        },
        "required": ["title", "head_branch"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def _create_pr_for_repository(
        self,
        repository: Repository,
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
        reviewers: list[str],
    ) -> PRCreateResult:
        """Create a PR for a single repository.

        Args:
            repository: Repository model instance.
            title: PR title.
            body: PR description.
            base_branch: Target branch.
            head_branch: Source branch.
            reviewers: List of reviewer usernames.

        Returns:
            PRCreateResult with success status or error.
        """
        repo_id = str(repository.id)
        repo_name = repository.name

        try:
            # 经统一解析器取 token：per-repo 优先 → host 实例池 fallback（D-02）
            token = await aresolve_git_token(repository)
            if not token:
                return PRCreateResult(
                    repository_id=repo_id,
                    repository_name=repo_name,
                    success=False,
                    error="No access token configured for repository",
                )

            # Get platform client
            client = get_git_platform_client(repository, token)

            # Create MR request
            request = MRCreateRequest(
                source_branch=head_branch,
                target_branch=base_branch,
                title=title,
                description=body,
                reviewer_usernames=reviewers,
            )

            # 创建前先查同 source→target 的 open PR/MR（与 AICodingNode 的 IDEMP-02
            # 同一围栏）。此前本节点完全没有去重：节点重试、手动 re-run、或 runner
            # 超时重投都会在同一对分支上再开一个 PR，连带交叉引用、飞书通知、review
            # 沉淀一起重复。查重失败显式中止而不是当「无命中」继续——后者正是重复件
            # 的来源；重试时查重恢复就会命中既有 PR。
            try:
                existing = await client.find_open_merge_request(head_branch, base_branch)
            except MergeRequestLookupFailed as e:
                logger.warning(
                    "pr_dedup_lookup_failed",
                    repository_id=repo_id,
                    repository_name=repo_name,
                    error=str(e),
                )
                return PRCreateResult(
                    repository_id=repo_id,
                    repository_name=repo_name,
                    success=False,
                    error=f"PR 去重查询失败，为避免重复创建已中止（可重试）: {e}",
                )
            if existing and existing.success:
                logger.info(
                    "pr_dedup_reuse_existing",
                    repository_id=repo_id,
                    repository_name=repo_name,
                    pr_url=existing.mr_url,
                    pr_id=existing.mr_id,
                )
                return PRCreateResult(
                    repository_id=repo_id,
                    repository_name=repo_name,
                    pr_url=existing.mr_url,
                    pr_id=existing.mr_id,
                    has_conflicts=False,
                    success=True,
                )

            # Create PR
            result: MRCreateResult = await client.create_merge_request(request)

            if result.success:
                logger.info(
                    "pr_created",
                    repository_id=repo_id,
                    repository_name=repo_name,
                    pr_url=result.mr_url,
                    pr_id=result.mr_id,
                )
                return PRCreateResult(
                    repository_id=repo_id,
                    repository_name=repo_name,
                    pr_url=result.mr_url,
                    pr_id=result.mr_id,
                    has_conflicts=result.has_conflicts,
                    success=True,
                )
            else:
                logger.error(
                    "pr_creation_failed",
                    repository_id=repo_id,
                    repository_name=repo_name,
                    error=result.error,
                )
                return PRCreateResult(
                    repository_id=repo_id,
                    repository_name=repo_name,
                    success=False,
                    error=result.error,
                )

        except Exception as e:
            error_msg = str(e)
            logger.error(
                "pr_creation_error",
                repository_id=repo_id,
                repository_name=repo_name,
                error=error_msg,
            )
            return PRCreateResult(
                repository_id=repo_id,
                repository_name=repo_name,
                success=False,
                error=error_msg,
            )

    async def _create_prs_parallel(
        self,
        repositories: list[Repository],
        title: str,
        body: str,
        base_branch: str,
        head_branch: str,
        reviewers: list[str],
    ) -> list[PRCreateResult]:
        """Create PRs in parallel for all repositories.

        Args:
            repositories: List of Repository model instances.
            title: PR title.
            body: PR description.
            base_branch: Target branch.
            head_branch: Source branch.
            reviewers: List of reviewer usernames.

        Returns:
            List of PRCreateResult for each repository.
        """
        tasks = [
            self._create_pr_for_repository(
                repo, title, body, base_branch, head_branch, reviewers
            )
            for repo in repositories
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results: list[PRCreateResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                repo = repositories[i]
                processed_results.append(
                    PRCreateResult(
                        repository_id=str(repo.id),
                        repository_name=repo.name,
                        success=False,
                        error=str(result),
                    )
                )
            else:
                processed_results.append(result)

        return processed_results

    def _generate_cross_reference_section(
        self,
        current_pr_url: str,
        all_successful_results: list[PRCreateResult],
    ) -> str:
        """Generate Markdown section with links to related PRs.

        Args:
            current_pr_url: URL of the current PR (to exclude from list).
            all_successful_results: All successful PR results.

        Returns:
            Markdown formatted cross-reference section.
        """
        other_prs = [r for r in all_successful_results if r.get("pr_url") != current_pr_url]

        if not other_prs:
            return ""

        lines = ["\n---", "## Related PRs", ""]
        for pr in other_prs:
            repo_name = pr.get("repository_name", "unknown")
            pr_url = pr.get("pr_url", "")
            lines.append(f"- [{repo_name}]({pr_url})")

        return "\n".join(lines)

    async def _add_cross_references(
        self,
        successful_results: list[PRCreateResult],
        repositories_by_id: dict[str, Repository],
        original_body: str,
    ) -> dict[str, bool]:
        """Add cross-references to all successful PRs.

        Updates each PR's description with links to related PRs.

        Args:
            successful_results: List of successful PR results.
            repositories_by_id: Dict mapping repository ID to Repository.
            original_body: Original PR body.

        Returns:
            Dict mapping pr_url to cross_referenced status.
        """
        cross_ref_status: dict[str, bool] = {}

        async def update_single_pr(result: PRCreateResult) -> tuple[str, bool]:
            pr_url = result.get("pr_url", "")
            repo_id = result.get("repository_id", "")

            try:
                repository = repositories_by_id.get(repo_id)
                if not repository:
                    logger.warning(
                        "cross_reference_skip_no_repo",
                        pr_url=pr_url,
                        repository_id=repo_id,
                    )
                    return pr_url, False

                # Generate cross-reference section
                cross_ref_section = self._generate_cross_reference_section(
                    pr_url, successful_results
                )

                if not cross_ref_section:
                    return pr_url, False

                # Build new body with cross-references
                new_body = original_body + cross_ref_section

                # 经统一解析器取 token：per-repo 优先 → host 实例池 fallback（D-02）
                token = await aresolve_git_token(repository)
                if not token:
                    logger.warning(
                        "cross_reference_skip_no_token",
                        pr_url=pr_url,
                        repository_id=repo_id,
                    )
                    return pr_url, False

                client = get_git_platform_client(repository, token)

                # Update PR description based on platform
                pr_id = result.get("pr_id", "")

                # Use platform-specific update method
                if hasattr(client, "_get_repo"):
                    # GitHub client
                    repo_obj = client._get_repo()
                    pr = await asyncio.to_thread(repo_obj.get_pull, int(pr_id))
                    await asyncio.to_thread(pr.edit, body=new_body)
                elif hasattr(client, "_get_project"):
                    # GitLab client
                    project = client._get_project()
                    mr = await asyncio.to_thread(project.mergerequests.get, int(pr_id))
                    mr.description = new_body
                    await asyncio.to_thread(mr.save)
                else:
                    logger.warning(
                        "cross_reference_unknown_platform",
                        pr_url=pr_url,
                        repository_id=repo_id,
                    )
                    return pr_url, False

                logger.info(
                    "cross_reference_added",
                    pr_url=pr_url,
                    repository_name=result.get("repository_name"),
                )
                return pr_url, True

            except Exception as e:
                logger.warning(
                    "cross_reference_failed",
                    pr_url=pr_url,
                    error=str(e),
                )
                return pr_url, False

        # Update all PRs in parallel
        update_tasks = [update_single_pr(r) for r in successful_results]
        update_results = await asyncio.gather(*update_tasks, return_exceptions=True)

        for update_result in update_results:
            if isinstance(update_result, BaseException):
                logger.warning("cross_reference_task_error", error=str(update_result))
            else:
                pr_url, status = update_result
                cross_ref_status[pr_url] = status

        return cross_ref_status

    async def execute(self, context: ExecutionContext) -> NodeResult:
        config = context.node_config

        title = context.render_template(config.get("title", ""))
        body = context.render_template(config.get("body", ""))
        base_branch = config.get("base_branch", "main")
        head_branch = context.render_template(config.get("head_branch", ""))
        reviewers = config.get("reviewers", [])
        add_cross_references = config.get("add_cross_references", True)

        if not title or not head_branch:
            return NodeResult(
                status="failed",
                error="PR 标题和源分支不能为空",
                next_handle="error",
            )

        # Normalize repositories configuration
        repo_configs = normalize_repositories(config, context)

        if not repo_configs:
            return NodeResult(
                status="failed",
                error="未配置仓库列表",
                next_handle="error",
            )

        # Extract repository IDs
        repo_ids = [r.get("id") for r in repo_configs if r.get("id")]

        if not repo_ids:
            return NodeResult(
                status="failed",
                error="仓库配置中缺少 id 字段",
                next_handle="error",
            )

        # Fetch repositories from database
        repositories = [
            r async for r in Repository.objects.filter(id__in=repo_ids, is_deleted=False)
        ]

        if not repositories:
            return NodeResult(
                status="failed",
                error=f"未找到有效的仓库: {repo_ids}",
                next_handle="error",
            )

        # Build lookup dict
        repositories_by_id = {str(r.id): r for r in repositories}

        # Phase: Create PRs in parallel
        logger.info(
            "batch_pr_start",
            total_repositories=len(repositories),
            title=title,
            head_branch=head_branch,
            base_branch=base_branch,
        )

        results = await self._create_prs_parallel(
            repositories, title, body, base_branch, head_branch, reviewers
        )

        # Separate successful and failed results
        successful: list[PRCreateResult] = [r for r in results if r.get("success")]
        failed: list[PRCreateResult] = [r for r in results if not r.get("success")]

        # Phase: Add cross-references if enabled and multiple PRs succeeded
        cross_ref_status: dict[str, bool] = {}
        if add_cross_references and len(successful) > 1:
            logger.info(
                "batch_pr_cross_reference_start",
                successful_count=len(successful),
            )
            cross_ref_status = await self._add_cross_references(
                successful, repositories_by_id, body
            )

        # Build output
        succeeded_output: list[PRSuccessResult] = []
        for r in successful:
            pr_url = r.get("pr_url", "")
            succeeded_output.append(
                PRSuccessResult(
                    repository_id=r.get("repository_id", ""),
                    repository_name=r.get("repository_name", ""),
                    pr_url=pr_url,
                    pr_id=r.get("pr_id", ""),
                    has_conflicts=r.get("has_conflicts", False),
                    cross_referenced=cross_ref_status.get(pr_url, False),
                )
            )

        failed_output: list[PRFailureResult] = []
        for r in failed:
            failed_output.append(
                PRFailureResult(
                    repository_id=r.get("repository_id", ""),
                    repository_name=r.get("repository_name", ""),
                    error=r.get("error", "Unknown error"),
                )
            )

        output: dict[str, Any] = {
            "title": title,
            "base_branch": base_branch,
            "head_branch": head_branch,
            "total": len(repositories),
            "succeeded": succeeded_output,
            "failed": failed_output,
            "all_succeeded": len(failed_output) == 0,
        }

        logger.info(
            "batch_pr_complete",
            total=len(repositories),
            succeeded=len(succeeded_output),
            failed=len(failed_output),
        )

        # Return success if at least one PR was created
        if succeeded_output:
            return NodeResult(
                status="completed",
                output=output,
                next_handle="default",
            )
        else:
            return NodeResult(
                status="failed",
                output=output,
                error="所有仓库创建 PR 均失败",
                next_handle="error",
            )


@register_node
class MergePRNode(BaseNode):
    """合并 Pull Request 节点

    使用 GitHub CLI (gh) 合并 Pull Request。
    """

    node_type = "merge_pr"
    display_name = "合并 PR"
    description = "合并 GitHub Pull Request"
    icon = "git-merge"
    category = NodeCategory.ACTION
    execution_mode = "server_local"

    config_schema = {
        "type": "object",
        "properties": {
            "repository_path": {
                "type": "string",
                "title": "仓库路径",
                "description": "Git 仓库的本地路径",
            },
            "pr_number": {
                "type": ["integer", "string"],
                "title": "PR 编号",
                "description": "要合并的 PR 编号，支持模板变量",
            },
            "merge_method": {
                "type": "string",
                "title": "合并方式",
                "enum": ["merge", "squash", "rebase"],
                "default": "squash",
            },
            "delete_branch": {
                "type": "boolean",
                "title": "删除源分支",
                "default": True,
            },
            "auto_merge": {
                "type": "boolean",
                "title": "自动合并",
                "description": "当所有检查通过后自动合并",
                "default": False,
            },
        },
        "required": ["repository_path", "pr_number"],
    }

    inputs = [NodePort(name="default", label="输入", port_type=PortType.OBJECT)]
    outputs = [
        NodePort(name="default", label="成功", port_type=PortType.OBJECT),
        NodePort(name="error", label="失败", port_type=PortType.OBJECT),
    ]

    async def execute(self, context: ExecutionContext) -> NodeResult:
        import subprocess

        config = context.node_config

        repo_path = context.render_template(config.get("repository_path", ""))
        pr_number = context.render_template(str(config.get("pr_number", "")))
        merge_method = config.get("merge_method", "squash")
        delete_branch = config.get("delete_branch", True)
        auto_merge = config.get("auto_merge", False)

        if not repo_path or not pr_number:
            return NodeResult(
                status="failed",
                error="仓库路径和 PR 编号不能为空",
                next_handle="error",
            )

        try:
            if auto_merge:
                # Enable auto-merge
                cmd = [
                    "gh",
                    "pr",
                    "merge",
                    pr_number,
                    "--auto",
                    f"--{merge_method}",
                ]
            else:
                # Direct merge
                cmd = [
                    "gh",
                    "pr",
                    "merge",
                    pr_number,
                    f"--{merge_method}",
                ]

            if delete_branch:
                cmd.append("--delete-branch")

            result = subprocess.run(
                cmd,
                cwd=repo_path,
                check=True,
                capture_output=True,
                text=True,
            )

            return NodeResult(
                status="completed",
                output={
                    "pr_number": pr_number,
                    "merge_method": merge_method,
                    "deleted_branch": delete_branch,
                    "auto_merge": auto_merge,
                    "message": result.stdout.strip(),
                },
                next_handle="default",
            )

        except subprocess.CalledProcessError as e:
            return NodeResult(
                status="failed",
                error=f"合并 PR 失败: {e.stderr or str(e)}",
                next_handle="error",
            )
        except Exception as e:
            return NodeResult(
                status="failed",
                error=str(e),
                next_handle="error",
            )
