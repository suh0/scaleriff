"""헤드리스 스모크 테스트 — 타임라인/후보 스케일/악보 흐름/플레이어 점검.

QT_QPA_PLATFORM=offscreen 으로 실행한다.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication(sys.argv)
    win = AppWindow()

    tl = build_dummy_timeline()
    print(f"타임라인: {tl.title} | {tl.key} | 종류 {tl.available_scales}")

    # 후보 스케일: 메이저/마이너/도리안으로 한정
    assert set(tl.available_scales) <= {"메이저", "마이너", "도리안"}, \
        f"한정 외 스케일: {tl.available_scales}"
    assert tl.segments[0].has_options(), "Dm7은 마이너↔도리안 선택 가능해야"  # Dm7
    assert not tl.segments[2].has_options(), "Cmaj7은 메이저 단일"            # Cmaj7
    for s in tl.segments[:3]:
        print(f"  [{s.idx}] {s.chord.name:6} {s.degree:4} 후보="
              f"{[c.name for c in s.candidates]}")

    # 마디↔구간 매핑
    assert tl.total_bars() == len(tl.segments)
    assert tl.segment_for_bar(0) is tl.segments[0]

    # 종류 통일: 도리안으로(가능한 구간만)
    tl.apply_kind("도리안")
    applied = [s for s in tl.segments if s.scale.kind == "도리안"]
    print(f"  '도리안' 통일 적용: {len(applied)}/{len(tl.segments)} 구간")
    assert applied, "통일 적용 안 됨"

    # 화면 흐름: 분석완료 → 악보 → 연습(메인)
    win._on_timeline_ready(tl)
    assert win.stack.currentWidget() is win.score
    win.score._apply_kind(tl.available_scales[0])     # 칩 클릭
    win.score._apply_choice(tl.segments[0], 1)        # 마디 선택 변경
    assert tl.segments[0].active == 1
    win.score.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen

    # 렌더 + 입력 + 모드토글
    ms = win.main_screen
    ms._render_at(0.3)
    ms._render_at(tl.segments[1].start_sec + 0.1)
    ms.on_midi_note(64, True)
    ms.on_midi_note(64, False)
    ms._toggle_mode(); assert ms._mode == "quiz"
    ms.on_midi_note(61, True); assert 61 in ms.piano._revealed

    # ML 예시: 굽기 + 듣기/같이연주
    assert all(s.example for s in tl.segments), "example_phrase 미생성"
    ms._on_listen()                       # 현재 구간 예시 재생(스케줄)
    ms._toggle_play_along(); assert ms._play_along
    print(f"  example_phrase: seg0 {len(tl.segments[0].example)}음 "
          f"(모델 {'O' if ms._ml_model else 'X'})")

    print("\nSMOKE OK — 후보스케일/악보선택/통일/모드/ML예시(듣기·같이연주) 정상")


if __name__ == "__main__":
    main()
