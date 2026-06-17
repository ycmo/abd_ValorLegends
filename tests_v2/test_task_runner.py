"""
test_task_runner.py — src_v2 Phase 1 完整 unittest

覆蓋：
  - DebugCapture: save_failure / save_action / cleanup / create
  - BaseTask._wait_for: 成功路徑、超時路徑（驗證 save_failure 被呼叫）
  - BaseTask._require: 成功 / 超時 raise TaskFailedError
  - BaseTask._tap: 成功路徑驗證 controller.tap 被呼叫
  - BaseTask._missing_assets: 正確識別缺失 asset
  - BaseTask._is_task_scene: anchor 匹配 / 不匹配
  - BaseTask._return_to_daily: 三條路徑
  - BaseTask._dismiss_overlay_by_blank_taps
  - GuildWishTask: execute / execute_from_current_scene 業務邏輯
  - DailyRunner: run_task / run_current_task / run_current_scene_task / run_all skip logic
  - TaskState / TaskRunResult dataclass

所有 ADB / 實機依賴全部用 unittest.mock 隔離。
"""
from __future__ import annotations

import shutil
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import TRANSITION_WAIT_SECONDS
from src.exceptions import TaskFailedError
from src.scene_detector import Scene
from src_v2.debug_capture import DebugCapture, _safe_label
from src_v2.task_runner import (
    BaseTask,
    TaskContext,
    TaskRunResult,
    TaskSceneAnchor,
    TaskState,
)
from src_v2.tasks.guild_wish import GuildWishTask
from src_v2.tasks.secret_realm import SecretRealmTask
from src_v2.tasks.summon import SummonTask
from src_v2.tasks.time_travel import TimeTravelTask
from src_v2.tasks.midas import MidasTask
from src_v2.tasks.endless_trial import EndlessTrialTask, EndlessTrialScene
from src_v2.tasks.arena import ArenaTask
from src_v2.daily_runner import DailyRunner


# ---------------------------------------------------------------------------
# 輔助
# ---------------------------------------------------------------------------

def _make_context(tmp_path: Path) -> TaskContext:
    """建立完全 mock 的 TaskContext，debug_capture 使用真實 tmp 目錄。"""
    controller = MagicMock()
    matcher = MagicMock()
    detector = MagicMock()
    finder = MagicMock()
    navigator = MagicMock()
    battle = MagicMock()
    logger = MagicMock()
    session_dir = tmp_path / "session"
    session_dir.mkdir(parents=True, exist_ok=True)
    debug_capture = DebugCapture(session_dir=session_dir, enabled=True)

    return TaskContext(
        controller=controller,
        matcher=matcher,
        detector=detector,
        finder=finder,
        navigator=navigator,
        battle=battle,
        logger=logger,
        debug_capture=debug_capture,
    )


def _make_match(confidence: float = 0.90, center=(100, 200)):
    m = MagicMock()
    m.confidence = confidence
    m.center = center
    return m


# ---------------------------------------------------------------------------
# DebugCapture
# ---------------------------------------------------------------------------

