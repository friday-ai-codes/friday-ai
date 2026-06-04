from __future__ import annotations
import pytest
from runners.models import hash_token
pytestmark = pytest.mark.django_db
def test_record_retrieval_trace_redacts_payload -> None:
 from interactions.ledger import create_interaction_run, record_retrieval_trace
 from interactions.models import RetrievalTrace
 plaintext = "friday_pat_" + "A" * 32
 run = create_interaction_run(token_fingerprint=hash_token("rt"), source="mcp")
 trace = record_retrieval_trace(
 run,
 kind=RetrievalTrace.Kind.CHUNK,
 payload={"content": f"secret={plaintext}"},
 )
 assert trace is not None
 trace.refresh_from_db
 assert plaintext not in str(trace.payload)
 assert trace.kind == RetrievalTrace.Kind.CHUNK
def test_record_retrieval_trace_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
 from interactions.ledger import create_interaction_run, record_retrieval_trace
 from interactions.models import RetrievalTrace
 run = create_interaction_run(token_fingerprint=hash_token("rt-fail"), source="mcp")
 def _boom(*args: object, **kwargs: object) -> object:
 raise RuntimeError("db down")
 monkeypatch.setattr(RetrievalTrace.objects, "create", _boom)
 assert record_retrieval_trace(run, kind=RetrievalTrace.Kind.FILE, payload={}) is None
