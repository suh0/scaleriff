"""키 밖 코드: 연주화면 주황 표시 + 학습설정 곡 정보 카드·제외(건반 강조·리프 없음)."""
import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import unittest

from PyQt6.QtWidgets import QApplication

from analyze.theory import song_scale_options
from gui.main_screen import MainScreen
from gui.riff_dialog import RiffDialog
from gui.setup_screen import SetupScreen
from player.dummy_timeline import build_dummy_timeline


def detour_timeline():
    tl = build_dummy_timeline()                        # C 메이저 · Dm7–G7–Cmaj7
    for seg in tl.segments:                            # G7을 키 밖 코드로 가정(같은 코드는 같은 판정)
        seg.is_detour = seg.chord.name == tl.segments[1].chord.name
    return tl


class DetourSkipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_setup_info_card_and_skip_saved(self):
        tl = detour_timeline()
        su = SetupScreen()
        su.set_timeline(tl)
        g7 = tl.segments[1].chord.name
        n = sum(s.chord.name == g7 for s in tl.segments)
        self.assertTrue(su.key_lbl.text().startswith("추정 키: "))
        self.assertEqual(su.detour_lbl.text(), f"키 밖 코드 1종 · {n}번 나와요 ({g7})")
        self.assertTrue(su.skip_chk.isEnabled() and not su.skip_chk.isChecked())
        su.skip_chk.click()
        su.remember()
        self.assertTrue(tl.practice["skip_detour"])
        su.set_timeline(tl)                            # 다시 들어와도 유지
        self.assertTrue(su.skip_chk.isChecked())

    def test_no_detour_disables_checkbox(self):
        su = SetupScreen()
        su.set_timeline(build_dummy_timeline())
        self.assertEqual(su.detour_lbl.text(), "키 밖 코드가 없어요")
        self.assertFalse(su.skip_chk.isEnabled())

    def test_play_screen_orange_and_skip_highlight(self):
        tl = detour_timeline()
        pent = song_scale_options(tl.key_root, "major")[0]
        tl.apply_song_scale(pent)
        s = MainScreen()
        s.note_player.set_volume(0)
        s.set_timeline(tl)
        seg = tl.segments[1]
        self.assertEqual(s.chord_hdr._detour, {seg.chord.name})
        mid = (seg.start_sec + seg.end_sec) / 2
        self.assertTrue(s.riff.in_detour(mid))
        self.assertFalse(s.riff.in_detour(tl.segments[0].start_sec))
        # 그리기 경로에서 예외(GeneratorExit 포함)가 나면 디버거가 그리기 도중 멈춰 Qt가 충돌한다
        raised = []

        def tracer(frame, event, arg):
            return local if frame.f_code.co_name == "in_detour" else None

        def local(frame, event, arg):
            if event == "exception":
                raised.append(arg[0].__name__)
            return local
        sys.settrace(tracer)
        try:
            s.riff.in_detour(mid)
        finally:
            sys.settrace(None)
        self.assertEqual(raised, [])
        s._seek_to(seg.start_sec + 1e-3)               # 제외 안 함 → 근음 강조
        self.assertEqual(s.piano._chord_root, seg.chord.root % 12)
        tl.practice["skip_detour"] = True
        s._last_idx = -2
        s._seek_to(seg.start_sec + 2e-3)               # 제외 → 곡 스케일만, 강조 없음
        self.assertIsNone(s.piano._chord_root)
        self.assertFalse(s.piano._chord_tones)
        self.assertEqual(set(s.piano._degrees), set(pent["note_set"]))
        s.close()

    def test_riff_skips_detour_segments(self):
        tl = detour_timeline()
        tl.apply_song_scale(song_scale_options(tl.key_root, "major")[0])
        tl.practice["skip_detour"] = True
        s = MainScreen()
        dialog = RiffDialog(tl, s._ml_model)
        self.assertFalse(any(pt["overlay"] for pt in dialog.patterns))
        dialog.accept()
        self.assertTrue(all(seg.example == [] for seg in tl.segments if seg.is_detour))
        self.assertTrue(any(seg.example for seg in tl.segments if not seg.is_detour))
        s.close()


if __name__ == "__main__":
    unittest.main()
