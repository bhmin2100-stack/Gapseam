from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.structure_library import (
    DEFAULT_EMULATOR_STRUCTURE_SHEETS,
    ensure_default_structures,
    list_structure_names,
    read_structure_points,
    sanitize_structure_name,
    save_structure_points,
)


class StructureLibraryTest(unittest.TestCase):
    def test_save_list_and_read_structure_sheet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"

            saved_name = save_structure_points(path, "My: Structure/01", [(-10.0, 0.0), (0.0, -5.0)])

            self.assertEqual(saved_name, "My_ Structure_01")
            self.assertEqual(list_structure_names(path), [saved_name])
            self.assertEqual(read_structure_points(path, saved_name), [(-10.0, 0.0), (0.0, -5.0)])

    def test_export_default_structures_preserves_existing_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"

            written = ensure_default_structures(path)
            second = ensure_default_structures(path)

            self.assertEqual(second, [])
            self.assertIn(DEFAULT_EMULATOR_STRUCTURE_SHEETS[2], written)
            self.assertIn(DEFAULT_EMULATOR_STRUCTURE_SHEETS[5], list_structure_names(path))
            self.assertGreaterEqual(len(read_structure_points(path, DEFAULT_EMULATOR_STRUCTURE_SHEETS[5])), 2)

    def test_sanitize_structure_name_for_excel_sheet_limits(self) -> None:
        self.assertEqual(sanitize_structure_name(" bad/name:*? "), "bad_name___")
        self.assertLessEqual(len(sanitize_structure_name("x" * 80)), 31)


if __name__ == "__main__":
    unittest.main()
