"""메인 화면 입력·설정 통합 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


class LearningFlowTest(unittest.TestCase):
    def test_midi_search_refreshes_open_settings_device_list(self):
        s = self.screen
        s.set_midi_status(["이전 장치"], "이전 장치")
        s.midiPortRequested.connect(lambda _: s.set_midi_status(["새 장치"], "새 장치"))

        def inspect_dialog(dialog):
            ports = next(combo for combo in dialog.findChildren(QComboBox)
                         if combo.findData("이전 장치") >= 0)
            button = next(button for button in dialog.findChildren(QPushButton)
                          if "새로 검색" in button.text())
            button.click()
            self.assertEqual(ports.currentData(), "새 장치")
            self.assertEqual(ports.findData("이전 장치"), -1)

        with patch("gui.main_screen.QDialog.exec", inspect_dialog):
            s._show_settings()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.screen = MainScreen()
        self.screen.set_timeline(build_dummy_timeline())
        self.screen.note_player.set_volume(0)

    def tearDown(self):
        self.screen.pause()
        self.screen.close()

    def test_midi_note_lights_key_and_out_of_range_only_sounds(self):
        s = self.screen
        with patch.object(s.note_player, "note_on") as on:
            s.on_midi_event({"type": "note", "pitch": 65, "is_on": True, "velocity": 70})
            self.assertIn(65, s.piano._pressed)
            s.on_midi_event({"type": "note", "pitch": 48, "is_on": True, "velocity": 70})
            self.assertEqual(on.call_count, 2, "범위 밖 음도 소리는 나야 함")
        self.assertNotIn(48, s.piano._pressed, "두 옥타브 밖 음이 건반에 표시됨")
        s.on_midi_event({"type": "note", "pitch": 65, "is_on": False})
        s.on_midi_event({"type": "note", "pitch": 48, "is_on": False})
        self.assertFalse(s.piano._pressed)

if __name__ == "__main__":
    unittest.main()
