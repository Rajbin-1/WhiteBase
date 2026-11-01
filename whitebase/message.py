from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional


@dataclass
class MessageEnvelope:
    message_id: str
    request_id: str
    session_id: str
    source: str
    target: str
    capability: str
    operation: str
    data_type: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"

    @classmethod
    def new(cls, *, source: str, target: str, capability: str, operation: str, data_type: str = "text", payload: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None, session_id: Optional[str] = None) -> "MessageEnvelope":
        if payload is None:
            payload = {}
        if metadata is None:
            metadata = {}
        return cls(
            message_id=str(uuid.uuid4()),
            request_id=request_id or str(uuid.uuid4()),
            session_id=session_id or str(uuid.uuid4()),
            source=source,
            target=target,
            capability=capability,
            operation=operation,
            data_type=data_type,
            payload=payload,
            metadata=metadata,
            correlation={"request_id": request_id or None},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "request_id": self.request_id,
            "session_id": self.session_id,
            "source": self.source,
            "target": self.target,
            "capability": self.capability,
            "operation": self.operation,
            "data_type": self.data_type,
            "payload": self.payload,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "correlation": self.correlation,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "MessageEnvelope":
        data = dict(value)
        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            request_id=data.get("request_id", str(uuid.uuid4())),
            session_id=data.get("session_id", str(uuid.uuid4())),
            source=data.get("source", "unknown"),
            target=data.get("target", "unknown"),
            capability=data.get("capability", "generic"),
            operation=data.get("operation", "invoke"),
            data_type=data.get("data_type", "text"),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            correlation=data.get("correlation", {}),
            schema_version=data.get("schema_version", "1.0"),
        )


def stream_response(*chunks: Any) -> Iterator[str]:
    for chunk in chunks:
        yield str(chunk)
