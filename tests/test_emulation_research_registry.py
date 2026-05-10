from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.research_registry import (
    DEFAULT_CREATED_EMULATOR_NUMBERS,
    EMULATOR_RESEARCH_SLOTS,
    MAX_EMULATOR_NUMBER,
    emulator_research_paths,
    ensure_emulator_research_slot,
    ensure_emulator_research_tree,
    get_emulator_research_slot,
    load_created_emulator_numbers,
    next_emulator_number,
    save_created_emulator_numbers,
)


EXPECTED_EMULATOR_NUMBERS = list(range(0, MAX_EMULATOR_NUMBER + 1))


class EmulationResearchRegistryTest(unittest.TestCase):
    def test_registry_has_rebuilt_emulator_slots(self) -> None:
        numbers = [slot.number for slot in EMULATOR_RESEARCH_SLOTS]

        self.assertEqual(numbers, EXPECTED_EMULATOR_NUMBERS)
        self.assertEqual(len({slot.directory_name for slot in EMULATOR_RESEARCH_SLOTS}), len(EXPECTED_EMULATOR_NUMBERS))
        self.assertEqual(DEFAULT_CREATED_EMULATOR_NUMBERS, tuple(EXPECTED_EMULATOR_NUMBERS))

    def test_slot_zero_is_integrated_model_without_redepo(self) -> None:
        slot = get_emulator_research_slot(0)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("통합", slot.title_ko)
        self.assertIn("Integrated", slot.title_en)
        self.assertIn("6번", slot.status_ko)
        self.assertIn("redepo", slot.status_ko)
        self.assertIn("에뮬레이터00", slot.presentation_filename)

    def test_slot_one_is_conformal_baseline(self) -> None:
        slot = get_emulator_research_slot(1)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("컨포멀", slot.title_ko)
        self.assertIn("Baseline", slot.title_en)
        self.assertIn("에뮬레이터01", slot.presentation_filename)
        self.assertTrue(slot.presentation_filename.endswith(".pptx"))

    def test_slot_two_is_angle_sputter_etch_emulator(self) -> None:
        slot = get_emulator_research_slot(2)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("각도기반", slot.title_ko)
        self.assertIn("Sputter", slot.title_en)
        self.assertIn("에뮬레이터02", slot.presentation_filename)

    def test_slot_three_is_ion_transmission_emulator(self) -> None:
        slot = get_emulator_research_slot(3)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("이온", slot.title_ko)
        self.assertIn("Transmission", slot.title_en)
        self.assertIn("에뮬레이터03", slot.presentation_filename)

    def test_slot_four_is_depth_deposition_emulator(self) -> None:
        slot = get_emulator_research_slot(4)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("깊이감쇠", slot.title_ko)
        self.assertIn("Depth-Dependent", slot.title_en)
        self.assertIn("에뮬레이터04", slot.presentation_filename)

    def test_slot_five_is_inhibition_deposition_emulator(self) -> None:
        slot = get_emulator_research_slot(5)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("인히비션", slot.title_ko)
        self.assertIn("Inhibition", slot.title_en)
        self.assertIn("에뮬레이터05", slot.presentation_filename)

    def test_slot_six_is_reflection_redeposition_emulator(self) -> None:
        slot = get_emulator_research_slot(6)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("반사", slot.title_ko)
        self.assertIn("Reflection", slot.title_en)
        self.assertIn("에뮬레이터06", slot.presentation_filename)

    def test_invalid_slot_number_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, f"0 to {MAX_EMULATOR_NUMBER}"):
            get_emulator_research_slot(-1)
        with self.assertRaisesRegex(ValueError, f"0 to {MAX_EMULATOR_NUMBER}"):
            get_emulator_research_slot(MAX_EMULATOR_NUMBER + 1)

    def test_paths_are_separate_per_slot(self) -> None:
        path_1 = emulator_research_paths(1, root=Path("research"))
        path_2 = emulator_research_paths(2, root=Path("research"))

        self.assertNotEqual(path_1["slot_dir"], path_2["slot_dir"])
        self.assertNotEqual(path_1["presentation"], path_2["presentation"])
        self.assertEqual(path_1["presentation"].parent, Path("research") / "presentations")

    def test_next_emulator_number_uses_first_missing_slot(self) -> None:
        self.assertEqual(next_emulator_number([0, 1]), 2)
        self.assertEqual(next_emulator_number([0, 2]), 1)
        self.assertIsNone(next_emulator_number(EXPECTED_EMULATOR_NUMBERS))

    def test_created_emulator_numbers_roundtrip_through_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_created_emulator_numbers(root=tmp), EXPECTED_EMULATOR_NUMBERS)

            manifest = save_created_emulator_numbers([0, 1, 2, 3], root=tmp)

            self.assertTrue(manifest.is_file())
            self.assertEqual(load_created_emulator_numbers(root=tmp), EXPECTED_EMULATOR_NUMBERS)

            save_created_emulator_numbers([2], root=tmp)
            self.assertEqual(load_created_emulator_numbers(root=tmp), EXPECTED_EMULATOR_NUMBERS)

    def test_ensure_single_slot_creates_only_requested_slot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_slot(0, root=tmp)

            self.assertTrue(created["updates_dir"].is_dir())
            self.assertTrue(created["presentations_dir"].is_dir())
            self.assertFalse((Path(tmp) / get_emulator_research_slot(1).directory_name).exists())

    def test_ensure_tree_creates_slot_and_presentation_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp)

            self.assertEqual(set(created), set(EXPECTED_EMULATOR_NUMBERS))
            self.assertTrue(created[0]["updates_dir"].is_dir())
            self.assertTrue(created[1]["updates_dir"].is_dir())
            self.assertTrue(created[MAX_EMULATOR_NUMBER]["updates_dir"].is_dir())
            self.assertTrue(created[1]["presentations_dir"].is_dir())

    def test_ensure_tree_can_create_a_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp, numbers=DEFAULT_CREATED_EMULATOR_NUMBERS)

            self.assertEqual(set(created), set(EXPECTED_EMULATOR_NUMBERS))
            for number in EXPECTED_EMULATOR_NUMBERS:
                self.assertTrue(created[number]["updates_dir"].is_dir())
            self.assertFalse((Path(tmp) / "emulator_06_unassigned").exists())


if __name__ == "__main__":
    unittest.main()
