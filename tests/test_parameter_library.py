from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.parameter_library import (
    delete_parameter_preset,
    list_parameter_presets,
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
            self.assertEqual(record["config"]["cycles"], 17)
            self.assertAlmostEqual(record["config"]["angstrom_per_cycle"], 9.5)
            self.assertNotIn("points", record["config"])

            deleted_name = delete_parameter_preset(path, saved_name)
            self.assertEqual(deleted_name, saved_name)
            self.assertEqual(list_parameter_presets(path), [])

    def test_sanitize_parameter_preset_name_keeps_korean_and_limits_length(self) -> None:
        self.assertEqual(sanitize_parameter_preset_name(" 리뎁/강함:*? "), "리뎁_강함___")
        self.assertLessEqual(len(sanitize_parameter_preset_name("x" * 200)), 80)


if __name__ == "__main__":
    unittest.main()
