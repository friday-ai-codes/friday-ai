# AI Development Automation Specification
## ADDED Requirements
### Requirement: Project Management
The system SHALL provide project configuration management, including Git repository URL, platform type (GitHub/GitLab/Gitea/Bitbucket), default branch, and developer-notes.md path.
#### Scenario: Create project with Git configuration
- **WHEN** user creates a new project with name, repo_url, and git_platform
- **THEN** the system creates a project record with unique ID
- **AND** the project is available for task assignment
#### Scenario: Update project configuration
- **WHEN** user updates project settings (default_branch, claude_md_path)
- **THEN** the system persists the changes
- **AND** future tasks use the updated configuration
### Requirement: Git Credential Management
The system SHALL support encrypted storage of Git credentials, including SSH private keys and access tokens, with project-level isolation.
#### Scenario: Add SSH key credential
- **WHEN** user adds an SSH private key for a project
- **THEN** the system encrypts the key using Fernet symmetric encryption
- **AND** stores the encrypted value in the database
- **AND** the credential is linked to the project
#### Scenario: Add access token credential
- **WHEN** user adds an access token for a project
- **THEN** the system encrypts the token
- **AND** stores it for HTTPS Git authentication
#### Scenario: Credential decryption for task execution
- **WHEN** a task container needs Git authentication
- **THEN** the system decrypts the credential
- **AND** injects it into the container environment
### Requirement: Task State Machine
The system SHALL implement a task state machine with the following states: PENDING, PLANNING, PLAN_REVIEW, EXECUTING, CODE_REVIEW, MERGED, FAILED.
#### Scenario: Task creation
- **WHEN** a new task is created with work_item_id, feature_id, and title
- **THEN** the task starts in PENDING state
- **AND** is associated with a project
#### Scenario: Valid state transition
- **WHEN** a task transitions from PENDING to PLANNING
- **THEN** the system updates the status
- **AND** records the plan_started_at timestamp
#### Scenario: Invalid state transition
- **WHEN** a task attempts an invalid transition (e.g., PENDING → EXECUTING)
- **THEN** the system rejects the transition
- **AND** returns an error with allowed transitions
#### Scenario: Task failure handling
- **WHEN** a task transitions to FAILED state
- **THEN** the system increments retry_count
- **AND** allows reset to PENDING for retry
### Requirement: Task Execution Container
The system SHALL execute each task in an isolated Docker container with Plan and Execute modes.
#### Scenario: Start task in Plan mode
- **WHEN** task execution is triggered with mode="plan"
- **THEN** the system starts a container with task configuration
- **AND** Claude Code analyzes the codebase
- **AND** generates an implementation plan
- **AND** task transitions to PLAN_REVIEW on completion
#### Scenario: Start task in Execute mode
- **WHEN** task execution is triggered with mode="execute" after plan approval
- **THEN** the system starts a container with session restoration
- **AND** Claude Code implements the approved plan
- **AND** commits and pushes changes to a feature branch
- **AND** task transitions to CODE_REVIEW on completion
#### Scenario: Container resource isolation
- **WHEN** a task container is started
- **THEN** the container has memory limit (2GB)
- **AND** CPU limit (1 core)
- **AND** isolated network
### Requirement: Feishu Integration
The system SHALL integrate with Feishu Project (Meego) for webhook events and status updates.
#### Scenario: Webhook challenge verification
- **WHEN** Feishu sends a URL verification challenge
- **THEN** the system returns the challenge token
- **AND** confirms webhook registration
#### Scenario: Work item status change event
- **WHEN** Feishu sends a work_item_status_change event
- **THEN** the system parses the event payload
- **AND** triggers appropriate task actions based on the new status
#### Scenario: Comment feedback processing
- **WHEN** a comment is added to a Feishu work item
- **THEN** the system captures the feedback
- **AND** includes it in the task context for Claude
### Requirement: Git Operations
The system SHALL perform Git operations including clone, branch creation, commit, and push with dynamic authentication.
#### Scenario: Clone repository with SSH key
- **WHEN** Git operations start with SSH authentication
- **THEN** the system configures SSH_COMMAND with the private key
- **AND** clones the repository to the workspace
#### Scenario: Create feature branch
- **WHEN** task execution begins
- **THEN** the system creates a branch named `friday/task-{task_id}`
- **AND** checks out the new branch
#### Scenario: Commit and push changes
- **WHEN** Claude Code completes code modifications
- **THEN** the system stages all changes
- **AND** commits with a descriptive message including task ID
- **AND** pushes to the remote repository
### Requirement: Claude Code Integration
The system SHALL invoke Claude Code CLI in headless mode with session persistence.
#### Scenario: Plan mode execution
- **WHEN** Claude Code runs in plan mode
- **THEN** the system restricts tools to read-only (Read, Glob, Grep, LS)
- **AND** generates an implementation plan without modifying code
- **AND** saves the session for later resumption
#### Scenario: Execute mode with session resume
- **WHEN** Claude Code runs in execute mode with a session ID
- **THEN** the system loads the previous session context
- **AND** Claude continues with the approved plan
- **AND** uses Edit tools to modify code
#### Scenario: Execution timeout handling
- **WHEN** Claude Code execution exceeds the configured timeout
- **THEN** the system terminates the process
- **AND** reports a timeout error to the callback endpoint
### Requirement: API Callback Mechanism
The system SHALL provide callback endpoints for task containers to report status updates.
#### Scenario: Report plan completion
- **WHEN** plan generation completes successfully
- **THEN** the container calls POST /api/tasks/{id}/status with status="plan_ready"
- **AND** includes the generated plan in details
#### Scenario: Report execution completion
- **WHEN** code execution completes successfully
- **THEN** the container calls POST /api/tasks/{id}/status with status="execution_complete"
- **AND** includes branch_name, commit_sha, and diff_summary
#### Scenario: Report error
- **WHEN** task execution fails
- **THEN** the container calls POST /api/tasks/{id}/status with status="error"
- **AND** includes error message and phase information