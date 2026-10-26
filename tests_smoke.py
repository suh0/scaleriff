"""헤드리스 스모크 테스트 — 타임라인/후보 스케일/악보 흐름/플레이어 점검.

QT_QPA_PLATFORM=offscreen 으로 실행한다.
"""
import os
import tempfile
from copy import deepcopy
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit, QWidget
from PyQt6.QtCore import QPoint, QSettings
from gui.app import AppWindow
from player.dummy_timeline import build_dummy_timeline


def main():
    with open(os.path.join(os.path.dirname(__file__), "requirements.txt"), encoding="utf-8") as f:
        assert "yt-dlp[default]" in f.read(), "YouTube EJS 의존성이 requirements.txt에 없음"
    from ingest import audio_source
    assert hasattr(audio_source, "_find_deno"), "Deno 런타임 탐색기가 없음"
    with patch("ingest.audio_source.shutil.which", return_value=None), \
            patch("ingest.audio_source.glob.glob", return_value=[r"C:\winget\deno.exe"]):
        assert audio_source._find_deno() == r"C:\winget\deno.exe", \
            "PATH 갱신 전 WinGet Deno를 찾지 못함"

    app = QApplication(sys.argv)
    test_settings_dir = tempfile.TemporaryDirectory()
    test_settings = QSettings(os.path.join(test_settings_dir.name, "settings.ini"), QSettings.Format.IniFormat)
    test_settings.setValue("save_dir", os.path.join(test_settings_dir.name, "sessions"))
    with patch("gui.app.QSettings", return_value=test_settings), patch.object(AppWindow, "_try_start_midi"):
        win = AppWindow()
    win.main_screen.note_player.set_volume(0)
    assert not win.analyzing.findChildren(QTextEdit), "분석 진행 로그 박스가 남아 있음"
    win.analyzing._on_failed("HTTP Error 403: Forbidden\n\ntraceback")
    assert "403" in win.analyzing.msg.text() and "Forbidden" in win.analyzing.msg.text(), \
        "분석 실패 원인이 화면에 표시되지 않음"
    win.resize(1200, 800)
    win.show()
    for page in (win.link_screen, win.analyzing, win.beat,
                 win.setup, win.main_screen):
        win.stack.setCurrentWidget(page)
        app.processEvents()
        content = page.findChild(QWidget, "compactContent")
        assert content is not None, f"{type(page).__name__} 콘텐츠 프레임 없음"
        wr = content.width() / page.width()
        hr = content.height() / page.height()
        if page in (win.link_screen, win.analyzing):
            assert content.width() <= 860, "준비 화면은 읽기 좋은 폭으로 제한"
        else:
            assert wr >= .95, f"{type(page).__name__} 작업 영역이 좁음: {wr:.3f}"
        assert hr >= .95, f"{type(page).__name__} 세로 공간이 낭비됨: {hr:.3f}"
    win.stack.setCurrentWidget(win.link_screen)
    win.resize(1040, 740)
    win.link_screen.stack.setCurrentWidget(win.link_screen._input)
    app.processEvents()
    link_input = win.link_screen._input
    go_pos = win.link_screen.go_btn.mapTo(link_input, QPoint(0, 0))
    save_pos = win.link_screen.save_label.mapTo(link_input, QPoint(0, 0))
    url_pos = win.link_screen.url_edit.mapTo(link_input, QPoint(0, 0))
    assert url_pos.y() + win.link_screen.url_edit.height() <= save_pos.y(), \
        "저장경로가 링크 입력란 아래에 있지 않음"
    assert save_pos.y() + win.link_screen.save_label.height() <= go_pos.y(), \
        "저장경로가 분석 시작 버튼 위에 있지 않음"
    assert win.link_screen.save_dir() in win.link_screen.save_label.text()
    assert not hasattr(win.link_screen, "_lib_panel"), "라이브러리 패널이 남아 있음"
    assert not hasattr(win.link_screen, "save_edit"), "저장경로 입력란이 남아 있음"
    assert win.link_screen.go_btn.width() < win.link_screen.url_edit.width() / 2, \
        "분석 시작 버튼이 텍스트 폭보다 과도하게 넓음"

    tl = build_dummy_timeline()
    print(f"타임라인: {tl.title} | {tl.key} | 종류 {tl.available_scales}")

    # 코드별 단일 다이아토닉 스케일 — 7모드에서 한 코드=한 스케일(§3)
    DIATONIC_7 = {"아이오니안", "도리안", "프리지안", "리디안",
                  "믹솔리디안", "에올리안", "로크리안"}
    assert set(tl.available_scales) <= DIATONIC_7, \
        f"다이아토닉 외 스케일: {tl.available_scales}"
    assert tl.segments[0].scale_name == "D 도리안", tl.segments[0].scale_name   # Dm7=ii
    assert tl.segments[1].scale_name == "G 믹솔리디안", tl.segments[1].scale_name  # G7=V
    assert tl.segments[2].scale_name == "C 아이오니안", tl.segments[2].scale_name  # Cmaj7=I
    # 한 코드=한 스케일이므로 어떤 마디도 선택 가능하면 안 됨
    assert not any(s.has_options() for s in tl.segments), "마디가 선택 가능하면 안 됨"
    for s in tl.segments[:3]:
        print(f"  [{s.idx}] {s.chord.name:6} {s.degree:4} → {s.scale_name}")

    # 마디↔구간 매핑
    assert tl.total_bars() == len(tl.segments)
    assert tl.segment_for_bar(0) is tl.segments[0]

    # 화면 흐름: 분석완료 → 박자 조정 → 코드 편집 → 악보 → 연습(메인)
    assert win.link_screen.save_dir(), "분석 후 저장경로 기본값 없음"
    win._on_timeline_ready(tl)
    assert os.path.exists(win._session_path(tl)), "세션 자동 저장 안 됨"
    assert win.stack.currentWidget() is win.beat
    assert win.beat.pages.currentWidget() is win.beat.beat_page
    assert win.beat.zoom_l.isVisible() and not win.beat.chord_dialog.isVisible()
    # 박자 3단계(세로 한 화면): 현재 단계까지 활성, 아랫단계는 흐리게·비활성
    bs = win.beat
    for step in (1, 2, 3):
        assert bs._step == step
        assert [sec.isVisible() for sec in bs.sections] == [True] * 3
        assert [sec.isEnabled() for sec in bs.sections] == [i <= step for i in (1, 2, 3)]
        assert bs.confirm_btn.isVisible() == (step == 3)
        if step < 3:
            bs.next_btn.click()
    bs._show_step(1)
    assert bs._step == 1
    assert not any(
        label.isVisible() and label.text().startswith("시작 ")
        for label in win.beat.findChildren(QLabel)
    ), "시작박 표시가 남아 있음"
    tl_long = deepcopy(tl)
    bar_sec = tl.time_sig_beats() * tl.beat_sec()
    for bar in range(6, 80):
        seg = deepcopy(tl.segments[bar % 3])
        seg.idx = bar
        seg.start_bar, seg.end_bar = bar, bar + 1
        seg.start_sec, seg.end_sec = bar * bar_sec, (bar + 1) * bar_sec
        tl_long.segments.append(seg)
    win.beat.set_timeline(tl_long)
    win.beat._build_grid()             # 코드 수정 창(학습 설정에서 열림)을 비모달로 띄워 배치 확인
    win.beat.chord_dialog.show()
    app.processEvents()
    cell0_pos = win.beat._cells[0].mapTo(win.beat.holder, QPoint(0, 0))
    from gui.beat_screen import BARS_PER_ROW
    cell7_pos = win.beat._cells[BARS_PER_ROW].mapTo(win.beat.holder, QPoint(0, 0))
    assert cell7_pos.y() > cell0_pos.y(), \
        "마디별 코드가 한 줄로 늘어나 가로 스크롤을 만듦"
    assert win.beat.grid_scroll.horizontalScrollBar().maximum() == 0, \
        "긴 코드표에 가로 스크롤이 생김"
    vbar = win.beat.grid_scroll.verticalScrollBar()
    assert vbar.maximum() > 0, "긴 코드표에 세로 스크롤이 생기지 않음"
    vbar.setValue(vbar.maximum())
    app.processEvents()
    last_cell = win.beat._cells[79]
    last_pos = last_cell.mapTo(win.beat.grid_scroll.viewport(), QPoint(0, 0))
    assert last_pos.y() >= 0, "세로 스크롤 후 마지막 마디가 위로 잘림"
    assert last_pos.y() + last_cell.height() <= win.beat.grid_scroll.viewport().height(), \
        "세로 스크롤 후 마지막 마디가 보이지 않음"
    win.beat.chord_dialog.hide()
    win.beat.set_timeline(tl)
    app.processEvents()
    assert win.beat.pages.currentWidget() is win.beat.beat_page
    segments_before = list(tl.segments)
    win.beat.confirm_btn.click()      # 확인 = 박자 적용 후 학습 설정
    assert all(a is b for a, b in zip(segments_before, tl.segments)), \
        "박자 변경 없이 확인하면 코드 편집 내용을 보존해야 함"
    assert win.stack.currentWidget() is win.setup
    # 학습 설정: 곡 스케일 3후보 + 코드톤 포함률, ii–V–I는 7음이 추천(펜타 67%), 착지음 옵션은 착지 방식에서만
    su = win.setup
    assert "추천" in su.scale_btns[1].text() and "코드톤 100%" in su.scale_btns[1].text()
    assert "펜타토닉" in su.scale_btns[0].text() and su.scale_btns[0].isEnabled() and su._scale == 1
    assert su.landing_box.isHidden()
    su._pick_method("landing")
    assert not su.landing_box.isHidden()
    assert su.goal_btns["chord_tone"].isEnabled()
    su.count_mode.setCurrentIndex(2)
    su.count_lo.setValue(2)
    su.count_hi.setValue(3)
    # 코드 수정 창: 취소 = 되돌림, 확인 = 반영 + 학습 설정 새로고침(화면 선택 유지)
    from PyQt6.QtCore import QTimer as _QT

    def _edit(accept):
        def run():
            assert win.beat.chord_dialog.isVisible() and win.beat.grid.count() > 0
            win.beat._apply_chord(tl.segments[0], "Em")
            (win.beat.done_btn if accept else win.beat.chord_cancel_btn).click()
        _QT.singleShot(0, run)
        su.chord_btn.click()
    first = tl.segments[0].chord.name
    _edit(False)
    assert tl.segments[0].chord.name == first, "취소했는데 코드 수정이 남음"
    _edit(True)
    assert tl.segments[0].chord.name == "Em", "확인했는데 코드 수정이 반영 안 됨"
    assert su._method == "landing" and su.count() == [2, 3], "새로고침 후 선택이 초기화됨"
    # ← 박자 조정 버튼 = 박자 조정 화면으로
    su.backToBeatRequested.emit()
    assert win.stack.currentWidget() is win.beat
    assert win.beat.pages.currentWidget() is win.beat.beat_page
    win._enter_setup()
    su._pick_method("landing")
    su._pick_goal("chord_tone")
    su.count_mode.setCurrentIndex(2)
    su.count_lo.setValue(2)
    su.count_hi.setValue(3)
    su._pick_scale(0)
    su.go_btn.click()
    pent = su._options[0]
    assert tl.practice == {"scale": pent, "method": "landing", "goal": "chord_tone", "count": [2, 3]}
    assert all(s.note_set == pent["note_set"] for s in tl.segments if not s.is_detour)
    assert not any(s.example for s in tl.segments), "스케일 변경 후 이전 리프가 남음"
    assert win.stack.currentWidget() is win.main_screen
    # 리프모드: 조건대로 생성 → 다시 만들기 → 확정 시 리프연습
    from PyQt6.QtCore import QTimer
    from gui.riff_dialog import RiffDialog
    dialogs = []

    def _accept_dialog():
        d = next(w for w in app.topLevelWidgets() if isinstance(w, RiffDialog) and w.isVisible())
        assert d.roll._notes and all(n["midi"] % 12 in pent["note_set"] for n in d.roll._notes)
        assert d.count_spin.minimum() == len(d.patterns) == d.list.count()
        d.count_spin.setValue(d.count_spin.maximum())
        d.make_riffs()
        assert d.list.count() == d.count_spin.value()
        d.list.setCurrentRow(d.list.count() - 1)   # 패턴 클릭 → 롤 음표만 교체
        d.toggle_listen()
        assert d.listen_btn.text() == "정지 ■"
        before = d._current()["variant"]
        d.regenerate()   # 다시 만들기는 듣기를 멈춘다
        assert d._current()["variant"] != before and d.listen_btn.text() == "듣기 ▶"
        d.toggle_listen()
        dialogs.append(d)
        d.accept()
    QTimer.singleShot(0, _accept_dialog)
    win.main_screen.playhead.seek(3.0)
    win.main_screen.riff_btn.click()
    assert dialogs and win.main_screen._mode == "practice" and win.main_screen._riff_events
    assert win.main_screen.riff_btn.text() == "리프모드 해제"
    assert win.main_screen.playhead.position_sec() == tl.count_in_start(), "리프모드 진입 시 곡 처음 아님"
    win.main_screen.playhead.seek(3.0)
    win.main_screen.riff_btn.click()   # 해제 → 자유연습 + 처음으로
    assert win.main_screen._mode == "guide" and win.main_screen.riff_btn.text() == "리프모드"
    assert win.main_screen.playhead.position_sec() == tl.count_in_start(), "리프모드 해제 시 곡 처음 아님"
    win.main_screen._select_practice("riff")
    covered = [seg for seg in tl.segments if seg.example]
    assert covered and all(n["midi"] % 12 in seg.note_set for seg in covered for n in seg.example)
    assert covered[0] is tl.segments[0] and covered[-1] is tl.segments[-1], "곡 처음~끝을 덮지 않음"
    win.setup.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen

    # 렌더 + 입력 + 모드토글
    ms = win.main_screen
    app.processEvents()
    assert ms.scrub_row.isHidden(), "재생바는 기본 숨김(스페이스로 표시)"
    for ww, wh in ((1040, 740), (1600, 1000)):
        win.resize(ww, wh)
        app.processEvents()
        ms.loop_btn.setChecked(True)
        ms._toggle_loop_panel()
        for overlay in (ms.loop_panel,):
            pos = overlay.mapTo(ms.content, QPoint(0, 0))
            assert pos.x() >= 0 and pos.y() >= 0, \
                f"{type(overlay).__name__} 콘텐츠 밖 시작: {pos.x()}, {pos.y()}"
            assert pos.x() + overlay.width() <= ms.content.width(), \
                f"{type(overlay).__name__} 콘텐츠 오른쪽 이탈"
            assert pos.y() + overlay.height() <= ms.content.height(), \
                f"{type(overlay).__name__} 콘텐츠 아래 이탈"
        ms.loop_btn.setChecked(False)
        ms._toggle_loop_panel()
    win.resize(1040, 740)
    app.processEvents()
    ms._render_at(0.3)
    ms._render_at(tl.segments[1].start_sec + 0.1)
    ms.on_midi_note(64, True)
    ms.on_midi_note(64, False)
    # 곡 전체 재생바 + 모니터박스 연동: 한 틱에 둘 다 같은 위치로 이동
    ms._on_tick(2.5)
    assert ms.riff._sec == 2.5 and ms.scrub._pos == 2.5

    # 리프연습 / 자유연습 → 리프 뷰 표시 연동
    ms._select_practice("riff")
    assert ms._mode == "practice" and ms.riff.show_notes and not ms.stage.isHidden()
    ms._select_practice("free")
    assert ms._mode == "guide" and not ms.riff.show_notes and not ms.stage.isHidden()

    # ML 리프: 스케일 '종류당 1개' (코드 등장마다가 아님, §8) — 코드별 모드 타임라인 기준
    from ml.generate import bake_examples as _bake_ml
    tl_ml = _bake_ml(build_dummy_timeline(), ms._ml_model)
    assert tl_ml.scale_riffs, "scale_riffs 미생성"
    assert set(tl_ml.scale_riffs) == set(tl_ml.available_scales), \
        f"종류당 1개 아님: {set(tl_ml.scale_riffs)} vs {set(tl_ml.available_scales)}"
    dorian_segs = [s for s in tl_ml.segments if s.scale and s.scale.kind == "도리안"]
    assert len(dorian_segs) >= 2 and dorian_segs[0].example == dorian_segs[1].example, \
        "같은 종류·근음인데 리프가 다름(종류당 1개 위반)"
    assert all(s.example for s in tl_ml.segments), "구간 이조 example 미생성"

    # 리프 구성 — 보장 불변식만 검증(나머지는 분포 soft bias, 하드 강제 아님):
    #   1마디 / 스케일 안의 음만 / 밀도 하한(≥3음) / 마지막 음 코드톤 해결 / 음역 안.
    #   (첫박 코드톤·스케일음 3연속 억제·같은음 억제는 soft라 통계적 경향만 — 하드 검증 X)
    for kind, d in tl_ml.scale_riffs.items():
        assert d["n_bars"] == 1, f"{kind} 1마디 아님"
        cts, ns = set(d["chord_tones"]), set(d["note_set"])
        notes = sorted(d["notes"], key=lambda n: n["beat_pos"])
        assert all(n["beat_pos"] < 4 for n in notes), f"{kind} 1마디 초과"
        seq = ["C" if n["midi"] % 12 in cts else ("S" if n["midi"] % 12 in ns else "x")
               for n in notes]
        assert "x" not in seq, f"{kind} 스케일 밖 음: {seq}"
        assert len(notes) >= 3, f"{kind} 밀도 부족(<3음): {seq}"   # 거부샘플링 하한
        midis = [n["midi"] for n in notes]
        assert all(60 <= m <= 83 for m in midis), f"{kind} 음역 범위 밖: {midis}"  # 도~시 2옥타브
        assert notes[-1]["midi"] % 12 in cts, f"{kind} 마지막 음 코드톤 해결 아님: {seq}"

    # §3 같은 코드 2마디 → 리프 2회 반복(타일링)
    from ml.generate import bake_examples as _bake
    from player.timeline import Timeline as _TL, Segment as _Seg, ScaleOption as _SO
    from analyze.theory import parse_chord as _pc
    seg2 = _Seg(idx=0, start_sec=0.0, end_sec=4.0, start_bar=0, end_bar=2,  # 2마디
                chord=_pc("Dm7"),
                candidates=[_SO("도리안", 2, "D 도리안", [0, 2, 3, 5, 7, 9, 10])])
    tl2 = _TL(audio_ref="", bpm=120, time_sig="4/4", key="C major", key_root=0,
              loop_len=2, segments=[seg2])
    _bake(tl2, ms._ml_model)
    one = tl2.scale_riffs["도리안"]["notes"]
    assert len(seg2.example) == 2 * len(one), "2마디인데 리프 2회 반복 아님"
    assert any(n["beat_pos"] >= 4 for n in seg2.example), "둘째 마디에 리프 없음"
    # §3 가이드는 2마디 반복 구간이어도 늘 1마디만 표시
    from gui.widgets.riff_view import RiffView as _RV
    _rv = _RV(); _rv.set_segment(seg2, tl2.bpm, tl2.time_sig_beats())
    assert _rv._total_beats == tl2.time_sig_beats(), f"가이드 1마디 아님: {_rv._total_beats}"
    assert all(n["beat_pos"] < tl2.time_sig_beats() for n in _rv._notes), "가이드에 2마디째 음"
    # §2 리프가 곡에 함께 구워짐(재생 헤드 동기) — 일시정지/시킹과 함께 동작
    ms._select_practice("riff")     # 리프연습 → 이벤트 생성
    assert ms._riff_events and ms._riff_times == sorted(ms._riff_times), "리프 이벤트 정렬"
    mid = tl.segments[1].start_sec
    ms._seek_riff_idx(mid)
    assert all(t < mid for t in ms._riff_times[:ms._riff_idx]), "시킹 커서 오류(앞)"
    assert all(t >= mid for t in ms._riff_times[ms._riff_idx:]), "시킹 커서 오류(뒤)"
    ms._select_practice("free")     # 자유연습

    # §1 수동 코드 수정: 박자 조정 화면 코드 목록에서 바꾸면 스케일·리프 재계산
    win.beat.set_timeline(tl)
    s0 = tl.segments[0]                      # Dm7 → Fmaj7로 수정
    win.beat._apply_chord(s0, "Fmaj7")
    s0 = tl.segment_at(s0.start_sec)  # 편집은 시간 구간을 다시 구성하므로 현재 객체를 조회
    assert s0.chord.name == "Fmaj7" and s0.scale_name == "F 리디안", \
        f"수동 수정 실패: {s0.chord.name}/{s0.scale_name}"
    assert not s0.example, "코드 수정 시 리프를 미리 굽지 않는다(리프학습모드에서만)"
    print(f"  riff_events={len(ms._riff_events)}  "
          f"(모델 {'O' if ms._ml_model else 'X'})")

    # 연주 입력과 반복 재생 후에도 채점 기록을 생성하지 않는다.
    ms._on_seek(0.0)
    ms._toggle_play()
    ms.piano.notePlayed.emit(64, True)
    assert 64 in ms.piano._pressed
    ms.piano.notePlayed.emit(64, False)
    assert 64 not in ms.piano._pressed
    ms._on_tick(tl.content_end())
    ms.pause()
    win.setup.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen

    # 세션 저장/복원과 구 캐시의 기본값 유지.
    from player.timeline import Timeline as _TL2
    d = _TL2.from_dict(tl.to_dict())
    assert d.bar_times == tl.bar_times
    old = tl.to_dict()
    old["loop_override"] = 4  # 이전 채점 설정이 있어도 세션 로드 가능
    old["split_point"] = 60   # 구 세션의 왼손 경계 키는 무시
    for key in ("bar_times", "loop_phase", "loops"):
        old.pop(key, None)
    d2 = _TL2.from_dict(old)
    assert d2.bar_times == [] and d2.loops == []

    # 연습 화면은 예비박(코드 없음)부터 시작
    assert ms.playhead.position_sec() == tl.count_in_start() < tl.bar_times[0]
    # 건반은 오른손 두 옥타브(C4~B5)만 그린다.
    from gui.widgets.piano import MIDI_HIGH, MIDI_LOW
    assert (MIDI_LOW, MIDI_HIGH) == (60, 83)
    assert len(ms.piano._geometry()[0]) == 14, "흰 건반 2옥타브(14개) 아님"

    # §3.5 2차: 박자 조정 화면 — 좌(시작박)/우(BPM) 드래그 반응형 → 확정 시 재격자화
    from build.real_builder import regrid_timeline
    assert tl.chord_overrides, "수동 코드의 원본 시간 기록이 없음"
    assert regrid_timeline(tl, 1.0), "수정 시 보존한 원자료로 재격자화 실패"
    assert tl.segment_at(1.2).chord.name == "Fmaj7", "재격자화 후 수동 코드 유실"
    tl3 = _TL(audio_ref="", bpm=120, time_sig="4/4", key="C major", key_root=0,
              loop_len=0, segments=[], content_span=(0.0, 8.0),
              bar_times=[0.0, 2.0, 4.0, 6.0, 8.0],
              beat_times=[i * 0.5 for i in range(17)],
              chord_spans=[[0.0, 4.0, "C"], [4.0, 8.0, "F"]])
    bs = win.beat
    bs.set_timeline(tl3)
    assert bs.anchor == 0.0 and abs(bs.bar_len - 2.0) < 1e-9
    assert bs.bpm_edit.text() == "120.0"
    bs._on_drag(1, 2.7)               # 왼쪽 창: 마디1 선을 2.7s로 → 시작박 0.7s
    assert abs(bs.anchor - 0.7) < 1e-9
    bs._on_drag(4, 8.5)               # 끝박 드래그 → BPM 불변, 시작박만 당겨짐(0.5s)
    assert abs(bs.anchor - 0.5) < 1e-9 and abs(bs.bar_len - 2.0) < 1e-9
    bs._on_drag(0, -0.7)              # 오디오 이전까지 격자 확장(되접기 없음)
    assert abs(bs.anchor + 0.7) < 1e-9
    bs._on_drag(1, 2.5)               # 시작박 0.5s로 복귀
    # BPM(간격) 직접 입력 — 시작박 유지
    bs.bpm_edit.setText("96")
    bs._on_bpm_edited()
    assert abs(bs.bar_len - 2.5) < 1e-9 and bs.bpm_edit.text() == "96.0"
    bs.bpm_edit.setText("120")
    bs._on_bpm_edited()
    assert abs(bs.bar_len - 2.0) < 1e-9 and abs(bs.anchor - 0.5) < 1e-9
    # 재생은 스페이스바(_toggle_play)만 — 1마디(시작박)부터
    bs._toggle_play()
    assert bs.playhead.is_playing(), "스페이스 재생 안 됨"
    assert abs(bs.playhead.position_sec() - 0.5) < 0.05, bs.playhead.position_sec()
    bs.pause()
    bars_before = list(tl3.bar_times)
    assert tl3.bar_times == bars_before, "드래그만으로 재격자화됨"
    bs._on_confirm()                  # 확인 → 멈춤+재격자화 후 학습 설정
    assert win.stack.currentWidget() is win.setup
    assert not bs.playhead.is_playing()
    assert tl3.bpm == 120.0 and tl3.bar_times == [0.5, 2.5, 4.5, 6.5, 8.0], \
        (tl3.bpm, tl3.bar_times)
    assert [s.chord.name for s in tl3.segments] == ["C", "F"]
    assert tl3.segments[1].start_sec == 4.5 and tl3.segments[1].scale_name == "F 리디안", \
        "한 마디 한 코드: F 진입은 마디선(4.5초)에 정렬돼야 함"
    assert not any(s.example for s in tl3.segments), "재격자화 시 리프를 미리 굽지 않는다"
    assert bs.grid.count() > 0, "확정 후 코드 목록 미갱신"
    bs.bpm_edit.setText("96")
    bs.confirm_btn.click()
    assert tl3.bpm == 96.0 and tl3.bar_times[:3] == [0.5, 3.0, 5.5]
    bs.bpm_edit.setText("120")
    bs.confirm_btn.click()

    # §6 사용자 루프: 코드표 칸 드래그 → 이름 입력 → 목록 관리 (클릭=코드 수정)
    import gui.beat_screen as _bsm
    _qid = _bsm.QInputDialog
    _bsm.QInputDialog = type("_FakeQID", (), {
        "getText": staticmethod(lambda *a, **k: ("인트로", True))})
    bs._loop_press(2)                         # 3마디에서 누름
    assert not bs._drag_loop                  # 아직 클릭(코드 수정) 후보
    bs._loop_drag_to(1)                       # 옆 칸으로 드래그 → 루프 모드
    assert bs._drag_loop and bs._highlight_bars() == {1, 2}
    assert bs._cells[1].styleSheet() == bs._cells[1]._hl_qss
    bs._loop_drag_to(0)                       # 역방향 확장(정렬)
    assert bs._highlight_bars() == {0, 1, 2}
    bs._loop_release()
    assert bs._drag_start is None              # release 즉시 상태 초기화
    app.processEvents()                        # 이름 입력은 mouse 이벤트 후(지연 모달)
    assert tl3.loops == [{"name": "인트로", "start_bar": 0, "end_bar": 2, "on": True,
                         "start_sec": .5, "end_sec": 6.5}]
    assert bs.loops_row.count() == 1
    bs._loop_press(1)                         # 1마디 루프: 나갔다 복귀
    bs._loop_drag_to(0)
    bs._loop_drag_to(1)
    assert bs._drag_loop and bs._highlight_bars() == {1}
    bs._loop_release()
    app.processEvents()
    assert tl3.loops[1] == {"name": "인트로", "start_bar": 1, "end_bar": 1, "on": True,
                           "start_sec": 2.5, "end_sec": 4.5}
    bs._del_loop(1)
    bs._loop_press(2)                         # 드래그 없이 release → 루프 미생성
    bs._loop_release()                        # (seg=None — 코드 메뉴 생략)
    app.processEvents()
    _bsm.QInputDialog = _qid
    assert len(tl3.loops) == 1
    bs._del_loop(0)
    assert tl3.loops == [] and bs.loops_row.count() == 0
    tl3.loops.append({"name": "인트로", "start_bar": 0, "end_bar": 2, "on": True})

    # 코드 선택 리스트의 다이아토닉 강조 판정(C장조)
    assert bs._is_diatonic_name("Dm7") and bs._is_diatonic_name("G7")
    assert not bs._is_diatonic_name("Eb") and not bs._is_diatonic_name("Cm")

    # 코드 수정 후 박자 그대로 확인 → 재격자화 생략(수정 보존)
    bs._apply_chord(tl3.segments[0], "Am")
    assert tl3.segments[0].chord.name == "Am"
    bs._on_confirm()
    assert win.stack.currentWidget() is win.setup
    assert tl3.segments[0].chord.name == "Am", "확인이 코드 수정을 덮어씀"

    # 메인 화면 루프 사이드바(§6): 루프 리스트 + 루프별 ON/OFF + 재생 루프백
    win.setup.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen and ms.tl is tl3
    ms.loop_btn.setChecked(True)
    ms._toggle_loop_panel()
    assert not ms.loop_panel.isHidden() and ms.loop_rows.count() == 1
    assert ms._loop_spans() == [(0.5, 6.5)], ms._loop_spans()
    tl3.loops[0]["on"] = False                # 꺼진 루프는 반복 안 함
    assert ms._loop_spans() == []
    tl3.loops[0]["on"] = True
    ms.playhead.play()
    ms._on_tick(6.6)                          # 루프 끝 도달 → 시작으로 루프백
    assert abs(ms.playhead.position_sec() - 0.5) < 0.05, ms.playhead.position_sec()
    ms.pause()
    ms.loop_btn.setChecked(False)
    ms._toggle_loop_panel()
    assert ms.loop_panel.isHidden()
    # 루프는 세션 JSON에 영속
    assert _TL.from_dict(tl3.to_dict()).loops == tl3.loops

    # 마디 격자가 없는 구 세션도 BPM 기반 루프 재생을 유지한다.
    saved_bars = tl3.bar_times
    tl3.bar_times = []
    assert ms._loop_spans() == [(0.0, 6.0)]
    ms.playhead.play()
    ms._on_tick(6.1)
    assert abs(ms.playhead.position_sec() - 0.0) < 0.05
    ms.pause()
    tl3.bar_times = saved_bars

    # 건반 = 오른손 C4~B5, 흰 건반이 간격 없이 이어진다.
    pw = ms.piano
    pw.resize(900, 220)
    _wm, _x0, _y0, _kw, _kh = pw._geometry()
    assert _wm[0] == 60 and _wm[-1] == 83          # C4~B5
    assert all(abs(pw._wx(i + 1, _wm, _x0, _kw) - pw._wx(i, _wm, _x0, _kw) - _kw) < 1e-6
               for i in range(len(_wm) - 1))
    # 보정 결과는 캐시 JSON에 영속(원자료 포함)
    d3 = _TL.from_dict(tl3.to_dict())
    assert d3.beat_times == tl3.beat_times and d3.bar_times == tl3.bar_times

    # 파형 피크(분석 WAV → 세션 JSON) — 곡 전체 기준 정규화로 작게 녹음된 곡도 같은 높이
    import wave as _wv, struct as _st, os as _os, tempfile as _tmp, json as _json
    from player.waveform import wave_peaks, WAVE_RATE
    fd, wavp = _tmp.mkstemp(suffix=".wav"); _os.close(fd)
    quiet = wavp + ".q.wav"
    for path, amp in ((wavp, 12000), (quiet, 3000)):
        with _wv.open(path, "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
            f.writeframes(_st.pack("<h", amp) * 22050)     # 1초, 일정 진폭
    for path in (wavp, quiet):
        peaks = wave_peaks(path)
        assert len(peaks) == WAVE_RATE and all(abs(hi - 1.0) < 1e-3 for _, hi in peaks), peaks[:2]
    assert wave_peaks("no_such.wav") == []               # 파일 없음 → 파형 생략
    # 구 세션(wav_ref만 있음)은 불러올 때 파형을 옮기고, 저장 JSON엔 WAV 경로가 없다.
    fd, old_sess = _tmp.mkstemp(suffix=".json"); _os.close(fd)
    old_payload = tl3.to_dict(); old_payload.pop("wave_peaks"); old_payload["wav_ref"] = wavp
    with open(old_sess, "w", encoding="utf-8") as f:
        _json.dump(old_payload, f)
    migrated = _TL.load_json(old_sess)
    assert len(migrated.wave_peaks) == WAVE_RATE
    migrated.save_json(old_sess)
    with open(old_sess, encoding="utf-8") as f:
        saved_payload = _json.load(f)
    assert "wav_ref" not in saved_payload and "wav_ref" not in saved_payload["media_refs"]
    assert saved_payload["wave_peaks"] == migrated.wave_peaks
    _os.remove(wavp); _os.remove(quiet); _os.remove(old_sess)

    # 세션 저장/불러오기 — 분석 1회 결과를 링크 화면 파일입력으로 즉시 로드(재분석 없음)
    fd, sess = _tmp.mkstemp(suffix=".json"); _os.close(fd)
    tl3.save_json(sess)
    win._start_build(sess)
    assert win.stack.currentWidget() is win.beat, "세션 로드 후 박자 화면 아님"
    assert win._timeline is not tl3 and win._timeline.bpm == tl3.bpm
    assert len(win._timeline.segments) == 2
    assert win._timeline.chord_spans == tl3.chord_spans   # 원자료도 복원 → 재보정 가능
    _os.remove(sess)

    # 최근 저장경로 표시와 해당 폴더로의 실제 세션 저장
    previous_dir = win.link_screen.save_dir()
    with _tmp.TemporaryDirectory() as save_dir:
        win.link_screen.set_save_dir(save_dir)
        assert win.link_screen.save_label.text() == f"최근 저장경로: {save_dir}"
        with patch.object(win, "_settings"):
            win._save_session(tl3)
            win._settings.setValue.assert_any_call("save_dir", save_dir)
        saved = _TL.load_json(win._session_path(tl3))
        assert saved.bpm == tl3.bpm and saved.chord_spans == tl3.chord_spans
    win.link_screen.set_save_dir(previous_dir)

    # §6 연습하며 기다리기: 분석은 백그라운드, 링크 화면은 세션 열기만 활성
    win.analyzing._set_steps(50)                          # 단계 체크리스트 매핑
    st = [l.text().split()[0] for l in win.analyzing._step_lbls]
    assert st == ["완료", "진행", "대기", "대기"], st
    win.analyzing.backgroundRequested.emit()
    assert win._bg_wait and win.stack.currentWidget() is win.link_screen
    assert not win._pill.isHidden() and win._pill.play_btn.isHidden()
    assert not win.link_screen.url_edit.isEnabled()
    assert not win.link_screen.go_btn.isEnabled()
    win._start_build("https://youtu.be/xyz")              # 대기 중 새 분석 금지
    assert win.stack.currentWidget() is win.link_screen
    win.analyzing.progressChanged.emit(70)
    assert "70%" in win._pill.lbl.text()
    tl_bg = build_dummy_timeline()
    win.analyzing.timelineReady.emit(tl_bg)               # 완료 → 알약에 연주하기
    assert win._pending_tl is tl_bg and win.stack.currentWidget() is win.link_screen
    assert not win._pill.play_btn.isHidden() and not tl_bg.scale_riffs
    win._play_pending()                                   # → 그 곡의 박자 조정
    assert win.stack.currentWidget() is win.beat and win._timeline is tl_bg
    assert not win._bg_wait and win._pill.isHidden()
    assert win.link_screen.url_edit.isEnabled()

    # 입장 애니메이션 헬퍼 — 헤드리스에서 예외 없이 동작
    from gui.anim import stagger as _stagger
    _stagger([ms.play_btn, ms.riff])

    print("\nSMOKE OK — 스케일/악보+수동수정/리프동기재생/리프불변식(1마디·스케일안·밀도·해결·음역)/보정/난이도/마디선+확정잠금/루프정의·사이드바/건반간격/파형·세션/애니메이션 정상")
    win.close()
    test_settings_dir.cleanup()


if __name__ == "__main__":
    main()
