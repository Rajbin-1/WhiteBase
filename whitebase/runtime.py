from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .connector import BrickConnector
from .manifest import (
    ManifestValidationError,
    load_manifest,
    validate_manifest,
    validate_package_archive,
)
from .message import MessageEnvelope


DEFAULT_INSTALL_DIR = Path.home() / ".whitebase" / "bricks"


class BrickPackageError(ValueError):
    pass


@dataclass
class InstalledBrick:
    brick_id: str
    package_path: str
    install_dir: str
    manifest_path: str
    state: str = "registered"
    health: str = "healthy"
    connectivity: str = "disconnected"
    loaded: bool = False
    running: bool = False
    active_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeouts: int = 0
    cancelled_requests: int = 0
    last_request_time: Optional[float] = None
    last_success_time: Optional[float] = None
    last_error_time: Optional[float] = None
    uptime: float = 0.0
    load_count: int = 0
    unload_count: int = 0
    restart_count: int = 0
    average_latency: float = 0.0
    last_latency: Optional[float] = None
    connector: Optional[BrickConnector] = None
    started_at: float = field(default_factory=time.time)


class WhiteBase:
    def __init__(self, install_dir: str | os.PathLike[str] = DEFAULT_INSTALL_DIR):
        self.install_dir = Path(install_dir)
        self.install_dir.mkdir(parents=True, exist_ok=True)
        self.registry: Dict[str, InstalledBrick] = {}
        self.loaded: Dict[str, InstalledBrick] = {}
        self.capability_index: Dict[str, List[str]] = {}
        self._lifecycle_lock = threading.RLock()
        self.events: List[str] = []
        self.start_time = time.time()
        self.runtime_metrics = {
            "active_requests": 0,
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "timeouts": 0,
            "cancelled_requests": 0,
            "average_latency": 0.0,
            "total_latency": 0.0,
        }
        self._discover_installed()

    def _discover_installed(self) -> None:
        entries = sorted(self.install_dir.iterdir()) if self.install_dir.exists() else []
        for entry in entries:
            if entry.is_dir():
                manifest_path = entry / "manifest.json"
                if manifest_path.exists():
                    try:
                        manifest = load_manifest(manifest_path)
                    except Exception:
                        continue
                    installed = InstalledBrick(
                        brick_id=manifest.id,
                        package_path=str(entry),
                        install_dir=str(entry),
                        manifest_path=str(manifest_path),
                        state="registered",
                    )
                    self.registry.setdefault(manifest.id, installed)
                    self._index_capabilities(manifest)
            elif entry.suffix.lower() == ".wb":
                try:
                    self.install(entry)
                except Exception:
                    continue

    def _update_runtime_metrics(self, *, success: bool = False, timeout: bool = False, cancelled: bool = False, latency: Optional[float] = None) -> None:
        self.runtime_metrics["total_requests"] += 1
        self.runtime_metrics["active_requests"] = max(0, self.runtime_metrics["active_requests"] - 1)
        if success:
            self.runtime_metrics["successful_requests"] += 1
        elif timeout:
            self.runtime_metrics["timeouts"] += 1
            self.runtime_metrics["failed_requests"] += 1
        elif cancelled:
            self.runtime_metrics["cancelled_requests"] += 1
            self.runtime_metrics["failed_requests"] += 1
        else:
            self.runtime_metrics["failed_requests"] += 1
        if latency is not None:
            self.runtime_metrics["total_latency"] += latency
            if self.runtime_metrics["total_requests"]:
                self.runtime_metrics["average_latency"] = self.runtime_metrics["total_latency"] / self.runtime_metrics["total_requests"]

    def log(self, level: str, message: str) -> None:
        self.events.append(f"[{level}] {message}")

    def _runtime_status(self) -> str:
        if self.runtime_metrics["active_requests"] > 0:
            return "busy"
        unhealthy = sum(1 for brick in self.registry.values() if brick.health == "unhealthy")
        degraded = sum(1 for brick in self.registry.values() if brick.health == "degraded")
        if unhealthy > 0:
            return "unhealthy"
        if degraded > 0:
            return "degraded"
        return "healthy"

    def install(self, package_path: str | os.PathLike[str]) -> InstalledBrick:
        with self._lifecycle_lock:
            return self._install(package_path)

    def _install(self, package_path: str | os.PathLike[str]) -> InstalledBrick:
        source = Path(package_path)
        if not source.exists():
            raise FileNotFoundError(f"Brick package not found: {source}")
        if source.suffix.lower() != ".wb":
            raise BrickPackageError("Only .wb brick package files are supported")
        try:
            with zipfile.ZipFile(source, "r") as archive:
                manifest = validate_package_archive(archive)
                if manifest.id in self.loaded:
                    raise BrickPackageError(
                        f"Cannot replace loaded component '{manifest.id}'; unload it first"
                    )
                self.install_dir.mkdir(parents=True, exist_ok=True)
                staging_dir = Path(
                    tempfile.mkdtemp(prefix=f".{manifest.id}.staging-", dir=self.install_dir)
                )
                try:
                    archive.extractall(staging_dir)
                    staged_manifest_path = staging_dir / "manifest.json"
                    validated_manifest = load_manifest(staged_manifest_path)
                    if validated_manifest.id != manifest.id:
                        raise BrickPackageError("Brick manifest changed while being installed")
                    import_dir = self.install_dir / manifest.id
                    backup_dir = self.install_dir / f".{manifest.id}.backup-{uuid.uuid4().hex}"
                    moved_existing = False
                    if import_dir.exists():
                        import_dir.replace(backup_dir)
                        moved_existing = True
                    try:
                        staging_dir.replace(import_dir)
                    except Exception:
                        if moved_existing:
                            backup_dir.replace(import_dir)
                        raise
                    if moved_existing:
                        shutil.rmtree(backup_dir)
                finally:
                    if staging_dir.exists():
                        shutil.rmtree(staging_dir)
        except zipfile.BadZipFile as exc:
            raise BrickPackageError(f"Invalid Brick ZIP archive: {source}") from exc
        except ManifestValidationError as exc:
            raise BrickPackageError(f"Invalid Brick package: {exc}") from exc
        except OSError as exc:
            raise BrickPackageError(f"Unable to safely install Brick package {source}: {exc}") from exc

        manifest_path = import_dir / "manifest.json"
        manifest = load_manifest(manifest_path)
        brick_id = manifest.id
        previous = self.registry.get(brick_id)
        if previous is not None:
            for capability, providers in list(self.capability_index.items()):
                self.capability_index[capability] = [
                    provider for provider in providers if provider != brick_id
                ]
                if not self.capability_index[capability]:
                    del self.capability_index[capability]
        installed = InstalledBrick(
            brick_id=brick_id,
            package_path=str(source),
            install_dir=str(import_dir),
            manifest_path=str(manifest_path),
            state="registered",
            health="healthy",
            connectivity="disconnected",
        )
        self.registry[brick_id] = installed
        self._index_capabilities(manifest)
        self.log("INFO", f"component registered: {brick_id}")
        return installed

    def _index_capabilities(self, manifest) -> None:
        for cap in manifest.capabilities:
            self.capability_index.setdefault(cap, []).append(manifest.id)

    def list_components(self) -> List[str]:
        return sorted(self.registry.keys())

    def capabilities(self) -> Dict[str, List[str]]:
        return {cap: list(vals) for cap, vals in sorted(self.capability_index.items())}

    def inspect(self, component_id: str) -> Dict[str, Any]:
        brick = self.registry.get(component_id)
        if brick is None:
            raise KeyError(f"Unknown component: {component_id}")
        manifest = load_manifest(brick.manifest_path)
        return {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "capabilities": manifest.capabilities,
            "state": brick.state,
            "health": brick.health,
            "connectivity": brick.connectivity,
            "loaded": brick.loaded,
            "running": brick.running,
            "active_requests": brick.active_requests,
            "successful_requests": brick.successful_requests,
            "failed_requests": brick.failed_requests,
            "timeouts": brick.timeouts,
            "cancelled_requests": brick.cancelled_requests,
            "last_request_time": brick.last_request_time,
            "last_success_time": brick.last_success_time,
            "last_error_time": brick.last_error_time,
            "uptime": round(time.time() - brick.started_at, 6),
            "load_count": brick.load_count,
            "unload_count": brick.unload_count,
            "restart_count": brick.restart_count,
            "average_latency": brick.average_latency,
            "last_latency": brick.last_latency,
            "resources": {"ram_mb": manifest.resources.ram_mb, "cpu": manifest.resources.cpu, "gpu_required": manifest.resources.gpu_required},
            "offline": manifest.runtime.offline,
            "streaming": manifest.runtime.streaming,
        }

    def component_status(self, component_id: str) -> Dict[str, Any]:
        brick = self.registry.get(component_id)
        if brick is None:
            raise KeyError(f"Unknown component: {component_id}")
        return self.inspect(component_id)

    def status(self) -> Dict[str, Any]:
        return self.health_snapshot()

    def health(self) -> Dict[str, Any]:
        return self.health_snapshot()

    def component_health(self, component_id: str) -> Dict[str, Any]:
        brick = self.registry.get(component_id)
        if brick is None:
            raise KeyError(f"Unknown component: {component_id}")
        if brick.connector is None:
            brick.connectivity = "disconnected"
            brick.health = "unhealthy"
            brick.state = "stopped"
            return self.inspect(component_id)
        try:
            result = brick.connector.health()
            status = str(result.get("status", "ok")).lower() if isinstance(result, dict) else "ok"
            brick.health = "healthy" if status in {"ok", "healthy"} else "degraded"
            brick.connectivity = "connected"
            brick.state = "ready" if brick.loaded else "registered"
        except Exception:
            brick.health = "unhealthy"
            brick.connectivity = "disconnected"
            brick.state = "error"
        return self.inspect(component_id)

    def capability_status(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for capability, candidates in sorted(self.capability_index.items()):
            entries: Dict[str, Any] = {}
            for brick_id in candidates:
                brick = self.registry.get(brick_id)
                if brick is None:
                    continue
                entry = self.component_status(brick_id)
                entries[brick_id] = {
                    "state": entry["state"],
                    "health": entry["health"],
                    "connectivity": entry["connectivity"],
                    "loaded": entry["loaded"],
                    "running": entry["running"],
                }
            statuses = {item["health"] for item in entries.values()}
            if not entries:
                result[capability] = {"status": "unavailable", "providers": {}}
            elif statuses and all(status == "healthy" for status in statuses):
                result[capability] = {"status": "ready", "providers": entries}
            elif any(status == "healthy" for status in statuses):
                result[capability] = {"status": "degraded", "providers": entries}
            else:
                result[capability] = {"status": "error", "providers": entries}
        return result

    def health_snapshot(self) -> Dict[str, Any]:
        runtime_status = self._runtime_status()
        runtime = {
            "status": runtime_status,
            "uptime": round(time.time() - self.start_time, 6),
            "active_requests": self.runtime_metrics["active_requests"],
            "total_requests": self.runtime_metrics["total_requests"],
            "successful_requests": self.runtime_metrics["successful_requests"],
            "failed_requests": self.runtime_metrics["failed_requests"],
            "timeouts": self.runtime_metrics["timeouts"],
            "cancelled_requests": self.runtime_metrics["cancelled_requests"],
            "average_latency": round(self.runtime_metrics["average_latency"], 6),
            "throughput": round((self.runtime_metrics["successful_requests"] / max(time.time() - self.start_time, 0.0001)), 6),
        }
        components = {component_id: self.inspect(component_id) for component_id in sorted(self.registry)}
        capability_index = self.capability_status()
        resources = {
            "component_count": len(self.registry),
            "loaded_component_count": len(self.loaded),
            "running_component_count": sum(1 for brick in self.registry.values() if brick.running),
            "healthy_component_count": sum(1 for brick in self.registry.values() if brick.health == "healthy"),
            "degraded_component_count": sum(1 for brick in self.registry.values() if brick.health == "degraded"),
            "unhealthy_component_count": sum(1 for brick in self.registry.values() if brick.health == "unhealthy"),
        }
        return {
            "runtime": runtime,
            "components": components,
            "capabilities": capability_index,
            "resources": resources,
            "requests": {
                "active_requests": runtime["active_requests"],
                "total_requests": runtime["total_requests"],
                "successful_requests": runtime["successful_requests"],
                "failed_requests": runtime["failed_requests"],
                "timeouts": runtime["timeouts"],
                "cancelled_requests": runtime["cancelled_requests"],
                "average_latency": runtime["average_latency"],
                "throughput": runtime["throughput"],
            },
        }

    def load(self, component_id: str) -> BrickConnector:
        with self._lifecycle_lock:
            return self._load(component_id)

    def _load(self, component_id: str) -> BrickConnector:
        brick = self.registry.get(component_id)
        if brick is None:
            raise KeyError(f"Unknown component: {component_id}")
        brick.state = "loading"
        brick.health = "healthy"
        brick.connectivity = "connecting"
        if brick.connector is not None:
            brick.state = "loaded"
            brick.loaded = True
            brick.running = True
            brick.connectivity = "connected"
            brick.health = "healthy"
            brick.load_count += 1
            self.loaded[component_id] = brick
            return brick.connector
        try:
            manifest = load_manifest(brick.manifest_path)
            module_path = Path(brick.install_dir) / manifest.entrypoint.get("module", "connector.py")
            if not module_path.exists():
                raise FileNotFoundError(f"Brick entrypoint not found: {module_path}")
            spec = importlib.util.spec_from_file_location(f"whitebase_brick_{component_id}", module_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Unable to import connector module from {module_path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            class_name = manifest.entrypoint.get("class")
            if not class_name:
                raise KeyError(f"Missing entrypoint.class in manifest for {component_id}")
            cls = getattr(module, class_name, None)
            if cls is None:
                raise AttributeError(f"Entry class '{class_name}' not found in {module_path}")
            instance = cls()
            connector = BrickConnector(
                brick_id=component_id,
                name=manifest.name,
                capabilities=list(manifest.capabilities),
                implementation=instance,
                manifest=manifest,
                metadata={"install_dir": brick.install_dir},
            )
        except Exception as exc:
            brick.connector = None
            brick.state = "error"
            brick.loaded = False
            brick.running = False
            brick.connectivity = "disconnected"
            brick.health = "unhealthy"
            brick.last_error_time = time.time()
            self.loaded.pop(component_id, None)
            self.log("ERROR", f"component load failed: {component_id}: {exc}")
            raise

        brick.connector = connector
        brick.state = "loaded"
        brick.loaded = True
        brick.running = True
        brick.connectivity = "connected"
        brick.health = "healthy"
        brick.load_count += 1
        self.loaded[component_id] = brick
        self.log("INFO", f"component loaded: {component_id}")
        return connector

    def unload(self, component_id: str) -> None:
        with self._lifecycle_lock:
            self._unload(component_id)

    def _unload(self, component_id: str) -> None:
        brick = self.registry.get(component_id)
        if brick is None:
            raise KeyError(f"Unknown component: {component_id}")
        if brick.active_requests:
            raise RuntimeError(
                f"Cannot unload component '{component_id}' while it has active requests"
            )
        brick.state = "stopping"
        brick.running = False
        if brick.connector is not None:
            try:
                brick.connector.unload()
            except Exception as exc:
                brick.state = "error"
                brick.health = "unhealthy"
                brick.connectivity = "disconnected"
                brick.last_error_time = time.time()
                self.log("ERROR", f"component unload failed: {component_id}: {exc}")
                raise
        brick.connector = None
        brick.state = "stopped"
        brick.loaded = False
        brick.connectivity = "disconnected"
        brick.health = "healthy"
        brick.unload_count += 1
        self.loaded.pop(component_id, None)
        self.log("INFO", f"component unloaded: {component_id}")

    def _resolve_target(self, capability: str, target: Optional[str]) -> str:
        candidates = self.capability_index.get(capability, [])
        if target is not None:
            if target not in self.registry:
                raise KeyError(f"Component not available: {target}")
            if target not in candidates:
                raise KeyError(f"Component '{target}' does not provide capability '{capability}'")
            return target
        if not candidates:
            raise KeyError(f"No component registered for capability: {capability}")
        return candidates[0]

    def request(self, capability: str, payload: Dict[str, Any], *, target: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None, timeout: Optional[float] = None) -> Any:
        with self._lifecycle_lock:
            resolved = self._resolve_target(capability, target)
            if resolved not in self.loaded:
                self.load(resolved)
            brick = self.loaded.get(resolved)
            if brick is None or brick.connector is None:
                raise RuntimeError(f"Component is not loaded: {resolved}")
            connector = brick.connector
            brick.state = "running"
            brick.running = True
            brick.health = "healthy"
            brick.connectivity = "connected"
            brick.active_requests += 1
            self.runtime_metrics["active_requests"] += 1
            self.runtime_metrics["total_requests"] += 1
            started = time.time()
        try:
            result = connector.invoke(capability, payload, metadata=metadata or {})
            elapsed = time.time() - started
            if timeout is not None and elapsed > timeout:
                raise TimeoutError(f"Request timed out for {capability} after {timeout}s")
            with self._lifecycle_lock:
                brick.last_request_time = time.time()
                brick.last_success_time = time.time()
                brick.last_latency = elapsed
                brick.successful_requests += 1
                brick.average_latency = ((brick.average_latency * max(brick.successful_requests - 1, 1)) + elapsed) / max(brick.successful_requests, 1)
                self.runtime_metrics["successful_requests"] += 1
                self.runtime_metrics["total_latency"] += elapsed
                self.runtime_metrics["average_latency"] = self.runtime_metrics["total_latency"] / self.runtime_metrics["total_requests"]
                self.log("INFO", f"request completed: {capability} via {resolved} in {elapsed:.4f}s")
            return result
        except TimeoutError as exc:
            with self._lifecycle_lock:
                brick.timeouts += 1
                brick.failed_requests += 1
                brick.last_error_time = time.time()
                brick.health = "degraded"
                brick.connectivity = "connected"
                brick.state = "loaded"
                self.runtime_metrics["timeouts"] += 1
                self.runtime_metrics["failed_requests"] += 1
                self.log("ERROR", str(exc))
            raise
        except Exception as exc:
            with self._lifecycle_lock:
                brick.failed_requests += 1
                brick.last_error_time = time.time()
                brick.health = "unhealthy"
                brick.connectivity = "disconnected"
                brick.state = "error"
                self.runtime_metrics["failed_requests"] += 1
                self.log("ERROR", str(exc))
            raise
        finally:
            with self._lifecycle_lock:
                brick.active_requests = max(0, brick.active_requests - 1)
                self.runtime_metrics["active_requests"] = max(0, self.runtime_metrics["active_requests"] - 1)
                if brick.active_requests == 0 and brick.state == "running":
                    brick.state = "loaded"

    def request_envelope(self, message: MessageEnvelope) -> Any:
        return self.request(message.capability, message.payload, target=message.target, metadata=message.metadata, session_id=message.session_id)

    def stream_request(self, capability: str, payload: Dict[str, Any], *, target: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Iterator[Any]:
        with self._lifecycle_lock:
            resolved = self._resolve_target(capability, target)
            if resolved not in self.loaded:
                self.load(resolved)
            connector = self.loaded[resolved].connector
            if connector is None:
                raise RuntimeError(f"Component is not loaded: {resolved}")
        return iter(connector.stream(capability, payload, metadata=metadata or {}))

    def remove(self, component_id: str) -> None:
        with self._lifecycle_lock:
            if component_id in self.loaded:
                self.unload(component_id)
            if component_id in self.registry:
                del self.registry[component_id]
            self.capability_index = {cap: [item for item in ids if item != component_id] for cap, ids in self.capability_index.items()}
            self.capability_index = {cap: ids for cap, ids in self.capability_index.items() if ids}
            package_dir = self.install_dir / component_id
            if package_dir.exists():
                shutil.rmtree(package_dir)
            self.log("INFO", f"component removed: {component_id}")

    def benchmark(self) -> Dict[str, Any]:
        start = time.perf_counter()
        self.log("INFO", "benchmark started")
        registered = len(self.registry)
        elapsed = time.perf_counter() - start
        return {
            "registered_components": registered,
            "startup_overhead_seconds": round(elapsed, 6),
            "event_count": len(self.events),
        }

    def install_from_directory(self, source_dir: str | os.PathLike[str]) -> InstalledBrick:
        source = Path(source_dir)
        if not source.exists():
            raise FileNotFoundError(source)
        manifest_path = source / "manifest.json"
        manifest = load_manifest(manifest_path)
        package_path = self.install_dir / f"{manifest.id}.wb"
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in source.rglob("*"):
                if file.is_file():
                    archive.write(file, file.relative_to(source))
        return self.install(package_path)


__all__ = ["WhiteBase", "InstalledBrick", "BrickPackageError"]
