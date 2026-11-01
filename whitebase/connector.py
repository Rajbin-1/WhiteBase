from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

from .manifest import BrickManifestRecord
from .message import MessageEnvelope


@dataclass
class BrickConnector:
    brick_id: str
    name: str
    capabilities: List[str]
    implementation: Any
    manifest: BrickManifestRecord
    metadata: Dict[str, Any] = field(default_factory=dict)

    def invoke(self, capability: str, payload: Dict[str, Any], *, metadata: Optional[Dict[str, Any]] = None) -> Any:
        if capability not in self.capabilities:
            raise ValueError(f"Brick '{self.brick_id}' does not expose capability '{capability}'")
        if metadata is None:
            metadata = {}
        if hasattr(self.implementation, "invoke"):
            return self.implementation.invoke(capability, payload, metadata=metadata)
        if hasattr(self.implementation, "handle_request"):
            return self.implementation.handle_request(capability, payload, metadata=metadata)
        raise NotImplementedError(f"No supported invoke method exists on brick '{self.brick_id}'")

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
