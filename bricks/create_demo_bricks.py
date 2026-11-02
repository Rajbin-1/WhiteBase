from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def write_brick(package_name: str, manifest: dict, source_code: str) -> Path:
    zip_path = ROOT / f"{package_name}.wb"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("connector.py", source_code)
        archive.writestr("README.md", f"# {manifest['name']}\n")
    return zip_path


def main() -> None:
    write_brick(
        "echo",
        {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": "echo",
            "name": "Echo Brick",
            "version": "0.1.0",
            "capabilities": ["echo", "text_generation"],
            "ports": {
                "inputs": [{"name": "text", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "echo", "data_type": "text", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows", "linux"], "offline": True, "streaming": False},
            "resources": {"ram_mb": 32, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "EchoBrick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"family": "mock", "category": "demo"},
        },
        '''class EchoBrick:\n    def invoke(self, capability, payload, metadata=None):\n        text = payload.get("text", "")\n        return {"text": text, "echoed": True, "source": "echo"}\n\n    def health(self):\n        return {"status": "ok", "brick": "echo"}\n''',
    )

    write_brick(
        "transform",
        {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": "transform",
            "name": "Transform Brick",
            "version": "0.1.0",
            "capabilities": ["transform", "structured_output"],
            "ports": {
                "inputs": [{"name": "text", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "struct", "data_type": "structured_data", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows", "linux"], "offline": True, "streaming": False},
            "resources": {"ram_mb": 32, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "TransformBrick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"family": "mock", "category": "demo"},
        },
        '''class TransformBrick:\n    def invoke(self, capability, payload, metadata=None):\n        text = payload.get("text", "")\n        words = text.split()\n        return {"structured": {"word_count": len(words), "chars": len(text), "tokens": words[:3]}}\n\n    def health(self):\n        return {"status": "ok", "brick": "transform"}\n''',
    )

    write_brick(
        "streaming",
        {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": "streaming",
            "name": "Streaming Brick",
            "version": "0.1.0",
            "capabilities": ["streaming"],
            "ports": {
                "inputs": [{"name": "text", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "chunks", "data_type": "text", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows", "linux"], "offline": True, "streaming": True},
            "resources": {"ram_mb": 24, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "StreamingBrick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"family": "mock", "category": "demo"},
        },
        '''class StreamingBrick:\n    def stream(self, capability, payload, metadata=None):\n        text = payload.get("text", "")\n        for chunk in text.split():\n            yield chunk\n\n    def health(self):\n        return {"status": "ok", "brick": "streaming"}\n''',
    )

    write_brick(
        "slow",
        {
            "format": "whitebase-brick",
            "format_version": "1.0",
            "id": "slow",
            "name": "Slow Brick",
            "version": "0.1.0",
            "capabilities": ["slow"],
            "ports": {
                "inputs": [{"name": "wait", "data_type": "text", "direction": "in"}],
                "outputs": [{"name": "done", "data_type": "text", "direction": "out"}],
            },
            "runtime": {"platforms": ["windows", "linux"], "offline": True, "streaming": False},
            "resources": {"ram_mb": 20, "cpu": "low", "gpu_required": False},
            "entrypoint": {"module": "connector.py", "class": "SlowBrick"},
            "dependencies": [],
            "permissions": [],
            "metadata": {"family": "mock", "category": "demo"},
        },
        '''import time\n\nclass SlowBrick:\n    def invoke(self, capability, payload, metadata=None):\n        time.sleep(0.05)\n        return {"done": True, "waited": 0.05}\n\n    def health(self):\n        return {"status": "ok", "brick": "slow"}\n''',
    )

    print(f"Created demo bricks in {ROOT}")


if __name__ == "__main__":
    main()
