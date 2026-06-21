from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.addon_manager import ADDON_MANIFEST_FILENAME, AddonManager
from gapsim.emulation.addon_runtime import load_enabled_addons


class _FakeWindow:
    def __init__(self) -> None:
        self.progress_widgets = []

    def _add_addon_progress_widget(self, widget, *, title: str = "") -> None:
        self.progress_widgets.append((widget, title))


class AddonRuntimeTest(unittest.TestCase):
    def test_load_enabled_addon_calls_register_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon_dir = root / "addons" / "hello"
            addon_dir.mkdir(parents=True)
            (addon_dir / ADDON_MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "id": "hello",
                        "name": "Hello",
                        "version": "0.1.0",
                        "entrypoint": "addon.py",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (addon_dir / "addon.py").write_text(
                "def register(context):\n"
                "    context.log('registered')\n"
                "    context.add_progress_widget({'ok': True}, title='Hello Box')\n"
                "    return {'handle': context.addon_id}\n",
                encoding="utf-8",
            )
            manager = AddonManager(addons_dir=root / "addons", state_path=root / "addons" / "addons_state.json")
            logs = []
            window = _FakeWindow()

            handles, results = load_enabled_addons(manager.scan(), window=window, log=logs.append)

            self.assertEqual(handles, [{"handle": "hello"}])
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].loaded)
            self.assertEqual(window.progress_widgets, [({"ok": True}, "Hello Box")])
            self.assertIn("[hello] registered", logs)

    def test_entrypoint_cannot_escape_addon_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            addon_dir = root / "addons" / "bad"
            addon_dir.mkdir(parents=True)
            (addon_dir / ADDON_MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "id": "bad",
                        "name": "Bad",
                        "version": "0.1.0",
                        "entrypoint": "../outside.py",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = AddonManager(addons_dir=root / "addons", state_path=root / "addons" / "addons_state.json")

            _handles, results = load_enabled_addons(manager.scan(), window=_FakeWindow(), log=lambda _msg: None)

            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].loaded)
            self.assertIn("escapes addon folder", results[0].message)


if __name__ == "__main__":
    unittest.main()
