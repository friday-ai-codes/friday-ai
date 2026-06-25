"""VAR-01 集成测试：bulk-update 保存路径的 short_id 收敛。

覆盖：
- 客户端 short_id 权威落库 / 缺失时服务端生成 / update 节点缺失时保留现值
- 冲突先到先得 + id_map 防卫规则（客户端值仍被合法占用时不重写）
- 冲突重生成后全工作流 config 引用重写（含 $nodes. JSONPath 形式）
- 核心不变式：保存成功 ⇒ config 中全部 nodes.* 引用可解析
- 跨工作流越权防护（T-17-11）与 bulk-update 响应契约

测试直接调用同步事务函数 _bulk_update_nodes_and_edges，绕开 HTTP 层鉴权噪音。
"""

import re

import pytest

from workflows.api.serializers import WorkflowSerializer
from workflows.api.views import _bulk_update_nodes_and_edges
from workflows.models import Workflow, WorkflowNode

pytestmark = pytest.mark.django_db

# 服务端生成的 short_id 约束：字母开头 + 字母数字，3-12 位
GENERATED_SHORT_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,11}$")

# 与不变式测试约定一致的引用标识符提取正则（覆盖 nodes. / $nodes. / $.nodes. 形式）
REF_IDENT_RE = re.compile(r"\{\{\s*(?:\$\.?)?nodes\.([A-Za-z0-9-]+)\.")


def _new_node(name: str, config: dict | None = None, short_id: str | None = None) -> dict:
    """构造新节点 payload（manual_trigger 的 config schema 允许任意附加键）。"""
    data: dict = {"node_type": "manual_trigger", "name": name, "config": config or {}}
    if short_id is not None:
        data["short_id"] = short_id
    return data


def _collect_ref_idents(workflow: Workflow) -> set[str]:
    """收集工作流全部节点 config 中 nodes.* 引用的标识符。"""
    idents: set[str] = set()

    def _walk(value):
        if isinstance(value, str):
            idents.update(REF_IDENT_RE.findall(value))
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    for node in workflow.nodes.all():
        _walk(node.config)
    return idents


@pytest.fixture
def workflow(obs_project, user):
    return Workflow.objects.create(
        name="short_id 收敛测试工作流",
        space=obs_project,
        created_by=user,
    )


class TestClientShortIdPersistence:
    """场景 1-3：落库 / 生成 / 保留。"""

    def test_client_short_id_persisted_as_authoritative(self, workflow):
        """新节点 payload 含 short_id="aB1" → DB 中该节点 short_id == "aB1"。"""
        _bulk_update_nodes_and_edges(workflow, [_new_node("n1", short_id="aB1")], [])

        node = workflow.nodes.get(name="n1")
        assert node.short_id == "aB1"

    def test_missing_short_id_generated_and_unique(self, workflow):
        """新节点缺失 short_id → 服务端生成合法格式且工作流内唯一。"""
        _bulk_update_nodes_and_edges(
            workflow,
            [_new_node("n1"), _new_node("n2"), _new_node("n3", short_id="aB1")],
            [],
        )

        short_ids = list(workflow.nodes.values_list("short_id", flat=True))
        assert len(short_ids) == len(set(short_ids)), "工作流内 short_id 必须唯一"
        for sid in short_ids:
            assert GENERATED_SHORT_ID_RE.match(sid), f"short_id 格式非法: {sid}"

    def test_update_without_short_id_keeps_db_value(self, workflow):
        """update 节点 payload 不含 short_id → DB 现值保留不变（存量行为不回退）。"""
        node = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="old", short_id="kP3"
        )

        _bulk_update_nodes_and_edges(
            workflow,
            [{"id": str(node.id), "node_type": "manual_trigger", "name": "renamed"}],
            [],
        )

        node.refresh_from_db()
        assert node.short_id == "kP3"
        assert node.name == "renamed"


