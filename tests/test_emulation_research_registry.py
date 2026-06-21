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


EXPECTED_EMULATOR_NUMBERS = list(DEFAULT_CREATED_EMULATOR_NUMBERS)


class EmulationResearchRegistryTest(unittest.TestCase):
    def test_registry_has_rebuilt_emulator_slots(self) -> None:
        numbers = [slot.number for slot in EMULATOR_RESEARCH_SLOTS]

        self.assertEqual(numbers, EXPECTED_EMULATOR_NUMBERS)
        self.assertEqual(len({slot.directory_name for slot in EMULATOR_RESEARCH_SLOTS}), len(EXPECTED_EMULATOR_NUMBERS))
        self.assertEqual(DEFAULT_CREATED_EMULATOR_NUMBERS, tuple(EXPECTED_EMULATOR_NUMBERS))

    def test_slot_zero_is_unified_default_model(self) -> None:
        slot = get_emulator_research_slot(0)

        self.assertEqual(slot.module, "gapsim.emulation.trench_depo")
        self.assertIn("기본_통합_모델", slot.title_ko)
        self.assertIn("Unified", slot.title_en)
        self.assertIn("기본 통합 모델", slot.status_ko)
        self.assertIn("에뮬레이터00", slot.presentation_filename)

    def test_invalid_slot_number_fails_clearly(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be 0"):
            get_emulator_research_slot(-1)
        with self.assertRaisesRegex(ValueError, "must be 0"):
            get_emulator_research_slot(MAX_EMULATOR_NUMBER + 1)

    def test_paths_are_rooted_for_single_slot(self) -> None:
        path_0 = emulator_research_paths(0, root=Path("research"))

        self.assertEqual(path_0["slot_dir"], Path("research") / get_emulator_research_slot(0).directory_name)
        self.assertEqual(path_0["presentation"].parent, Path("research") / "presentations")

    def test_next_emulator_number_uses_first_missing_slot(self) -> None:
        self.assertEqual(next_emulator_number([]), 0)
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
            self.assertFalse((Path(tmp) / "emulator_01_conformal").exists())

    def test_ensure_tree_creates_slot_and_presentation_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp)

            self.assertEqual(set(created), set(EXPECTED_EMULATOR_NUMBERS))
            self.assertTrue(created[0]["updates_dir"].is_dir())
            self.assertTrue(created[MAX_EMULATOR_NUMBER]["updates_dir"].is_dir())
            self.assertTrue(created[0]["presentations_dir"].is_dir())

    def test_ensure_tree_can_create_a_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            created = ensure_emulator_research_tree(root=tmp, numbers=DEFAULT_CREATED_EMULATOR_NUMBERS)

            self.assertEqual(set(created), set(EXPECTED_EMULATOR_NUMBERS))
            for number in EXPECTED_EMULATOR_NUMBERS:
                self.assertTrue(created[number]["updates_dir"].is_dir())
            self.assertFalse((Path(tmp) / "emulator_06_unassigned").exists())


if __name__ == "__main__":
    unittest.main()
