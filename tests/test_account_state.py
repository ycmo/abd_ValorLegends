import json
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from src.account_state import (
    TAIPEI_TZ,
    clear_activity_state,
    read_activity_state,
    read_current_account,
    warn_if_midas_activity_active,
    write_activity_state,
    write_current_account,
)


class AccountStateTests(unittest.TestCase):
    def test_write_and_read_current_account(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "current_account.json"
            write_current_account(
                "311",
                source="test",
                path=path,
                now=datetime(2026, 7, 1, 12, 0, tzinfo=TAIPEI_TZ),
            )

            data = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(data["account"], "311")
            self.assertEqual(data["source"], "test")
            self.assertEqual(read_current_account(path=path), "311")

    def test_read_current_account_returns_default_for_missing_or_stale_state(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "current_account.json"

            self.assertEqual(read_current_account(path=path, default="default"), "default")

            write_current_account(
                "em3",
                source="test",
                path=path,
                now=datetime(2026, 7, 1, 12, 0, tzinfo=TAIPEI_TZ),
            )

            self.assertEqual(
                read_current_account(
                    path=path,
                    default="default",
                    max_age_seconds=60,
                    now=datetime(2026, 7, 1, 12, 2, tzinfo=TAIPEI_TZ),
                ),
                "default",
            )
            self.assertEqual(
                read_current_account(
                    path=path,
                    default="default",
                    max_age_seconds=60,
                    now=datetime(2026, 7, 1, 12, 0, 30, tzinfo=TAIPEI_TZ),
                ),
                "em3",
            )

    def test_write_clear_and_read_activity_state(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.json"
            write_activity_state(
                "midas_auto",
                active=True,
                source="test.active",
                path=path,
                now=datetime(2026, 7, 3, 12, 0, tzinfo=TAIPEI_TZ),
                extra={"wake_at": "2026-07-03T20:00:00+08:00"},
            )

            active = read_activity_state(path=path)

            self.assertEqual(active["activity"], "midas_auto")
            self.assertTrue(active["active"])
            self.assertEqual(active["source"], "test.active")
            self.assertEqual(active["wake_at"], "2026-07-03T20:00:00+08:00")

            clear_activity_state(
                "midas_auto",
                source="test.sleep",
                path=path,
                now=datetime(2026, 7, 3, 12, 5, tzinfo=TAIPEI_TZ),
            )

            inactive = read_activity_state(path=path)
            self.assertEqual(inactive["activity"], "midas_auto")
            self.assertFalse(inactive["active"])
            self.assertEqual(inactive["source"], "test.sleep")

    def test_read_activity_state_returns_inactive_for_missing_or_stale_state(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.json"

            self.assertFalse(read_activity_state(path=path)["active"])

            write_activity_state(
                "midas_auto",
                active=True,
                source="test",
                path=path,
                now=datetime(2026, 7, 3, 12, 0, tzinfo=TAIPEI_TZ),
            )

            self.assertFalse(
                read_activity_state(
                    path=path,
                    max_age_seconds=60,
                    now=datetime(2026, 7, 3, 12, 2, tzinfo=TAIPEI_TZ),
                )["active"]
            )
            self.assertTrue(
                read_activity_state(
                    path=path,
                    max_age_seconds=60,
                    now=datetime(2026, 7, 3, 12, 0, 30, tzinfo=TAIPEI_TZ),
                )["active"]
            )

    def test_warn_if_midas_activity_active_prints_warning_without_blocking(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.json"
            write_activity_state(
                "midas_auto",
                active=True,
                source="test.active",
                path=path,
                now=datetime(2026, 7, 3, 12, 0, tzinfo=TAIPEI_TZ),
            )

            err = StringIO()
            with redirect_stderr(err):
                warned = warn_if_midas_activity_active(process_name="test-process", path=path)

        self.assertTrue(warned)
        warning = err.getvalue()
        self.assertIn("點金手掛機狀態仍是活動中", warning)
        self.assertIn("test-process", warning)
        self.assertIn("active 改成 false", warning)

    def test_warn_if_midas_activity_active_ignores_inactive_state(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "activity.json"
            write_activity_state(
                "midas_auto",
                active=False,
                source="test.sleep",
                path=path,
                now=datetime(2026, 7, 3, 12, 0, tzinfo=TAIPEI_TZ),
            )

            err = StringIO()
            with redirect_stderr(err):
                warned = warn_if_midas_activity_active(process_name="test-process", path=path)

        self.assertFalse(warned)
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