class TestConflictResolution:
    """场景 4-5：冲突先到先得防卫 / 冲突重生成 + 全工作流重写。"""

    def test_conflict_first_come_first_served_no_rewrite(self, workflow):
        """两个新节点都声明 "aB1"：首个采纳，第二个重生成；

        客户端值仍被首个节点合法占用 → id_map 不得包含 aB1，
        第二个节点 config 中的引用保持 aB1 原样（指向首个节点，语义正确）。
        """
        config2 = {
            "ref": "{{nodes.aB1.out}}",
            "jsonpath": "{{$nodes.aB1.items[*].x}}",
        }
        _bulk_update_nodes_and_edges(
            workflow,
            [
                _new_node("first", short_id="aB1"),
                _new_node("second", config=config2, short_id="aB1"),
            ],
            [],
        )

        first = workflow.nodes.get(name="first")
        second = workflow.nodes.get(name="second")
        assert first.short_id == "aB1", "先到先得：首个节点采纳客户端值"
        assert second.short_id != "aB1", "第二个节点冲突重生成"
        assert GENERATED_SHORT_ID_RE.match(second.short_id)
        # 防卫规则：aB1 仍属首个节点，引用不得被误改
        assert second.config["ref"] == "{{nodes.aB1.out}}"
        assert second.config["jsonpath"] == "{{$nodes.aB1.items[*].x}}"

    def test_conflict_with_existing_node_rewrites_all_configs(self, workflow):
        """节点 A 声明 "xY9" 与既有节点冲突（既有节点本次被 delete_orphans 删除）：

        A 重生成为新值 N，xY9 最终无归属 → 全工作流 config 中
        {{nodes.xY9.*}} 与 {{$nodes.xY9.*}} 同步重写为 N，无关字符串保持原样。
        """
        WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="stale", short_id="xY9"
        )

        config_a = {"self_ref": "{{nodes.xY9.out}}"}
        config_neighbor = {
            "ref": "{{nodes.xY9.out}}",
            "jsonpath": "{{$nodes.xY9.items[0].v}}",
            "unrelated": "plain {{trigger.payload.x}} text",
        }
        _bulk_update_nodes_and_edges(
            workflow,
            [
                _new_node("A", config=config_a, short_id="xY9"),
                _new_node("neighbor", config=config_neighbor),
            ],
            [],
            delete_orphans=True,
        )

        assert not workflow.nodes.filter(name="stale").exists(), "孤儿节点已删除"
        node_a = workflow.nodes.get(name="A")
        neighbor = workflow.nodes.get(name="neighbor")
        new_id = node_a.short_id
        assert new_id != "xY9"
        assert GENERATED_SHORT_ID_RE.match(new_id)
        # 两节点 config 全部重写（含 $nodes. JSONPath 形式）
        assert node_a.config["self_ref"] == f"{{{{nodes.{new_id}.out}}}}"
        assert neighbor.config["ref"] == f"{{{{nodes.{new_id}.out}}}}"
        assert neighbor.config["jsonpath"] == f"{{{{$nodes.{new_id}.items[0].v}}}}"
        # 未涉及该引用的字符串保持原样
        assert neighbor.config["unrelated"] == "plain {{trigger.payload.x}} text"


