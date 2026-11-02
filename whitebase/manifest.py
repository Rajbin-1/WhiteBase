from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional
from zipfile import BadZipFile, ZipFile

from .types import BrickManifestRecord, PortSpec


SUPPORTED_FORMAT_VERSIONS = {"1.0", "1.1"}
SUPPORTED_FORMAT_MAJOR_VERSIONS = {1}


class ManifestValidationError(ValueError):
    pass


def _safe_package_path(value: str, *, field_name: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ManifestValidationError(f"{field_name} must be a non-empty relative path without null bytes")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ManifestValidationError(f"{field_name} must stay within the Brick package")
    return path


def validate_manifest(data: Dict[str, Any]) -> BrickManifestRecord:
    if not isinstance(data, dict):
        raise ManifestValidationError("Manifest must be a JSON object / dictionary")

    required = ["format", "format_version", "id", "name", "version", "capabilities", "ports", "runtime", "resources", "entrypoint"]
    for field_name in required:
        if field_name not in data:
            raise ManifestValidationError(f"Missing required manifest field: {field_name}")

    if data["format"] != "whitebase-brick":
        raise ManifestValidationError("Manifest format must be 'whitebase-brick'")

    # Validate format_version
    format_version = str(data["format_version"])
    version_match = re.match(r"^(\d+)(?:\.(\d+))?.*$", format_version)
    if not version_match:
        raise ManifestValidationError(f"Invalid format_version format: '{format_version}'")
    major_version = int(version_match.group(1))
    if major_version not in SUPPORTED_FORMAT_MAJOR_VERSIONS:
        raise ManifestValidationError(f"Unsupported format_version major version: {major_version} (supported major versions: {SUPPORTED_FORMAT_MAJOR_VERSIONS})")

    brick_id = data["id"]
    if not isinstance(brick_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", brick_id):
        raise ManifestValidationError("Brick id must be a safe identifier")

    capabilities = data.get("capabilities", [])
    if not isinstance(capabilities, list) or not capabilities:
        raise ManifestValidationError("Manifest capabilities must be a non-empty list")
    for cap in capabilities:
        if not isinstance(cap, str) or not cap:
            raise ManifestValidationError("Manifest capabilities must be non-empty strings")

    ports = data.get("ports", {})
    if not isinstance(ports, dict) or not ports:
        raise ManifestValidationError("Manifest ports must define input and output specifications")
    for direction in ("inputs", "outputs"):
        if direction not in ports:
            raise ManifestValidationError(f"Missing port group: {direction}")
        if not isinstance(ports[direction], list):
            raise ManifestValidationError(f"Port group '{direction}' must be a list")
        for proto in ports[direction]:
            if not isinstance(proto, dict):
                raise ManifestValidationError(f"Port definition in '{direction}' must be a dictionary")
            if "name" not in proto or not proto["name"]:
                raise ManifestValidationError(f"Port in {direction} missing name")
            try:
                PortSpec.from_dict(proto)
            except (ValueError, TypeError) as exc:
                raise ManifestValidationError(f"Invalid port specification in '{direction}': {exc}") from exc

    # Validate runtime and resources structures
    if not isinstance(data.get("runtime"), dict):
        raise ManifestValidationError("Manifest runtime must be a dictionary")
    if not isinstance(data.get("resources"), dict):
        raise ManifestValidationError("Manifest resources must be a dictionary")

    # Validate entrypoint structure
    entrypoint = data.get("entrypoint")
    if not isinstance(entrypoint, dict):
        raise ManifestValidationError("Manifest entrypoint must be a dictionary")
    if not entrypoint.get("module") or not isinstance(entrypoint.get("module"), str):
        raise ManifestValidationError("Manifest entrypoint.module must be a non-empty string")
    if not entrypoint.get("class") or not isinstance(entrypoint.get("class"), str):
        raise ManifestValidationError("Manifest entrypoint.class is required")

    # Validate optional permissions, dependencies, and metadata structures
    if "permissions" in data and not isinstance(data["permissions"], list):
        raise ManifestValidationError("Manifest permissions must be a list")
    if "dependencies" in data and not isinstance(data["dependencies"], list):
        raise ManifestValidationError("Manifest dependencies must be a list")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise ManifestValidationError("Manifest metadata must be a dictionary")

    try:
        return BrickManifestRecord.from_dict(data)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"Manifest structure validation error: {exc}") from exc


def validate_package_archive(archive: ZipFile) -> BrickManifestRecord:
    names: set[str] = set()
    entries = archive.infolist()
    if not entries:
        raise ManifestValidationError("Brick package archive is empty")
    if len(entries) > 1000:
        raise ManifestValidationError("Brick package contains too many archive entries")

    total_size = 0
    for entry in entries:
        if "\x00" in entry.filename:
            raise ManifestValidationError(f"Null bytes are not allowed in archive paths: {entry.filename}")
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

    # If manifest declares a package checksum, verify actual package archive content
    declared_checksum = manifest.checksum
    if declared_checksum:
        archive_bytes = archive.read("connector.py")
        actual_connector_sha = hashlib.sha256(archive_bytes).hexdigest()
        raw_manifest_sha = hashlib.sha256(raw_manifest).hexdigest()
        combined_sha = hashlib.sha256(raw_manifest + archive_bytes).hexdigest()
        if declared_checksum not in (actual_connector_sha, raw_manifest_sha, combined_sha):
            raise ManifestValidationError(
                f"Package content checksum mismatch: declared '{declared_checksum}' does not match package content"
            )

    return manifest


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(path: str | Path) -> BrickManifestRecord:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    manifest = validate_manifest(data)
    # If checksum was not declared in manifest.json, compute sha256 of the manifest file
    if not manifest.checksum:
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
    "SUPPORTED_FORMAT_VERSIONS",
    "SUPPORTED_FORMAT_MAJOR_VERSIONS",
]
