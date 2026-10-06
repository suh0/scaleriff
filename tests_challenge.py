"""도전 선택·시작·포기와 재생 위치 잠금 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    screen = MainScreen()
    screen.set_timeline(build_dummy_timeline())
    screen.resize(1040, 740)
    screen.show()
    app.processEvents()
    assert screen.challenge_btn.text() == "자유연습" and not screen._challenge_active
    assert len(screen._difficulty_actions) == 3
    screen._on_seek(3.0)
    for mode in ("riff", "free", "riff", "free"):
        screen._mode_actions[mode].trigger()
        assert screen.playhead.position_sec() == 3.0, "연습 간 전환은 위치 유지"
        assert screen.lane.isEnabled() and screen.scrub.isEnabled()
        assert screen.loop_btn.isVisible()
        assert screen.riff.isVisible() == (mode == "riff")
        assert screen.challenge_btn.text() == ("리프연습" if mode == "riff" else "자유연습")
    screen.playhead.play()
    screen._mode_actions["riff"].trigger()
    assert screen.playhead.is_playing() and screen.playhead.position_sec() >= 3.0
    screen.pause()
    screen.tl.loops = [{"name": "test", "start_bar": 0, "end_bar": 0, "on": True}]
    for action in [*screen._difficulty_actions, screen._mode_actions["riff_challenge"]]:
        screen._mode_actions["free"].trigger()
        screen._on_seek(3.0)
        screen.loop_btn.click()
        assert screen.loop_panel.isVisible()
        screen.playhead.play()
        action.trigger()
        selected_mode, level = screen._selected_mode, screen._difficulty
        mode_text = screen.challenge_btn.text()
        assert not screen.loop_btn.isVisible() and not screen.loop_panel.isVisible()
        assert screen._loop_spans() == [], "도전에는 기존 루프도 적용하지 않음"
        assert screen.playhead.position_sec() == 0
        assert not screen.playhead.is_playing()
        assert screen.lane._pos == screen.scrub._pos == 0
        assert screen.play_btn.text() == "도전"
        assert screen.challenge_btn.isEnabled(), "도전 대기 중 모드 선택 가능"
        assert not screen.lane.isEnabled() and not screen.scrub.isEnabled()
        for bar in (screen.lane, screen.scrub):
            QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                             pos=QPoint(bar.width() - 5, bar.height() // 2))
            bar.seekRequested.emit(5.0)
        assert screen.playhead.position_sec() == 0, "클릭/seek 신호 잠금"
        screen.play_btn.click()
        assert screen.playhead.is_playing() and screen.play_btn.text() == "포기"
        assert not screen.challenge_btn.isEnabled(), "도전 중 모드 선택 잠금"
        QTest.mouseClick(screen.challenge_btn, Qt.MouseButton.LeftButton)
        assert not screen.challenge_menu.isVisible(), "잠긴 버튼은 메뉴를 열지 않음"
        screen.play_btn.click()
        assert not screen.playhead.is_playing() and screen.play_btn.text() == "도전"
        assert screen.challenge_btn.isEnabled(), "포기 후 모드 선택 잠금 해제"
        assert screen.playhead.position_sec() == 0
        assert screen._selected_mode == selected_mode and screen._difficulty == level
        assert screen.challenge_btn.text() == mode_text
        assert not screen.lane.isEnabled() and not screen.scrub.isEnabled()
        assert not screen.loop_btn.isVisible()
        assert screen.riff.isVisible() == (selected_mode == "riff_challenge")
        screen.play_btn.click()
        assert screen.playhead.is_playing() and screen.playhead.position_sec() < 0.1
        screen.play_btn.click()
        screen._mode_actions["free"].trigger()
        assert screen.lane.isEnabled() and screen.scrub.isEnabled()
        assert screen.piano._split == 0 and screen.riff.isHidden()
        screen._on_seek(2.0)
        assert screen.playhead.position_sec() == 2.0
    screen._mode_actions["riff_challenge"].trigger()
    screen.play_btn.click()
    screen.playhead.seek(screen.playhead.total_sec())
    screen.playhead.pause()
    assert screen.play_btn.text() == "도전", "곡 종료 후 재도전 가능"
    assert screen.challenge_btn.isEnabled(), "곡 종료 후 모드 선택 잠금 해제"
    screen.play_btn.click()
    assert screen.playhead.position_sec() < 0.1, "재도전은 0초부터 시작"
    screen.set_timeline(build_dummy_timeline())
    assert not screen._challenge_active and screen.play_btn.text() == "▶"
    assert screen.lane.isEnabled() and screen.scrub.isEnabled()
    assert screen.challenge_btn.text() == "자유연습" and screen.loop_btn.isVisible()
    for width, height in ((1040, 740), (1600, 1000)):
        screen.resize(width, height)
        screen._mode_actions["free"].trigger()
        app.processEvents()
        piano_rect = screen.piano.geometry()
        key_geometry = screen.piano._geometry()[1:]
        for mode, level in (("riff", 0), ("scale_challenge", 1), ("riff_challenge", 0), ("free", 0)):
            screen._select_practice(mode, level)
            app.processEvents()
            assert screen.piano.geometry() == piano_rect, "모드 전환으로 건반 영역 변경"
            assert screen.piano._geometry()[1:] == key_geometry, "모드별 건반 크기 변경"
            assert screen.scrub.geometry().top() > piano_rect.bottom()
            button_bottom = screen.play_btn.mapTo(screen, QPoint(0, screen.play_btn.height())).y()
            assert screen.height() - button_bottom < 40, "재생 버튼이 창 하단에서 멀리 떨어짐"
    screen.close()
    print("CHALLENGE OK")


if __name__ == "__main__":
    main()
