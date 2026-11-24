"""메인 화면 입력·설정 통합 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import statistics
import time
import unittest
from unittest.mock import patch
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QPushButton
from gui.main_screen import MainScreen, tap_offset
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

    def test_settings_song_edit_buttons_emit_after_close(self):
        s = self.screen
        for text, signal in (("박자 조정", s.beatEditRequested), ("코드 수정", s.chordEditRequested)):
            got = []
            signal.connect(lambda: got.append(True))

            def click(dialog, text=text):
                next(b for b in dialog.findChildren(QPushButton) if b.text() == text).click()
                self.assertEqual(got, [], "설정 창이 닫히기 전에 조정 창을 열면 모달이 겹침")
            with patch("gui.main_screen.QDialog.exec", click):
                s._show_settings()
            self.assertEqual(got, [True])

    def test_sync_offset_tap_sets_and_shifts_screen_and_judge(self):
        s = self.screen
        beats = [i * 0.6 for i in range(40)]
        # 들리는 박보다 120ms 늦게 탭(±15ms 흔들림) + 헛탭 한 번 → 중앙값으로 약 120ms
        jitter = [0.0, 0.015, -0.015, 0.01, -0.01, 0.005, -0.005, 0.25]
        taps = [beats[5 + i] + 0.12 + j for i, j in enumerate(jitter)]
        self.assertAlmostEqual(tap_offset(taps, beats), 0.12, delta=0.011)
        saved, now = [], [0.0]
        s.syncChanged.connect(saved.append)
        s.tl.beat_grid = lambda: beats
        s.playhead.is_playing = lambda: True
        s.playhead.position_sec = lambda: now[0]

        def tap_along(dialog):
            button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "박자에 탭")
            for t in taps:
                now[0] = t
                button.pressed.emit()
        with patch("gui.main_screen.QDialog.exec", tap_along):
            s._show_settings()
        self.assertTrue(saved and 115 <= saved[-1] <= 125, saved)
        self.assertAlmostEqual(s._sync_sec, saved[-1] / 1000)
        # 판정은 들리는 위치(재생 위치 - 보정)로
        s._mode = "practice"
        now[0] = 3.0
        with patch.object(s.riff, "judge", return_value=None) as judge:
            s.on_midi_event({"type": "note", "pitch": 65, "is_on": True})
        self.assertAlmostEqual(judge.call_args.args[1], 3.0 - s._sync_sec)
        del s.playhead.is_playing, s.playhead.position_sec
        # 화면도 늦게: G7 시작(2.4초) 직후라도 보정만큼은 아직 Dm7
        s._render_at(2.45)
        self.assertEqual(s.piano._chord_root, 2)
        s.set_sync_ms(0)
        s._render_at(2.45)
        self.assertEqual(s.piano._chord_root, 7)

    def test_playback_tick_alone_drives_frames_at_60hz(self):
        s = self.screen
        s.resize(1040, 740)
        s.show()
        if s._curtain is not None:            # 진입 커튼(불투명)이 덮고 있으면 무대가 안 그려짐 — 끝냄
            s._curtain.anim.setCurrentTime(s._curtain.anim.totalDuration())
        s._seek_to(0.5)                       # Dm7 구간 — 근음 반짝이가 보이는 자리
        stamps = []
        s.playhead.positionChanged.connect(lambda _: stamps.append(time.perf_counter()))
        s.playhead.play()
        QTest.qWait(400)
        self.assertTrue(s.stage.driven)
        self.assertFalse(s.stage._sparkle_timer.isActive(), "재생 중 반짝이 타이머가 따로 그림")
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        self.assertLess(statistics.mean(gaps), 0.025, "재생 틱이 60fps보다 느림(Coarse 타이머 ~31ms) — 부하 여유 포함")
        s.playhead.pause()
        QTest.qWait(80)
        self.assertFalse(s.stage.driven)
        self.assertTrue(s.stage._sparkle_timer.isActive(), "멈춤 중엔 반짝이 타이머가 다시 돎")

    def test_chord_change_never_rebuilds_key_cache(self):
        s = self.screen
        s.resize(1040, 740)
        s.show()
        QTest.qWait(50)                                 # 레이아웃 → 무대 크기 확정
        stage, segs = s.stage, s.tl.segments          # Dm7 G7 Cmaj7 ×2
        if s._curtain is not None:                      # 진입 커튼(불투명)이 덮고 있으면 무대가 안 그려짐 — 끝냄
            s._curtain.anim.setCurrentTime(s._curtain.anim.totalDuration())

        def frame(sec):
            s._render_at(sec)
            stage.grab()                                # paintEvent 강제(오프스크린 repaint는 안 그릴 수 있음)
        frame(segs[0].start_sec + 0.1)                  # 첫 프레임 = 곡의 건반 상태 전부를 한꺼번에 굽는다(로딩)
        self.assertGreaterEqual(len(stage._caches), 3)  # 실제로 그렸음(빈 검사 방지)
        builds = stage.cache_builds
        for seg in segs:                                # 첫 바퀴부터 코드 전환 = 다시 안 그림
            frame(seg.start_sec + 0.1)
        self.assertEqual(stage.cache_builds, builds, "재생 중 코드 전환에 건반 캐시를 다시 그림")
        bg = stage._bg
        self.assertIsNotNone(bg)
        s._select_practice("riff")                      # 리프모드 건반은 코드와 무관 → 상태 1개
        frame(segs[0].start_sec + 0.1)
        builds = stage.cache_builds
        for seg in segs[1:]:
            frame(seg.start_sec + 0.1)
        self.assertEqual(stage.cache_builds, builds, "리프모드에서 코드마다 건반 캐시를 다시 그림")
        self.assertIs(stage._bg, bg, "배경은 창 크기가 바뀔 때만")
        s.resize(1000, 700)
        QTest.qWait(50)
        frame(segs[0].start_sec + 0.1)
        self.assertIsNotNone(stage._bg)
        self.assertIsNot(stage._bg, bg)

    def test_stage_curtain_opens_on_entry_and_riff_restart(self):
        from gui import anim
        s = self.screen
        s.show()                                        # 연주화면 진입 = 무대 커튼
        curtain = s._curtain
        self.assertIsNotNone(curtain)
        self.assertIs(curtain.parentWidget(), s, "커튼은 화면 전체(HUD 포함)를 덮음")
        s.content.raise_()                              # 나중에 다른 층이 올라와도
        curtain.anim.setCurrentTime(100)                # 다음 프레임에 다시 맨 앞
        self.assertIs([w for w in s.children() if w.isWidgetType()][-1], curtain, "커튼이 맨 앞 레이어가 아님")
        self.assertTrue(curtain.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        QTest.qWait(curtain.anim.totalDuration() + 150)
        self.assertIsNone(s._curtain, "다 열린 뒤 커튼이 남음")
        s._mode = "practice"                            # 리프모드 해제 = 처음부터 다시 → 커튼 다시
        s._toggle_riff_mode()
        self.assertIsNotNone(s._curtain)
        self.app.setProperty("reduceMotion", True)      # 효과 축소면 커튼 없음(이전 커튼은 정리)
        try:
            anim.open_curtain(s)
            QTest.qWait(30)
            self.assertIsNone(s._curtain)
        finally:
            self.app.setProperty("reduceMotion", False)

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
