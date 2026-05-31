"""GraphNeighborsView API 测试 —— 覆盖。
端点：GET /api/repositories/{repository_id}/codegraph/graph/neighbors/
覆盖 file | component | symbol 三 node_type、direction 三态、400/404 边界。
"""
import uuid
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from codegraph.models import CallEdge, Symbol
from repositories.models import Repository
User = get_user_model
@pytest.fixture
def user(db):
 return User.objects.create_user(
 username="neighbors_api_user",
 email="neighbors_api@example.com",
 password="testpassword",
 )
@pytest.fixture
def api_client(user):
 client = APIClient
 client.force_authenticate(user=user)
 return client
@pytest.fixture
def repo(db):
 return Repository.objects.create(
 name="neighbors-test-repo",
 git_url="https://example.com/neighbors-test.git",
 default_branch="main",
 )
def _url(repo_id, **params):
 qs = "&".join(f"{k}={v}" for k, v in params.items)
 return f"/api/repositories/{repo_id}/codegraph/graph/neighbors/?{qs}"
@pytest.mark.django_db
def test_file_neighbors_returns_nodes_and_edges(api_client, repo):
 """node_type=file 返回 {nodes, edges}，含上下游文件边。"""
 Symbol.objects.create(
 repository=repo, name="a_fn", symbol_type="FUNCTION",
 file_path="a.py", start_line=1, end_line=2,
 )
 Symbol.objects.create(
 repository=repo, name="b_fn", symbol_type="FUNCTION",
 file_path="b.py", start_line=1, end_line=2,
 )
 CallEdge.objects.create(
 repository=repo, caller_file="a.py", callee_name="b_fn",
 callee_file="b.py", call_type="DIRECT", line_number=1,
 )
 resp = api_client.get(_url(repo.id, node_type="file", id="a.py", direction="both"))
 assert resp.status_code == 200
 data = resp.json
 assert data["node_type"] == "file"
 files = {n["id"] for n in data["nodes"]}
 assert {"a.py", "b.py"} <= files
 assert any(e["source"] == "a.py" and e["target"] == "b.py" for e in data["edges"])
@pytest.mark.django_db
def test_component_neighbors(api_client, repo):
 """node_type=component：A 用 B → A 下游含 B 组件。"""
 a = Symbol.objects.create(
 repository=repo, name="A", symbol_type="CLASS",
 file_path="src/A.vue", start_line=1, end_line=2,
 )
 b = Symbol.objects.create(
 repository=repo, name="B", symbol_type="CLASS",
 file_path="src/B.vue", start_line=1, end_line=2,
 )
 CallEdge.objects.create(
 repository=repo, caller_file="src/A.vue", callee_name="B",
 callee_symbol=b, callee_file="src/B.vue", is_cross_file=True,
 call_type="TEMPLATE_REF", line_number=1,
 )
 resp = api_client.get(
 _url(repo.id, node_type="component", id=str(a.id), direction="down")
 )
 assert resp.status_code == 200
 data = resp.json
 labels = {n["label"] for n in data["nodes"]}
 assert {"A", "B"} <= labels
@pytest.mark.django_db
def test_symbol_neighbors(api_client, repo):
 """node_type=symbol：seed 调 target → 下游含 target（受益 callee_symbol）。"""
 seed = Symbol.objects.create(
 repository=repo, name="seed", symbol_type="FUNCTION",
 file_path="a.py", start_line=1, end_line=2,
 )
 target = Symbol.objects.create(
 repository=repo, name="target", symbol_type="FUNCTION",
 file_path="b.py", start_line=1, end_line=2,
 )
 CallEdge.objects.create(
 repository=repo, caller_symbol=seed, caller_file="a.py",
 callee_name="target", callee_symbol=target, callee_file="b.py",
 is_cross_file=True, call_type="DIRECT", line_number=1,
 )
 resp = api_client.get(
 _url(repo.id, node_type="symbol", id=str(seed.id), direction="down")
 )
 assert resp.status_code == 200
 data = resp.json
 ids = {n["id"] for n in data["nodes"]}
 assert str(target.id) in ids
 assert any(e["target"] == str(target.id) for e in data["edges"])
@pytest.mark.django_db
def test_invalid_node_type_returns_400(api_client, repo):
 resp = api_client.get(_url(repo.id, node_type="bogus", id="a.py"))
 assert resp.status_code == 400
@pytest.mark.django_db
def test_symbol_not_found_returns_404(api_client, repo):
 resp = api_client.get(
 _url(repo.id, node_type="symbol", id=str(uuid.uuid4), direction="both")
 )
 assert resp.status_code == 404
@pytest.mark.django_db
def test_invalid_direction_returns_400(api_client, repo):
 resp = api_client.get(
 _url(repo.id, node_type="file", id="a.py", direction="sideways")
 )
 assert resp.status_code == 400
