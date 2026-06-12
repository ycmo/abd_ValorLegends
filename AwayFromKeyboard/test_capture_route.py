import unittest
from pathlib import Path
import tempfile
import shutil
import sys

# Ensure capture_route can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_route import RouteCapturer

class FakeEnv:
    def __init__(self, prompt_replies=None, adb_returncode=0, adb_exception=None):
        self.prompt_replies = prompt_replies or []
        self.adb_returncode = adb_returncode
        self.adb_exception = adb_exception
        self.adb_calls = []
        self.mspaint_calls = []
        self.prompts_shown = []
        
    def prompt_user(self, msg: str) -> str:
        self.prompts_shown.append(msg)
        return self.prompt_replies.pop(0) if self.prompt_replies else 'n'
        
    def run_adb_screencap(self, adb_path: str, serial: str, out_file: Path) -> int:
        self.adb_calls.append((adb_path, serial, out_file))
        if self.adb_exception:
            raise self.adb_exception
        # Fake creating a file
        out_file.write_text("fake_png_data")
        return self.adb_returncode

    def open_mspaint(self, file_path: Path):
        self.mspaint_calls.append(file_path)


class TestCaptureRoute(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        
    def tearDown(self):
        shutil.rmtree(self.temp_dir)
        
    def test_capture_new_file_success(self):
        env = FakeEnv(adb_returncode=0)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertTrue(success)
        self.assertEqual(len(env.adb_calls), 1)
        self.assertEqual(env.adb_calls[0][1], "test-serial")
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
        self.assertEqual(len(env.adb_calls), 0)
        self.assertEqual((screenshots_dir / "test_tag.png").read_text(), "old_data")

    def test_capture_file_exists_user_overwrites(self):
        # Setup existing file
        screenshots_dir = self.temp_dir / "route_screenshots" / "test_route"
        screenshots_dir.mkdir(parents=True)
        (screenshots_dir / "test_tag.png").write_text("old_data")
        
        env = FakeEnv(prompt_replies=['y'], adb_returncode=0)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertTrue(success)
        self.assertEqual(len(env.adb_calls), 1)
        self.assertEqual((screenshots_dir / "test_tag.png").read_text(), "fake_png_data")

    def test_adb_fails(self):
        env = FakeEnv(adb_returncode=1)
        capturer = RouteCapturer(env=env)
        
        success = capturer.capture("test_route", "test_tag", "test-serial", base_dir=self.temp_dir)
        
        self.assertFalse(success)
        self.assertEqual(len(env.adb_calls), 1)
        self.assertEqual(len(env.mspaint_calls), 0)

if __name__ == "__main__":
    unittest.main()
