import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from AwayFromKeyboard.ui_recovery import UIRecovery
from src.ui.blockers import BLOCKER_POLICY_SAFE


class UIRecoveryTests(unittest.TestCase):
    @patch("AwayFromKeyboard.ui_recovery.BlockerHandler")
    def test_wakeup_exception_check_clears_safe_blocker_before_login_detection(self, mock_blocker_class):
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        controller = MagicMock()
        controller.screenshot.return_value = screen
        matcher = MagicMock()
        detector = MagicMock()
        blocker = mock_blocker_class.return_value
        blocker.handle_known_blocker.return_value = True

        recovery = UIRecovery(controller, matcher, detector)
        handled = recovery.handle_wakeup_exceptions()

        self.assertTrue(handled)
        blocker.handle_known_blocker.assert_called_once_with(screen, policy=BLOCKER_POLICY_SAFE)
        matcher.match_template.assert_not_called()


if __name__ == "__main__":
    unittest.main()
