from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from .manifest import BrickManifestRecord
from .message import MessageEnvelope


def _subprocess_invoke_worker(
    pipe: Any,
    implementation: Any,
    capability: str,
    payload: Dict[str, Any],
    metadata: Dict[str, Any],
) -> None:
    try:
        if hasattr(implementation, "invoke"):
            res = implementation.invoke(capability, payload, metadata=metadata)
        elif hasattr(implementation, "handle_request"):
            res = implementation.handle_request(capability, payload, metadata=metadata)
        else:
            raise NotImplementedError("No supported invoke method found")
        pipe.send(("OK", res))
    except BaseException as exc:
        pipe.send(("ERR", exc))


@dataclass
class BrickConnector:
    brick_id: str
    name: str
    capabilities: List[str]
    implementation: Any
    manifest: BrickManifestRecord
    metadata: Dict[str, Any] = field(default_factory=dict)

    def invoke(
        self,
        capability: str,
        payload: Dict[str, Any],
        *,
        metadata: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        if capability not in self.capabilities:
            raise ValueError(f"Brick '{self.brick_id}' does not expose capability '{capability}'")
        if metadata is None:
            metadata = {}

        if timeout is None:
            if hasattr(self.implementation, "invoke"):
                return self.implementation.invoke(capability, payload, metadata=metadata)
            if hasattr(self.implementation, "handle_request"):
                return self.implementation.handle_request(capability, payload, metadata=metadata)
            raise NotImplementedError(f"No supported invoke method exists on brick '{self.brick_id}'")

        # Subprocess isolation to enforce real timeouts and enable actual termination of hung execution
        parent_conn, child_conn = mp.Pipe()
        proc = mp.Process(
            target=_subprocess_invoke_worker,
            args=(child_conn, self.implementation, capability, payload, metadata),
        )
        proc.start()
        child_conn.close()
        try:
            if parent_conn.poll(timeout):
                status, result = parent_conn.recv()
                proc.join(timeout=1.0)
                if status == "OK":
                    return result
                raise result
            else:
                proc.terminate()
                proc.join(timeout=0.5)
                if proc.is_alive():
                    proc.kill()
                    proc.join(timeout=0.5)
                raise TimeoutError(
                    f"Request timed out for {capability} on brick '{self.brick_id}' after {timeout}s (execution terminated)"
                )
        finally:
            parent_conn.close()
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=0.5)

    def stream(self, capability: str, payload: Dict[str, Any], *, metadata: Optional[Dict[str, Any]] = None) -> Iterable[Any]:
        if capability not in self.capabilities:
            raise ValueError(f"Brick '{self.brick_id}' does not expose capability '{capability}'")
        if metadata is None:
            metadata = {}
        if hasattr(self.implementation, "stream"):
            return self.implementation.stream(capability, payload, metadata=metadata)
        raise NotImplementedError(f"Brick '{self.brick_id}' does not support streaming")

    def health(self) -> Dict[str, Any]:
        if hasattr(self.implementation, "health"):
            return self.implementation.health()
        return {"status": "ok", "brick_id": self.brick_id}

    def unload(self) -> None:
        if hasattr(self.implementation, "shutdown"):
            self.implementation.shutdown()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


__all__ = ["BrickConnector"]