class TestDebugCapture(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_safe_label(self):
        self.assertEqual(_safe_label("free wish button"), "free_wish_button")
        self.assertEqual(_safe_label("  Close/Dialog  "), "close_dialog")

    def test_save_failure_creates_file(self):
        import numpy as np
        dc = DebugCapture(session_dir=self.tmp / "s1", enabled=True)
        (self.tmp / "s1").mkdir(parents=True)
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        path = dc.save_failure(
            screen=screen,
            task_key="guild_wish",
            step_label="free_wish_button",
            roi=(165, 360, 220, 95),
            best_confidence=0.61,
            threshold=0.86,
        )
        self.assertTrue(path.exists(), f"file not found: {path}")
        self.assertIn("roi_165_360_220_95", path.name)
        self.assertIn("conf_0.61", path.name)
        self.assertIn("thr_0.86", path.name)

    def test_save_failure_disabled_returns_empty(self):
        dc = DebugCapture(session_dir=self.tmp / "s1", enabled=False)
        result = dc.save_failure(
            screen=MagicMock(),
            task_key="guild_wish",
            step_label="x",
            roi=None,
            best_confidence=None,
            threshold=0.82,
        )
        self.assertIsNone(result)

    def test_save_action_creates_before_after(self):
        import numpy as np
        dc = DebugCapture(session_dir=self.tmp / "s1", enabled=True)
        (self.tmp / "s1").mkdir(parents=True)
        screen = np.zeros((540, 960, 3), dtype=np.uint8)
        dc.save_action(screen, "guild_wish", "free_wish_button", "before")
        dc.save_action(screen, "guild_wish", "free_wish_button", "after")
        step_dirs = list((self.tmp / "s1" / "guild_wish").glob("step_01_*"))
        self.assertEqual(len(step_dirs), 1)
        step_dir = step_dirs[0]
        self.assertTrue((step_dir / "before.png").exists())
        self.assertTrue((step_dir / "after.png").exists())

    def test_cleanup_keeps_latest_sessions(self):
        sessions_dir = self.tmp / "sessions"
        sessions_dir.mkdir()
        for i in range(7):
            d = sessions_dir / f"session_{i:02d}"
            d.mkdir()
            time.sleep(0.01)
        deleted = DebugCapture.cleanup(self.tmp, keep_sessions=3)
        remaining = [d for d in sessions_dir.iterdir() if d.is_dir() and d.name != "latest"]
        self.assertEqual(deleted, 4)
        self.assertEqual(len(remaining), 3)

    def test_cleanup_noop_when_sessions_dir_missing(self):
        deleted = DebugCapture.cleanup(self.tmp / "nonexistent", keep_sessions=5)
        self.assertEqual(deleted, 0)


# ---------------------------------------------------------------------------
# BaseTask._wait_for / _require / _tap
# ---------------------------------------------------------------------------

class TestBaseTaskAPI(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _task(self):
        return GuildWishTask(self.ctx)

    def test_wait_for_returns_match_immediately(self):
        task = self._task()
        mock_match = _make_match(0.92)
        self.ctx.matcher.match_template.return_value = mock_match
        with patch.object(task, '_asset_path', return_value=MagicMock(spec=Path)):
            result = task._wait_for("guild_wish_title.png", roi=(0, 0, 100, 100))
        self.assertIs(result, mock_match)

    def test_wait_for_returns_none_on_timeout_and_saves_failure(self):
        import numpy as np
        task = self._task()
        fake_screen = np.zeros((540, 960, 3), dtype=np.uint8)
        self.ctx.controller.screenshot.return_value = fake_screen
        self.ctx.matcher.match_template.return_value = None
        self.ctx.matcher.best_template_match.return_value = None

        with patch.object(task, '_asset_path', return_value=MagicMock(spec=Path)):
            with patch.object(task.context.debug_capture, 'save_failure') as mock_save:
                result = task._wait_for(
                    "guild_wish_title.png",
                    roi=(0, 0, 100, 100),
                    threshold=0.84,
                    timeout_seconds=0.15,
                    poll_interval=0.05,
                )
        self.assertIsNone(result)
        mock_save.assert_called_once()

    def test_require_raises_task_failed_error_on_timeout(self):
        import numpy as np
        task = self._task()
        fake_screen = np.zeros((540, 960, 3), dtype=np.uint8)
        self.ctx.controller.screenshot.return_value = fake_screen
        self.ctx.matcher.match_template.return_value = None
        self.ctx.matcher.best_template_match.return_value = None

        with patch.object(task, '_asset_path', return_value=MagicMock(spec=Path)):
            with patch.object(task.context.debug_capture, 'save_failure'):
                with self.assertRaises(TaskFailedError) as cm:
                    task._require(
                        "Guild Wish dialog title",
                        "guild_wish_title.png",
                        roi=(390, 45, 190, 80),
                        timeout_seconds=0.1,
                    )
        self.assertIn("Guild Wish dialog title", str(cm.exception))

    def test_tap_calls_controller_tap(self):
        task = self._task()
        mock_match = _make_match(center=(300, 400))
        with patch.object(task, '_require', return_value=mock_match):
            with patch('time.sleep'):
                task._tap("label", "some_button.png", wait_after=0.1)
        self.ctx.controller.tap.assert_called_once_with(300, 400)


# ---------------------------------------------------------------------------
# BaseTask._missing_assets
# ---------------------------------------------------------------------------

class TestMissingAssets(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_returns_nonexistent_paths(self):
        task = GuildWishTask(self.ctx)
        fake_nonexistent = Path("/nonexistent_dir/fake_asset.png")
        with patch.object(task, '_asset_path', return_value=fake_nonexistent):
            missing = task._missing_assets()
        self.assertGreater(len(missing), 0)
        for p in missing:
            self.assertIsInstance(p, Path)


# ---------------------------------------------------------------------------
# BaseTask._is_task_scene
# ---------------------------------------------------------------------------

class TestIsTaskScene(unittest.TestCase):

    def setUp(self):
        import tempfile
        import numpy as np
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)
        self.fake_screen = np.zeros((540, 960, 3), dtype=np.uint8)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_true_when_anchor_matches(self):
        task = GuildWishTask(self.ctx)
        mock_match = _make_match()
        existing_path = MagicMock()
        existing_path.exists.return_value = True
        with patch.object(task, '_asset_path', return_value=existing_path):
            self.ctx.matcher.match_template.return_value = mock_match
            result = task._is_task_scene(self.fake_screen)
        self.assertTrue(result)

    def test_false_when_no_anchor_matches(self):
        task = GuildWishTask(self.ctx)
        existing_path = MagicMock()
        existing_path.exists.return_value = True
        with patch.object(task, '_asset_path', return_value=existing_path):
            self.ctx.matcher.match_template.return_value = None
            result = task._is_task_scene(self.fake_screen)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# BaseTask._return_to_daily
# ---------------------------------------------------------------------------

class TestReturnToDaily(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_noop_when_already_at_daily(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_daily_tasks_visible', return_value=True):
            task._return_to_daily()
        self.ctx.navigator.return_to_daily_tasks.assert_not_called()

    def test_hook_not_called_when_already_at_daily(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_daily_tasks_visible', return_value=True), \
             patch.object(task, '_pre_return_hook') as mock_hook:
            task._return_to_daily()
        mock_hook.assert_not_called()

    def test_uses_navigator_when_not_at_daily(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_daily_tasks_visible', return_value=False):
            self.ctx.navigator.return_to_daily_tasks.return_value = True
            task._return_to_daily()
        self.ctx.navigator.return_to_daily_tasks.assert_called_once()

    def test_raises_when_navigator_fails(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_daily_tasks_visible', return_value=False):
            self.ctx.navigator.return_to_daily_tasks.return_value = False
            with self.assertRaises(TaskFailedError):
                task._return_to_daily()


# ---------------------------------------------------------------------------
# BaseTask._dismiss_overlay_by_blank_taps
# ---------------------------------------------------------------------------

class TestDismissOverlay(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_noop_when_already_closed(self):
        task = GuildWishTask(self.ctx)
        with patch('time.sleep'):
            task._dismiss_overlay_by_blank_taps(is_closed=lambda: True)
        self.ctx.controller.tap.assert_not_called()

    def test_taps_until_closed(self):
        task = GuildWishTask(self.ctx)
        call_count = [0]

        def is_closed():
            call_count[0] += 1
            return call_count[0] >= 2

        with patch('time.sleep'):
            task._dismiss_overlay_by_blank_taps(is_closed=is_closed, max_taps=3)
        self.assertEqual(self.ctx.controller.tap.call_count, 1)

    def test_raises_after_max_taps(self):
        task = GuildWishTask(self.ctx)
        with patch('time.sleep'):
            with self.assertRaises(TaskFailedError):
                task._dismiss_overlay_by_blank_taps(
                    is_closed=lambda: False,
                    max_taps=2,
                    failure_message="test fail",
                )


# ---------------------------------------------------------------------------
# GuildWishTask 業務邏輯
# ---------------------------------------------------------------------------

class TestGuildWishExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_happy_path(self):
        task = GuildWishTask(self.ctx)
        mock_match = _make_match(center=(200, 400))

        with patch.object(task, '_require', return_value=mock_match), \
             patch.object(task, '_tap', return_value=mock_match), \
             patch.object(task, '_dismiss_reward_overlay_if_present'), \
             patch.object(task, '_close_dialog'):
            result = task.execute()

        self.assertEqual(result, "free guild wish completed")

    def test_execute_from_current_scene_ready(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_guild_wish_dialog_ready', return_value=True), \
             patch.object(task, 'execute', return_value="free guild wish completed"):
            result = task.execute_from_current_scene()
        self.assertEqual(result, "free guild wish completed")

    def test_execute_from_current_scene_after_reward(self):
        task = GuildWishTask(self.ctx)
        with patch.object(task, '_is_guild_wish_dialog_ready', return_value=False), \
             patch.object(task, '_dismiss_reward_overlay_if_present'), \
             patch.object(task, '_close_dialog'):
            result = task.execute_from_current_scene()
        self.assertIn("reward overlay", result)


# ---------------------------------------------------------------------------
# SecretRealmTask 業務邏輯
# ---------------------------------------------------------------------------

class TestSecretRealmExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_happy_path(self):
        task = SecretRealmTask(self.ctx)
        mock_match = _make_match(center=(200, 400))

        with patch.object(task, '_wait_for', return_value=mock_match), \
             patch.object(task, '_require', return_value=mock_match), \
             patch.object(task, '_tap', return_value=mock_match), \
             patch.object(task, '_dismiss_possible_reward_overlay'):
            result = task.execute()

        self.assertEqual(result, "bought Lost Forest twice and tapped sweep all")

    def test_wait_for_realm_screen_raises_on_timeout(self):
        task = SecretRealmTask(self.ctx)
        with patch.object(task, '_wait_for', return_value=None):
            with self.assertRaises(TaskFailedError) as cm:
                task._wait_for_realm_screen("test label")
        self.assertIn("Lost Forest screen not visible", str(cm.exception))


# ---------------------------------------------------------------------------
# SummonTask 業務邏輯
# ---------------------------------------------------------------------------

class TestSummonExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_happy_path(self):
        task = SummonTask(self.ctx)
        with patch.object(task, '_require_summon_page'), \
             patch.object(task, '_tap') as mock_tap, \
             patch.object(task, '_dismiss_post_confirm_reward_if_present'):
            result = task.execute()
        self.assertIn("summon", result)
        self.assertEqual(mock_tap.call_count, 2)

    def test_execute_from_current_scene_fast_path(self):
        task = SummonTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        with patch.object(task, '_wait_for', return_value=mock_match), \
             patch.object(task, '_tap') as mock_tap, \
             patch.object(task, '_dismiss_post_confirm_reward_if_present'), \
             patch.object(task, '_require_summon_page') as mock_require:
            result = task.execute_from_current_scene()
        mock_require.assert_not_called()
        mock_tap.assert_called_once()
        self.assertIn("confirmed", result)

    def test_is_summon_page_visible_false_when_both_timeout(self):
        task = SummonTask(self.ctx)
        with patch.object(task, '_wait_for', return_value=None):
            self.assertFalse(task._is_summon_page_visible(1.0))

    def test_pre_return_hook_taps_leave_when_on_page(self):
        task = SummonTask(self.ctx)
        with patch.object(task, '_is_summon_page_visible', return_value=True), \
             patch.object(task, '_tap') as mock_tap:
            task._pre_return_hook()
        mock_tap.assert_called_once()


# ---------------------------------------------------------------------------
# TimeTravelTask 業務邏輯
# ---------------------------------------------------------------------------

class TestTimeTravelExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_with_free_button(self):
        task = TimeTravelTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        
        def wait_for_side_effect(asset_name, **kwargs):
            if asset_name == "free_button.png":
                return mock_match
            if asset_name == "time_travel_title.png":
                return mock_match
            return None

        with patch.object(task, '_require'), \
             patch.object(task, '_wait_for', side_effect=wait_for_side_effect), \
             patch.object(task, '_tap') as mock_tap, \
             patch.object(task, '_dismiss_reward_overlay_if_present') as mock_dismiss, \
             patch.object(task, '_tap_all_gem_50', return_value=0), \
             patch.object(task, '_close_dialog_if_visible'):
            result = task.execute()
            
        mock_tap.assert_called_with(
            "free", 
            "free_button.png", 
            roi=task.ACTION_BUTTON_ROI, 
            threshold=0.88, 
            wait_after=TRANSITION_WAIT_SECONDS
        )
        self.assertEqual(mock_dismiss.call_count, 2)
        self.assertIn("free", result)

    def test_execute_no_free_button(self):
        task = TimeTravelTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        
        def wait_for_side_effect(asset_name, **kwargs):
            if asset_name == "free_button.png":
                return None
            if asset_name == "time_travel_title.png":
                return mock_match
            return None

        with patch.object(task, '_require'), \
             patch.object(task, '_wait_for', side_effect=wait_for_side_effect), \
             patch.object(task, '_tap'), \
             patch.object(task, '_dismiss_reward_overlay_if_present'), \
             patch.object(task, '_tap_all_gem_50', return_value=1) as mock_tap_all, \
             patch.object(task, '_close_dialog_if_visible'):
            result = task.execute()
            
        mock_tap_all.assert_called_once()
        self.assertNotIn("free", result)
        self.assertIn("1x 50-gem", result)

    def test_tap_all_gem_50_respects_max_taps(self):
        task = TimeTravelTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        
        with patch.object(task, '_wait_for', return_value=mock_match), \
             patch.object(task, '_detect_action_cost', return_value=50), \
             patch.object(task, '_tap') as mock_tap, \
             patch.object(task, '_dismiss_reward_overlay_if_present'):
            with self.assertRaises(TaskFailedError) as cm:
                task._tap_all_gem_50()
        
        self.assertIn("exceeded", str(cm.exception))
        self.assertEqual(mock_tap.call_count, task.MAX_50_GEM_TAPS)

    def test_close_dialog_raises_if_still_visible(self):
        task = TimeTravelTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        with patch.object(task, '_wait_for', return_value=mock_match), \
             patch.object(task, '_tap'):
            with self.assertRaises(TaskFailedError) as cm:
                task._close_dialog_if_visible()
        self.assertIn("did not close", str(cm.exception))


# ---------------------------------------------------------------------------
# MidasTask 業務邏輯
# ---------------------------------------------------------------------------

class TestMidasExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_wait_for_midas_returns_match_immediately(self):
        task = MidasTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        with patch.object(task, '_is_busy_overlay', return_value=False), \
             patch.object(task.context.matcher, 'match_template', return_value=mock_match):
            result = task._wait_for_midas("test.png")
            self.assertEqual(result, mock_match)

    def test_wait_for_midas_extends_deadline_on_busy(self):
        task = MidasTask(self.ctx)
        mock_match = _make_match(center=(200, 400))
        
        # mock _is_busy_overlay to return True twice, then False
        busy_calls = [True, True, False, False]
        def mock_is_busy(*args, **kwargs):
            return busy_calls.pop(0) if busy_calls else False
            
        # mock match_template to return None until busy is cleared
        match_calls = [None, mock_match]
        def mock_match_t(*args, **kwargs):
            return match_calls.pop(0) if match_calls else mock_match

        with patch.object(task, '_is_busy_overlay', side_effect=mock_is_busy), \
             patch.object(task.context.matcher, 'match_template', side_effect=mock_match_t), \
             patch('time.sleep'):
            result = task._wait_for_midas("test.png")
            self.assertEqual(result, mock_match)

    def test_execute_happy_path(self):
        task = MidasTask(self.ctx)
        with patch.object(task, '_require_midas_dialog'), \
             patch.object(task, '_tap_if_active', side_effect=[True, False, False, False]), \
             patch.object(task, '_dismiss_reward_overlay_if_present'), \
             patch.object(task, '_tap_close_until_gone'):
            result = task.execute()
        self.assertEqual(result, "midas taps completed")

    def test_tap_if_active_returns_false_when_not_found(self):
        task = MidasTask(self.ctx)
        with patch.object(task, '_wait_for_midas', return_value=None), \
             patch.object(task.context.controller, 'tap') as mock_tap:
            result = task._tap_if_active("test.png", (0,0,0,0))
            self.assertFalse(result)
            mock_tap.assert_not_called()

    def test_tap_close_until_gone_returns_when_button_gone(self):
        task = MidasTask(self.ctx)
        with patch.object(task, '_wait_for_midas', return_value=None), \
             patch.object(task.context.controller, 'tap') as mock_tap:
            task._tap_close_until_gone()
            mock_tap.assert_not_called()


# ---------------------------------------------------------------------------
# EndlessTrialTask 業務邏輯
# ---------------------------------------------------------------------------

class TestEndlessTrialExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detect_route_scene_returns_best_match(self):
        task = EndlessTrialTask(self.ctx)
        match_low = _make_match(center=(100, 100), confidence=0.85)
        match_high = _make_match(center=(200, 200), confidence=0.95)
        
        def mock_match(screen, path, threshold=None, **kwargs):
            name = path.name
            if name == "trial_lobby_anchor.png":
                return match_low
            elif name == "stage_popup_anchor.png":
                return match_high
            return None
            
        with patch.object(task.context.matcher, 'match_template', side_effect=mock_match):
            import numpy as np
            result = task.detect_route_scene(np.zeros((10, 10)))
        
        self.assertIsNotNone(result)
        scene, match = result
        self.assertEqual(scene, EndlessTrialScene.STAGE_DETAILS)
        self.assertEqual(match.confidence, 0.95)

    def test_detect_route_scene_returns_none_when_all_fail(self):
        task = EndlessTrialTask(self.ctx)
        with patch.object(task.context.matcher, 'match_template', return_value=None):
            import numpy as np
            result = task.detect_route_scene(np.zeros((10, 10)))
        self.assertIsNone(result)

    def test_execute_exits_on_trial_lobby_post_battle_finished(self):
        task = EndlessTrialTask(self.ctx)
        mock_match = _make_match(center=(100, 100), confidence=0.99)
        
        scenes = [
            (EndlessTrialScene.TRIAL_LOBBY, mock_match),
            (EndlessTrialScene.BATTLE_END, mock_match),
            (EndlessTrialScene.TRIAL_LOBBY_POST, mock_match)
        ]
        
        def mock_detect(*args, **kwargs):
            return scenes.pop(0) if scenes else None
            
        with patch.object(task, 'detect_route_scene', side_effect=mock_detect), \
             patch.object(task.context.controller, 'tap'), \
             patch('time.sleep'):
            result = task.execute()
            
        self.assertIn("completed", result)


# ---------------------------------------------------------------------------
# ArenaTask 業務邏輯
# ---------------------------------------------------------------------------

class TestArenaExecute(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_completes_target_fights(self):
        import numpy as np
        task = ArenaTask(self.ctx)
        opponents = [{"row": r, "col": c, "power_k": 1000, "confidence": 0.9} for r in range(1, 5) for c in range(1, 3)]
        
        with patch.object(task, '_require'), \
             patch.object(task, '_wait_for') as mock_wait_for, \
             patch.object(task, '_tap'), \
             patch('time.sleep'), \
             patch('src_v2.tasks.arena.extract_arena_powers_easyocr', return_value=opponents), \
             patch.object(task, '_checkbox_state', return_value="checked"), \
             patch.object(task.context.controller, 'screenshot', return_value=np.zeros((10, 10, 3), dtype=np.uint8)), \
             patch.object(task.context.matcher, 'match_template', return_value=_make_match()):
            
            mock_wait_for.side_effect = lambda *args, **kwargs: _make_match()
            result = task.execute()
            self.assertIn("Arena fights: 8", result)

    def test_execute_raises_when_no_safe_opponents(self):
        import numpy as np
        task = ArenaTask(self.ctx)
        opponents = [{"row": r, "col": c, "power_k": 9000, "confidence": 0.9} for r in range(1, 5) for c in range(1, 3)]
        
        with patch.object(task, '_require'), \
             patch.object(task, '_wait_for') as mock_wait_for, \
             patch.object(task, '_tap'), \
             patch('time.sleep'), \
             patch('src_v2.tasks.arena.extract_arena_powers_easyocr', return_value=opponents), \
             patch.object(task, '_checkbox_state', return_value="unchecked"), \
             patch.object(task.context.controller, 'screenshot', return_value=np.zeros((10, 10, 3), dtype=np.uint8)), \
             patch.object(task.context.matcher, 'match_template', return_value=_make_match()):
            
            mock_wait_for.side_effect = lambda *args, **kwargs: _make_match()
            with self.assertRaisesRegex(TaskFailedError, "No safe opponents or OCR failed"):
                task.execute()

    def test_pre_return_hook_closes_list_and_returns(self):
        task = ArenaTask(self.ctx)
        with patch.object(task, '_wait_for', return_value=_make_match()), \
             patch.object(task.context.controller, 'tap') as mock_tap, \
             patch.object(task, '_tap') as mock_task_tap, \
             patch('time.sleep'):
            
            task._pre_return_hook()
            mock_tap.assert_called_with(846, 70)
            from src.config import TRANSITION_WAIT_SECONDS
            mock_task_tap.assert_called_with("arena back", "arena_back_button.png", roi=task.BACK_BUTTON_ROI, threshold=0.86, wait_after=TRANSITION_WAIT_SECONDS)

    def test_checkbox_checked_detection(self):
        import numpy as np
        task = ArenaTask(self.ctx)
        img = np.zeros((30, 30, 3), dtype=np.uint8)
        img[:, :] = [50, 200, 50]  # BGR green-ish
        with patch.object(task, '_checkbox_center', return_value=(15, 15)):
            state = task._checkbox_state(img, 1, 1)
            self.assertEqual(state, "checked")


# ---------------------------------------------------------------------------
# DailyRunner
# ---------------------------------------------------------------------------

class TestDailyRunner(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = _make_context(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _result(self, state: TaskState, key="guild_wish"):
        return TaskRunResult(task_key=key, state=state, message="test", elapsed_seconds=1.0)

    def test_run_task(self):
        runner = DailyRunner(self.ctx)
        expected = self._result(TaskState.COMPLETED)
        with patch.object(GuildWishTask, 'run', return_value=expected):
            result = runner.run_task("guild_wish")
        self.assertEqual(result.state, TaskState.COMPLETED)

    def test_run_current_task(self):
        runner = DailyRunner(self.ctx)
        expected = self._result(TaskState.SKIPPED)
        with patch.object(GuildWishTask, 'run_from_current_daily_screen', return_value=expected):
            result = runner.run_current_task("guild_wish")
        self.assertEqual(result.state, TaskState.SKIPPED)

    def test_run_current_scene_task(self):
        runner = DailyRunner(self.ctx)
        expected = self._result(TaskState.COMPLETED)
        with patch.object(GuildWishTask, 'run_from_current_scene', return_value=expected):
            result = runner.run_current_scene_task("guild_wish")
        self.assertEqual(result.state, TaskState.COMPLETED)

    def test_run_all_skips_unported_tasks(self):
        """run_all 碰到未移植的 key → skip，不 crash，results 只含已移植的。"""
        runner = DailyRunner(self.ctx)
        order = ["arena", "guild_wish"]  # arena 尚未移植
        expected = self._result(TaskState.COMPLETED)
        with patch.object(GuildWishTask, 'run', return_value=expected):
            results = runner.run_all(order)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_key, "guild_wish")


# ---------------------------------------------------------------------------
# TaskState / TaskRunResult
# ---------------------------------------------------------------------------

class TestDataClasses(unittest.TestCase):

    def test_task_state_values(self):
        self.assertEqual(TaskState.COMPLETED.value, "completed")
        self.assertEqual(TaskState.SKIPPED.value, "skipped")
        self.assertEqual(TaskState.NEEDS_ASSETS.value, "needs_assets")
        self.assertEqual(TaskState.FAILED.value, "failed")

    def test_task_run_result_frozen(self):
        r = TaskRunResult(task_key="guild_wish", state=TaskState.COMPLETED)
        with self.assertRaises((AttributeError, TypeError)):
            r.task_key = "other"  # type: ignore

    def test_task_run_result_defaults(self):
        r = TaskRunResult(task_key="x", state=TaskState.FAILED)
        self.assertEqual(r.message, "")
        self.assertEqual(r.elapsed_seconds, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
