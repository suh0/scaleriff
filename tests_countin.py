"""0마디, 음수 격자 및 무음 프리롤 회귀 테스트."""
import os
import tempfile
import unittest
import wave
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QUrl, QPoint, Qt
from gui.beat_screen import BeatScreen
from player.dummy_timeline import build_dummy_timeline
from player.timeline import Timeline
from player.playhead import Playhead
from build.real_builder import regrid_timeline


class CountInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_negative_grid_and_blank_zero_bar(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6, 8]
        tl.chord_spans = [[0, 4, "Dm7"], [4, 8, "G7"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen._on_drag(0, -0.7)
        self.assertAlmostEqual(screen.anchor, -0.7)
        self.assertLessEqual(screen.zoom_l._t0, -2.7)
        screen._on_confirm()
        self.assertEqual(tl.bar_times[0], -0.7)
        self.assertNotIn(-1, screen._cells)          # 예비박은 코드표에 없음
        self.assertAlmostEqual(tl.count_in_start(), -2.7)
        screen._loop_press(0)
        screen._loop_drag_to(-1)
        self.assertFalse(screen._drag_loop)
        screen._reset_drag()
        self.assertIsNone(tl.segment_at(-0.1))
        self.assertEqual(tl.segment_index_at(-0.1), -1)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "session.json")
            tl.save_json(path)
            restored = Timeline.load_json(path)
        self.assertEqual(restored.bar_times, tl.bar_times)
        self.assertEqual(restored.audio_ref, tl.audio_ref)
        screen.pause()

    def test_wholly_negative_regular_bars_have_no_chords(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6]
        tl.chord_spans = [[0, 6, "C"]]
        self.assertTrue(regrid_timeline(tl, anchor_sec=-4.5))
        self.assertIsNone(tl.segment_for_bar(0))
        self.assertIsNone(tl.segment_for_bar(1))
        self.assertGreaterEqual(tl.segments[0].start_sec, 0)

    def test_left_extension_keeps_waveform_scale(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        zoom = screen.zoom_l
        zoom.resize(400, 96)
        spacing = zoom._sec_to_x(1) - zoom._sec_to_x(0)
        for anchor in (-1, -5, -20):
            screen._on_drag(0, anchor)
            self.assertAlmostEqual(zoom._sec_to_x(1) - zoom._sec_to_x(0), spacing)
            self.assertAlmostEqual(zoom._t1 - zoom._t0, 10)
            self.assertAlmostEqual(zoom._t0, max(-5, anchor - screen.bar_len))

    def test_countin_cannot_extend_before_minus_five(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        for bar in (-1, 0, 8):
            for _ in range(3):
                screen._on_drag(bar, -100)
                self.assertAlmostEqual(screen.anchor - screen.bar_len, -5)
                self.assertAlmostEqual(screen.zoom_l._t0, -5)
        screen.bpm_edit.setText("20")
        screen._on_bpm_edited()
        self.assertAlmostEqual(screen.anchor - screen.bar_len, -5)
        screen.sig_box.setCurrentIndex(screen.sig_box.findData("3/4"))
        self.assertGreaterEqual(screen.anchor - screen.bar_len, -5 - 1e-9)

    def test_stationary_drag_does_not_keep_expanding(self):
        screen = BeatScreen()
        screen.set_timeline(build_dummy_timeline())
        zoom = screen.zoom_l
        zoom.resize(400, 96)
        QTest.mousePress(zoom, Qt.MouseButton.LeftButton, pos=QPoint(120, 40))
        QTest.mouseMove(zoom, QPoint(20, 40))
        anchor = screen.anchor
        for _ in range(5):
            QTest.mouseMove(zoom, QPoint(20, 40))
            self.assertAlmostEqual(screen.anchor, anchor)
        QTest.mouseRelease(zoom, Qt.MouseButton.LeftButton, pos=QPoint(20, 40))
        screen.pause()

    def _screen(self):
        tl = build_dummy_timeline()
        tl.bpm = 120
        tl.bar_times = [0, 2, 4, 6, 8]
        tl.chord_spans = [[0, 4, "Dm7"], [4, 8, "G7"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        return screen, tl

    def test_space_toggles_play_instead_of_link(self):
        screen, _ = self._screen()
        screen.show()
        link = Mock()
        screen.backToLinkRequested.connect(link)
        screen.link_btn.setFocus()
        self.app.processEvents()
        screen.playhead.seek(5.0)
        # 창 경유(실제 키 입력 경로) — 단축키가 포커스 버튼보다 먼저 처리돼야 함
        QTest.keyClick(screen.windowHandle(), Qt.Key.Key_Space)
        link.assert_not_called()
        self.assertTrue(screen.playhead.is_playing())
        self.assertLess(abs(screen.playhead.position_sec() - screen.anchor), 0.05)  # 1마디부터
        QTest.keyClick(screen.windowHandle(), Qt.Key.Key_Space)
        self.assertFalse(screen.playhead.is_playing())
        screen._show_step(2)                  # 2단계: 끝부분 창의 첫 마디부터
        screen._toggle_play()
        pos = screen.playhead.position_sec()
        self.assertTrue(screen.zoom_r._t0 <= pos < screen.zoom_r._t0 + screen.bar_len)
        screen.pause()
        screen.close()

    def test_click_sets_start_drag_pauses_and_release_plays(self):
        screen, _ = self._screen()
        zoom = screen.zoom_l
        zoom.resize(400, 96)
        x = round(zoom._sec_to_x(1.3))
        sec = zoom._x_to_sec(x)
        QTest.mouseClick(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
        self.assertAlmostEqual(screen.anchor, sec)
        self.assertAlmostEqual(screen.bar_len, 2.0)       # BPM 불변
        self.assertFalse(screen.playhead.is_playing())    # 클릭으로는 재생 안 함
        screen._toggle_play()
        QTest.mousePress(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
        QTest.mouseMove(zoom, QPoint(x + 40, 40))
        self.assertFalse(screen.playhead.is_playing())    # 끄는 동안 음원도 정지
        screen.playhead.seek(5.0)
        QTest.mouseRelease(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x + 40, 40))
        self.assertTrue(screen.playhead.is_playing())     # 놓으면 스페이스바처럼 1마디부터
        self.assertLess(abs(screen.playhead.position_sec() - screen.anchor), 0.05)
        screen.pause()
        screen._show_step(2)                               # 끝 핸들도 같음(끝부분 창 첫 마디부터)
        zr = screen.zoom_r
        zr.resize(400, 96)
        ex = round(zr._sec_to_x(zr._end))
        QTest.mousePress(zr, Qt.MouseButton.LeftButton, pos=QPoint(ex, 40))
        QTest.mouseMove(zr, QPoint(ex + 30, 40))
        self.assertFalse(screen.playhead.is_playing())
        QTest.mouseRelease(zr, Qt.MouseButton.LeftButton, pos=QPoint(ex + 30, 40))
        self.assertTrue(screen.playhead.is_playing())
        pos = screen.playhead.position_sec()
        self.assertTrue(zr._t0 <= pos < zr._t0 + screen.bar_len)
        screen.pause()

    def _beat_screen(self, beats, bar0):
        tl = build_dummy_timeline()
        tl.beat_times = beats
        tl.bar_times = [bar0, beats[-1] + 0.5]
        tl.chord_spans = [[0, beats[-1] + 0.5, "C"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        for z in (screen.zoom_l, screen.zoom_r):
            z.resize(400, 96)                     # 10초/400px → 8px ≈ 0.2초
        return screen, tl

    def test_bar_lines_snap_to_detected_beats(self):
        screen, tl = self._beat_screen([0.3 + 0.5 * i for i in range(24)], 0.3)
        screen._on_zoom_click(1.42)               # 1.3 근처 → 그 비트가 1마디
        self.assertAlmostEqual(screen.anchor, 1.3)
        self.assertEqual((screen._bar1, screen._offset), (2, 0.0))
        screen._on_zoom_click(1.05)               # 비트 사이 → 평행이동(간격은 검출 비트)
        self.assertAlmostEqual(screen.anchor, 1.05)
        self.assertAlmostEqual(screen.beat_at(1) - screen.beat_at(0), 0.5)
        screen._on_drag(0, 0.75)                  # 0.8 근처 → 다시 비트에 붙음
        self.assertAlmostEqual(screen.anchor, 0.8)
        self.assertEqual(screen._offset, 0.0)
        screen._show_step(2)
        screen._on_stretch(4, 8.71)               # 끝 마디선 8.8(비트)로 붙음 → 균등 격자
        self.assertIsNone(screen._lattice)
        self.assertAlmostEqual(screen.anchor, 0.8)
        self.assertAlmostEqual(screen.bar_len, 60 * 4 / round(60 * 4 / 2.0, 1), 3)

    def test_entry_grid_is_detected_beats_exactly(self):
        import random
        random.seed(3)
        true = [0.4 + 0.55 * i for i in range(120)]
        beats = [round(t + random.uniform(-0.04, 0.04), 2) for t in true]
        screen, tl = self._beat_screen(beats, 1.5)
        ghost = screen.zoom_l._ghost
        self.assertEqual(ghost, tl.smoothed_beats())          # 흐린 선 = 보정 비트
        bar1 = min(range(len(ghost)), key=lambda k: abs(ghost[k] - 1.5))
        for i in range(-4, 100):                              # 실선 = 흐린 선(오차 0)
            if 0 <= bar1 + i < len(ghost):
                self.assertEqual(screen.beat_at(i), ghost[bar1 + i])
        self.assertLess(max(abs(a - b) for a, b in zip(ghost, true)), 0.02)
        # BPM 직접 입력 → 균등 격자(1마디 유지)
        anchor = screen.anchor
        screen.bpm_edit.setText("100")
        screen._on_bpm_edited()
        self.assertIsNone(screen._lattice)
        self.assertAlmostEqual(screen.anchor, anchor)
        self.assertAlmostEqual(screen.beat_at(4) - screen.beat_at(0), 2.4)

    def test_confirm_uses_beat_grid_and_reentry_restores(self):
        beats = [0.3 + 0.5 * i + (0.02 if i % 7 == 0 else 0) for i in range(40)]
        screen, tl = self._beat_screen(beats, 0.3)
        screen._on_drag(0, 1.05)                  # 비트 사이로 평행이동(오프셋 유지)
        expected = screen._bar_list()
        screen._on_confirm()
        self.assertEqual(tl.bar_times[:-1], expected)
        self.assertFalse(tl.timing_override)      # 박도 검출 비트를 따름
        segments = list(tl.segments)
        screen._back_to_beat()
        screen._on_confirm()                      # 무변경 확정 → 재격자화 생략
        self.assertTrue(all(a is b for a, b in zip(segments, tl.segments)))
        screen.set_timeline(tl)                   # 재진입: 같은 격자 복원
        self.assertIsNotNone(screen._lattice)
        self.assertEqual([round(t, 6) for t in screen._bar_list()],
                         [round(t, 6) for t in expected])

    def test_smooth_beats_follows_tempo_and_fills_missing(self):
        from player.timeline import smooth_beats
        import random
        random.seed(5)
        true, t = [], 0.5
        for i in range(160):                      # 100 → 120 BPM으로 점점 빨라짐
            true.append(t)
            t += 60 / (100 + 20 * i / 159)
        noisy = [round(x + random.uniform(-0.04, 0.04), 2) for x in true]
        del noisy[70]                             # 놓친 박
        out = smooth_beats(noisy)
        self.assertEqual(len(out), len(true))
        self.assertLess(sum(abs(a - b) for a, b in zip(out, true)) / len(true), 0.015)

    def test_bpm_follows_beat_spacing_without_octave_fix(self):
        from ingest.mir_extract import _bpm_from_beats
        self.assertEqual(_bpm_from_beats([0.82 + 0.87 * i for i in range(20)]), 69.0)
        self.assertEqual(_bpm_from_beats([0.3 * i for i in range(20)]), 200.0)

    def test_click_sample_is_long_enough_to_be_heard(self):
        import soundfile as sf
        from player.note_synth import render_click_wav
        data, sr = sf.read(render_click_wav(1760.0))
        self.assertGreaterEqual(len(data) / sr, 0.1)
        self.assertLess(abs(data[-1]), 1e-3)       # 끝은 0으로(끊김 팝 없음)

    def test_end_handle_sets_chord_recognition_end(self):
        screen, tl = self._screen()                # 0~8초, 마디 2초
        screen._show_step(2)
        zoom = screen.zoom_r
        zoom.resize(400, 96)
        self.assertAlmostEqual(zoom._end, 8.0)     # 기본 = 곡 끝
        x = round(zoom._sec_to_x(8.0))
        QTest.mousePress(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
        self.assertTrue(zoom.dragging)            # 핸들 잡는 동안 메트로놈 무음
        x2 = round(zoom._sec_to_x(5.3))           # 끝선을 5.3초 자리로 끌어다 놓기
        QTest.mouseMove(zoom, QPoint(x2, 40))
        QTest.mouseRelease(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x2, 40))
        self.assertEqual(screen._end_bar, 3)       # 5.3초 → 가장 가까운 마디선 6초
        self.assertAlmostEqual(zoom._end, 6.0)
        # 놓으면 끝선이 처음 자리(창 가운데)로 — 창이 6초 기준(1~11초)으로 이동
        self.assertAlmostEqual((zoom._t0, zoom._t1), (1.0, 11.0))
        self.assertAlmostEqual(zoom._sec_to_x(6.0), zoom.width() / 2)
        self.assertAlmostEqual((zoom._wave_t0, zoom._wave_t1), (0.0, 8.0))   # 파형은 곡 전체
        x = round(zoom._sec_to_x(6.0))             # 다시 끌어 더 앞으로(새 창 기준)
        QTest.mousePress(zoom, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
        QTest.mouseMove(zoom, QPoint(round(zoom._sec_to_x(2.2)), 40))
        QTest.mouseRelease(zoom, Qt.MouseButton.LeftButton, pos=QPoint(round(zoom._sec_to_x(2.2)), 40))
        self.assertAlmostEqual(zoom._end, 2.0)
        self.assertAlmostEqual(zoom._t0, 0.0)      # 음원 앞으로는 나가지 않음
        screen._on_end_drag(5.3)
        self.assertEqual(screen.anchor, 0.0)       # 격자는 그대로
        screen._on_end_drag(100)                   # 음원 끝 + 5초(13초)까지만
        self.assertLessEqual(screen._end_time(), 13.0)
        screen._on_end_drag(5.9)
        screen._on_confirm()
        self.assertEqual(tl.chord_end, 6.0)
        self.assertEqual(tl.total_bars(), 3)       # 코드표는 끝 마디까지
        self.assertEqual(tl.bar_times[-1], 8)      # 마디선·곡 길이는 그대로
        self.assertIsNone(tl.segment_at(7.0))      # 끝 이후 코드 없음(재생은 가능)
        self.assertEqual(tl.total_sec(), 8)
        screen._apply_chord(tl.segments[0], "Fmaj7", 0)   # 코드 수정 후에도 끝 유지
        self.assertEqual(tl.total_bars(), 3)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "session.json")
            tl.save_json(path)
            loaded = Timeline.load_json(path)
        self.assertEqual(loaded.chord_end, 6.0)
        screen.set_timeline(loaded)                # 재진입: 끝 핸들 복원
        self.assertEqual(screen._end_bar, 3)

    def test_drag_moves_audio_not_bar_line(self):
        screen, _ = self._screen()                # 0~8초, 마디 2초
        for z in (screen.zoom_l, screen.zoom_r):
            z.resize(400, 96)
        zl = screen.zoom_l
        zl.set_window(-1.0, 9.0)
        x = round(zl._sec_to_x(2.0))              # 2마디선을 잡고 오른쪽으로 80px(2초)
        QTest.mousePress(zl, Qt.MouseButton.LeftButton, pos=QPoint(x, 40))
        QTest.mouseMove(zl, QPoint(x + 80, 40))
        self.assertAlmostEqual(screen.anchor, -2.0)            # 음원이 오른쪽 = 격자는 앞으로
        self.assertAlmostEqual(zl._sec_to_x(screen.beat_at(4)), x, delta=1)   # 선은 제자리
        QTest.mouseMove(zl, QPoint(x - 2000, 40))  # 창 밖 멀리(50초 뒤)까지도 이어서 이동
        self.assertAlmostEqual(screen.anchor, 8.0)              # 1마디는 음원 끝까지만
        self.assertAlmostEqual(zl._sec_to_x(screen.beat_at(4)), x, delta=1)
        QTest.mouseMove(zl, QPoint(x + 5000, 40))
        QTest.mouseRelease(zl, Qt.MouseButton.LeftButton, pos=QPoint(x + 5000, 40))
        self.assertAlmostEqual(screen.anchor - screen.bar_len, -5)   # 예비박은 음원 앞 5초까지
        screen._show_step(2)
        zr = screen.zoom_r
        self.assertAlmostEqual(zr._t1 - zr._t0, zl._t1 - zl._t0)   # 처음 창과 같은 축척
        bar_len, t0 = screen.bar_len, zr._t0
        x = round(zr._sec_to_x(screen.beat_at(4 * 4)))
        QTest.mousePress(zr, Qt.MouseButton.LeftButton, pos=QPoint(x - 30, 40))
        QTest.mouseMove(zr, QPoint(x - 60, 40))   # 2단계 마디선은 선이 마우스를 따라감
        QTest.mouseMove(zr, QPoint(-5000, 40))
        QTest.mouseRelease(zr, Qt.MouseButton.LeftButton, pos=QPoint(-5000, 40))
        self.assertGreater(screen.bar_len, bar_len * 0.5)         # 창 시작에서 멈춤(간격 폭주 없음)
        self.assertAlmostEqual(zr._t0, t0)                        # 창은 그대로

    def test_step2_end_drag_keeps_start_and_changes_bpm(self):
        screen, _ = self._screen()
        screen._show_step(2)
        screen.anchor = 0.5
        screen._on_stretch(4, 8.9)           # 마디 4선 8.5 → 8.9: 114.3 BPM
        self.assertAlmostEqual(screen.anchor, 0.5)
        self.assertAlmostEqual(screen.bar_len, 2.1)
        self.assertEqual(screen.bpm_edit.text(), "114.3")
        screen._on_stretch(0, 3.0)           # 시작선은 BPM 드래그 대상 아님
        self.assertAlmostEqual(screen.bar_len, 2.1)

    def test_auto_bpm_display_keeps_detected_grid(self):
        screen, _ = self._screen()
        tl = build_dummy_timeline()            # 표시는 소수 첫째 자리, 검출 비트 격자 자체는 그대로
        tl.beat_times = [0.4 + (60 / 131.48) * i for i in range(40)]
        tl.bar_times = [0.4, 20.0]
        tl.chord_spans = [[0, 20, "C"]]
        screen.set_timeline(tl)
        self.assertIn("131.5", screen.auto_bpm_lbl.text())
        self.assertEqual(screen.bpm_edit.text(), "131.5")
        self.assertAlmostEqual(60 / screen.beat_len, 131.48, 2)
        screen.bpm_edit.editingFinished.emit()   # 표시값 그대로 → 격자 유지
        self.assertIsNotNone(screen._lattice)

    def test_count_in_steps_and_limit(self):
        screen, tl = self._screen()
        screen._show_step(3)
        self.assertEqual(screen.count_in, 1)
        screen.count_plus.click()
        self.assertEqual(screen.count_in, 2)
        self.assertAlmostEqual(screen.zoom_l._t0, -4.0)
        for _ in range(10):
            screen.count_plus.click()
        self.assertEqual(screen.count_in, 2)               # 0 − 2×2 = −4초(음원 앞 5초 한계)
        self.assertFalse(screen.count_plus.isEnabled())
        for _ in range(10):
            screen.count_minus.click()
        self.assertEqual(screen.count_in, 1)               # 최소 1마디
        self.assertFalse(screen.count_minus.isEnabled())
        screen.count_plus.click()
        # 이전 단계(1) UI를 누르면 1단계로 돌아가고 아랫단계는 다시 비활성(값은 유지)
        screen.show()
        QTest.mouseClick(screen.zoom_l, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(screen.zoom_l._sec_to_x(0.0)), 40))
        self.assertEqual(screen._step, 1)
        screen.anchor = 0.0                    # 클릭이 1마디를 옮긴 만큼 되돌림
        self.assertFalse(screen.sections[1].isEnabled() or screen.sections[2].isEnabled())
        self.assertEqual(screen.count_in, 2)
        screen._show_step(3)
        screen.pause()
        screen._on_confirm()
        self.assertEqual(tl.count_in_bars, 2)
        self.assertAlmostEqual(tl.count_in_start(), -4.0)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "session.json")
            tl.save_json(path)
            self.assertEqual(Timeline.load_json(path).count_in_bars, 2)
        screen.set_timeline(tl)
        self.assertEqual(screen.count_in, 2)

    def test_metronome_schedules_each_beat_once(self):
        screen, _ = self._screen()
        screen.playhead.is_playing = lambda: True
        clicks = []
        screen._schedule_click = lambda delay, strong: clicks.append(strong)
        screen._metro_next = 0                # _play_from(0.0)과 같은 상태
        # 오디오 위치가 ~90ms 계단으로 갱신·되돌아가도 박마다 한 번만
        for est in (0.0, 0.03, 0.03, 0.09, 0.47, 0.46, 0.5, 0.52, 0.55, 0.98, 1.0, 1.02):
            screen._metronome(est)
        self.assertEqual(clicks, [True, False, False])    # 0초 강박, 0.5·1.0초 약박
        screen._metronome(5.1)                # 큰 점프 → 다음 박부터 다시(밀린 박 몰아치기 없음)
        self.assertEqual(len(clicks), 3)
        screen._metronome(5.97)
        self.assertEqual(clicks[3:], [True])              # 6.0초 = 4마디 강박

    def test_clock_smoothing_interpolates_and_caps(self):
        screen, _ = self._screen()
        screen.playhead.is_playing = lambda: True
        self.assertEqual(screen._smooth(1.0), 1.0)
        QTest.qWait(50)
        self.assertTrue(1.03 < screen._smooth(1.0) <= 1.12)
        QTest.qWait(150)
        self.assertAlmostEqual(screen._smooth(1.0), 1.12)  # 멈춘 위치에서 앞서가지 않음

    def test_entry_aligns_bar_one_to_detected_beats(self):
        tl = build_dummy_timeline()
        tl.bpm = 137.9                         # 분석 BPM이 비트 간격의 두 배로 추정된 경우
        tl.bar_times = [0.884, 4.36, 7.84, 11.32]
        tl.beat_times = [0.82 + 0.87 * i for i in range(14)]
        tl.chord_spans = [[0, 11.32, "C"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        self.assertAlmostEqual(screen.anchor, 0.82)          # 가장 가까운 검출 비트(회귀선 위)
        self.assertAlmostEqual(screen.beat_len, 0.87)
        self.assertEqual(screen.bpm_edit.text(), f"{60 / 0.87:.1f}")
        self.assertIn(f"{60 / 0.87:.1f}", screen.auto_bpm_lbl.text())
        self.assertTrue(screen.bpm_edit.isVisibleTo(screen))   # 1단계에서도 BPM 입력
        screen._on_confirm()                                  # 정렬된 격자로 재격자화
        self.assertAlmostEqual(tl.bar_times[0], 0.82)
        self.assertTrue(tl.grid_confirmed)
        screen._on_drag(0, 1.0)
        screen._on_confirm()
        screen.set_timeline(tl)                               # 확정 후 재진입: 사용자 격자 유지
        self.assertAlmostEqual(screen.anchor, 1.0)

    def test_entry_grid_follows_quantized_beats_to_song_end(self):
        tl = build_dummy_timeline()
        true_len = 60 / 104                    # 0.5769… — 10ms 반올림 간격 중앙값은 0.58
        tl.beat_times = [round(0.82 + true_len * i, 2) for i in range(350)]
        del tl.beat_times[100]                 # 놓친 박 하나
        tl.bpm = 104.0
        tl.bar_times = [0.884, 0.884 + 4 * true_len]
        tl.chord_spans = [[0, 200, "C"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        self.assertAlmostEqual(screen.beat_len, true_len, 4)
        last = tl.beat_times[-1]               # 곡 끝에서도 격자가 검출 비트에 붙어 있음
        grid = screen.anchor + round((last - screen.anchor) / screen.beat_len) * screen.beat_len
        self.assertLess(abs(grid - last), 0.02)
        precise = screen.beat_len
        screen.bpm_edit.editingFinished.emit()  # 포커스 이동 — 표시 반올림으로 바뀌면 안 됨
        self.assertEqual(screen.beat_len, precise)
        screen._on_confirm()
        self.assertAlmostEqual(tl.beat_sec(), precise, 9)   # 확정 후에도 반올림 없음

    def test_metronome_silent_while_dragging(self):
        screen, _ = self._screen()
        screen.playhead.is_playing = lambda: True
        clicks = []
        screen._schedule_click = lambda delay, strong: clicks.append(strong)
        screen.zoom_l._drag_k, screen.zoom_l._moved = 0, True
        for est in (0.0, 0.5, 1.0):
            screen._metronome(est)
        self.assertEqual(clicks, [])
        screen.zoom_l._drag_k = None           # 놓으면 다음 박부터 다시
        screen._metronome(1.47)
        self.assertEqual(clicks, [False])

    def test_vertical_steps_enter_backspace_and_dimming(self):
        screen, _ = self._screen()
        screen.show()
        self.app.processEvents()
        win = screen.windowHandle()
        en = lambda: [sec.isEnabled() for sec in screen.sections]
        self.assertEqual((screen._step, en()), (1, [True, False, False]))
        self.assertTrue(all(sec.isVisible() for sec in screen.sections))   # 한 화면에 모두
        QTest.keyClick(win, Qt.Key.Key_Return)
        self.assertEqual((screen._step, en()), (2, [True, True, False]))
        QTest.keyClick(win, Qt.Key.Key_Enter)
        self.assertEqual((screen._step, en()), (3, [True, True, True]))
        self.assertTrue(screen.confirm_btn.isVisible() and not screen.next_btn.isVisible())
        QTest.keyClick(win, Qt.Key.Key_Backspace)
        self.assertEqual((screen._step, en()), (2, [True, True, False]))
        screen.bpm_edit.setFocus()                 # BPM 칸 안의 Backspace는 글자 지우기
        screen.bpm_edit.setText("120.0")
        screen.bpm_edit.end(False)
        QTest.keyClick(win, Qt.Key.Key_Backspace)
        self.assertEqual(screen.bpm_edit.text(), "120.")
        screen.bpm_edit.setText("120.0")
        screen.zoom_l.setFocus()
        QTest.keyClick(win, Qt.Key.Key_Return)
        QTest.keyClick(win, Qt.Key.Key_Return)     # 3단계에서 Enter = 확인 → 코드 편집
        self.assertTrue(screen._locked)
        screen.close()

    def test_tempo_row_on_top_reset_and_bpm_enter_releases_cursor(self):
        tl = build_dummy_timeline()
        tl.beat_times = [0.3 + 0.5 * i for i in range(30)]
        tl.bar_times = [0.3, 15.0]
        tl.chord_spans = [[0, 15, "C"]]
        screen = BeatScreen()
        screen.set_timeline(tl)
        screen.show()
        self.app.processEvents()
        win = screen.windowHandle()
        self.assertNotIn(screen.tempo_row, [w for sec in screen.sections
                                             for w in sec.findChildren(QWidget)])
        self.assertTrue(screen.tempo_row.isEnabled())          # 단계와 무관하게 활성
        # BPM 입력 후 Enter → 적용, 커서 해제, 단계는 그대로 → 스페이스는 재생
        screen.bpm_edit.setFocus()
        screen.bpm_edit.selectAll()
        QTest.keyClicks(screen.bpm_edit, "100")
        QTest.keyClick(win, Qt.Key.Key_Return)
        self.assertEqual((screen.bpm_edit.text(), screen._step), ("100.0", 1))
        self.assertFalse(screen.bpm_edit.hasFocus())
        self.assertIsNone(screen._lattice)                     # BPM 지정 → 균등 격자
        QTest.keyClick(win, Qt.Key.Key_Space)
        self.assertEqual(screen.bpm_edit.text(), "100.0")      # 칸에 입력되지 않음
        self.assertTrue(screen.playhead.is_playing())
        screen.pause()
        QTest.mouseClick(screen.bpm_edit, Qt.MouseButton.LeftButton)
        self.assertTrue(screen.bpm_edit.hasFocus())            # 다시 누르면 커서
        # 자동추정값 초기화 → 검출 비트 격자·BPM·박자로
        screen.sig_box.setCurrentIndex(screen.sig_box.findData("3/4"))
        screen.reset_btn.click()
        self.assertIsNotNone(screen._lattice)
        self.assertEqual(screen.bpm_edit.text(), "120.0")
        self.assertEqual(screen.sig_box.currentData(), tl.time_sig)
        self.assertIn(round(screen.anchor, 6), [round(t, 6) for t in screen.zoom_l._ghost])
        screen.close()

    def test_virtual_preroll_pause_and_resume(self):
        head = Playhead(2)
        head.seek(-0.2)
        self.assertEqual(head.position_sec(), -0.2)
        head.play()
        QTest.qWait(50)
        head.pause()
        paused = head.position_sec()
        self.assertTrue(-0.2 < paused < 0)
        QTest.qWait(30)
        self.assertEqual(head.position_sec(), paused)
        head.play()
        QTest.qWait(250)
        self.assertGreater(head.position_sec(), 0)
        head.pause()

    def test_audio_waits_for_zero(self):
        head = Playhead(2)
        head._use_audio = True
        head._player = Mock()
        head._player.position.return_value = 0
        head.seek(-0.08)
        self.assertEqual(head.position_sec(), -0.08)
        head.play()
        self.assertFalse(head._player.play.called)
        QTest.qWait(150)
        self.assertTrue(head._player.play.called)
        self.assertGreaterEqual(head._player.setPosition.call_args.args[0], 0)
        head.pause()

    def test_real_audio_preroll(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "audio.wav")
            with wave.open(path, "wb") as wav:
                wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 16000)
            head = Playhead(2, path)
            self.assertTrue(head._use_audio)
            head._audio_out.setVolume(0)
            QTest.qWait(300)
            head.seek(-0.2)
            head.play()
            QTest.qWait(60)
            self.assertLess(head.position_sec(), 0)
            QTest.qWait(400)
            self.assertGreater(head.position_sec(), 0)
            head.stop()
            head._player.setSource(QUrl())


if __name__ == "__main__":
    unittest.main()
