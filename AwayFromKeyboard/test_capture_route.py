import unittest
from pathlib import Path
import tempfile
import shutil
import sys

# Ensure capture_route can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_route import RouteCapturer

class FakeEnv:
    def __init__(self, prompt_replies=None, connect_result=True, screenshot_exception=None):
        self.prompt_replies = prompt_replies or []
        self.connect_result = connect_result
        self.screenshot_exception = screenshot_exception
        self.controllers = []
        self.screenshot_calls = []
        self.mspaint_calls = []
        self.prompts_shown = []
        
    def prompt_user(self, msg: str) -> str:
        self.prompts_shown.append(msg)
        return self.prompt_replies.pop(0) if self.prompt_replies else 'n'

    def create_controller(self, serial=None):
        controller = FakeController(serial, self.connect_result)
        self.controllers.append(controller)
        return controller

    def write_screenshot(self, controller, out_file: Path) -> None:
        self.screenshot_calls.append((controller, out_file))
        if self.screenshot_exception:
            raise self.screenshot_exception
        out_file.write_text("fake_png_data")

    def open_mspaint(self, file_path: Path):
        self.mspaint_calls.append(file_path)


class FakeController:
    def __init__(self, serial, connect_result):
        self.serial = serial
        self.connect_result = connect_result

    def connect(self):
        return self.connect_result


class TestCaptureRoute(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def test_capture_new_file_success(self):
        env = FakeEnv(connect_result=True)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", base_dir=self.temp_dir)
        
        self.assertTrue(success)
        self.assertEqual(len(env.controllers), 1)
        self.assertIsNone(env.controllers[0].serial)
        self.assertEqual(len(env.screenshot_calls), 1)
        self.assertEqual(len(env.mspaint_calls), 1)
        
        expected_file = self.temp_dir / "route_screenshots" / "test_route" / "test_tag.png"
        self.assertTrue(expected_file.exists())
        self.assertEqual(expected_file.read_text(), "fake_png_data")

    def test_capture_file_exists_user_cancels(self):
        # Setup existing file
        screenshots_dir = self.temp_dir / "route_screenshots" / "test_route"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "test_tag.png").write_text("old_data")
        
        env = FakeEnv(prompt_replies=['n'])
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertFalse(success)
        self.assertEqual(len(env.screenshot_calls), 0)
        self.assertEqual((screenshots_dir / "test_tag.png").read_text(), "old_data")

    def test_capture_file_exists_user_overwrites(self):
        # Setup existing file
        screenshots_dir = self.temp_dir / "route_screenshots" / "test_route"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "test_tag.png").write_text("old_data")
        
        env = FakeEnv(prompt_replies=['y'], connect_result=True)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertTrue(success)
        self.assertEqual(len(env.screenshot_calls), 1)
        self.assertEqual((screenshots_dir / "test_tag.png").read_text(), "fake_png_data")

    def test_adb_fails(self):
        env = FakeEnv(connect_result=False)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertFalse(success)
        self.assertEqual(len(env.controllers), 1)
        self.assertEqual(len(env.screenshot_calls), 0)
        self.assertEqual(len(env.mspaint_calls), 0)

if __name__ == "__main__":
    unittest.main()
