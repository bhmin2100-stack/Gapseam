from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.research_registry import (
    DEFAULT_CREATED_EMULATOR_NUMBERS,
    EMULATOR_RESEARCH_SLOTS,
    emulator_research_paths,
    ensure_emulator_research_slot,
    ensure_emulator_research_tree,
    get_emulator_research_slot,
    load_created_emulator_numbers,
    next_emulator_number,
    save_created_emulator_numbers,
)


class EmulationResearchRegistryTest(unittest.TestCase):
    def test_registry_has_baseline_and_ten_numbered_slots(self) -> None:
        numbers = [slot.number for slot in EMULATOR_RESEARCH_SLOTS]

        self.assertEqual(numbers, list(range(0, 11)))
        self.assertEqual(len({slot.directory_name for slot in EMULATOR_RESEARCH_SLOTS}), 11)
        self.assertEqual(DEFAULT_CREATED_EMULATOR_NUMBERS, (0, 1, 2, 3, 4, 5))

    def test_slot_zero_is_conformal_baseline(self) -> None:
        slot = get_emulator_research_slot(0)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("컨포멀", slot.title_ko)
        self.assertIn("Baseline", slot.title_en)
        self.assertIn("에뮬레이터00", slot.presentation_filename)

    def test_slot_one_is_current_angle_sputter_etch_emulator(self) -> None:
        slot = get_emulator_research_slot(1)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("각도기반", slot.title_ko)
        self.assertIn("Sputter", slot.title_en)
        self.assertIn("에뮬레이터01", slot.presentation_filename)
        self.assertTrue(slot.presentation_filename.endswith(".pptx"))

    def test_slot_two_is_ion_transmission_emulator(self) -> None:
        slot = get_emulator_research_slot(2)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("이온", slot.title_ko)
        self.assertIn("Transmission", slot.title_en)
        self.assertIn("에뮬레이터02", slot.presentation_filename)

    def test_slot_three_is_reflected_ion_emulator(self) -> None:
        slot = get_emulator_research_slot(3)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("반사", slot.title_ko)
        self.assertIn("Reflected", slot.title_en)
        self.assertIn("에뮬레이터03", slot.presentation_filename)

    def test_slot_four_is_redeposition_prep_emulator(self) -> None:
        slot = get_emulator_research_slot(4)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("리데포", slot.title_ko)
        self.assertIn("Redeposition", slot.title_en)
        self.assertIn("에뮬레이터04", slot.presentation_filename)

    def test_slot_five_is_depth_deposition_emulator(self) -> None:
        slot = get_emulator_research_slot(5)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("깊이감쇠", slot.title_ko)
        self.assertIn("Depth-Dependent", slot.title_en)
        self.assertIn("에뮬레이터05", slot.presentation_filename)

    def test_invalid_slot_number_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "0 to 10"):
            get_emulator_research_slot(-1)
        with self.assertRaisesRegex(ValueError, "0 to 10"):
            get_emulator_research_slot(11)

    def test_paths_are_separate_per_slot(self) -> None:
        path_1 = emulator_research_paths(1, root=Path("research"))
        path_2 = emulator_research_paths(2, root=Path("research"))

        self.assertNotEqual(path_1["slot_dir"], path_2["slot_dir"])
        self.assertNotEqual(path_1["presentation"], path_2["presentation"])
        self.assertEqual(path_1["presentation"].parent, Path("research") / "presentations")

    def test_next_emulator_number_uses_first_missing_slot(self) -> None:
        self.assertEqual(next_emulator_number([0, 1]), 2)
        self.assertEqual(next_emulator_number([0, 2]), 1)
        self.assertIsNone(next_emulator_number(range(0, 11)))

    def test_created_emulator_numbers_roundtrip_through_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_created_emulator_numbers(root=tmp), [0, 1, 2, 3, 4, 5])

            manifest = save_created_emulator_numbers([0, 1, 2, 3, 4, 5], root=tmp)

            self.assertTrue(manifest.is_file())
            self.assertEqual(load_created_emulator_numbers(root=tmp), [0, 1, 2, 3, 4, 5])

            save_created_emulator_numbers([2], root=tmp)
            self.assertEqual(load_created_emulator_numbers(root=tmp), [0, 1, 2, 3, 4, 5])

    def test_ensure_single_slot_creates_only_requested_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_slot(0, root=tmp)

            self.assertTrue(created["updates_dir"].is_dir())
            self.assertTrue(created["presentations_dir"].is_dir())
            self.assertFalse((Path(tmp) / "emulator_01_direct_angle_sputter_etch").exists())

    def test_ensure_tree_creates_slot_and_presentation_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp)

            self.assertEqual(set(created), set(range(0, 11)))
            self.assertTrue(created[0]["updates_dir"].is_dir())
            self.assertTrue(created[1]["updates_dir"].is_dir())
            self.assertTrue(created[10]["updates_dir"].is_dir())
            self.assertTrue(created[1]["presentations_dir"].is_dir())

    def test_ensure_tree_can_create_a_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp, numbers=DEFAULT_CREATED_EMULATOR_NUMBERS)

            self.assertEqual(set(created), {0, 1, 2, 3, 4, 5})
            self.assertTrue(created[0]["updates_dir"].is_dir())
            self.assertTrue(created[1]["updates_dir"].is_dir())
            self.assertTrue(created[2]["updates_dir"].is_dir())
            self.assertTrue(created[3]["updates_dir"].is_dir())
            self.assertTrue(created[4]["updates_dir"].is_dir())
            self.assertTrue(created[5]["updates_dir"].is_dir())
            self.assertFalse((Path(tmp) / "emulator_06_unassigned").exists())


if __name__ == "__main__":
    unittest.main()
