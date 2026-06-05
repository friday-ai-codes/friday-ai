"""文件通信协议模块测试。"""


def test_protocol_constants():
    """验证协议常量定义。"""
    from services.protocols import (
        ANSWER_FILE,
        CONTAINER_PROTOCOL_DIR,
        CONTEXT_FILE,
        HEARTBEAT_FILE,
        QUESTION_FILE,
        RESULT_FILE,
        STATUS_FILE,
    )

    assert CONTAINER_PROTOCOL_DIR == "/workspace/.friday"
    assert STATUS_FILE == "status.json"
    assert RESULT_FILE == "result.json"
    assert CONTEXT_FILE == "context.json"
    assert QUESTION_FILE == "question.json"
    assert ANSWER_FILE == "answer.json"
    assert HEARTBEAT_FILE == "heartbeat"


def test_status_payload_dataclass():
    """验证 StatusPayload 可实例化。"""
    from services.protocols import StatusPayload

    payload = StatusPayload(
        status="running",
        task_type="coding",
        started_at="2026-02-11T10:00:00Z",
        updated_at="2026-02-11T10:05:00Z",
    )
    assert payload.status == "running"
    assert payload.progress == 0.0
    assert payload.message == ""


def test_result_payload_dataclass():
    """验证 ResultPayload 可实例化。"""
    from services.protocols import ResultPayload

    payload = ResultPayload(status="completed", duration_ms=12345)
    assert payload.output == {}
    assert payload.error is None
    assert payload.completed_at == ""


def test_context_payload_dataclass():
    """验证 ContextPayload 可实例化。"""
    from services.protocols import ContextPayload

    payload = ContextPayload(
        session_id="exec-abc123",
        task_type="coding",
        prompt="test prompt",
    )
    assert payload.session_id == "exec-abc123"
    assert payload.project == {}
    assert payload.work_item == {}
    assert payload.target_branch is None


def test_env_constants():
    """验证环境变量常量使用 FRIDAY_* 前缀。"""
    from services.protocols import (
        ENV_CALLBACK_TOKEN,
        ENV_CALLBACK_URL,
        ENV_PROTOCOL_DIR,
        ENV_SESSION_ID,
        ENV_TASK_TYPE,
    )

    assert ENV_SESSION_ID == "FRIDAY_SESSION_ID"
    assert ENV_TASK_TYPE == "FRIDAY_TASK_TYPE"
    assert ENV_PROTOCOL_DIR == "FRIDAY_PROTOCOL_DIR"
    assert ENV_CALLBACK_URL == "FRIDAY_CALLBACK_URL"
    assert ENV_CALLBACK_TOKEN == "FRIDAY_CALLBACK_TOKEN"


def test_no_django_dependency():
    """验证 protocols.py 不依赖 Django（可在容器内复用）。"""
    import importlib

    spec = importlib.util.find_spec("services.protocols")
    assert spec is not None
    assert spec.origin is not None
    with open(spec.origin) as f:
        source = f.read()
    assert "from django" not in source
    assert "import django" not in source


def test_protocol_status_values():
    """验证 ProtocolStatus 常量。"""
    from services.protocols import ProtocolStatus

    assert ProtocolStatus.RUNNING == "running"
    assert ProtocolStatus.COMPLETED == "completed"
    assert ProtocolStatus.FAILED == "failed"


def test_result_status_values():
    """验证 ResultStatus 常量。"""
    from services.protocols import ResultStatus

    assert ResultStatus.COMPLETED == "completed"
    assert ResultStatus.FAILED == "failed"
