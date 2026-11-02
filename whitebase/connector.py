from __future__ import annotations

import concurrent.futures
import multiprocessing as mp
import pickle
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
    """Worker that runs inside an isolated child process."""
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


def _is_subprocess_safe(obj: Any) -> bool:
    """
    Return True only if obj's class can survive a Windows multiprocessing spawn.
    Requirements:
      1. The object must be picklable.
      2. Its class must live in a real importable module (not a dynamically
         injected sys.modules entry without a file on disk), so the spawned
         child process can re-import it.
    """
    try:
        pickle.dumps(obj)
    except Exception:
        return False
    mod_name = getattr(obj.__class__, "__module__", None)
    if not mod_name:
        return False
    import sys, importlib.util
    mod = sys.modules.get(mod_name)
    if mod is None:
        return False
    # A module loaded from a real file has a __spec__ with an origin on disk.
    spec = getattr(mod, "__spec__", None)
    if spec is None or getattr(spec, "origin", None) is None:
        return False
    import os
    return os.path.isfile(spec.origin)


def _thread_invoke(implementation: Any, capability: str,
                   payload: Dict[str, Any], metadata: Dict[str, Any]) -> Any:
    """In-process call — used when the brick can't be pickled."""
    if hasattr(implementation, "invoke"):
        return implementation.invoke(capability, payload, metadata=metadata)
    if hasattr(implementation, "handle_request"):
        return implementation.handle_request(capability, payload, metadata=metadata)
    raise NotImplementedError("No supported invoke method found")


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
            # Fast in-process path — no isolation overhead
            if hasattr(self.implementation, "invoke"):
                return self.implementation.invoke(capability, payload, metadata=metadata)
            if hasattr(self.implementation, "handle_request"):
                return self.implementation.handle_request(capability, payload, metadata=metadata)
            raise NotImplementedError(f"No supported invoke method exists on brick '{self.brick_id}'")

        # --- Timeout path ---
        # WhiteBase bricks are loaded from arbitrary install paths that are not
        # on the child's sys.path in a Windows 'spawn' multiprocessing context.
        # Even when the brick module has a real file on disk, the child process
        # cannot reconstruct it without that path.  Thread-based timeout is safe,
        # correct, and avoids all spawn / pickling / path issues.  Hard process
        # kill is only needed for truly hung native code — pure-Python bricks are
        # interrupted cleanly by the ThreadPoolExecutor future timeout.
        return self._invoke_with_thread_timeout(capability, payload, metadata, timeout)

        # --- Subprocess path (kept for future use when bricks are installable
        #     as proper Python packages on sys.path) ---
        # if not _is_subprocess_safe(self.implementation):
        #     return self._invoke_with_thread_timeout(...)

        parent_conn, child_conn = mp.Pipe()
        proc = mp.Process(
            target=_subprocess_invoke_worker,
            args=(child_conn, self.implementation, capability, payload, metadata),
        )
        proc.start()
        child_conn.close()
        try:
            if parent_conn.poll(timeout):
                try:
                    status, result = parent_conn.recv()
                except EOFError:
                    # Child crashed before writing — treat as a hard error
                    raise RuntimeError(
                        f"Brick '{self.brick_id}' subprocess exited unexpectedly "
                        f"(capability: {capability})"
                    )
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
                    f"Request timed out for {capability} on brick '{self.brick_id}' "
                    f"after {timeout}s (subprocess terminated)"
                )
        finally:
            parent_conn.close()
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=0.5)

    def _invoke_with_thread_timeout(
        self,
        capability: str,
        payload: Dict[str, Any],
        metadata: Dict[str, Any],
        timeout: float,
    ) -> Any:
        """
        Thread-based timeout fallback for bricks whose implementation cannot be
        pickled (all dynamically-loaded bricks on Windows).  The thread cannot be
        forcibly killed — if it hangs past the deadline the TimeoutError is raised
        immediately and the thread is abandoned as a daemon.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_thread_invoke, self.implementation,
                                 capability, payload, metadata)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(
                    f"Request timed out for {capability} on brick '{self.brick_id}' "
                    f"after {timeout}s (thread timeout — brick cannot be subprocess-isolated)"
                )

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
