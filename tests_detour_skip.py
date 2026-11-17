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
        dialog.accept()
        self.assertTrue(all(seg.example == [] for seg in tl.segments if seg.is_detour))
        self.assertTrue(any(seg.example for seg in tl.segments if not seg.is_detour))
        s.close()


    def test_riff_alternates_program_and_my_bars(self):
        # 4마디 블록 = 같은 리프(같은 음·같은 박) [프로그램, 나, 프로그램, 나]
        tl = build_dummy_timeline()
        tl.apply_song_scale(song_scale_options(tl.key_root, "major")[0])
        s = MainScreen()
        s.set_timeline(tl)
        dialog = RiffDialog(tl, s._ml_model)
        self.assertTrue(dialog.blocks)
        dialog.accept()
        s._build_riff_events()
        for block in dialog.blocks:
            bars = []
            for a, b in block["bars"]:
                bars.append([(round(tl.beat_at(t) - tl.beat_at(a), 3), m, c)
                             for t, m, c in s._riff_events if a <= t < b])
            self.assertTrue(5 <= len(bars[0]) and all(c for _, _, c in bars[0]), bars[0])
            for k, notes in enumerate(bars):
                self.assertEqual([(x, m) for x, m, _ in notes], [(x, m) for x, m, _ in bars[0]])
                self.assertTrue(all(c == (k % 2 == 0) for _, _, c in notes))
        # 낙하 노드 = 두 차례 모두, 판정·흐린 레일 = 프로그램 차례만
        self.assertEqual(len(s.riff._events), len(s._riff_events))
        self.assertEqual(s.riff._calls, [span for blk in dialog.blocks for span in blk["bars"][::2]])
        s.riff.show_notes = True
        call = next((t, m) for t, m, c in s._riff_events if c)
        mine = next((t, m) for t, m, c in s._riff_events if not c)
        self.assertIsNone(s.riff.judge(call[1], call[0]))
        self.assertEqual(s.riff.judge(mine[1], mine[0])[0], "PERFECT")
        s.riff.resize(100, 400)
        a, b = s.riff._calls[0]
        s.riff.set_position(a)
        self.assertEqual(s.riff.call_bands()[0], (400 * (1 - (min(b, a + s.riff._lead) - a) / s.riff._lead), 400))
        s.close()

    def test_landing_check_alternates_blocks_and_highlights_only_there(self):
        from ml.generate import _landing_pc
        tl = build_dummy_timeline()
        tl.apply_song_scale(song_scale_options(tl.key_root, "major")[1])   # 키 7음 → 모든 코드 3도 가능
        s = MainScreen()
        s.set_timeline(tl)
        dialog = RiffDialog(tl, s._ml_model)
        self.assertGreaterEqual(len(dialog.blocks), 2)
        n = len(dialog.blocks)
        self.assertEqual([chk.text() for chk in dialog.landing_chks.values()], ["3도 착지 섞기", "7도 착지 섞기"])
        self.assertEqual([dialog._goal(i) for i in range(n)], [None] * n)          # 기본 = 착지 없음
        dialog.landing_chks["seventh"].setChecked(True)
        self.assertEqual([dialog._goal(i) for i in range(n)], [None, "seventh"] * (n // 2) + [None] * (n % 2))
        dialog.landing_chks["third"].setChecked(True)                             # 둘 다 = 기본→3도→7도 순환
        self.assertEqual([dialog._goal(i) for i in range(6)], [None, "third", "seventh"] * 2)
        last = dialog.riffs[1]["notes"][-1]                                        # 3도 리프 끝 = 3도
        self.assertEqual(last["midi"] % 12, _landing_pc(tl.segment_at(last["start_sec"]), "third"))
        dialog.accept()
        self.assertEqual(tl.practice["landing"], ["third", "seventh"])
        self.assertEqual(RiffDialog(tl, s._ml_model)._goals(), ["third", "seventh"])   # 다시 열어도 유지
        s._select_practice("riff")
        a, _, goal = s._landing_spans[0]
        self.assertEqual(goal, "third")
        s._seek_to(a + 1e-3)                    # 착지음 블록 = 목표음만 초록
        seg = tl.segment_at(a + 1e-3)
        self.assertEqual(set(s.piano._chord_tones), {_landing_pc(seg, "third")})
        s._seek_to(dialog.blocks[0]["bars"][0][0] + 1e-3)   # 기본 블록 = 코드톤 전체
        self.assertEqual(set(s.piano._chord_tones),
                         set(tl.segment_at(dialog.blocks[0]["bars"][0][0] + 1e-3).chord_tones()))
        s._select_practice("free")              # 자유연습 = 착지음 강조 없음
        s._seek_to(a + 1e-3)
        self.assertEqual(set(s.piano._chord_tones), set(seg.chord_tones()))
        s.close()

if __name__ == "__main__":
    unittest.main()
