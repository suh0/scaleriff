"""코드편집 키 선택 → 스케일 화면/세션 반영 회귀 테스트."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow
from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline
from build.real_builder import regrid_timeline


class KeyEditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_selection_preserves_chords_and_updates_next_screen(self):
        with patch.object(AppWindow, "_try_start_midi"):
            win = AppWindow()
        tl = build_dummy_timeline()
        win._timeline = tl
        win.beat.set_timeline(tl)
        win.beat._on_confirm()
        box = win.beat.key_box
        self.assertEqual(box.currentData(), "C major")
        self.assertEqual(box.count(), 24)
        win.beat._apply_chord(tl.segments[0], "Fmaj7")
        snapshot = [(s.chord.name, s.start_sec, s.end_sec, s.start_bar, s.end_bar)
                    for s in tl.segments]
        bars = list(tl.bar_times)
        box.setCurrentIndex(box.findData("G major"))
        self.assertEqual((tl.key, tl.key_root), ("G major", 7))
        self.assertEqual(snapshot, [(s.chord.name, s.start_sec, s.end_sec,
                                     s.start_bar, s.end_bar) for s in tl.segments])
        self.assertEqual(tl.bar_times, bars)
        self.assertEqual(tl.segments[2].scale_name, "C 리디안")
        self.assertEqual(tl.segments[2].note_set, [0, 2, 4, 6, 7, 9, 11])
        self.assertNotIn(-1, win.beat._cells)   # 예비박은 코드표에 없음
        win.beat._on_done()
        self.assertIs(win.stack.currentWidget(), win.setup)
        self.assertIn("G major", win.setup.key_lbl.text())
        self.assertIn("G 메이저 펜타토닉", win.setup.scale_btns[0].text())
        win.beat._back_to_beat()
        win.beat._on_confirm()
        self.assertEqual(tl.key, "G major")
        self.assertEqual(tl.segments[0].chord.name, "Fmaj7")
        box.setCurrentIndex(box.findData("C minor"))
        self.assertEqual((tl.key, tl.key_root), ("C minor", 0))
        self.assertTrue(tl.segments[1].is_detour)  # G7의 B는 C 자연단음계 밖
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "session.json")
            tl.save_json(path)
            loaded = Timeline.load_json(path)
        self.assertEqual(loaded.key, "C minor")
        self.assertTrue(loaded.key_override)
        win.beat.set_timeline(loaded)
        self.assertEqual(box.currentData(), "C minor")
        win.close()

    def test_manual_key_survives_regrid(self):
        from gui.beat_screen import BeatScreen
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6]
        tl.chord_spans = [[0, 6, "Cmaj7"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen.key_box.setCurrentIndex(screen.key_box.findData("G major"))
        self.assertTrue(regrid_timeline(tl, anchor_sec=0.5))
        self.assertEqual(tl.key, "G major")
        self.assertEqual(tl.segments[0].scale_name, "C 리디안")


if __name__ == "__main__":
    unittest.main()