class TestInvariant:
    """场景 6：核心不变式——保存成功 ⇒ 引用可解析。"""

    def test_invariant_save_implies_resolvable(self, workflow):
        """混合场景保存后，config 中全部 nodes.* 引用的标识符
        都属于该工作流的 short_id 或 UUID 集合。"""
        # 既有节点：一个不在 payload 中（保留），一个在 payload 中被更新（UUID 引用目标）
        keeper = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="keeper", short_id="kP3"
        )
        updated = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="updated", short_id="uQ7"
        )

        _bulk_update_nodes_and_edges(
            workflow,
            [
                # 合法客户端值 + 自引用
                _new_node("n1", config={"a": "{{nodes.aB1.out}}"}, short_id="aB1"),
                # 缺失 short_id + 引用他人（合法占用者 aB1 与存量 kP3）
                _new_node("n2", config={"b": "{{nodes.aB1.x}}", "c": "{{nodes.kP3.y}}"}),
                # 冲突重生成 + JSONPath 形式引用
                _new_node("n3", config={"d": "{{$nodes.aB1.items[0].v}}"}, short_id="aB1"),
                # update 节点缺失 short_id，config 含 UUID 形式引用
                {
                    "id": str(updated.id),
                    "node_type": "manual_trigger",
                    "name": "updated",
                    "config": {"e": f"{{{{nodes.{keeper.id}.out}}}}"},
                },
            ],
            [],
        )

        nodes = list(workflow.nodes.all())
        valid_idents = {n.short_id for n in nodes} | {str(n.id) for n in nodes}
        referenced = _collect_ref_idents(workflow)
        assert referenced, "测试场景必须实际产生 nodes.* 引用"
        unresolvable = referenced - valid_idents
        assert not unresolvable, f"存在不可解析引用: {unresolvable}"


class TestCrossWorkflowIsolation:
    """场景 7：越权防护（T-17-11）——重写严格限定本工作流。"""

    def test_other_workflow_config_untouched(self, workflow, obs_project, user):
        other_workflow = Workflow.objects.create(
            name="另一个工作流", space=obs_project, created_by=user
        )
        other_node = WorkflowNode.objects.create(
            workflow=other_workflow,
            node_type="manual_trigger",
            name="other",
            short_id="zW8",
            config={"ref": "{{nodes.xY9.out}}"},
        )

        # 对第一个 workflow 触发含 xY9 的冲突重写（同场景 5 构造）
        WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="stale", short_id="xY9"
        )
        _bulk_update_nodes_and_edges(
            workflow,
            [_new_node("A", config={"ref": "{{nodes.xY9.out}}"}, short_id="xY9")],
            [],
            delete_orphans=True,
        )

        node_a = workflow.nodes.get(name="A")
        assert node_a.config["ref"] == f"{{{{nodes.{node_a.short_id}.out}}}}", "本工作流已重写"
        other_node.refresh_from_db()
        assert other_node.config["ref"] == "{{nodes.xY9.out}}", "其他工作流 config 原样未动"


class TestResponseContract:
    """场景 8：bulk-update 响应契约（Pitfall 4）——序列化返回 DB 最终状态。"""

    def test_serializer_returns_rewritten_config_and_final_short_id(self, workflow):
        WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="stale", short_id="xY9"
        )
        _bulk_update_nodes_and_edges(
            workflow,
            [_new_node("A", config={"ref": "{{nodes.xY9.out}}"}, short_id="xY9")],
            [],
            delete_orphans=True,
        )

        workflow.refresh_from_db()
        data = WorkflowSerializer(workflow).data
        assert len(data["nodes"]) == 1
        node_payload = data["nodes"][0]
        final_short_id = node_payload["short_id"]
        assert final_short_id != "xY9", "响应中 short_id 为最终权威值"
        assert GENERATED_SHORT_ID_RE.match(final_short_id)
        assert node_payload["config"]["ref"] == f"{{{{nodes.{final_short_id}.out}}}}", (
            "响应中 config 为重写后内容"
        )


class TestInvalidFormatRegeneration:
    """补充：非法格式客户端值（注入模板语法字符）必须被白名单拒绝并重生成。"""

    @pytest.mark.parametrize(
        "bad_value",
        ["a.B1", "a{b}", "1abc", "ab cd", "", "a" * 13, "中文id", "a", "ab"],
    )
    def test_invalid_short_id_regenerated(self, workflow, bad_value):
        _bulk_update_nodes_and_edges(workflow, [_new_node("n1", short_id=bad_value)], [])

        node = workflow.nodes.get(name="n1")
        assert node.short_id != bad_value
        assert GENERATED_SHORT_ID_RE.match(node.short_id), "重生成值必须符合白名单格式"


