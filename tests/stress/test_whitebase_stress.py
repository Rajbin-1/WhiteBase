from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import tracemalloc
import unittest
import zipfile
from pathlib import Path

from whitebase.runtime import BrickPackageError, WhiteBase


class WhiteBaseStressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="whitebase_stress_"))
        self.wb = WhiteBase(self.tempdir / "bricks")
        self._install_graph_bricks()

    def _install_package(self, brick_id: str, capability: str, source_code: str) -> None:
        package_path = self.tempdir / f"{brick_id}.wb"
        manifest = {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": brick_id,
            "name": brick_id.title(),
            "version": "0.1.0",
            "capabilities": [capability],
            "ports": {
                "inputs": [{"name": "text", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "result", "data_type": "text", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows", "linux"], "offline": True, "streaming": capability == "streaming"},
            "resources": {"ram_mb": 32, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "Brick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"family": "mock", "category": "stress"},
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("connector.py", source_code)
        self.wb.install(package_path)

    def _install_graph_bricks(self) -> None:
        sys.modules["test_runtime_binding"] = type("Binding", (), {"RUNTIME": self.wb})

        self._install_package(
            "stt",
            "speech_to_text",
            '''import test_runtime_binding
RUNTIME = test_runtime_binding.RUNTIME

class Brick:
    def invoke(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        next_capability = metadata.get("next_capability") if metadata else None
        next_target = metadata.get("next_target") if metadata else None
        if next_capability:
            return RUNTIME.request(next_capability, {"text": text.strip().lower()}, target=next_target, metadata={"next_capability": "maps", "next_target": "maps"})
        return {"text": text.strip().lower(), "source": capability}
''',
        )

        self._install_package(
            "brain",
            "reasoning",
            '''import test_runtime_binding
RUNTIME = test_runtime_binding.RUNTIME

class Brick:
    def invoke(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        next_capability = metadata.get("next_capability") if metadata else None
        next_target = metadata.get("next_target") if metadata else None
        processed = text.upper()
        if next_capability:
            return RUNTIME.request(next_capability, {"text": processed}, target=next_target, metadata={"next_capability": "maps", "next_target": "maps"})
        return {"text": processed, "source": capability}
''',
        )

        self._install_package(
            "maps",
            "maps",
            '''import test_runtime_binding
RUNTIME = test_runtime_binding.RUNTIME

class Brick:
    def invoke(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        next_capability = metadata.get("next_capability") if metadata else None
        next_target = metadata.get("next_target") if metadata else None
        processed = f"map:{text}"
        if next_capability:
            return RUNTIME.request(next_capability, {"text": processed}, target=next_target, metadata={"next_capability": "text_to_speech", "next_target": "tts"})
        return {"text": processed, "source": capability}
''',
        )

        self._install_package(
            "tts",
            "text_to_speech",
            '''class Brick:
    def invoke(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        return {"text": f"spoken:{text}", "source": capability}
''',
        )

    def test_registration_discovery_and_graph_routing(self) -> None:
        self.assertIn("stt", self.wb.list_components())
        self.assertIn("speech_to_text", self.wb.capabilities())
        self.assertIn("reasoning", self.wb.capabilities())
        self.assertIn("maps", self.wb.capabilities())
        self.assertIn("text_to_speech", self.wb.capabilities())

        result = self.wb.request(
            "speech_to_text",
            {"text": "  Hello World  "},
            target="stt",
            metadata={"next_capability": "reasoning", "next_target": "brain"},
        )
        self.assertIn("spoken:", result["text"])
        self.assertIn("HELLO", result["text"])
        self.assertTrue(result["text"].startswith("spoken:"))

    def test_installing_new_bricks_during_running_runtime(self) -> None:
        extra_id = "validator"
        self._install_package(
            extra_id,
            "validation",
            '''class Brick:
    def invoke(self, capability, payload, metadata=None):
        return {"ok": True, "text": payload.get("text", "")}
''',
        )

        self.assertIn(extra_id, self.wb.list_components())
        self.assertIn("validation", self.wb.capabilities())
        self.assertEqual(self.wb.request("validation", {"text": "still-live"}, target=extra_id)["text"], "still-live")

        original = self.wb.request("speech_to_text", {"text": "original"}, target="stt")
        self.assertEqual(original["text"], "original")

    def test_load_unload_cycles_do_not_leak_state(self) -> None:
        tracemalloc.start()
        base, _ = tracemalloc.get_traced_memory()

        for index in range(100):
            self.wb.load("stt")
            response = self.wb.request("speech_to_text", {"text": f"cycle-{index}"}, target="stt")
            self.assertEqual(response["text"], f"cycle-{index}")
            self.wb.unload("stt")

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertLess(current - base, 50 * 1024 * 1024, f"memory growth too large after 100 cycles: {current - base} bytes")

    def test_concurrent_requests_remain_isolated(self) -> None:
        def worker(value: str) -> dict:
            return self.wb.request("speech_to_text", {"text": value}, target="stt")

        threads = []
        results = []
        lock = threading.Lock()

        def runner(value: str) -> None:
            result = worker(value)
            with lock:
                results.append(result)

        for index in range(25):
            thread = threading.Thread(target=runner, args=(f"request-{index}",))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        self.assertEqual(len(results), 25)
        texts = sorted((item["text"] for item in results), key=lambda value: int(value.split("-")[1]))
        self.assertEqual(texts, [f"request-{index}" for index in range(25)])

    def test_streaming_ordering_and_cancellation(self) -> None:
        self._install_package(
            "streamer",
            "streaming",
            '''class Brick:
    def stream(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        for index, chunk in enumerate(text.split()):
            yield f"{index}:{chunk}"
''',
        )
        stream = self.wb.stream_request("streaming", {"text": "one two three four five"}, target="streamer")
        chunks = list(stream)
        self.assertEqual(len(chunks), 5)
        self.assertEqual(chunks[0], "0:one")
        self.assertEqual(chunks[-1], "4:five")

        iterator = self.wb.stream_request("streaming", {"text": "a b c d e f g"}, target="streamer")
        first_six = [next(iterator) for _ in range(3)]
        self.assertEqual(first_six, ["0:a", "1:b", "2:c"])

    def test_broken_components_fail_cleanly(self) -> None:
        self._install_package(
            "crasher",
            "crash",
            '''class Brick:
    def invoke(self, capability, payload, metadata=None):
        raise RuntimeError("simulated component crash")
''',
        )

        with self.assertRaises(RuntimeError):
            self.wb.request("crash", {"text": "boom"}, target="crasher")

        with self.assertRaises(BrickPackageError):
            self.wb.install(
                self._write_invalid_manifest_package(
                    "broken_manifest",
                    {"format": "whitebase-brick", "id": "broken_manifest", "capabilities": []},
                )
            )

    def _write_invalid_manifest_package(self, brick_id: str, manifest_data: dict) -> Path:
        package_path = self.tempdir / f"{brick_id}.wb"
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest_data))
            archive.writestr("connector.py", "class Brick:\n    def invoke(self, capability, payload, metadata=None):\n        return {}\n")
        return package_path


if __name__ == "__main__":
    unittest.main()
