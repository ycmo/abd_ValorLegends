from unittest import TestCase

from src.config import TASK_SPECS
from src.ocr_utils import contains_core_keywords, fuzzy_text_score, normalize_ocr_text


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
