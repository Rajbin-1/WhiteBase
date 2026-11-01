from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from whitebase.manifest import validate_manifest
from whitebase.runtime import WhiteBase

ROOT = Path(__file__).resolve().parents[1]
BRICK_DIR = ROOT / "bricks"


class WhiteBaseRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="whitebase_"))
        self.wb = WhiteBase(self.tempdir / "bricks")

    def test_manifest_validation(self) -> None:
        manifest = {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": "demo",
            "name": "Demo Brick",
            "version": "0.1.0",
            "capabilities": ["echo"],
            "ports": {
                "inputs": [{"name": "text", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "out", "data_type": "text", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows"], "offline": True, "streaming": False},
            "resources": {"ram_mb": 32, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "EchoBrick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"category": "test"},
        }
        record = validate_manifest(manifest)
        self.assertEqual(record.id, "demo")

    def test_install_and_discover(self) -> None:
        self.wb.install(BRICK_DIR / "echo.wb")
        self.assertIn("echo", self.wb.list_components())
        self.assertIn("text_generation", self.wb.capabilities())

    def test_request_round_trip(self) -> None:
        self.wb.install(BRICK_DIR / "echo.wb")
        result = self.wb.request("text_generation", {"text": "hello"}, target="echo")
        self.assertEqual(result["text"], "hello")

    def test_streaming(self) -> None:
        self.wb.install(BRICK_DIR / "streaming.wb")
        result = list(self.wb.stream_request("streaming", {"text": "one two"}, target="streaming"))
        self.assertEqual(result, ["one", "two"])

    def test_streaming_requires_a_stream_capable_connector(self) -> None:
        self.wb.install(BRICK_DIR / "echo.wb")
        with self.assertRaises(NotImplementedError):
            list(self.wb.stream_request("echo", {"text": "hello"}, target="echo"))

    def test_transform_structured_output(self) -> None:
        self.wb.install(BRICK_DIR / "transform.wb")
        result = self.wb.request("transform", {"text": "alpha beta gamma"}, target="transform")
        self.assertEqual(result["structured"]["word_count"], 3)

    def test_unload_and_remove(self) -> None:
        self.wb.install(BRICK_DIR / "echo.wb")
        self.wb.unload("echo")
        self.assertEqual(self.wb.loaded.get("echo"), None)
        self.wb.remove("echo")
        self.assertNotIn("echo", self.wb.list_components())

    def test_timeout_guard(self) -> None:
        self.wb.install(BRICK_DIR / "slow.wb")
        with self.assertRaises(TimeoutError):
            self.wb.request("slow", {"wait": "true"}, target="slow", timeout=0.01)

    def test_health_snapshot_and_component_state_tracking(self) -> None:
        self.wb.install(BRICK_DIR / "echo.wb")
        self.wb.load("echo")
        snapshot = self.wb.health_snapshot()
        self.assertEqual(snapshot["runtime"]["status"], "healthy")
        self.assertEqual(snapshot["components"]["echo"]["health"], "healthy")
        self.assertEqual(snapshot["components"]["echo"]["connectivity"], "connected")
        self.assertIn("text_generation", snapshot["capabilities"])
        self.assertIn("ready", snapshot["capabilities"]["text_generation"]["status"])

        self.wb.request("text_generation", {"text": "health state"}, target="echo")
        snapshot = self.wb.health_snapshot()
        self.assertEqual(snapshot["components"]["echo"]["state"], "loaded")
        self.assertTrue(snapshot["components"]["echo"]["running"])
        self.assertEqual(snapshot["resources"]["running_component_count"], 1)

        self.wb.unload("echo")
        snapshot = self.wb.health_snapshot()
        self.assertEqual(snapshot["components"]["echo"]["connectivity"], "disconnected")
        self.assertEqual(snapshot["components"]["echo"]["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
