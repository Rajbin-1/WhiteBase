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
        return cls(
            name=value["name"],
            data_type=value.get("data_type", "text"),
            direction=value.get("direction", "in"),
            required=value.get("required", True),
            description=value.get("description", ""),
            schema=value.get("schema", {}),
        )


@dataclass
class BrickResourceInfo:
    ram_mb: int = 0
    cpu: str = "low"
    gpu_required: bool = False
    vram_mb: int = 0

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "BrickResourceInfo":
        return cls(
            ram_mb=int(value.get("ram_mb", 0)),
            cpu=str(value.get("cpu", "low")),
            gpu_required=bool(value.get("gpu_required", False)),
            vram_mb=int(value.get("vram_mb", 0)),
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
        return cls(
            platforms=list(value.get("platforms", ["any"])),
            offline=bool(value.get("offline", True)),
            streaming=bool(value.get("streaming", False)),
            batch=bool(value.get("batch", False)),
            concurrency=int(value.get("concurrency", 1)),
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
        ports_dict = {}
        for direction, port_list in (value.get("ports", {}) or {}).items():
            ports_dict[direction] = [PortSpec.from_dict(item) for item in port_list]
        return cls(
            format=value.get("format", "whitebase-brick"),
            format_version=str(value.get("format_version", "1.0")),
            id=str(value.get("id", "")),
            name=str(value.get("name", "")),
            version=str(value.get("version", "0.1.0")),
            capabilities=list(value.get("capabilities", [])),
            ports=ports_dict,
            runtime=BrickRuntimeInfo.from_dict(value.get("runtime", {})),
            resources=BrickResourceInfo.from_dict(value.get("resources", {})),
            entrypoint=value.get("entrypoint", {}),
            dependencies=list(value.get("dependencies", [])),
            permissions=list(value.get("permissions", [])),
            metadata=value.get("metadata", {}),
            checksum=value.get("checksum"),
        )
