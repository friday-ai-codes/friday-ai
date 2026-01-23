# Workflow Engine Specification
## ADDED Requirements
### Requirement: Workflow Definition
The system SHALL allow users to create and manage workflow definitions that describe automated processes as directed acyclic graphs (DAGs).
#### Scenario: Create new workflow
- **GIVEN** a user with project access
- **WHEN** the user creates a new workflow with name and description
- **THEN** the system creates an empty workflow associated with the project
- **AND** the workflow is set to inactive by default
#### Scenario: Add nodes to workflow
- **GIVEN** an existing workflow
- **WHEN** the user adds a node with type and configuration
- **THEN** the system creates the node with the specified position on the canvas
- **AND** the node configuration is validated against the node type schema
#### Scenario: Connect nodes with edges
- **GIVEN** a workflow with multiple nodes
- **WHEN** the user connects a source node to a target node
- **THEN** the system creates an edge between the nodes
- **AND** the system validates that no cycles are created
#### Scenario: Reject cyclic connections
- **GIVEN** a workflow with nodes A → B → C
- **WHEN** the user attempts to connect C → A
- **THEN** the system rejects the connection with a cycle detection error
---
### Requirement: Node Type System
The system SHALL provide an extensible node type system with predefined categories and configurable behavior.
#### Scenario: List available node types
- **WHEN** the user requests available node types
- **THEN** the system returns all registered node types
- **AND** each type includes: node_type, display_name, category, config_schema, inputs, outputs
#### Scenario: Validate node configuration
- **GIVEN** a node type with a JSON Schema configuration
- **WHEN** the user saves a node with configuration
- **THEN** the system validates the configuration against the schema
- **AND** rejects invalid configurations with specific error messages
#### Scenario: Node categories
- **WHEN** listing node types
- **THEN** nodes are organized into categories: trigger, git, ai, approval, integration, control
---
### Requirement: Workflow Execution
The system SHALL execute workflows by traversing the DAG and running nodes in dependency order.
#### Scenario: Start workflow execution
- **GIVEN** a valid workflow with at least one trigger node
- **WHEN** the user triggers execution
- **THEN** the system creates a WorkflowExecution record with status "running"
- **AND** the system starts executing entry nodes (nodes with no incoming edges)
#### Scenario: Execute nodes in order
- **GIVEN** a workflow A → B → C being executed
- **WHEN** node A completes successfully
- **THEN** node B starts execution
- **AND** node B receives the output of node A as input
#### Scenario: Parallel execution
- **GIVEN** a workflow where A → B and A → C (B and C are independent)
- **WHEN** node A completes
- **THEN** nodes B and C start executing in parallel
- **AND** both must complete before any downstream nodes start
#### Scenario: Node execution failure
- **GIVEN** a running workflow
- **WHEN** a node fails with an error
- **THEN** the node status is set to "failed"
- **AND** the error message is recorded
- **AND** downstream nodes are marked as "skipped"
- **AND** the workflow execution status is set to "failed"
---
### Requirement: Human Approval Nodes
The system SHALL support nodes that pause execution until human approval is received.
#### Scenario: Approval node pauses execution
- **GIVEN** a workflow with an approval node
- **WHEN** execution reaches the approval node
- **THEN** the node status is set to "waiting_approval"
- **AND** a notification is sent to configured approvers
- **AND** downstream nodes remain pending
#### Scenario: Approve and resume
- **GIVEN** a workflow paused at an approval node
- **WHEN** an authorized user approves the node
- **THEN** the node status changes to "completed"
- **AND** downstream nodes begin execution
#### Scenario: Reject and fail
- **GIVEN** a workflow paused at an approval node
- **WHEN** an authorized user rejects the node
- **THEN** the node status changes to "failed"
- **AND** the workflow execution is marked as "failed"
---
### Requirement: Execution Control
The system SHALL allow users to control running workflow executions.
#### Scenario: Pause execution
- **GIVEN** a running workflow execution
- **WHEN** the user requests to pause
- **THEN** currently running nodes complete
- **AND** no new nodes are started
- **AND** execution status changes to "paused"
#### Scenario: Resume execution
- **GIVEN** a paused workflow execution
- **WHEN** the user requests to resume
- **THEN** execution continues from where it was paused
- **AND** status changes to "running"
#### Scenario: Cancel execution
- **GIVEN** a running or paused workflow execution
- **WHEN** the user requests to cancel
- **THEN** running containers are stopped
- **AND** pending nodes are marked as "skipped"
- **AND** execution status changes to "cancelled"
---
### Requirement: Real-time Status Updates
The system SHALL push execution status updates to connected clients via WebSocket.
#### Scenario: Subscribe to execution updates
- **GIVEN** a workflow execution
- **WHEN** a client connects to the WebSocket endpoint
- **THEN** the client receives the current execution state
- **AND** receives subsequent node status changes in real-time
#### Scenario: Node status change broadcast
- **GIVEN** connected WebSocket clients
- **WHEN** a node status changes
- **THEN** all connected clients receive a message with:
 - event_type (node_started, node_completed, node_failed)
 - node_id
 - status
 - output_data (on completion)
 - error_message (on failure)
---
### Requirement: Workflow Visual Editor
The system SHALL provide a visual editor for creating and editing workflows.
#### Scenario: Drag node from palette
- **GIVEN** the workflow editor is open
- **WHEN** the user drags a node type from the palette to the canvas
- **THEN** a new node of that type is created at the drop position
- **AND** the node configuration panel opens for the new node
#### Scenario: Connect nodes visually
- **GIVEN** two nodes on the canvas
- **WHEN** the user drags from one node's output handle to another node's input handle
- **THEN** an edge is created connecting the nodes
- **AND** the edge is visually displayed as a line/curve
#### Scenario: Configure node properties
- **GIVEN** a node on the canvas
- **WHEN** the user selects the node
- **THEN** the configuration panel displays editable fields based on the node type schema
#### Scenario: Delete nodes and edges
- **GIVEN** a node or edge on the canvas
- **WHEN** the user selects and presses delete
- **THEN** the selected element is removed
- **AND** connected edges are also removed (for nodes)
---
### Requirement: Execution Monitoring
The system SHALL display execution progress and allow interaction with running workflows.
#### Scenario: View execution progress
- **GIVEN** a running workflow execution
- **WHEN** the user opens the execution detail page
- **THEN** the workflow graph is displayed with nodes colored by status:
 - Gray: pending
 - Blue (animated): running
 - Yellow: waiting_approval
 - Green: completed
 - Red: failed
#### Scenario: View node logs
- **GIVEN** a completed or running node
- **WHEN** the user clicks on the node
- **THEN** the execution logs for that node are displayed
#### Scenario: Approve from monitoring view
- **GIVEN** a node in "waiting_approval" status
- **WHEN** the user clicks the approve button
- **THEN** the approval is processed
- **AND** execution continues
---
### Requirement: Docker Node Execution
The system SHALL execute AI and compute-intensive nodes in isolated Docker containers.
#### Scenario: Start container for node
- **GIVEN** a node type that requires container execution
- **WHEN** the node starts execution
- **THEN** a Docker container is started with:
 - Environment variables for node type and configuration
 - Mounted volumes for data transfer
 - Network access to callback API
#### Scenario: Receive node result via callback
- **GIVEN** a running container for a node
- **WHEN** the container completes and calls the callback API
- **THEN** the node execution record is updated with output data
- **AND** the container is stopped and removed
#### Scenario: Handle container timeout
- **GIVEN** a running container for a node
- **WHEN** the container exceeds the configured timeout
- **THEN** the container is forcefully stopped
- **AND** the node is marked as failed with a timeout error
