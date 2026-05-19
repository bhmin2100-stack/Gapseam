from __future__ import annotations

import unittest
from unittest.mock import patch

from gapsim.engine.run_logger import _runtime_info, make_meta


class RunLoggerTest(unittest.TestCase):
    def tearDown(self) -> None:
        _runtime_info.cache_clear()

    def test_make_meta_returns_expected_keys(self) -> None:
        meta = make_meta(
            {"units": {"length": "A", "y_down_is_negative": True}},
            engine_version="1.2.3",
        )

        self.assertEqual(meta["app_name"], "GFE")
        self.assertEqual(meta["engine_version"], "1.2.3")
        self.assertIn("created_at_local", meta)
        self.assertIsInstance(meta["python"], str)
        self.assertTrue(meta["python"])
        self.assertIsInstance(meta["platform"], str)
        self.assertTrue(meta["platform"])
        self.assertEqual(meta["units"]["length"], "A")

    def test_make_meta_uses_default_units_when_missing(self) -> None:
        meta = make_meta({}, engine_version="0.0.0")
        self.assertEqual(meta["units"], {"length": "Å", "y_down_is_negative": True})

    def test_runtime_info_falls_back_when_platform_fields_are_blank(self) -> None:
        with (
            patch("gapsim.engine.run_logger.platform.system", return_value=""),
            patch("gapsim.engine.run_logger.platform.release", return_value=""),
            patch("gapsim.engine.run_logger.platform.machine", return_value=""),
            patch("gapsim.engine.run_logger.platform.python_version", return_value=""),
        ):
            _runtime_info.cache_clear()
            meta = make_meta({}, engine_version="0.0.0")

        self.assertEqual(meta["python"], "unknown")
        self.assertEqual(meta["platform"], "unknown")


if __name__ == "__main__":
    unittest.main()
