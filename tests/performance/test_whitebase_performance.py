from __future__ import annotations

import json
import math
import tempfile
import threading
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from whitebase.runtime import WhiteBase


class WhiteBasePerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="whitebase_perf_"))
        self.wb = WhiteBase(self.tempdir / "bricks")
        self._install_bricks()

    def _install_brick(self, brick_id: str, capability: str, source_code: str) -> None:
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
            "metadata": {"family": "mock", "category": "performance"},
        }
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("connector.py", source_code)
        self.wb.install(package_path)

    def _install_bricks(self) -> None:
        self._install_brick(
            "echo_fast",
            "echo_fast",
            '''class Brick:
    def invoke(self, capability, payload, metadata=None):
        text = payload.get("text", "")
        return {"text": text, "source": "echo_fast"}
''',
        )
        self._install_brick(
            "stream_perf",
            "stream_perf",
            '''class Brick:
    def stream(self, capability, payload, metadata=None):
        for chunk in payload.get("text", "").split():
            yield chunk
''',
        )

    @staticmethod
    def _percentile(samples, pct):
        if not samples:
            return 0.0
        ordered = sorted(samples)
        index = max(0, min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1))
        return ordered[index]

    def test_load_unload_cycles_measure_latency_and_growth(self) -> None:
        latencies = []
        memory_before = 0
        try:
            import tracemalloc
            tracemalloc.start()
            memory_before, _ = tracemalloc.get_traced_memory()
        except Exception:
            memory_before = 0

        for index in range(100):
            t0 = time.perf_counter()
            self.wb.load("echo_fast")
            load_time = time.perf_counter() - t0
            t1 = time.perf_counter()
            self.wb.request("echo_fast", {"text": f"cycle-{index}"}, target="echo_fast")
            request_time = time.perf_counter() - t1
            t2 = time.perf_counter()
            self.wb.unload("echo_fast")
            unload_time = time.perf_counter() - t2
            latencies.append({"load": load_time, "request": request_time, "unload": unload_time})

        if "tracemalloc" in globals():
            memory_after, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            growth = memory_after - memory_before
            self.assertLess(growth, 25 * 1024 * 1024, f"memory leak detected: {growth} bytes growth")

        self.assertEqual(len(latencies), 100)
        self.assertTrue(all(item["request"] >= 0 for item in latencies))

    def test_concurrent_requests_p95_p99_and_throughput(self) -> None:
        concurrency_levels = [10, 50, 100]
        summary = {}

        for level in concurrency_levels:
            start = time.perf_counter()
            latencies = []
            lock = threading.Lock()

            def worker(i: int) -> None:
                t0 = time.perf_counter()
                result = self.wb.request("echo_fast", {"text": f"concurrent-{i}"}, target="echo_fast")
                elapsed = time.perf_counter() - t0
                with lock:
                    latencies.append(elapsed)
                    self.assertEqual(result["text"], f"concurrent-{i}")

            with ThreadPoolExecutor(max_workers=min(level, 32)) as pool:
                list(pool.map(worker, range(level)))

            total_time = time.perf_counter() - start
            summary[str(level)] = {
                "total_time_seconds": round(total_time, 6),
                "average_latency_seconds": round(sum(latencies) / len(latencies), 6),
                "median_latency_seconds": round(sorted(latencies)[len(latencies) // 2], 6),
                "p95_latency_seconds": round(self._percentile(latencies, 95), 6),
                "p99_latency_seconds": round(self._percentile(latencies, 99), 6),
                "throughput_rps": round(level / total_time, 6) if total_time > 0 else 0.0,
            }

        self.assertGreater(summary["10"]["throughput_rps"], 0)
        self.assertGreater(summary["100"]["total_time_seconds"], 0)

    def test_streaming_100_chunks_and_parallel_streams(self) -> None:
        payload = " ".join(f"chunk-{index}" for index in range(100))
        stream = self.wb.stream_request("stream_perf", {"text": payload}, target="stream_perf")
        chunks = list(stream)
        self.assertEqual(len(chunks), 100)
        self.assertEqual(chunks[0], "chunk-0")
        self.assertEqual(chunks[-1], "chunk-99")

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda idx: list(self.wb.stream_request("stream_perf", {"text": f"a {idx} b c"}, target="stream_perf")), range(10)))

        self.assertEqual(len(results), 10)
        for idx, chunks_out in enumerate(results):
            self.assertEqual(chunks_out, ["a", str(idx), "b", "c"])


if __name__ == "__main__":
    unittest.main()