class TestMalformedPayload:
    """IN-03：畸形 payload（nodes 元素非 dict）须报 400（ValidationError）而非 500。"""

    def test_non_dict_node_element_raises_validation_error(self, workflow):
        from rest_framework.exceptions import ValidationError

        with pytest.raises(ValidationError):
            _bulk_update_nodes_and_edges(workflow, ["not-a-dict"], [])

    def test_non_list_nodes_raises_validation_error(self, workflow):
        from rest_framework.exceptions import ValidationError

        with pytest.raises(ValidationError):
            _bulk_update_nodes_and_edges(workflow, {"id": "x"}, [])


class TestRewriteCandidateSafety:
    """CR-01 回归：非法客户端值不得进入重写映射；旧 DB 身份的存量引用必须被重写。"""

    def test_invalid_client_value_must_not_rewrite_legit_node_refs(self, workflow):
        """非法值 "abc.out"（含点号）被重生成时，不得把 {{nodes.abc.out.c}}——
        指向合法节点 abc 字段 out.c 的引用——误改写为新生成值。"""
        WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="legit", short_id="abc"
        )
        neighbor = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="neighbor",
            short_id="nB7",
            config={"ref": "{{nodes.abc.out.c}}"},
        )

        _bulk_update_nodes_and_edges(
            workflow, [_new_node("attacker", short_id="abc.out")], []
        )

        attacker = workflow.nodes.get(name="attacker")
        assert attacker.short_id != "abc.out"
        assert GENERATED_SHORT_ID_RE.match(attacker.short_id)
        neighbor.refresh_from_db()
        assert neighbor.config["ref"] == "{{nodes.abc.out.c}}", (
            "指向合法节点 abc 的引用不得被非法客户端值污染的重写映射篡改"
        )

    def test_invalid_client_value_on_update_rewrites_old_db_refs(self, workflow):
        """update 节点送非法 short_id 导致 DB 旧值被重生成替换时，
        对旧 DB short_id 的存量引用必须重写到新值（不变式：保存后引用可解析）。"""
        target = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="target", short_id="kP3"
        )
        neighbor = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="neighbor",
            short_id="nB7",
            config={"ref": "{{nodes.kP3.out}}"},
        )

        _bulk_update_nodes_and_edges(
            workflow,
            [
                {
                    "id": str(target.id),
                    "node_type": "manual_trigger",
                    "name": "target",
                    "short_id": "k.P3",
                }
            ],
            [],
        )

        target.refresh_from_db()
        assert target.short_id != "kP3", "非法客户端值触发重生成"
        assert GENERATED_SHORT_ID_RE.match(target.short_id)
        neighbor.refresh_from_db()
        assert neighbor.config["ref"] == f"{{{{nodes.{target.short_id}.out}}}}", (
            "旧 DB short_id 的存量引用必须随重生成同步重写"
        )

    def test_rename_rewrites_old_db_refs(self, workflow):
        """客户端合法重命名（kP3 → wZ5）后，对旧值 kP3 的存量引用同步重写。"""
        target = WorkflowNode.objects.create(
            workflow=workflow, node_type="manual_trigger", name="target", short_id="kP3"
        )
        neighbor = WorkflowNode.objects.create(
            workflow=workflow,
            node_type="manual_trigger",
            name="neighbor",
            short_id="nB7",
            config={"ref": "{{nodes.kP3.out}}"},
        )

        _bulk_update_nodes_and_edges(
            workflow,
            [
                {
                    "id": str(target.id),
                    "node_type": "manual_trigger",
                    "name": "target",
                    "short_id": "wZ5",
                }
            ],
            [],
        )

        target.refresh_from_db()
        assert target.short_id == "wZ5"
        neighbor.refresh_from_db()
        assert neighbor.config["ref"] == "{{nodes.wZ5.out}}"
