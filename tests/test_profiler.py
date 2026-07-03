from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from src.profiler import configure_profile_log, profile_enabled, profile_load


class ProfilerTests(TestCase):
    def setUp(self):
        configure_profile_log(None)

    def tearDown(self):
        configure_profile_log(None)

    def test_profile_log_file_env_enables_file_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "route.profile.txt"
            with patch.dict(os.environ, {"VL_PROFILE_LOG_FILE": str(path)}, clear=False):
                self.assertTrue(profile_enabled())
                profile_load("easyocr cache miss languages=en")

            text = path.read_text(encoding="utf-8")

        self.assertIn("easyocr cache miss languages=en", text)
        self.assertIn("[perf pid=", text)

    def test_configure_profile_log_enables_file_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profile_loads.log"
            configure_profile_log(path)
            self.assertTrue(profile_enabled())
            profile_load("template loaded path=x.png elapsed=0.0010s")

            text = path.read_text(encoding="utf-8")

        self.assertIn("template loaded path=x.png", text)
