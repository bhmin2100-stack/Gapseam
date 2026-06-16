from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.addon_manager import (
    ADDON_MANIFEST_FILENAME,
    AddonError,
    AddonManager,
    read_addon_manifest,
    sanitize_addon_id,
)


class AddonManagerTest(unittest.TestCase):
    def test_install_scan_and_toggle_addon_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source_addon"
            source.mkdir()
            (source / ADDON_MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "id": "depth-helper",
                        "name": "Depth Helper",
                        "version": "1.2.3",
                        "description": "Adds depth utilities.",
                        "extension_points": ["progress.panel"],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = AddonManager(addons_dir=root / "addons", state_path=root / "addons_state.json")

            manifest = manager.install_from_path(source, enable=True)

            self.assertEqual(manifest.addon_id, "depth-helper")
            installed_manifest = root / "addons" / "depth-helper" / ADDON_MANIFEST_FILENAME
            self.assertTrue(installed_manifest.exists())
            records = manager.scan()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].manifest.name, "Depth Helper")
            self.assertTrue(records[0].enabled)
            self.assertEqual(manager.enabled_ids(), ["depth-helper"])

            manager.set_enabled("depth-helper", False)

            records = manager.scan()
            self.assertFalse(records[0].enabled)
            self.assertEqual(manager.enabled_ids(), [])

            manager.install_from_path(root / "addons" / "depth-helper", enable=True)

            records = manager.scan()
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0].enabled)

    def test_read_manifest_uses_safe_folder_id_when_id_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            addon_dir = Path(tmp) / "bad id 한글"
            addon_dir.mkdir()
            (addon_dir / ADDON_MANIFEST_FILENAME).write_text(
                json.dumps({"name": "No ID"}, ensure_ascii=False),
                encoding="utf-8",
            )

            manifest = read_addon_manifest(addon_dir)

            self.assertEqual(manifest.addon_id, "bad_id")
            self.assertEqual(manifest.name, "No ID")
            self.assertEqual(sanitize_addon_id(" a/b:c "), "a_b_c")

    def test_invalid_manifest_raises_addon_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / ADDON_MANIFEST_FILENAME
            manifest_path.write_text("{bad json", encoding="utf-8")

            with self.assertRaises(AddonError):
                read_addon_manifest(manifest_path)


if __name__ == "__main__":
    unittest.main()
