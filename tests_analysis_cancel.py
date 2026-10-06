"""분석 중단: 실제 자식 프로세스 종료, 파일 정리, 재시작 검증."""
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from gui.analyzing_screen import AnalyzingScreen


def blocking_build(source, cb):
    from ingest import audio_source
    directory = Path(audio_source._CACHE_DIR)
    child = subprocess.Popen([sys.executable, "-c",
        "import sys,time; f=open(sys.argv[1], 'wb'); f.write(b'partial'); "
        "f.flush(); time.sleep(120)", str(directory / "download.part")])
    while not (directory / "download.part").exists():
        time.sleep(0.01)
    (directory / "child.pid").write_text(str(child.pid))
    cb(38, "변환 중")
    while True:
        time.sleep(0.05)


def successful_build(source, cb):
    from ingest.audio_source import resolve_audio
    from player.dummy_timeline import build_dummy_timeline
    wav, audio, title = resolve_audio(source, cb)
    Path(wav).parent.joinpath("unused.part").write_bytes(b"partial")
    tl = build_dummy_timeline()
    tl.wav_ref, tl.audio_ref, tl.title = wav, audio, title
    return tl


def failed_build(source, cb):
    from ingest import audio_source
    Path(audio_source._CACHE_DIR, "partial.wav").write_bytes(b"partial")
    raise ValueError("test failure")


def wait_until(app, predicate, timeout=15):
    end = time.monotonic() + timeout
    while not predicate():
        app.processEvents()
        assert time.monotonic() < end, "작업 대기 시간 초과"
        time.sleep(0.01)
    app.processEvents()


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        try:
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main():
    app = QApplication([])
    screen = AnalyzingScreen()
    assert hasattr(screen, "cancel_btn"), "분석중단하기 버튼 없음"
    cancelled, ready, errors = [], [], []
    screen.analysisCancelled.connect(lambda: cancelled.append(True))
    screen.timelineReady.connect(ready.append)
    screen.analysisFailed.connect(lambda: errors.append(screen.msg.toolTip()))
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory, "original.wav")
        with wave.open(str(source), "wb") as wav:
            wav.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 22050)
        original = source.read_bytes()
        screen.show()
        screen.start(blocking_build, str(source))
        wait_until(app, lambda: screen.msg.text() == "변환 중")
        worker = screen._worker
        work_dir = Path(worker.work_dir)
        pid = int((work_dir / "child.pid").read_text())
        assert process_alive(pid)
        screen.cancel_btn.click()
        screen.cancel_btn.click()  # 중복 클릭도 안전
        wait_until(app, lambda: bool(cancelled))
        assert not worker.isRunning() and not process_alive(pid)
        assert not work_dir.exists(), "중단한 분석 파일이 남음"
        assert source.read_bytes() == original and not ready and not errors

        screen.start(successful_build, str(source))
        wait_until(app, lambda: bool(ready))
        tl = ready[0]
        assert Path(tl.wav_ref).is_file() and tl.audio_ref == str(source)
        assert not Path(tl.wav_ref).parent.joinpath("unused.part").exists()
        assert source.read_bytes() == original
        import shutil
        shutil.rmtree(Path(tl.wav_ref).parent)

        # 완료 통지가 UI에 도착하기 직전의 중단도 결과를 저장하지 않는다.
        screen.start(successful_build, str(source))
        late_worker = screen._worker
        assert late_worker.wait(15000)
        screen.cancel()
        wait_until(app, lambda: len(cancelled) == 2)
        assert len(ready) == 1 and not Path(late_worker.work_dir).exists()

        screen.start(blocking_build, str(source))
        early_dir = Path(screen._worker.work_dir)
        screen.cancel()
        wait_until(app, lambda: len(cancelled) == 3)
        assert not early_dir.exists()

        screen.start(failed_build, str(source))
        failed_dir = Path(screen._worker.work_dir)
        wait_until(app, lambda: bool(errors))
        assert not failed_dir.exists() and "test failure" in screen.msg.text()

        screen.start(blocking_build, str(source))
        wait_until(app, lambda: screen.msg.text() == "변환 중")
        closing_dir = Path(screen._worker.work_dir)
        closing_pid = int((closing_dir / "child.pid").read_text())
        screen.shutdown()
        assert not closing_dir.exists() and not process_alive(closing_pid)
        app.processEvents()
        # 합성 오디오를 실제 변환 → MIR → 구조/화성 → Timeline까지 실행.
        import numpy as np
        import soundfile as sf
        from tests_mir import synth_chord
        from build.timeline_builder import build_timeline
        samples = np.concatenate([synth_chord(notes, 2.4) for notes in
                                  ([60, 64, 67], [57, 60, 64],
                                   [53, 57, 60], [55, 59, 62]) * 2])
        sf.write(str(source), samples, 22050)
        screen.start(build_timeline, str(source))
        wait_until(app, lambda: len(ready) == 2 or len(errors) > 1, timeout=90)
        assert len(errors) == 1, errors
        assert ready[-1].segments and ready[-1].beat_times
        assert Path(ready[-1].wav_ref).is_file()
        shutil.rmtree(Path(ready[-1].wav_ref).parent)

        from PyQt6.QtCore import QSettings
        from gui.app import AppWindow
        with patch.object(AppWindow, "_try_start_midi"), \
                patch("player.playhead._HAS_MULTIMEDIA", False):
            win = AppWindow()
            win._settings = QSettings(str(Path(directory, "settings.ini")),
                                      QSettings.Format.IniFormat)
            win.show()
            win.stack.setCurrentWidget(win.analyzing)
            win.analyzing.start(blocking_build, str(source))
            wait_until(app, lambda: win.analyzing.msg.text() == "변환 중")
            win.analyzing.cancel_btn.click()
            wait_until(app, lambda: win.stack.currentWidget() is win.link_screen)
            assert not win._bg_wait and win.link_screen.url_edit.isEnabled()
            assert not list(Path(directory).glob("*.json"))

            # 실제 창 닫기 경로에서도 백그라운드 분석과 파일을 정리한다.
            win.analyzing.start(blocking_build, str(source))
            wait_until(app, lambda: win.analyzing.msg.text() == "변환 중")
            close_dir = Path(win.analyzing._worker.work_dir)
            close_pid = int((close_dir / "child.pid").read_text())
            win.close()
            app.processEvents()
            assert not close_dir.exists() and not process_alive(close_pid)

    screen.close()
    print("ANALYSIS CANCEL OK")


if __name__ == "__main__":
    main()
