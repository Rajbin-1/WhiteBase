from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional


class DataType(str, Enum):
    TEXT = "text"
    AUDIO = "audio"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    STRUCTURED_DATA = "structured_data"
    CONTEXT = "context"
    EMBEDDING = "embedding"
    TOOL_REQUEST = "tool_request"
    TOOL_RESULT = "tool_result"
    EVENT = "event"


class Capability(str, Enum):
    TEXT_GENERATION = "text_generation"
    CONVERSATION = "conversation"
    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    IMAGE_TO_TEXT = "image_to_text"
    RETRIEVAL = "retrieval"
    MEMORY = "memory"
    MAPS = "maps"
    TRANSLATION = "translation"
    CODING = "coding"
    TOOL_EXECUTION = "tool_execution"
    ROUTING = "routing"
    ECHO = "echo"


@dataclass
class PortSpec:
    name: str
    data_type: str
    direction: Literal["in", "out", "inout"]
    required: bool = True
    description: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "PortSpec":
        if not isinstance(value, dict):
            raise TypeError("Port specification must be a dictionary")
        if "name" not in value or not isinstance(value["name"], str) or not value["name"]:
            raise ValueError("Port specification requires a non-empty string 'name'")
        data_type = value.get("data_type", "text")
        if not isinstance(data_type, str):
            raise TypeError("Port 'data_type' must be a string")
        direction = value.get("direction", "in")
        if direction not in ("in", "out", "inout"):
            raise ValueError(f"Invalid port direction '{direction}', must be 'in', 'out', or 'inout'")
        required = bool(value.get("required", True))
        description = str(value.get("description", ""))
        schema = value.get("schema", {})
        if not isinstance(schema, dict):
            raise TypeError("Port 'schema' must be a dictionary")
        return cls(
            name=value["name"],
            data_type=data_type,
            direction=direction,
            required=required,
            description=description,
            schema=schema,
        )


@dataclass
class BrickResourceInfo:
    ram_mb: int = 0
    cpu: str = "low"
    gpu_required: bool = False
    vram_mb: int = 0

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BrickResourceInfo":
        if not isinstance(value, dict):
            raise TypeError("resources must be a dictionary")
        try:
            ram_mb = int(value.get("ram_mb", 0))
        except (ValueError, TypeError) as exc:
            raise TypeError("resources.ram_mb must be an integer") from exc
        cpu = str(value.get("cpu", "low"))
        gpu_required = bool(value.get("gpu_required", False))
        try:
            vram_mb = int(value.get("vram_mb", 0))
        except (ValueError, TypeError) as exc:
            raise TypeError("resources.vram_mb must be an integer") from exc
        return cls(
            ram_mb=ram_mb,
            cpu=cpu,
            gpu_required=gpu_required,
            vram_mb=vram_mb,
        )


@dataclass
class BrickRuntimeInfo:
    platforms: List[str]
    offline: bool = True
    streaming: bool = False
    batch: bool = False
    concurrency: int = 1

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BrickRuntimeInfo":
        if not isinstance(value, dict):
            raise TypeError("runtime must be a dictionary")
        platforms_val = value.get("platforms", ["any"])
        if not isinstance(platforms_val, list):
            raise TypeError("runtime.platforms must be a list of strings")
        platforms = [str(p) for p in platforms_val]
        offline = bool(value.get("offline", True))
        streaming = bool(value.get("streaming", False))
        batch = bool(value.get("batch", False))
        try:
            concurrency = int(value.get("concurrency", 1))
        except (ValueError, TypeError) as exc:
            raise TypeError("runtime.concurrency must be an integer") from exc
        return cls(
            platforms=platforms,
            offline=offline,
            streaming=streaming,
            batch=batch,
            concurrency=concurrency,
        )


@dataclass
class BrickManifestRecord:
    format: str
    format_version: str
    id: str
    name: str
    version: str
    capabilities: List[str]
    ports: Dict[str, List[PortSpec]]
    runtime: BrickRuntimeInfo
    resources: BrickResourceInfo
    entrypoint: Dict[str, Any]
    dependencies: List[str]
    permissions: List[str]
    metadata: Dict[str, Any]
    checksum: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BrickManifestRecord":
        raw_ports = value.get("ports", {}) or {}
        if not isinstance(raw_ports, dict):
            raise TypeError("Manifest ports must be a dictionary")
        ports_dict = {}
        for direction, port_list in raw_ports.items():
            if not isinstance(port_list, list):
                raise TypeError(f"Port group '{direction}' must be a list")
            ports_dict[direction] = [PortSpec.from_dict(item) for item in port_list]

        dependencies_val = value.get("dependencies", []) or []
        if not isinstance(dependencies_val, list):
            raise TypeError("Manifest dependencies must be a list")
        permissions_val = value.get("permissions", []) or []
        if not isinstance(permissions_val, list):
            raise TypeError("Manifest permissions must be a list")
        metadata_val = value.get("metadata", {}) or {}
        if not isinstance(metadata_val, dict):
            raise TypeError("Manifest metadata must be a dictionary")

        return cls(
            format=str(value.get("format", "whitebase-brick")),
            format_version=str(value.get("format_version", "1.0")),
            id=str(value.get("id", "")),
            name=str(value.get("name", "")),
            version=str(value.get("version", "0.1.0")),
            capabilities=[str(c) for c in value.get("capabilities", [])],
            ports=ports_dict,
            runtime=BrickRuntimeInfo.from_dict(value.get("runtime", {})),
            resources=BrickResourceInfo.from_dict(value.get("resources", {})),
            entrypoint=dict(value.get("entrypoint", {})),
            dependencies=[str(d) for d in dependencies_val],
            permissions=[str(p) for p in permissions_val],
            metadata=dict(metadata_val),
            checksum=value.get("checksum"),
        )
