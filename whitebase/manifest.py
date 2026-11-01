from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List
from zipfile import BadZipFile, ZipFile

from .types import BrickManifestRecord, PortSpec


class ManifestValidationError(ValueError):
    pass


def _safe_package_path(value: str, *, field_name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ManifestValidationError(f"{field_name} must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ManifestValidationError(f"{field_name} must stay within the Brick package")
    return path


def validate_package_archive(archive: ZipFile) -> BrickManifestRecord:
    names: set[str] = set()
    entries = archive.infolist()
    if not entries:
        raise ManifestValidationError("Brick package archive is empty")
    if len(entries) > 1000:
        raise ManifestValidationError("Brick package contains too many archive entries")

    total_size = 0
    for entry in entries:
        if entry.is_dir():
            name = entry.filename.rstrip("/")
        else:
            name = entry.filename
        path = _safe_package_path(name, field_name="Archive member path")
        normalized_name = path.as_posix().casefold()
        if normalized_name in names:
            raise ManifestValidationError(f"Duplicate archive member path: {entry.filename}")
        names.add(normalized_name)
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise ManifestValidationError(f"Symbolic links are not allowed in Brick packages: {entry.filename}")
        total_size += entry.file_size
        if total_size > 512 * 1024 * 1024:
            raise ManifestValidationError("Brick package expands beyond the 512 MiB safety limit")

    try:
        raw_manifest = archive.read("manifest.json")
        manifest_data = json.loads(raw_manifest.decode("utf-8"))
    except KeyError as exc:
        raise ManifestValidationError("Brick package is missing manifest.json") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError("Brick package manifest.json is not valid UTF-8 JSON") from exc

    manifest = validate_manifest(manifest_data)
    if "connector.py" not in names:
        raise ManifestValidationError("Brick package is missing connector.py")
    entrypoint = manifest.entrypoint.get("module")
    if not isinstance(entrypoint, str):
        raise ManifestValidationError("Manifest entrypoint.module must name a packaged file")
    entrypoint_path = _safe_package_path(entrypoint, field_name="Manifest entrypoint.module")
    if entrypoint_path.as_posix().casefold() not in names:
        raise ManifestValidationError("Manifest entrypoint.module is not present in the package")
    if not manifest.entrypoint.get("class"):
        raise ManifestValidationError("Manifest entrypoint.class is required")
    return manifest


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(data: Dict[str, Any]) -> BrickManifestRecord:
    required = ["format", "format_version", "id", "name", "version", "capabilities", "ports", "runtime", "resources", "entrypoint"]
    for field_name in required:
        if field_name not in data:
            raise ManifestValidationError(f"Missing required manifest field: {field_name}")
    if data["format"] != "whitebase-brick":
        raise ManifestValidationError("Manifest format must be 'whitebase-brick'")
    brick_id = data["id"]
    if not isinstance(brick_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", brick_id):
        raise ManifestValidationError("Brick id must be a safe identifier")
    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list) or not capabilities:
        raise ManifestValidationError("Manifest capabilities must be a non-empty list")
    ports = data.get("ports", {})
    if not isinstance(ports, dict) or not ports:
        raise ManifestValidationError("Manifest ports must define input and output specifications")
    for direction in ("inputs", "outputs"):
        if direction not in ports:
            raise ManifestValidationError(f"Missing port group: {direction}")
        for proto in ports[direction]:
            if "name" not in proto:
                raise ManifestValidationError(f"Port in {direction} missing name")
            PortSpec.from_dict(proto)
    return BrickManifestRecord.from_dict(data)


def load_manifest(path: str | Path) -> BrickManifestRecord:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = validate_manifest(data)
    manifest.checksum = _sha256_file(file_path)
    return manifest


def load_manifest_from_package(package_dir: str | Path, manifest_name: str = "manifest.json") -> BrickManifestRecord:
    file_path = Path(package_dir) / manifest_name
    return load_manifest(file_path)


__all__ = [
    "ManifestValidationError",
    "validate_manifest",
    "validate_package_archive",
    "load_manifest",
    "load_manifest_from_package",
]
