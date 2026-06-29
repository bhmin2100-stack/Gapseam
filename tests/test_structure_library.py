from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gapsim.emulation.structure_library import (
    DEFAULT_EMULATOR_STRUCTURE_SHEETS,
    StructureLibraryError,
    delete_structure_sheet,
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

            deleted_name = delete_structure_sheet(path, saved_name)
            self.assertEqual(deleted_name, saved_name)
            self.assertEqual(list_structure_names(path), [])

    def test_export_default_structures_preserves_existing_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"

            written = ensure_default_structures(path)
            second = ensure_default_structures(path)

            self.assertEqual(second, [])
            self.assertEqual(written, [DEFAULT_EMULATOR_STRUCTURE_SHEETS[0]])
            self.assertEqual(list_structure_names(path), [DEFAULT_EMULATOR_STRUCTURE_SHEETS[0]])
            self.assertGreaterEqual(len(read_structure_points(path, DEFAULT_EMULATOR_STRUCTURE_SHEETS[0])), 2)

    def test_sanitize_structure_name_for_excel_sheet_limits(self) -> None:
        self.assertEqual(sanitize_structure_name(" bad/name:*? "), "bad_name___")
        self.assertLessEqual(len(sanitize_structure_name("x" * 80)), 31)

    def test_corrupt_xlsx_reports_structure_library_error_for_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"
            path.write_text("not a zip workbook", encoding="utf-8")

            with self.assertRaisesRegex(StructureLibraryError, "not a valid .xlsx"):
                list_structure_names(path)
            with self.assertRaisesRegex(StructureLibraryError, "not a valid .xlsx"):
                read_structure_points(path, DEFAULT_EMULATOR_STRUCTURE_SHEETS[0])

    def test_save_structure_recovers_corrupt_workbook_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"
            path.write_text("not a zip workbook", encoding="utf-8")

            saved_name = save_structure_points(path, "Recovered", [(-1.0, 0.0), (1.0, -2.0)])

            self.assertEqual(saved_name, "Recovered")
            self.assertEqual(list_structure_names(path), ["Recovered"])
            self.assertEqual(read_structure_points(path, "Recovered"), [(-1.0, 0.0), (1.0, -2.0)])
            backups = list(Path(tmp).glob("structures.invalid_*.xlsx"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "not a zip workbook")

    def test_export_default_structures_recovers_corrupt_workbook_with_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "structures.xlsx"
            path.write_text("not a zip workbook", encoding="utf-8")

            written = ensure_default_structures(path)

            self.assertEqual(written, [DEFAULT_EMULATOR_STRUCTURE_SHEETS[0]])
            self.assertEqual(list_structure_names(path), [DEFAULT_EMULATOR_STRUCTURE_SHEETS[0]])
            self.assertEqual(len(list(Path(tmp).glob("structures.invalid_*.xlsx"))), 1)


if __name__ == "__main__":
    unittest.main()
