from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from whitebase.runtime import BrickPackageError, WhiteBase


def write_package(path: Path, *, brick_id: str = "test-brick", capability: str = "test_capability",
                  connector: str = "class Brick:\n    def invoke(self, capability, payload, metadata=None):\n        return payload\n",
                  entrypoint: str = "connector.py", members: dict[str, str] | None = None) -> Path:
    manifest = {
        "format": "whitebase-brick",
        "format_version": "1.0",
        "id": brick_id,
        "name": brick_id,
        "version": "0.1.0",
        "capabilities": [capability],
        "ports": {
            "inputs": [{"name": "payload", "data_type": "object", "direction": "in"}],
            "outputs": [{"name": "result", "data_type": "object", "direction": "out"}],
        },
        "runtime": {"platforms": ["windows"], "offline": True, "streaming": False},
        "resources": {"ram_mb": 16, "cpu": "low", "gpu_required": False},
        "entrypoint": {"module": entrypoint, "class": "Brick"},
        "dependencies": [],
        "permissions": [],
        "metadata": {"category": "architecture-test"},
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("connector.py", connector)
        for name, content in (members or {}).items():
            archive.writestr(name, content)
    return path


class BrickPackageSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="whitebase_arch_security_"))
        self.wb = WhiteBase(self.tempdir / "installed")

    def test_rejects_parent_traversal_and_does_not_write_outside_install_dir(self) -> None:
        outside = self.tempdir / "escape.txt"
        package = write_package(
            self.tempdir / "traversal.wb",
            members={"../escape.txt": "escaped"},
        )

        with self.assertRaises(BrickPackageError):
            self.wb.install(package)

        self.assertFalse(outside.exists())
        self.assertEqual(self.wb.list_components(), [])

    def test_rejects_windows_parent_traversal(self) -> None:
        package = write_package(
            self.tempdir / "windows-traversal.wb",
            members={"..\\escape.txt": "escaped"},
        )

        with self.assertRaises(BrickPackageError):
            self.wb.install(package)

        self.assertFalse((self.tempdir / "escape.txt").exists())

    def test_rejects_unsafe_manifest_entrypoint(self) -> None:
        package = write_package(
            self.tempdir / "unsafe-entrypoint.wb",
            entrypoint="../outside.py",
        )

        with self.assertRaises(BrickPackageError):
            self.wb.install(package)

        self.assertEqual(self.wb.list_components(), [])

    def test_failed_replacement_preserves_existing_brick(self) -> None:
        original = write_package(self.tempdir / "original.wb")
        self.wb.install(original)
        invalid = self.tempdir / "invalid.wb"
        with zipfile.ZipFile(invalid, "w") as archive:
            archive.writestr("../escape.txt", "no manifest")

        with self.assertRaises(BrickPackageError):
            self.wb.install(invalid)

        self.assertEqual(self.wb.list_components(), ["test-brick"])
        self.assertEqual(self.wb.request("test_capability", {"value": 1}), {"value": 1})

    def test_reinstall_updates_capability_index_without_duplicates(self) -> None:
        self.wb.install(write_package(self.tempdir / "first.wb"))
        replacement = write_package(
            self.tempdir / "replacement.wb",
            capability="replacement_capability",
        )
        self.wb.install(replacement)

        self.assertEqual(self.wb.capabilities(), {"replacement_capability": ["test-brick"]})

    def test_cannot_replace_a_loaded_brick(self) -> None:
        self.wb.install(write_package(self.tempdir / "loaded.wb"))
        self.wb.load("test-brick")

        with self.assertRaises(BrickPackageError):
            self.wb.install(
                write_package(self.tempdir / "replacement-loaded.wb", capability="new_capability")
            )

        self.assertEqual(self.wb.capabilities(), {"test_capability": ["test-brick"]})
        self.wb.unload("test-brick")


class RuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="whitebase_arch_runtime_"))
        self.wb = WhiteBase(self.tempdir / "installed")

    def test_target_must_provide_requested_capability(self) -> None:
        package = write_package(
            self.tempdir / "other.wb",
            brick_id="other",
            capability="other_capability",
        )
        self.wb.install(package)

        with self.assertRaisesRegex(KeyError, "does not provide"):
            self.wb.request("missing_capability", {}, target="other")

    def test_timeout_is_not_counted_as_success(self) -> None:
        package = write_package(
            self.tempdir / "slow.wb",
            brick_id="slow",
            capability="slow",
            connector=(
                "import time\n"
                "class Brick:\n"
                "    def invoke(self, capability, payload, metadata=None):\n"
                "        time.sleep(0.03)\n"
                "        return {'done': True}\n"
            ),
        )
        self.wb.install(package)
        with self.assertRaises(TimeoutError):
            self.wb.request(
                "slow",
                {"wait": "true"},
                target="slow",
                timeout=0.01,
            )

        stats = self.wb.inspect("slow")
        snapshot = self.wb.health_snapshot()["runtime"]
        self.assertEqual(stats["successful_requests"], 0)
        self.assertEqual(stats["failed_requests"], 1)
        self.assertEqual(stats["timeouts"], 1)
        self.assertEqual(snapshot["successful_requests"], 0)
        self.assertEqual(snapshot["failed_requests"], 1)
        self.assertEqual(snapshot["timeouts"], 1)

    def test_failed_connector_load_records_error_state(self) -> None:
        package = write_package(
            self.tempdir / "invalid-connector.wb",
            connector="raise RuntimeError('connector import failed')\n",
        )
        self.wb.install(package)

        with self.assertRaisesRegex(RuntimeError, "connector import failed"):
            self.wb.load("test-brick")

        component = self.wb.inspect("test-brick")
        self.assertEqual(component["state"], "error")
        self.assertEqual(component["health"], "unhealthy")
        self.assertEqual(component["connectivity"], "disconnected")
        self.assertNotIn("test-brick", self.wb.loaded)

    def test_concurrent_first_requests_load_connector_once(self) -> None:
        marker = self.tempdir / "constructors.txt"
        connector = (
            "import time\n"
            "class Brick:\n"
            "    def __init__(self):\n"
            f"        with open({str(marker)!r}, 'a', encoding='utf-8') as handle:\n"
            "            handle.write('loaded\\n')\n"
            "        time.sleep(0.05)\n"
            "    def invoke(self, capability, payload, metadata=None):\n"
            "        return payload\n"
        )
        self.wb.install(
            write_package(
                self.tempdir / "concurrent.wb",
                brick_id="concurrent",
                capability="concurrent",
                connector=connector,
            )
        )
        barrier = threading.Barrier(12)

        def request(index: int) -> dict:
            barrier.wait()
            return self.wb.request(
                "concurrent",
                {"value": index},
                target="concurrent",
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(request, range(12)))

        self.assertEqual(results, [{"value": index} for index in range(12)])
        self.assertEqual(len(marker.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(self.wb.inspect("concurrent")["load_count"], 1)

    def test_unload_is_rejected_while_request_is_active(self) -> None:
        package = write_package(
            self.tempdir / "slow-active.wb",
            brick_id="slow-active",
            capability="slow-active",
            connector=(
                "import time\n"
                "class Brick:\n"
                "    def invoke(self, capability, payload, metadata=None):\n"
                "        time.sleep(payload.get('delay', 0.1))\n"
                "        return {'done': True}\n"
            ),
        )
        self.wb.install(package)

        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(
                self.wb.request,
                "slow-active",
                {"delay": 0.1},
                target="slow-active",
            )
            deadline = time.monotonic() + 2
            while self.wb.inspect("slow-active")["active_requests"] == 0 and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertEqual(self.wb.inspect("slow-active")["active_requests"], 1)
            with self.assertRaisesRegex(RuntimeError, "active requests"):
                self.wb.unload("slow-active")
            self.assertTrue(self.wb.inspect("slow-active")["loaded"])
            self.assertEqual(result.result(timeout=2), {"done": True})

        self.wb.unload("slow-active")
        self.assertEqual(self.wb.inspect("slow-active")["state"], "stopped")

    def test_failed_shutdown_records_error_and_can_be_retried(self) -> None:
        package = write_package(
            self.tempdir / "shutdown-fails-once.wb",
            connector=(
                "class Brick:\n"
                "    def __init__(self):\n"
                "        self.shutdown_attempts = 0\n"
                "    def shutdown(self):\n"
                "        self.shutdown_attempts += 1\n"
                "        if self.shutdown_attempts == 1:\n"
                "            raise RuntimeError('shutdown failed once')\n"
            ),
        )
        self.wb.install(package)
        self.wb.load("test-brick")

        with self.assertRaisesRegex(RuntimeError, "shutdown failed once"):
            self.wb.unload("test-brick")
        component = self.wb.inspect("test-brick")
        self.assertEqual(component["state"], "error")
        self.assertEqual(component["health"], "unhealthy")
        self.assertIn("test-brick", self.wb.loaded)

        self.wb.unload("test-brick")
        self.assertEqual(self.wb.inspect("test-brick")["state"], "stopped")
        self.assertNotIn("test-brick", self.wb.loaded)

    def test_transient_connector_failure_recovers_on_retry(self) -> None:
        package = write_package(
            self.tempdir / "recovers.wb",
            connector=(
                "class Brick:\n"
                "    def __init__(self):\n"
                "        self.failed = False\n"
                "    def invoke(self, capability, payload, metadata=None):\n"
                "        if not self.failed:\n"
                "            self.failed = True\n"
                "            raise RuntimeError('transient connector error')\n"
                "        return {'recovered': True}\n"
            ),
        )
        self.wb.install(package)

        with self.assertRaisesRegex(RuntimeError, "transient connector error"):
            self.wb.request("test_capability", {}, target="test-brick")
        self.assertEqual(self.wb.inspect("test-brick")["state"], "error")

        self.assertEqual(
            self.wb.request("test_capability", {}, target="test-brick"),
            {"recovered": True},
        )
        component = self.wb.inspect("test-brick")
        self.assertEqual(component["state"], "loaded")
        self.assertEqual(component["health"], "healthy")
        self.assertEqual(component["failed_requests"], 1)
        self.assertEqual(component["successful_requests"], 1)


if __name__ == "__main__":
    unittest.main()
