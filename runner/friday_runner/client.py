from __future__ import annotations
import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from .models import RegisterResponse, RunnerStatus
_retry_on_network_error = retry(
 retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
 stop=stop_after_attempt(3),
 wait=wait_exponential(multiplier=1, min=1, max=10),
 reraise=True,
)
class FridayClient:
 def __init__(self, base_url: str) -> None:
 self._client = httpx.Client(base_url=base_url, timeout=30)
 @_retry_on_network_error
 def register(
 self, token: str, name: str, scope: str, concurrent: int, version: str
 ) -> RegisterResponse:
 resp = self._client.post(
 "/api/runners/register/",
 json={"token": token, "name": name, "scope": scope, "concurrent": concurrent, "version": version},
 )
 resp.raise_for_status
 data = resp.json
 return RegisterResponse(**data)
 @_retry_on_network_error
 def unregister(self, runner_token: str) -> None:
 resp = self._client.delete(
 "/api/runners/unregister/",
 headers={"Authorization": f"Bearer {runner_token}"},
 )
 resp.raise_for_status
 @_retry_on_network_error
 def verify(self, runner_token: str) -> RunnerStatus:
 resp = self._client.get(
 "/api/runners/verify/",
 headers={"Authorization": f"Bearer {runner_token}"},
 )
 resp.raise_for_status
 return RunnerStatus(**resp.json)
 def close(self) -> None:
 self._client.close
