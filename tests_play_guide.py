"""자유연습 번호 표시(곡 스케일 주음 고정 + 코드 근음 강조)와 첫 진입 화면 가이드."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from analyze.theory import degree_number, parse_chord, song_scale_options
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


def pentatonic_timeline():
    tl = build_dummy_timeline()                        # C 메이저 · Dm7–G7–Cmaj7
    tl.apply_song_scale(song_scale_options(tl.key_root, "major")[0])   # C 메이저 펜타토닉(1 = C)
    return tl


class PlayGuideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.screen = MainScreen()
        self.screen.resize(1100, 720)
        self.screen.note_player.set_volume(0)

    def tearDown(self):
        self.screen.pause()
        self.screen.close()

    def test_numbers_stay_on_song_tonic_and_chord_root_is_marked(self):
        s, tl = self.screen, pentatonic_timeline()
        tl.segments[0].chord = parse_chord("F")        # 근음 F는 C 펜타토닉 밖
        s.set_timeline(tl)
        for seg in tl.segments:
            s._seek_to(seg.start_sec + 1e-3)
            root = seg.chord.root % 12
            self.assertEqual(s.piano._chord_root, root)
            # 번호는 어느 구간이든 C = 1 기준(코드마다 다시 매기지 않음)
            self.assertEqual(s.piano._degrees.get(0), "1")
            self.assertEqual(s.piano._degrees[root], degree_number(root, 0), "근음 번호 없음")
            self.assertEqual(s.stage._tone(60 + root).name(), "#1f4bff", "근음 강조 없음")
            self.assertIn(f"근음 {degree_number(root, 0)}번", s.chord_hdr._chords[1])
        s._seek_to(tl.segments[0].start_sec + 1e-3)
        self.assertEqual(s.piano._degrees[5], "4")     # 스케일 밖 근음도 번호 표시
        self.assertFalse(s.piano._is_out(65), "스케일 밖 근음을 누르면 빨강으로 표시됨")
        self.assertTrue(s.piano._is_out(66))            # 근음 아닌 스케일 밖 음은 그대로 빨강

    def test_count_in_shows_song_scale_numbers_without_root(self):
        s, tl = self.screen, pentatonic_timeline()
        s.set_timeline(tl)
        s._seek_to(-0.5)                                # 첫 코드 전 예비박(무음 프리롤)
        self.assertIsNone(s.piano._chord_root)
        self.assertEqual(set(s.piano._degrees), set(tl.practice["scale"]["note_set"]))

    def test_guide_steps_through_and_lands_on_count_in(self):
        s, tl = self.screen, pentatonic_timeline()
        s.set_timeline(tl)
        s.show()
        done = []
        s.guideFinished.connect(lambda: done.append(1))
        s.show_guide()
        guide = s.guide
        self.assertIsNotNone(guide)
        self.assertNotEqual(s.piano._chord_root, 0, "설명 자리 근음이 1번과 같은 건반")
        steps = len(guide._steps)
        self.assertGreaterEqual(steps, 5)
        for i in range(steps):
            self.assertTrue(guide.isVisible())
            self.assertEqual(guide.count_lbl.text(), f"{i + 1} / {steps}")
            self.assertTrue(all(guide.rect().contains(r.center()) for r in guide._holes()), i)
            QTest.keyClick(guide, Qt.Key.Key_Return)
        self.assertEqual(done, [1])
        self.assertIsNone(s.guide)
        self.assertAlmostEqual(s.playhead.position_sec(), tl.count_in_start())
        self.assertFalse(s.playhead.is_playing())

    def test_guide_skip_and_space_do_not_start_playback(self):
        s, tl = self.screen, pentatonic_timeline()
        s.set_timeline(tl)
        s.show()
        s.show_guide()
        s._on_space()                                   # 가이드 중 스페이스 = 다음 단계
        self.assertFalse(s.playhead.is_playing())
        self.assertEqual(s.guide.count_lbl.text().split(" / ")[0], "2")
        s.guide.skip_btn.click()
        self.assertIsNone(s.guide)
        self.assertAlmostEqual(s.playhead.position_sec(), tl.count_in_start())

    def test_app_shows_guide_only_on_first_entry(self):
        from gui.app import AppWindow
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(AppWindow, "_try_start_midi"), \
                patch("player.playhead._HAS_MULTIMEDIA", False):
            win = AppWindow()
            win._settings = QSettings(str(Path(directory) / "s.ini"), QSettings.Format.IniFormat)
            win.link_screen.set_save_dir(directory)
            win._timeline = pentatonic_timeline()
            win._enter_main()
            self.assertIsNotNone(win.main_screen.guide, "첫 진입에 가이드 없음")
            win.main_screen.guide.finish()
            self.assertTrue(win._settings.value("seen_play_guide", False, type=bool))
            win._enter_main()
            self.assertIsNone(win.main_screen.guide, "두 번째 진입에도 가이드가 뜸")
            win.close()


if __name__ == "__main__":
    unittest.main()
