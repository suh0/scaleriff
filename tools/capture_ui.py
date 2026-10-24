"""더미 세션으로 전 화면 PNG 생성. 사용자 설정·미디어·MIDI를 변경하지 않는다."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt6.QtCore import QSettings
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow
from player.dummy_timeline import build_dummy_timeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="cache/ui_ux/after")
    parser.add_argument("--sizes", default="1040x740,1280x800,1600x1000")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    records = []
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.Format.IniFormat)
        settings.setValue("save_dir", str(Path(directory) / "sessions"))
        with patch("gui.app.QSettings", return_value=settings), patch.object(AppWindow, "_try_start_midi"):
            win = AppWindow()
        win.main_screen.note_player.set_volume(0)
        tl = build_dummy_timeline()
        win._open_timeline(tl)
        win.score.set_timeline(tl, win.main_screen._ml_model)
        win.main_screen.set_timeline(tl)
        win.show()

        def capture(name, page):
            win.stack.setCurrentWidget(page)
            app.processEvents()
            QTest.qWait(650)
            page.grab().save(str(output / f"{name}_{width}.png"))
            records.append(f"| [{name}_{width}.png]({name}_{width}.png) | {width}×{height} | {page.width()}×{page.height()} |")

        for dimensions in args.sizes.split(","):
            width, height = map(int, dimensions.split("x"))
            win.resize(width, height)
            win.link_screen.stack.setCurrentIndex(0)
            capture("onboarding", win.link_screen)
            win.link_screen.stack.setCurrentIndex(1)
            # 표시 fixture만 바꾸고 실제 저장 목적지는 임시 폴더로 유지한다.
            win.link_screen.save_label.setText(r"최근 저장경로: C:\Music\ScaleRiff\sessions")
            capture("link", win.link_screen)
            win.analyzing.title.setText("분석 중…")
            win.analyzing.err_btn.hide()
            win.analyzing.bg_btn.show()
            win.analyzing.cancel_btn.show()
            win.analyzing._on_progress(55, "박자와 코드 진행을 확인하고 있어요")
            capture("analyzing", win.analyzing)
            win.analyzing._on_failed("오디오를 열지 못했어요. 링크나 파일 경로를 확인해 주세요.")
            capture("analysis_error", win.analyzing)
            win.beat._set_locked(False)
            capture("beat", win.beat)
            win.beat._set_locked(True)
            capture("chords", win.beat)
            capture("riffs", win.score)
            win.main_screen._select_practice("free")
            win.main_screen._render_at(1)
            capture("play", win.main_screen)
            win.main_screen.lesson_combo.setCurrentIndex(win.main_screen.lesson_combo.findData("copy"))
            win.main_screen._render_at(1)
            capture("copy", win.main_screen)
            win.main_screen.loop_btn.setChecked(True)
            win.main_screen._toggle_loop_panel()
            capture("loops", win.main_screen)
            win.main_screen.loop_btn.setChecked(False)
            win.main_screen._toggle_loop_panel()

            def capture_dialog(dialog):
                dialog.show()
                app.processEvents()
                dialog.grab().save(str(output / f"settings_{width}.png"))
                dialog.close()
            with patch("gui.main_screen.QDialog.exec", capture_dialog):
                win.main_screen._show_settings()
        win.close()
    (output / "README.md").write_text(
        "# UI 렌더 기록\n\n더미 데이터, offscreen 렌더. 요청 창 크기와 실제 페이지 크기를 구분한다.\n\n"
        "| 화면 | 요청 창 크기 | 실제 페이지 크기 |\n|---|---|---|\n" + "\n".join(records) + "\n", encoding="utf-8")
    print(f"UI CAPTURE OK: {output.resolve()}")


if __name__ == "__main__":
    main()
