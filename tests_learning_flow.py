"""사용자 연습→연주 기록→점수→세션 복원 통합 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline
from player.scoring import reference_notes


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

    def test_seek_while_playing_starts_new_take(self):
        s = self.screen
        s.playhead.play()
        self.assertTrue(s.recorder.active)
        s._seek_to(1)
        self.assertTrue(s.playhead.is_playing())
        self.assertTrue(s.recorder.active, "시킹 후 재생은 계속되지만 기록이 끊김")
        self.assertEqual(s.recorder.start_sec, 1)
        s.recorder.event({"type": "note", "pitch": 65, "is_on": True}, 1.2)
        s.recorder.event({"type": "note", "pitch": 65, "is_on": False}, 1.4)
        self.assertIsNotNone(s._finish_take(2))
        self.assertEqual(len(s.tl.practice_history), 1)

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

    def test_riff_capture_score_roundtrip(self):
        s = self.screen
        s._select_practice("riff")
        start, end = 0, 2.4
        s._start_take(start)
        for n in reference_notes(s.tl, start, end):
            s.recorder.event({"type": "note", "pitch": n["midi"], "is_on": True,
                              "velocity": 80}, n["start_sec"])
            s.recorder.event({"type": "note", "pitch": n["midi"], "is_on": False},
                             n["start_sec"] + n["duration_sec"])
        summary = s._finish_take(end)
        self.assertEqual(summary["score"], 100)
        self.assertEqual(len(s.tl.practice_history), 1)
        restored = Timeline.from_dict(s.tl.to_dict())
        self.assertTrue(restored.practice_history[0]["notes"])
        s._finish_take(end)
        self.assertEqual(len(s.tl.practice_history), 1, "중복 종료 기록")

    def test_seek_discards_incomplete_take(self):
        s = self.screen
        self.assertTrue(hasattr(s, "recorder"), "연주 캡처 없음")
        s._start_take(0)
        s.recorder.event({"type": "note", "pitch": 65, "is_on": True}, .1)
        s._seek_to(3)
        self.assertFalse(s.recorder.active)
        self.assertEqual(s.tl.practice_history, [])

    def test_midi_note_off_updates_display_and_recorded_length(self):
        s = self.screen
        self.assertTrue(hasattr(s, "on_midi_event"), "전체 MIDI 이벤트 수신 없음")
        s._start_take(0)
        with patch.object(s.playhead, "position_sec", return_value=.2):
            s.on_midi_event({"type": "note", "pitch": 65, "is_on": True, "velocity": 70})
        self.assertIn(65, s.piano._pressed)
        with patch.object(s.playhead, "position_sec", return_value=.6):
            s.on_midi_event({"type": "note", "pitch": 65, "is_on": False})
        self.assertNotIn(65, s.piano._pressed)
        summary = s._finish_take(2.4)
        self.assertIsNotNone(summary)
        self.assertAlmostEqual(s.tl.practice_history[-1]["notes"][0]["duration_sec"], .4)


if __name__ == "__main__":
    unittest.main()
