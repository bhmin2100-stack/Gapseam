from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gapsim.emulation import addon_manager, research_registry, trench_depo_export
from gapsim.emulation.data_paths import (
    DATA_CONFIG_ENV,
    DATA_ROOT_ENV,
    configure_data_root,
    configured_data_paths,
)


class DataPathsTest(unittest.TestCase):
    def test_configure_data_root_creates_shared_layout_and_persists_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "shared_gfe_data"
            config = Path(tmp) / "settings" / "data_root.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                paths = configure_data_root(root, config_path=config)

                self.assertEqual(paths.root, root.resolve())
                self.assertTrue(paths.runs_root.is_dir())
                self.assertTrue(paths.results_root.is_dir())
                self.assertTrue(paths.research_root.is_dir())
                self.assertTrue(paths.addons_root.is_dir())
                self.assertEqual(os.environ[DATA_ROOT_ENV], str(root.resolve()))

            payload = json.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(payload["data_root"], str(root.resolve()))

            with mock.patch.dict(os.environ, {DATA_CONFIG_ENV: str(config)}, clear=True):
                loaded = configured_data_paths()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.structure_library_path, root.resolve() / "emulator_research" / "structures.xlsx")
            self.assertEqual(loaded.parameter_library_path, root.resolve() / "emulator_research" / "parameter_presets.json")
            self.assertEqual(loaded.addon_state_path, root.resolve() / "addons" / "addons_state.json")

    def test_data_root_env_overrides_saved_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_root = Path(tmp) / "config_root"
            env_root = Path(tmp) / "env_root"
            config = Path(tmp) / "settings.json"
            with mock.patch.dict(os.environ, {}, clear=True):
                configure_data_root(config_root, config_path=config)

            with mock.patch.dict(
                os.environ,
                {
                    DATA_CONFIG_ENV: str(config),
                    DATA_ROOT_ENV: str(env_root),
                },
                clear=True,
            ):
                loaded = configured_data_paths()

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.root, env_root.resolve())

    def test_existing_default_helpers_follow_configured_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "portable_data"
            with mock.patch.dict(os.environ, {DATA_ROOT_ENV: str(root)}, clear=True):
                self.assertEqual(
                    trench_depo_export._default_runs_root(),
                    root.resolve() / "runs" / "trench_depo_emulation",
                )
                self.assertEqual(
                    trench_depo_export._default_results_root(),
                    root.resolve() / "results" / "trench_depo_emulation",
                )
                self.assertEqual(
                    research_registry._default_research_root(),
                    root.resolve() / "emulator_research",
                )
                self.assertEqual(
                    addon_manager._default_addon_root(),
                    root.resolve() / "addons",
                )


if __name__ == "__main__":
    unittest.main()
