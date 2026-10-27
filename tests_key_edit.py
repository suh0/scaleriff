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
        win.beat._build_grid()
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
        win._enter_setup()
        self.assertIs(win.stack.currentWidget(), win.setup)
        self.assertIn("G major", win.setup.key_lbl.text())
        self.assertIn("G 메이저 펜타토닉", win.setup.scale_btns[0].text())
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

    def test_chord_dialog_reestimates_key_unless_chosen(self):
        from PyQt6.QtCore import QTimer
        with patch.object(AppWindow, "_try_start_midi"), \
                patch.object(AppWindow, "_save_session"):
            win = AppWindow()
            tl = build_dummy_timeline()
            win._timeline = tl
            win.beat.set_timeline(tl)
            win._enter_setup()

            def edit(names, key=None):
                def run():
                    for i, name in enumerate(names):
                        win.beat._apply_chord(tl.segments[i], name)
                    if key:
                        win.beat.key_box.setCurrentIndex(win.beat.key_box.findData(key))
                    win.beat.done_btn.click()
                QTimer.singleShot(0, run)
                win.setup.chord_btn.click()
            edit(["E", "A", "B7", "E", "A", "B7"])
            self.assertEqual(tl.key, "E major")
            self.assertIn("E 메이저", win.setup.scale_btns[0].text())
            self.assertTrue(all(not s.is_detour for s in tl.segments))
            edit(["Dm7", "G7", "Cmaj7"], key="E minor")     # 직접 고른 키 → 재추정 안 함
            self.assertEqual(tl.key, "E minor")
            win.close()

    def test_fix_detours_applies_only_checked(self):
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QCheckBox
        from gui.beat_screen import BeatScreen, nearest_diatonic
        from analyze.theory import parse_chord
        self.assertEqual(nearest_diatonic(parse_chord("D"), 7, "minor"), "Dm")
        self.assertEqual(nearest_diatonic(parse_chord("D7"), 7, "minor"), "Dm7")
        self.assertEqual(nearest_diatonic(parse_chord("G7"), 0, "minor"), "Gm7")
        tl = build_dummy_timeline()
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen.key_box.setCurrentIndex(screen.key_box.findData("C minor"))
        self.assertTrue(screen.fix_btn.isEnabled() and not screen.detour_guide.isHidden())
        before = [s.chord.name for s in tl.segments if s.is_detour]
        self.assertIn("G7", before)

        def answer(check_all):
            def run():
                dlg = QApplication.activeModalWidget()
                if check_all:
                    dlg.findChildren(QCheckBox)[0].setChecked(True)   # 전체 선택
                dlg.accept()
            QTimer.singleShot(0, run)
            screen.fix_btn.click()
        answer(False)                       # 체크 안 함 → 그대로
        self.assertEqual(before, [s.chord.name for s in tl.segments if s.is_detour])
        answer(True)
        self.assertFalse(any(s.is_detour for s in tl.segments))
        self.assertIn("Gm7", [s.chord.name for s in tl.segments])
        self.assertFalse(screen.fix_btn.isEnabled())

    def test_revert_to_analysis(self):
        from gui.beat_screen import BeatScreen
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6]
        tl.chord_spans = [[0, 2, "Dm7"], [2, 4, "G7"], [4, 6, "Cmaj7"]]
        tl.analysis_info["key"], tl.analysis_info["key_root"] = "C major", 0
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen._build_grid()
        self.assertFalse(screen.revert_btn.isEnabled())
        screen.key_box.setCurrentIndex(screen.key_box.findData("E minor"))
        screen._apply_chord(tl.segments[1], "Em", 1)
        self.assertTrue(screen.revert_btn.isEnabled())
        bars = list(tl.bar_times)
        screen.revert_btn.click()
        self.assertEqual([s.chord.name for s in tl.segments], ["Dm7", "G7", "Cmaj7"])
        self.assertEqual((tl.key, tl.key_root, tl.key_override), ("C major", 0, False))
        self.assertEqual(screen.key_box.currentData(), "C major")
        self.assertFalse(any(s.is_detour for s in tl.segments))
        self.assertEqual(tl.bar_times, bars)
        self.assertFalse(screen.revert_btn.isEnabled())

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
