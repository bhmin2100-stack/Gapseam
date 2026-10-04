from __future__ import annotations

import tempfile
import unittest
import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest import mock

from gapsim.emulation.parameter_library import (
    delete_parameter_preset,
    list_parameter_presets,
    parameter_preset_application_values,
    ParameterLibraryError,
    CALCULATION_PARAMETER_FIELDS,
    GEOMETRY_PARAMETER_FIELDS,
    RUN_PARAMETER_FIELDS,
    read_parameter_preset,
    sanitize_parameter_preset_name,
    save_parameter_preset,
)
from gapsim.emulation.trench_depo import TrenchDepoConfig


class ParameterLibraryTest(unittest.TestCase):
    def test_save_list_read_and_delete_parameter_preset_without_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parameter_presets.json"
            config = TrenchDepoConfig(
                points=[(-10.0, 0.0), (10.0, 0.0)],
                cycles=17,
                angstrom_per_cycle=9.5,
                sputter_enabled=True,
                sputter_strength_a_per_cycle=3.25,
            )

            saved_name = save_parameter_preset(path, "  모델/4 테스트  ", config, emulator_number=4)

            self.assertEqual(saved_name, "모델_4 테스트")
            self.assertEqual(list_parameter_presets(path), [saved_name])
            record = read_parameter_preset(path, saved_name)
            self.assertEqual(record["emulator_number"], 4)
            self.assertEqual(record["config"]["emulator_number"], 4)
            self.assertEqual(parameter_preset_application_values(record, config)["emulator_number"], 4)
            self.assertEqual(record["run_defaults"]["cycles"], 17)
            self.assertAlmostEqual(record["config"]["angstrom_per_cycle"], 9.5)
            self.assertNotIn("points", record["config"])
            self.assertNotIn("cycles", record["config"])
            self.assertNotIn("reparam_ds_a", record["config"])
            self.assertNotIn("deposition_feature_width_a", record["config"])
            self.assertEqual(record["schema_version"], 2)

            deleted_name = delete_parameter_preset(path, saved_name)
            self.assertEqual(deleted_name, saved_name)
            self.assertEqual(list_parameter_presets(path), [])

    def test_sanitize_parameter_preset_name_keeps_korean_and_limits_length(self) -> None:
        self.assertEqual(sanitize_parameter_preset_name(" 리뎁/강함:*? "), "리뎁_강함___")
        self.assertLessEqual(len(sanitize_parameter_preset_name("x" * 200)), 80)

    def test_apply_keeps_current_structure_run_and_solver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            saved = TrenchDepoConfig(
                points=[(-10.0, 0.0), (10.0, 0.0)], cycles=150,
                angstrom_per_cycle=2.0, reparam_ds_a=5.0,
                deposition_feature_type="hole", deposition_feature_width_a=500.0,
                deposition_feature_depth_a=2200.0, redepo_incident_ray_count=25,
                sputter_enabled=True, sputter_smoothing_a=20.0,
            )
            current = replace(
                saved, points=[(-20.0, 0.0), (20.0, 0.0)], cycles=600,
                angstrom_per_cycle=7.0, reparam_ds_a=10.0,
                deposition_feature_type="line", deposition_feature_width_a=800.0,
                deposition_feature_depth_a=4000.0, redepo_incident_ray_count=49,
                sputter_enabled=False, sputter_smoothing_a=90.0,
            )
            save_parameter_preset(path, "공정", saved, emulator_number=0)
            record = read_parameter_preset(path, "공정")
            actual = parameter_preset_application_values(record, current)
            for key in GEOMETRY_PARAMETER_FIELDS | RUN_PARAMETER_FIELDS | CALCULATION_PARAMETER_FIELDS:
                if key in actual:
                    self.assertEqual(actual[key], asdict(current)[key], key)
            self.assertEqual(actual["angstrom_per_cycle"], 2.0)
            self.assertTrue(actual["sputter_enabled"])
            self.assertEqual(actual["sputter_smoothing_a"], 20.0)
            restored = parameter_preset_application_values(
                record, current, include_run_defaults=True, include_calculation_settings=True,
            )
            self.assertEqual(restored["cycles"], 150)
            self.assertEqual(restored["reparam_ds_a"], 5.0)
            self.assertEqual(restored["redepo_incident_ray_count"], 25)
            self.assertEqual(restored["points"], asdict(current)["points"])
            self.assertEqual(restored["deposition_feature_width_a"], 800.0)

    def test_legacy_read_is_non_mutating_and_missing_flags_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            raw = {"version": 1, "presets": {"old": {
                "name": "old", "emulator_number": 0,
                "config": {"cycles": 40, "angstrom_per_cycle": 3.0,
                           "deposition_feature_width_a": 500.0, "reparam_ds_a": 5.0},
            }}}
            path.write_text(json.dumps(raw), encoding="utf-8")
            original = path.read_bytes()
            record = read_parameter_preset(path, "old")
            current = TrenchDepoConfig(cycles=200, redepo_incident_los_enabled=True,
                                      deposition_feature_width_a=1200.0, reparam_ds_a=10.0)
            actual = parameter_preset_application_values(record, current)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(actual["cycles"], 200)
            self.assertEqual(actual["deposition_feature_width_a"], 1200.0)
            self.assertEqual(actual["reparam_ds_a"], 10.0)
            self.assertFalse(actual["redepo_incident_los_enabled"])
            explicit = parameter_preset_application_values(record, current, include_run_defaults=True)
            self.assertEqual(explicit["cycles"], 40)

    def test_saving_one_legacy_record_preserves_other_records_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            old_record = {"config": {"cycles": 12}, "created_at": "before", "memo": "keep"}
            untouched = {"config": {"cycles": 17}, "custom": {"a": 2}}
            path.write_text(json.dumps({"version": 1, "metadata": "keep-library",
                                       "presets": {"edit": old_record, "other": untouched}}),
                            encoding="utf-8")
            save_parameter_preset(path, "edit", TrenchDepoConfig(), emulator_number=0)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(result["version"], 2)
            self.assertEqual(result["metadata"], "keep-library")
            self.assertEqual(result["presets"]["other"], untouched)
            self.assertEqual(result["presets"]["edit"]["created_at"], "before")
            self.assertEqual(result["presets"]["edit"]["memo"], "keep")

    def test_all_configuration_fields_remain_reconstructable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            config = TrenchDepoConfig(points=[(-10.0, 0.0), (10.0, 0.0)], cycles=32)
            save_parameter_preset(path, "full", config, emulator_number=0)
            record = read_parameter_preset(path, "full")
            reconstructed = {}
            for group in ("config", "run_defaults", "calculation_settings", "source_structure"):
                self.assertFalse(set(reconstructed) & set(record[group]), group)
                reconstructed.update(record[group])
            # JSON intentionally stores point tuples as arrays.
            self.assertEqual(reconstructed, json.loads(json.dumps(asdict(config))))

    def test_atomic_save_failure_preserves_library(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            save_parameter_preset(path, "old", TrenchDepoConfig(), emulator_number=0)
            original = path.read_bytes()
            with mock.patch("gapsim.emulation.parameter_library.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    save_parameter_preset(path, "new", TrenchDepoConfig(), emulator_number=0)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(tmp).iterdir()), [path])

    def test_future_library_version_is_not_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            path.write_text('{"version": 99, "presets": {}}', encoding="utf-8")
            original = path.read_bytes()
            with self.assertRaises(ParameterLibraryError):
                save_parameter_preset(path, "new", TrenchDepoConfig(), emulator_number=0)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
