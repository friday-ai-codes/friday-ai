"""Tests for DAG (Directed Acyclic Graph) module.

Tests cover:
- DAG construction from workflow
- Cycle detection
- Entry node identification
- Successor node retrieval
- Topological sorting
"""

import pytest

from projects.models import Space
from workflows.engine.dag import DAG
from workflows.models import Workflow, WorkflowEdge, WorkflowNode


@pytest.fixture
def dag_project(db):
    """Create a project for DAG tests."""
    return Space.objects.create(
        name="DAG Test Space",
        description="Space for DAG testing",
    )


@pytest.fixture
def linear_workflow(db, dag_project):
    """Create a linear workflow: A -> B -> C."""
    workflow = Workflow.objects.create(
        name="Linear Workflow",
        space=dag_project,
        trigger_type="manual",
    )

    node_a = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Node A",
        position_x=0,
        position_y=0,
    )
    node_b = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Node B",
        position_x=200,
        position_y=0,
    )
    node_c = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="http_request",
        name="Node C",
        position_x=400,
        position_y=0,
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_b,
        target_node=node_c,
        source_handle="default",
        target_handle="default",
    )

    return workflow


@pytest.fixture
def branching_workflow(db, dag_project):
    """Create a branching workflow: A -> B, A -> C."""
    workflow = Workflow.objects.create(
        name="Branching Workflow",
        space=dag_project,
        trigger_type="manual",
    )

    node_a = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Node A",
        position_x=0,
        position_y=0,
    )
    node_b = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Node B",
        position_x=200,
        position_y=-100,
    )
    node_c = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="http_request",
        name="Node C",
        position_x=200,
        position_y=100,
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="true",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_c,
        source_handle="false",
        target_handle="default",
    )

    return workflow


@pytest.fixture
def cyclic_workflow(db, dag_project):
    """Create a workflow with a cycle: A -> B -> C -> A."""
    workflow = Workflow.objects.create(
        name="Cyclic Workflow",
        space=dag_project,
        trigger_type="manual",
    )

    node_a = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="manual_trigger",
        name="Node A",
        position_x=0,
        position_y=0,
    )
    node_b = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="condition",
        name="Node B",
        position_x=200,
        position_y=0,
    )
    node_c = WorkflowNode.objects.create(
        workflow=workflow,
        node_type="http_request",
        name="Node C",
        position_x=400,
        position_y=0,
    )

    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_a,
        target_node=node_b,
        source_handle="default",
        target_handle="default",
    )
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_b,
        target_node=node_c,
        source_handle="default",
        target_handle="default",
    )
    # Create cycle
    WorkflowEdge.objects.create(
        workflow=workflow,
        source_node=node_c,
        target_node=node_a,
        source_handle="default",
        target_handle="default",
    )

    return workflow


# ============================================================================
# DAG Construction Tests
# ============================================================================


@pytest.mark.django_db
class TestDAGConstruction:
    """Tests for DAG construction from workflow."""

    def test_build_dag_from_linear_workflow(self, linear_workflow):
        """Test building DAG from linear workflow."""
        dag = DAG.from_workflow(linear_workflow)

        assert len(dag.nodes) == 3
        assert len(dag.edges) == 2

    def test_build_dag_from_branching_workflow(self, branching_workflow):
        """Test building DAG from branching workflow."""
        dag = DAG.from_workflow(branching_workflow)

        assert len(dag.nodes) == 3
        assert len(dag.edges) == 2

    def test_dag_node_incoming_edges(self, linear_workflow):
        """Test that incoming edges are correctly recorded."""
        dag = DAG.from_workflow(linear_workflow)

        # Find node B (middle node)
        node_b = None
        for dag_node in dag.nodes.values():
            if dag_node.node.name == "Node B":
                node_b = dag_node
                break

        assert node_b is not None
        assert node_b.in_degree == 1

    def test_dag_node_outgoing_edges(self, branching_workflow):
        """Test that outgoing edges are correctly recorded."""
        dag = DAG.from_workflow(branching_workflow)

        # Find node A (entry node with branches)
        node_a = None
        for dag_node in dag.nodes.values():
            if dag_node.node.name == "Node A":
                node_a = dag_node
                break

        assert node_a is not None
        # Should have outgoing edges to both B and C (different handles)
        assert "true" in node_a.outgoing
        assert "false" in node_a.outgoing


# ============================================================================
# Cycle Detection Tests
# ============================================================================


@pytest.mark.django_db
class TestCycleDetection:
    """Tests for cycle detection in DAG."""

    def test_no_cycle_in_linear_workflow(self, linear_workflow):
        """Test that linear workflow has no cycle."""
        dag = DAG.from_workflow(linear_workflow)
        assert dag.has_cycle() is False

    def test_no_cycle_in_branching_workflow(self, branching_workflow):
        """Test that branching workflow has no cycle."""
        dag = DAG.from_workflow(branching_workflow)
        assert dag.has_cycle() is False

    def test_cycle_detected(self, cyclic_workflow):
        """Test that cycle is detected."""
        dag = DAG.from_workflow(cyclic_workflow)
        assert dag.has_cycle() is True


