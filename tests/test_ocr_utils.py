from unittest import TestCase
from unittest.mock import patch

from src.config import TASK_SPECS
from src.ocr_utils import (
    clear_easyocr_reader_cache,
    contains_core_keywords,
    fuzzy_text_score,
    get_cached_easyocr_reader,
    normalize_ocr_text,
)


class FakeReader:
    def __init__(self):
        self.calls = []

    def readtext(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return [("box", "123", 0.9)]


class EasyOcrReaderCacheTests(TestCase):
    def setUp(self):
        clear_easyocr_reader_cache()

    def tearDown(self):
        clear_easyocr_reader_cache()

    @patch("src.ocr_utils.build_easyocr_reader")
    def test_same_languages_share_one_reader(self, mock_build):
        mock_build.return_value = FakeReader()

        first = get_cached_easyocr_reader(("en",), download_enabled=False)
        second = get_cached_easyocr_reader(("en",), download_enabled=False)

        self.assertIs(first, second)
        mock_build.assert_called_once_with(("en",), download_enabled=False)

    @patch("src.ocr_utils.build_easyocr_reader")
    def test_different_languages_use_separate_readers(self, mock_build):
        mock_build.side_effect = [FakeReader(), FakeReader()]

        english = get_cached_easyocr_reader(("en",), download_enabled=False)
        traditional_chinese = get_cached_easyocr_reader(("ch_tra", "en"), download_enabled=False)

        self.assertIsNot(english, traditional_chinese)
        self.assertEqual(mock_build.call_count, 2)

    @patch("src.ocr_utils.build_easyocr_reader")
    def test_cached_reader_delegates_readtext(self, mock_build):
        raw_reader = FakeReader()
        mock_build.return_value = raw_reader
        reader = get_cached_easyocr_reader(("en",), download_enabled=False)

        result = reader.readtext("image", detail=1)

        self.assertEqual(result, [("box", "123", 0.9)])
        self.assertEqual(raw_reader.calls, [(('image',), {"detail": 1})])


class OcrTextMatchingTests(TestCase):
    def test_task_specs_have_full_daily_text(self):
        self.assertEqual(TASK_SPECS["guild_dungeon"].daily_text, "成功通關2次公會副本挑戰")
        self.assertEqual(TASK_SPECS["summon"].daily_text, "完成1次高級契約召喚")
        self.assertEqual(TASK_SPECS["guild_wish"].daily_text, "進行1次公會祈願")

    def test_normalize_ocr_text_removes_noise(self):
        self.assertEqual(normalize_ocr_text("完成 1 次 高級契約召喚!"), "完成1次高級契約召喚")

    def test_fuzzy_text_score_tolerates_minor_ocr_errors(self):
        score = fuzzy_text_score("完成1次高紐契約召喚", "完成1次高級契約召喚")

        self.assertGreater(score, 0.85)
        self.assertTrue(contains_core_keywords("完成1次高紐契約召喚", "完成1次高級契約召喚"))

    def test_fuzzy_text_score_keeps_different_guild_tasks_apart(self):
        wish_score = fuzzy_text_score("進行1次公會祈願", "成功通關2次公會副本挑戰")

        self.assertLess(wish_score, 0.60)
        self.assertFalse(contains_core_keywords("進行1次公會祈願", "成功通關2次公會副本挑戰"))
