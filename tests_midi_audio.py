"""MIDI 이벤트·신스 음길이·느린 재생의 원본 시간축 회귀."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mido
import numpy as np
import soundfile as sf

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QAudioBufferOutput, QMediaPlayer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from player.midi_input import MidiInput
from player.note_synth import RELEASE_SEC, NotePlayer
from player.playhead import Playhead


RELEASE_MS = round(RELEASE_SEC * 1000) + 80


class FakePort:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.closed = False
        self.after_poll = lambda: None

    def iter_pending(self):
        pending, self.messages = self.messages, []
        self.after_poll()
        return iter(pending)

    def close(self):
        self.closed = True


class FakeEffect:
    class Status:
        Error = "error"
        Ready = "ready"

    def __init__(self, parent):
        self.statusChanged = SimpleNamespace(connect=lambda callback: None)
        self.playing = False
        self.level = 0.0

    def setSource(self, source):
        self.source_url = source

    def setVolume(self, value):
        self.level = value

    def status(self):
        return self.Status.Ready

    def play(self):
        self.playing = True

    def stop(self):
        self.playing = False


class MidiAudioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_midi_preserves_velocity_channel_release_and_pedal(self):
        self.assertTrue(hasattr(MidiInput, "note_event"), "full MIDI events missing")
        port = FakePort([
            mido.Message("note_on", note=64, velocity=37, channel=2),
            mido.Message("note_on", note=64, velocity=0, channel=2),
            mido.Message("note_off", note=65, velocity=23, channel=3),
            mido.Message("control_change", control=64, value=127, channel=2),
            mido.Message("control_change", control=64, value=0, channel=2),
            mido.Message("control_change", control=1, value=99, channel=2),
        ])
        source = MidiInput()
        events, legacy = [], []
        source.note_event.connect(events.append)
        source.note_received.connect(lambda pitch, on: legacy.append((pitch, on)))
        with patch("player.midi_input.mido.get_input_names", return_value=["Piano"]), \
                patch("player.midi_input.mido.open_input", return_value=port):
            self.assertTrue(source.open_port("Piano"))
        port.after_poll = lambda: setattr(source, "_running", False)
        before = time.monotonic()
        source.run()
        after = time.monotonic()
        self.assertEqual(legacy, [(64, True), (64, False), (65, False)])
        self.assertEqual(len(events), 5)
        self.assertEqual([(e["pitch"], e["is_on"], e["velocity"], e["channel"])
                          for e in events[:3]],
                         [(64, True, 37, 2), (64, False, 0, 2), (65, False, 23, 3)])
        self.assertEqual([(e["type"], e["down"], e["channel"]) for e in events[3:]],
                         [("pedal", True, 2), ("pedal", False, 2)])
        self.assertTrue(all(before <= e["received_time"] <= after for e in events))
        self.assertTrue(port.closed)

    def test_midi_reconnect_closes_previous_port_and_invalid_choice_is_safe(self):
        self.assertTrue(callable(getattr(MidiInput, "open_port", None)), "port selection missing")
        first, second = FakePort(), FakePort()
        source = MidiInput()
        with patch("player.midi_input.mido.get_input_names", return_value=["A", "B"]), \
                patch("player.midi_input.mido.open_input", side_effect=[first, second]):
            self.assertTrue(source.open_first_available())
            self.assertEqual(source.port_name, "A")
            self.assertTrue(source.open_port("B"))
            self.assertTrue(first.closed)
            self.assertEqual(source.port_name, "B")
            source.stop()
            self.assertTrue(second.closed)
            self.assertFalse(source.open_port("missing"))
            self.assertEqual(source.port_name, "")

    def test_disconnect_during_poll_is_reported_without_worker_exception(self):
        self.assertTrue(hasattr(MidiInput, "errorOccurred"), "disconnect errors missing")
        source = MidiInput()
        port = FakePort()
        port.iter_pending = lambda: (_ for _ in ()).throw(OSError("disconnected"))
        failures = []
        source.errorOccurred.connect(failures.append)
        with patch("player.midi_input.mido.get_input_names", return_value=["A"]), \
                patch("player.midi_input.mido.open_input", return_value=port):
            source.open_port("A")
        source.run()
        self.assertTrue(failures)
        self.assertTrue(port.closed)
        self.assertEqual(source.port_name, "")

    def test_reconnect_notification_cannot_be_overwritten_by_old_worker_close(self):
        first, second = FakePort(), FakePort()
        source = MidiInput()
        connections = []
        source.connectionChanged.connect(connections.append)
        try:
            with patch("player.midi_input.mido.get_input_names", return_value=["A", "B"]), \
                    patch("player.midi_input.mido.open_input", side_effect=[first, second]):
                source.open_port("A")
                source.start()
                QTest.qWait(20)
                self.assertTrue(source.open_port("B"))
                QTest.qWait(30)
                self.assertEqual(source.port_name, "B")
                self.assertEqual(connections[-1], "B")
        finally:
            source.stop()

    def test_note_off_pedal_velocity_channel_and_stop_all(self):
        self.assertTrue(callable(getattr(NotePlayer, "note_on", None)), "note lifecycle missing")
        with patch("player.note_synth.QSoundEffect", FakeEffect):
            synth = NotePlayer(prewarm=())
            synth.set_volume(0.8)
            synth.note_on(60, velocity=32, channel=0)
            quiet = synth._effect(60, 0)
            synth.note_on(60, velocity=127, channel=1)
            loud = synth._effect(60, 1)
            self.assertLess(quiet.level, loud.level)
            self.assertAlmostEqual(loud.level, 0.8)
            synth.set_pedal(True, channel=0)
            synth.note_off(60, channel=0)
            self.assertTrue(quiet.playing)
            synth.note_off(60, channel=1)
            self.assertTrue(loud.playing)          # 즉시 끊지 않고 페이드
            self.assertLess(loud.level, 0.8)
            QTest.qWait(RELEASE_MS)
            self.assertFalse(loud.playing)
            self.assertEqual(loud.level, 0.0)
            synth.set_pedal(False, channel=0)
            QTest.qWait(RELEASE_MS)
            self.assertFalse(quiet.playing)
            synth.note_on(62, velocity=127)
            synth.set_volume(0.3)
            self.assertAlmostEqual(synth._effect(62).level, 0.3)
            synth.stop_all()
            QTest.qWait(RELEASE_MS)
            self.assertFalse(synth._effect(62).playing)

    def test_scheduled_note_length_and_old_timer_cannot_stop_repeated_note(self):
        self.assertTrue(callable(getattr(NotePlayer, "note_off", None)), "note duration missing")
        with patch("player.note_synth.QSoundEffect", FakeEffect):
            synth = NotePlayer(prewarm=())
            synth.play_note(60, duration=0.04)
            QTest.qWait(20)
            synth.play_note(60, duration=0.15)
            QTest.qWait(50)
            self.assertTrue(synth._effect(60, 16).playing)
            QTest.qWait(100 + RELEASE_MS)
            self.assertFalse(synth._effect(60, 16).playing)
            synth.play_note(60, duration=0.03)
            synth.stop_all()
            synth.note_on(60, channel=16)
            QTest.qWait(60)
            self.assertTrue(synth._effect(60, 16).playing)
            synth.stop_all()

    def test_user_riff_and_review_same_pitch_have_independent_voices(self):
        with patch("player.note_synth.QSoundEffect", FakeEffect):
            synth = NotePlayer(prewarm=())
            synth.note_on(60, velocity=64, channel=0)
            synth.play_note(60, duration=0.03)
            self.assertTrue(synth._effect(60, 16).playing)
            synth.play_note(60, duration=0.15, channel=17)
            user = synth._effect(60, 0)
            riff = synth._effect(60, 16)
            review = synth._effect(60, 17)
            synth.note_off(60, channel=0)
            QTest.qWait(RELEASE_MS)
            self.assertFalse(user.playing)
            self.assertTrue(review.playing)
            QTest.qWait(10)
            self.assertFalse(riff.playing)
            self.assertTrue(review.playing)
            synth.stop_all()
            QTest.qWait(RELEASE_MS)
            self.assertFalse(review.playing)

    def test_virtual_rate_change_preserves_position_and_preroll_pause(self):
        self.assertTrue(callable(getattr(Playhead, "set_rate", None)), "playback rate missing")
        head = Playhead(3)
        self.assertTrue(head.set_rate(0.75))
        head.seek(-0.3)
        head.play()
        QTest.qWait(100)
        head.pause()
        paused = head.position_sec()
        self.assertAlmostEqual(paused, -0.225, delta=0.035)
        QTest.qWait(40)
        self.assertEqual(head.position_sec(), paused)
        head.play()
        before = head.position_sec()
        head.set_rate(1.5)
        self.assertAlmostEqual(head.position_sec(), before, delta=0.015)
        QTest.qWait(100)
        self.assertAlmostEqual(head.position_sec() - before, 0.15, delta=0.04)
        head.stop()

    def test_missing_audio_does_not_run_virtual_clock(self):
        self.assertTrue(hasattr(Playhead, "errorOccurred"), "media errors missing")
        head = Playhead(2, os.path.join(tempfile.gettempdir(), "scaleriff-missing-audio.wav"))
        errors = []
        head.errorOccurred.connect(errors.append)
        head.play()
        QTest.qWait(80)
        self.assertFalse(head.is_playing())
        self.assertEqual(head.position_sec(), 0.0)
        self.assertTrue(errors)

    def test_real_three_quarter_audio_preserves_pitch_and_source_seconds(self):
        self.assertTrue(callable(getattr(Playhead, "prepare_rate", None)), "pitch-preserving preparation missing")
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "tone.wav")
            rate = 22050
            samples = 0.25 * np.sin(2 * np.pi * 440 * np.arange(rate * 3) / rate)
            sf.write(path, samples, rate)
            head = Playhead(3, path)
            errors = []
            head.errorOccurred.connect(errors.append)
            self.assertTrue(head.prepare_rate(0.75), errors)
            self.assertTrue(head.set_rate(0.75), errors)
            self.assertEqual(head.rate, 0.75)
            head.set_volume(0)
            prepared = head._player.source().toLocalFile()
            self.assertNotEqual(Path(prepared), Path(path))
            audio, sample_rate = sf.read(prepared)
            self.assertAlmostEqual(len(audio) / sample_rate, 4.0, delta=0.08)
            if audio.ndim == 2:
                audio = audio.mean(axis=1)
            middle = audio[sample_rate:sample_rate * 2]
            peaks = np.fft.rfftfreq(len(middle), 1 / sample_rate)
            peak = peaks[np.argmax(abs(np.fft.rfft(middle * np.hanning(len(middle)))))]
            self.assertAlmostEqual(peak, 440, delta=2)
            # 로딩 완료 전 seek도 실제 재생 시작 시 보존되어야 한다.
            head.seek(1.5)
            self.assertAlmostEqual(head.position_sec(), 1.5, delta=0.025)
            head.play()
            deadline = time.monotonic() + 2
            while ((head._pending_seek is not None
                    or head._player.mediaStatus() != QMediaPlayer.MediaStatus.BufferedMedia
                    or head.position_sec() <= 1.52)
                   and time.monotonic() < deadline):
                self.assertGreaterEqual(head.position_sec(), 1.5,
                                        "로딩 뒤 seek가 원점으로 되돌아감")
                QTest.qWait(10)
            self.assertIsNone(head._pending_seek, "실제 음원 seek 완료 시간 초과")
            self.assertEqual(head._player.mediaStatus(), QMediaPlayer.MediaStatus.BufferedMedia)
            started = head.position_sec()
            self.assertGreaterEqual(started, 1.5, "로딩 뒤 seek가 원점으로 되돌아감")
            QTest.qWait(500)
            progressed = head.position_sec()
            self.assertGreater(progressed, 1.65, errors)
            self.assertLess(progressed, 2.05)
            self.assertAlmostEqual(progressed - started, 0.375, delta=0.10)
            head.pause()
            paused = head.position_sec()
            QTest.qWait(80)
            self.assertAlmostEqual(head.position_sec(), paused, delta=0.02)
            head.seek(1.5)
            self.assertAlmostEqual(head._player.position() / 1000, 2.0, delta=0.04)
            head.stop()
            head._player.setSource(QUrl())

    def test_real_ffmpeg_seek_play_burn_in_keeps_decoding_nonzero_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "burn_in.wav")
            sample_rate = 22050
            sf.write(path, 0.2 * np.sin(2 * np.pi * 330 * np.arange(sample_rate * 4) / sample_rate),
                     sample_rate)
            head = Playhead(4, path)
            decoded = []
            errors = []
            head.errorOccurred.connect(errors.append)
            try:
                self.assertTrue(head.set_rate(0.75), errors)
                head.set_volume(0)
                output = QAudioBufferOutput(head)
                head._player.setAudioBufferOutput(output)

                def capture(buffer):
                    if buffer.isValid() and buffer.byteCount():
                        pcm = buffer.constData().asstring(buffer.byteCount())
                        decoded.append((buffer.startTime(), any(pcm)))

                output.audioBufferReceived.connect(capture)
                head.play()
                deadline = time.monotonic() + 2
                while head.position_sec() <= 0.05 and time.monotonic() < deadline:
                    QTest.qWait(10)
                self.assertGreater(head.position_sec(), 0.05, errors)
                for index in range(24):
                    target = (0.15, 0.75, 1.35)[index % 3]
                    received_before = len(decoded)
                    head.pause()
                    if index in (8, 16):
                        previous = head.position_sec()
                        self.assertTrue(head.set_rate(1.0 if index == 8 else 0.75), errors)
                        self.assertAlmostEqual(head.position_sec(), previous, delta=0.015)
                    head.seek(target)
                    head.play()
                    deadline = time.monotonic() + 0.8
                    while ((head.position_sec() <= target + 0.025 or len(decoded) <= received_before)
                           and time.monotonic() < deadline):
                        QTest.qWait(10)
                    self.assertGreater(head.position_sec(), target + 0.025, (index, errors))
                    self.assertLess(head.position_sec(), target + 0.6, index)
                    tail = decoded[received_before:]
                    self.assertTrue(any(nonzero for _, nonzero in tail), (index, tail, errors))
                    media_target_us = target / head.rate * 1_000_000
                    self.assertTrue(any(media_target_us - 150_000 <= start <= media_target_us + 600_000
                                        for start, _ in tail), (index, tail))
                    self.assertTrue(head.is_playing())
                    self.assertEqual(head._player.error(), QMediaPlayer.Error.NoError)
                self.assertFalse(errors)
            finally:
                head.stop()
                head._player.setSource(QUrl())


if __name__ == "__main__":
    unittest.main()
