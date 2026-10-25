"""같은 링크의 저장된 세션 재사용 및 손상·누락 시 재분석 검증."""
import os
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication

from gui.app import AppWindow
from ingest.audio_source import _cache_key
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        with patch("gui.app._CACHE_DIR", directory), \
                patch.object(AppWindow, "_try_start_midi"), \
                patch("player.playhead._HAS_MULTIMEDIA", False):
            win = AppWindow()
            win._settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
            win.link_screen.set_save_dir(directory)
            url = "https://www.youtube.com/watch?v=cache-test"
            audio = Path(directory) / f"dl_{_cache_key(url)}.wav"
            with wave.open(str(audio), "wb") as wav:
                wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 22050)
            tl = build_dummy_timeline()
            tl.audio_ref = str(audio)
            tl.bpm = 137.0
            win._on_timeline_ready(tl)
            saved = tl.to_dict()
            session = Path(win._session_path(tl))
            assert session.exists()

            with patch.object(win.analyzing, "start") as start:
                win._start_build(url)
                assert not start.called, "저장된 링크를 재분석함"
                assert win._timeline.to_dict() == saved, "저장된 수정 내용이 달라짐"
                assert win.stack.currentWidget() is win.beat

            # 중단 가능한 분석이 보관한 작업별 폴더에서도 세션을 재사용.
            nested = Path(directory) / "analysis_saved"
            nested.mkdir()
            audio = audio.rename(nested / audio.name)
            tl.audio_ref = str(audio)
            win._on_timeline_ready(tl)
            saved = tl.to_dict()
            session = Path(win._session_path(tl))
            with patch.object(win.analyzing, "start") as start:
                win._start_build(url)
                assert not start.called, "작업별 폴더의 저장된 링크를 재분석함"
                assert win._timeline.to_dict() == saved

            win._bg_wait = True
            with patch.object(win, "_load_link_cache", side_effect=AssertionError("대기 중 조회")):
                win._start_build(url)
            win._bg_wait = False

            with patch.object(win.analyzing, "start") as start:
                win._start_build(url + "-new")
                assert start.call_count == 1, "새 링크의 분석을 시작하지 않음"

            session.write_text("{broken", encoding="utf-8")
            with patch.object(win.analyzing, "start") as start:
                win._start_build(url)
                assert start.call_count == 1, "손상된 세션에서 재분석하지 않음"

            tl.save_json(str(session))
            audio.unlink()
            with patch.object(win.analyzing, "start") as start:
                win._start_build(url)
                assert start.call_count == 1, "오디오가 없는데 분석을 시작하지 않음"
            win.close()
            app.processEvents()
    print("LINK CACHE OK")


if __name__ == "__main__":
    main()
