from __future__ import annotations

import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from whitebase.manifest import ManifestValidationError, validate_manifest
from whitebase.runtime import AmbiguousRoutingError, BrickPackageError, WhiteBase


def create_brick(
    path: Path,
    *,
    brick_id: str,
    capability: str,
    format_version: str = "1.0",
    ports: dict | None = None,
    runtime: dict | None = None,
    resources: dict | None = None,
    entrypoint: dict | None = None,
    dependencies: list | None = None,
    permissions: list | None = None,
    metadata: dict | None = None,
    checksum: str | None = None,
    connector_code: str | None = None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    manifest = {
        "format": "whitebase-brick",
        "format_version": format_version,
        "id": brick_id,
        "name": brick_id,
        "version": "0.1.0",
        "capabilities": [capability],
        "ports": ports
        if ports is not None
        else {
            "inputs": [{"name": "in", "data_type": "text", "direction": "in"}],
            "outputs": [{"name": "out", "data_type": "text", "direction": "out"}],
        },
        "runtime": runtime
        if runtime is not None
        else {"platforms": ["any"], "offline": True, "streaming": False},
        "resources": resources
        if resources is not None
        else {"ram_mb": 16, "cpu": "low", "gpu_required": False},
        "entrypoint": entrypoint
        if entrypoint is not None
        else {"module": "connector.py", "class": "Brick"},
        "dependencies": dependencies if dependencies is not None else [],
        "permissions": permissions if permissions is not None else [],
        "metadata": metadata if metadata is not None else {},
    }
    if checksum is not None:
        manifest["checksum"] = checksum

    if connector_code is None:
        connector_code = (
            "class Brick:\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        return {'echo': payload}\n"
        )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        z.writestr("connector.py", connector_code)
        for name, content in (extra_files or {}).items():
            z.writestr(name, content)
    return path


class AuditedDefectsRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = Path(tempfile.mkdtemp(prefix="wb_audit_test_"))
        self.install_dir = self.tempdir / "installed"
        self.wb = WhiteBase(self.install_dir)

    # --- Defect 1: Connector loading regression tests ---
    def test_multi_file_and_sibling_module_imports(self) -> None:
        sibling_code = "SECRET = 'sibling-value-42'\n"
        connector_code = (
            "from __future__ import annotations\n"
            "import helper\n"
            "class Brick:\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        return {'val': helper.SECRET}\n"
        )
        pkg = create_brick(
            self.tempdir / "multifile.wb",
            brick_id="multifile",
            capability="multifile_cap",
            connector_code=connector_code,
            extra_files={"helper.py": sibling_code},
        )
        self.wb.install(pkg)
        res = self.wb.request("multifile_cap", {}, target="multifile")
        self.assertEqual(res, {"val": "sibling-value-42"})

    def test_dataclass_connector_with_future_annotations(self) -> None:
        connector_code = (
            "from __future__ import annotations\n"
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Brick:\n"
            "    counter: int = 100\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        return {'count': self.counter}\n"
        )
        pkg = create_brick(
            self.tempdir / "dataclass_brick.wb",
            brick_id="dc_brick",
            capability="dc_cap",
            connector_code=connector_code,
        )
        self.wb.install(pkg)
        res = self.wb.request("dc_cap", {}, target="dc_brick")
        self.assertEqual(res, {"count": 100})

    def test_module_name_isolation_between_bricks(self) -> None:
        conn1 = (
            "class Brick:\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        return {'brick': 1}\n"
        )
        conn2 = (
            "class Brick:\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        return {'brick': 2}\n"
        )
        pkg1 = create_brick(self.tempdir / "b1.wb", brick_id="brick1", capability="cap1", connector_code=conn1)
        pkg2 = create_brick(self.tempdir / "b2.wb", brick_id="brick2", capability="cap2", connector_code=conn2)
        self.wb.install(pkg1)
        self.wb.install(pkg2)

        c1 = self.wb.load("brick1")
        c2 = self.wb.load("brick2")
        self.assertNotEqual(c1.implementation.__class__.__module__, c2.implementation.__class__.__module__)
        self.assertEqual(self.wb.request("cap1", {}, target="brick1"), {"brick": 1})
        self.assertEqual(self.wb.request("cap2", {}, target="brick2"), {"brick": 2})

    # --- Defect 2: Real timeouts regression tests ---
    def test_real_timeout_terminates_execution(self) -> None:
        conn = (
            "import time\n"
            "class Brick:\n"
            "    def invoke(self, cap, payload, metadata=None):\n"
            "        time.sleep(10)\n"
            "        return {'done': True}\n"
        )
        pkg = create_brick(self.tempdir / "hung.wb", brick_id="hung", capability="hung_cap", connector_code=conn)
        self.wb.install(pkg)
        t0 = time.time()
        with self.assertRaises(TimeoutError):
            self.wb.request("hung_cap", {}, target="hung", timeout=0.1)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 2.0, f"Timeout took too long to terminate: {elapsed}s")

    # --- Defect 3: Manifest validation regression tests ---
    def test_unsupported_format_major_version_rejected(self) -> None:
        with self.assertRaises(ManifestValidationError):
            validate_manifest({
                "format": "whitebase-brick",
                "format_version": "2.0",
                "id": "v2",
                "name": "v2",
                "version": "0.1.0",
                "capabilities": ["test"],
                "ports": {
                    "inputs": [{"name": "in", "data_type": "text", "direction": "in"}],
                    "outputs": [{"name": "out", "data_type": "text", "direction": "out"}],
                },
                "runtime": {"platforms": ["any"]},
                "resources": {"ram_mb": 16},
                "entrypoint": {"module": "connector.py", "class": "Brick"},
            })

    def test_manifest_invalid_port_direction_rejected(self) -> None:
        with self.assertRaises(ManifestValidationError):
            validate_manifest({
                "format": "whitebase-brick",
                "format_version": "1.0",
                "id": "badport",
                "name": "badport",
                "version": "0.1.0",
                "capabilities": ["test"],
                "ports": {
                    "inputs": [{"name": "in", "data_type": "text", "direction": "invalid_dir"}],
                    "outputs": [{"name": "out", "data_type": "text", "direction": "out"}],
                },
                "runtime": {"platforms": ["any"]},
                "resources": {"ram_mb": 16},
                "entrypoint": {"module": "connector.py", "class": "Brick"},
            })

    def test_manifest_checksum_verification_failure(self) -> None:
        pkg = create_brick(
            self.tempdir / "badchecksum.wb",
            brick_id="badchecksum",
            capability="check_cap",
            checksum="0000000000000000000000000000000000000000000000000000000000000000",
        )
        with self.assertRaises(BrickPackageError):
            self.wb.install(pkg)

    # --- Defect 4: Install and routing robustness regression tests ---
    def test_discovery_ignores_stale_staging_and_backup_dirs(self) -> None:
        # Create a hidden staging directory and backup directory in install_dir
        staging = self.install_dir / ".stale.staging-12345"
        staging.mkdir(parents=True)
        (staging / "manifest.json").write_text('{"invalid": true}')

        backup = self.install_dir / ".brick.backup-67890"
        backup.mkdir(parents=True)
        (backup / "manifest.json").write_text('{"invalid": true}')

        # Re-initialize runtime
        fresh_wb = WhiteBase(self.install_dir)
        self.assertEqual(fresh_wb.list_components(), [])
        self.assertEqual(fresh_wb.discovery_errors, [])

    def test_discovery_exposes_failures_for_corrupt_unhidden_directories(self) -> None:
        bad_dir = self.install_dir / "corrupted_brick"
        bad_dir.mkdir(parents=True)
        (bad_dir / "manifest.json").write_text('{"format": "invalid"}')

        fresh_wb = WhiteBase(self.install_dir)
        self.assertGreater(len(fresh_wb.discovery_errors), 0)
        self.assertIn("corrupted_brick", fresh_wb.discovery_errors[0]["path"])

    def test_reinstall_does_not_duplicate_capability_registration(self) -> None:
        pkg = create_brick(self.tempdir / "dup.wb", brick_id="dup_brick", capability="dup_cap")
        self.wb.install(pkg)
        self.assertEqual(self.wb.capabilities()["dup_cap"], ["dup_brick"])
        # Reinstall same package
        self.wb.install(pkg)
        self.assertEqual(self.wb.capabilities()["dup_cap"], ["dup_brick"])

    def test_ambiguous_routing_raises_error_when_no_priority_or_default(self) -> None:
        pkg1 = create_brick(self.tempdir / "p1.wb", brick_id="provider1", capability="shared_cap")
        pkg2 = create_brick(self.tempdir / "p2.wb", brick_id="provider2", capability="shared_cap")
        self.wb.install(pkg1)
        self.wb.install(pkg2)

        with self.assertRaises(AmbiguousRoutingError):
            self.wb.request("shared_cap", {})

        # Specifying target resolves disambiguation
        res = self.wb.request("shared_cap", {"v": 1}, target="provider1")
        self.assertEqual(res, {"echo": {"v": 1}})

    def test_provider_selection_respects_priority_and_default_metadata(self) -> None:
        pkg_low = create_brick(
            self.tempdir / "low.wb",
            brick_id="low_priority",
            capability="ranked_cap",
            metadata={"priority": 10},
            connector_code="class Brick:\n    def invoke(self, c, p, metadata=None): return {'selected': 'low'}\n",
        )
        pkg_high = create_brick(
            self.tempdir / "high.wb",
            brick_id="high_priority",
            capability="ranked_cap",
            metadata={"priority": 50},
            connector_code="class Brick:\n    def invoke(self, c, p, metadata=None): return {'selected': 'high'}\n",
        )
        self.wb.install(pkg_low)
        self.wb.install(pkg_high)

        res = self.wb.request("ranked_cap", {})
        self.assertEqual(res, {"selected": "high"})


if __name__ == "__main__":
    unittest.main()