# ============================================================================
# Entry Node Tests
# ============================================================================


@pytest.mark.django_db
class TestEntryNodes:
    """Tests for entry node identification."""

    def test_get_entry_nodes_linear(self, linear_workflow):
        """Test getting entry nodes from linear workflow."""
        dag = DAG.from_workflow(linear_workflow)
        entry_nodes = dag.get_entry_nodes()

        assert len(entry_nodes) == 1
        assert entry_nodes[0].node.name == "Node A"
        assert entry_nodes[0].node.node_type == "manual_trigger"

    def test_get_entry_nodes_branching(self, branching_workflow):
        """Test getting entry nodes from branching workflow."""
        dag = DAG.from_workflow(branching_workflow)
        entry_nodes = dag.get_entry_nodes()

        assert len(entry_nodes) == 1
        assert entry_nodes[0].node.name == "Node A"


# ============================================================================
# Successor Tests
# ============================================================================


@pytest.mark.django_db
class TestSuccessors:
    """Tests for successor node retrieval."""

    def test_get_successors_by_handle(self, branching_workflow):
        """Test getting successors by specific handle."""
        dag = DAG.from_workflow(branching_workflow)

        # Find node A
        node_a = None
        for dag_node in dag.nodes.values():
            if dag_node.node.name == "Node A":
                node_a = dag_node
                break

        # Get successors for 'true' handle
        true_successors = dag.get_successors(node_a.id, "true")
        assert len(true_successors) == 1
        assert true_successors[0].node.name == "Node B"

        # Get successors for 'false' handle
        false_successors = dag.get_successors(node_a.id, "false")
        assert len(false_successors) == 1
        assert false_successors[0].node.name == "Node C"

    def test_get_all_successors(self, branching_workflow):
        """Test getting all successors regardless of handle."""
        dag = DAG.from_workflow(branching_workflow)

        # Find node A
        node_a = None
        for dag_node in dag.nodes.values():
            if dag_node.node.name == "Node A":
                node_a = dag_node
                break

        all_successors = dag.get_all_successors(node_a.id)
        assert len(all_successors) == 2

        successor_names = {s.node.name for s in all_successors}
        assert "Node B" in successor_names
        assert "Node C" in successor_names


# ============================================================================
# Topological Sort Tests
# ============================================================================


@pytest.mark.django_db
class TestTopologicalSort:
    """Tests for topological sorting."""

    def test_topological_sort_linear(self, linear_workflow):
        """Test topological sort of linear workflow."""
        dag = DAG.from_workflow(linear_workflow)
        sorted_nodes = dag.topological_sort()

        assert len(sorted_nodes) == 3

        # Node A should be first
        assert sorted_nodes[0].node.name == "Node A"
        # Node B should be second
        assert sorted_nodes[1].node.name == "Node B"
        # Node C should be last
        assert sorted_nodes[2].node.name == "Node C"

    def test_topological_sort_branching(self, branching_workflow):
        """Test topological sort of branching workflow."""
        dag = DAG.from_workflow(branching_workflow)
        sorted_nodes = dag.topological_sort()

        assert len(sorted_nodes) == 3

        # Node A should always be first (entry node)
        assert sorted_nodes[0].node.name == "Node A"


# ============================================================================
# Validation Tests
# ============================================================================


@pytest.mark.django_db
class TestDAGValidation:
    """Tests for DAG validation."""

    def test_validate_valid_workflow(self, linear_workflow):
        """Test validation passes for valid workflow."""
        dag = DAG.from_workflow(linear_workflow)
        errors = dag.validate()

        assert len(errors) == 0

    def test_validate_cyclic_workflow(self, cyclic_workflow):
        """Test validation fails for cyclic workflow."""
        dag = DAG.from_workflow(cyclic_workflow)
        errors = dag.validate()

        assert len(errors) > 0
        assert any("循环" in error for error in errors)

    def test_validate_no_entry_node(self, dag_project):
        """Test validation fails when no entry node."""
        workflow = Workflow.objects.create(
            name="No Entry Workflow",
            space=dag_project,
            trigger_type="manual",
        )

        # Create two nodes that point to each other but no entry
        node_a = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Node A",
            position_x=0,
            position_y=0,
        )
        node_b = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="condition",
            name="Node B",
            position_x=200,
            position_y=0,
        )

        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node_a,
            target_node=node_b,
            source_handle="default",
            target_handle="default",
        )
        WorkflowEdge.objects.create(
            workflow=workflow,
            source_node=node_b,
            target_node=node_a,
            source_handle="default",
            target_handle="default",
        )

        dag = DAG.from_workflow(workflow)
        errors = dag.validate()

        # Should have errors for both cycle and no entry
        assert len(errors) >= 1
