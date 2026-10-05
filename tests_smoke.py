"""헤드리스 스모크 테스트 — 타임라인/후보 스케일/악보 흐름/플레이어 점검.

QT_QPA_PLATFORM=offscreen 으로 실행한다.
"""
import os
import tempfile
from copy import deepcopy
from unittest.mock import patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 연습 기록은 임시 경로로(테스트가 실제 data/practice_log.jsonl 오염 방지)
os.environ["SCALERIFF_PRACTICE_LOG"] = os.path.join(tempfile.mkdtemp(), "practice_log.jsonl")
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit, QWidget
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtCore import QPoint
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
    win = AppWindow()
    assert not win.analyzing.findChildren(QTextEdit), "분석 진행 로그 박스가 남아 있음"
    win.analyzing._on_failed("HTTP Error 403: Forbidden\n\ntraceback")
    assert "403" in win.analyzing.msg.text() and "Forbidden" in win.analyzing.msg.text(), \
        "분석 실패 원인이 화면에 표시되지 않음"
    win.resize(1200, 800)
    win.show()
    for page in (win.link_screen, win.analyzing, win.beat,
                 win.score, win.main_screen):
        win.stack.setCurrentWidget(page)
        app.processEvents()
        content = page.findChild(QWidget, "compactContent")
        assert content is not None, f"{type(page).__name__} 콘텐츠 프레임 없음"
        wr = content.width() / page.width()
        hr = content.height() / page.height()
        assert 0.73 <= wr <= 0.77, f"{type(page).__name__} 가로 비율: {wr:.3f}"
        assert 0.73 <= hr <= 0.77, f"{type(page).__name__} 세로 비율: {hr:.3f}"
    win.stack.setCurrentWidget(win.link_screen)
    win.resize(1040, 740)
    win.link_screen.stack.setCurrentWidget(win.link_screen._input)
    app.processEvents()
    link_input = win.link_screen._input
    go_pos = win.link_screen.go_btn.mapTo(link_input, QPoint(0, 0))
    save_pos = win.link_screen.save_edit.mapTo(link_input, QPoint(0, 0))
    lib_pos = win.link_screen._lib_panel.mapTo(link_input, QPoint(0, 0))
    assert go_pos.y() < save_pos.y(), "분석 시작 버튼이 저장경로 아래에 있음"
    assert lib_pos.y() > save_pos.y() + win.link_screen.save_edit.height(), \
        "최근 세션이 저장경로 아래에 있지 않음"
    lib_center = lib_pos.x() + win.link_screen._lib_panel.width() / 2
    assert abs(lib_center - link_input.width() / 2) <= 2, \
        "최근 세션이 화면 가운데 정렬되지 않음"
    lib_ratio = win.link_screen._lib_panel.width() / link_input.width()
    assert 0.45 <= lib_ratio <= 0.55, \
        f"최근 세션 가로 비율: {lib_ratio:.3f}"
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

    # 화면 흐름: 분석완료 → 박자 조정(코드 목록 포함) → 악보 → 연습(메인)
    assert win.link_screen.save_dir(), "분석 후 저장경로 기본값 없음"
    win._on_timeline_ready(tl)
    assert os.path.exists(win._session_path(tl)), "세션 자동 저장 안 됨"
    assert win.stack.currentWidget() is win.beat
    assert win.beat.grid.count() > 0, "박자 화면에 코드 목록 없음"
    assert not win.beat.holder.isEnabled(), "확정 전 코드표 잠김 아님"
    beat_content = win.beat.findChild(QWidget, "compactContent")
    for ww, wh in ((1040, 740), (1600, 1000)):
        win.resize(ww, wh)
        app.processEvents()
        zoom_l_pos = win.beat.zoom_l.mapTo(beat_content, QPoint(0, 0))
        zoom_r_pos = win.beat.zoom_r.mapTo(beat_content, QPoint(0, 0))
        confirm_pos = win.beat.confirm_btn.mapTo(beat_content, QPoint(0, 0))
        grid_pos = win.beat.grid_scroll.mapTo(beat_content, QPoint(0, 0))
        assert abs(zoom_l_pos.y() - zoom_r_pos.y()) <= 2, \
            "처음/마지막 10초 확대바가 한 줄에 있지 않음"
        assert confirm_pos.x() > zoom_r_pos.x() + win.beat.zoom_r.width(), \
            "확정 버튼이 박자 조정바 오른쪽에 있지 않음"
        zoom_bottom = max(zoom_l_pos.y() + win.beat.zoom_l.height(),
                          zoom_r_pos.y() + win.beat.zoom_r.height())
        assert grid_pos.y() > zoom_bottom, \
            "마디별 코드가 박자 조정바 아래에 있지 않음"
        assert win.beat.grid_scroll.horizontalScrollBar().maximum() == 0, \
            "마디별 코드에 가로 스크롤이 생김"
    win.resize(1040, 740)
    app.processEvents()
    assert not any(
        label.isVisible() and label.text().startswith("시작 ")
        for label in win.beat.findChildren(QLabel)
    ), "시작박 표시가 남아 있음"
    tl_long = deepcopy(tl)
    bar_sec = tl.time_sig_beats() * tl.beat_sec()
    for bar in range(6, 50):
        seg = deepcopy(tl.segments[bar % 3])
        seg.idx = bar
        seg.start_bar, seg.end_bar = bar, bar + 1
        seg.start_sec, seg.end_sec = bar * bar_sec, (bar + 1) * bar_sec
        tl_long.segments.append(seg)
    win.beat.set_timeline(tl_long)
    app.processEvents()
    cell0_pos = win.beat._cells[0].mapTo(win.beat.holder, QPoint(0, 0))
    cell7_pos = win.beat._cells[7].mapTo(win.beat.holder, QPoint(0, 0))
    assert cell7_pos.y() > cell0_pos.y(), \
        "마디별 코드가 한 줄로 늘어나 가로 스크롤을 만듦"
    assert win.beat.grid_scroll.horizontalScrollBar().maximum() == 0, \
        "긴 코드표에 가로 스크롤이 생김"
    vbar = win.beat.grid_scroll.verticalScrollBar()
    assert vbar.maximum() > 0, "긴 코드표에 세로 스크롤이 생기지 않음"
    vbar.setValue(vbar.maximum())
    app.processEvents()
    last_cell = win.beat._cells[49]
    last_pos = last_cell.mapTo(win.beat.grid_scroll.viewport(), QPoint(0, 0))
    assert last_pos.y() >= 0, "세로 스크롤 후 마지막 마디가 위로 잘림"
    assert last_pos.y() + last_cell.height() <= win.beat.grid_scroll.viewport().height(), \
        "세로 스크롤 후 마지막 마디가 보이지 않음"
    win.beat.set_timeline(tl)
    app.processEvents()
    win.beat._on_confirm()      # 확정 = 멈춤+적용+편집 잠금 / 코드표 열림
    assert win.stack.currentWidget() is win.beat
    assert win.beat._locked and win.beat.confirm_btn.text() == "수정"
    assert not win.beat.zoom_l.isEnabled() and not win.beat.bpm_edit.isEnabled()
    assert win.beat.holder.isEnabled() and win.beat._loop_wrap.isEnabled()
    win.beat._on_confirm()      # 수정 = 잠금 해제 / 코드표 다시 잠김
    assert not win.beat._locked and win.beat.confirm_btn.text() == "확정"
    assert win.beat.zoom_l.isEnabled() and not win.beat.holder.isEnabled()
    win.beat._on_done()         # 조정 완료 → 악보 화면
    assert win.stack.currentWidget() is win.score
    # 악보 화면: 사용된 스케일 칩이 종류 수만큼 생성 + 첫 스케일이 기본 선택됐는지
    assert len(win.score._kind_btns) == len(tl.scale_riffs), "스케일 칩 수 불일치"
    assert win.score._sel_kind in tl.scale_riffs, "기본 선택 스케일 없음"
    win.score._show_riff(list(tl.scale_riffs)[-1])     # 다른 스케일 선택 → 리프 갱신
    assert win.score._sel_kind == list(tl.scale_riffs)[-1]
    # 곡맥락 리스트: 행 텍스트에 사용 코드(마디 범위 제거)
    assert "Dm7" in win.score._kind_btns["도리안"].text()
    assert "마디" not in win.score._kind_btns["도리안"].text()
    # 피아노롤: 오른손 2옥타브(도~시 60~83) 고정 + 위=고음 + 세미톤 선형 y
    roll = win.score.roll
    r_notes = tl.scale_riffs[win.score._sel_kind]["notes"]
    assert roll._notes == r_notes
    assert (roll._lo, roll._hi) == (60, 83)
    assert all(60 <= n["midi"] <= 83 for n in r_notes)     # 생성 음역과 일치
    assert roll._y(roll._hi) < roll._y(roll._lo), "피아노롤 위=고음 아님"
    assert abs((roll._y(60) - roll._y(72)) - 12 * (roll._y(60) - roll._y(61))) < 1e-6
    # 근음(도수 1 = C, pc 0)은 파랑, 다른 코드톤은 초록
    from gui import theme as _T
    assert roll._fill(0).name() == _T.BADGE_ROOT, "근음 파랑 아님"
    other_ct = next(pc for pc in roll._chord_tones if pc != 0)
    assert roll._fill(other_ct).name() == _T.BADGE_CHORD
    score_content = win.score.findChild(QWidget, "compactContent")
    for ww, wh in ((1040, 740), (1600, 1000)):
        win.resize(ww, wh)
        app.processEvents()
        for widget in (win.score.title, win.score.riffs_title,
                       win.score._kinds_wrap, win.score.riff_lbl,
                       win.score.roll, win.score.go_btn):
            pos = widget.mapTo(score_content, QPoint(0, 0))
            assert pos.x() >= 0 and pos.y() >= 0, \
                f"ScoreScreen {type(widget).__name__} 콘텐츠 밖 시작"
            assert pos.x() + widget.width() <= score_content.width(), \
                f"ScoreScreen {type(widget).__name__} 오른쪽 이탈"
            assert pos.y() + widget.height() <= score_content.height(), \
                f"ScoreScreen {type(widget).__name__} 아래 이탈"
    win.resize(1040, 740)
    app.processEvents()
    # 리프 재생성: 변주 시드 증가 + 그 종류 구간 재타일링
    k0 = win.score._sel_kind
    win.score._regen_riff()
    assert tl.scale_riffs[k0].get("variant") == 1, "재생성 변주 안 됨"
    assert all(s.example for s in tl.segments if s.scale and s.scale.kind == k0)
    # 리프 미리듣기: 노트 수만큼 재생 예약 + 중단
    win.score._play_riff()
    assert len(win.score._riff_timers) == len(tl.scale_riffs[k0]["notes"])
    win.score._stop_riff()
    assert not win.score._riff_timers
    # ← 박자 조정 버튼 = 조정 화면으로
    win.score.backToBeatRequested.emit()
    assert win.stack.currentWidget() is win.beat
    win._enter_score()
    win.score.practiceRequested.emit()
    assert win.stack.currentWidget() is win.main_screen

    # 렌더 + 입력 + 모드토글
    ms = win.main_screen
    app.processEvents()
    assert ms.scrub.geometry().top() > ms.piano.geometry().bottom(), \
        "재생바가 건반 아래에 있지 않음"
    from player.scoring import PassSummary as _OverlaySummary
    overlay_summary = _OverlaySummary(number=1, right_hits=1, right_total=1)
    for ww, wh in ((1040, 740), (1600, 1000)):
        win.resize(ww, wh)
        app.processEvents()
        ms.pass_card.show_summary(overlay_summary, [])
        ms.loop_btn.setChecked(True)
        ms._toggle_loop_panel()
        for overlay in (ms.pass_card, ms.loop_panel):
            pos = overlay.mapTo(ms.content, QPoint(0, 0))
            assert pos.x() >= 0 and pos.y() >= 0, \
                f"{type(overlay).__name__} 콘텐츠 밖 시작: {pos.x()}, {pos.y()}"
            assert pos.x() + overlay.width() <= ms.content.width(), \
                f"{type(overlay).__name__} 콘텐츠 오른쪽 이탈"
            assert pos.y() + overlay.height() <= ms.content.height(), \
                f"{type(overlay).__name__} 콘텐츠 아래 이탈"
        ms.pass_card._timer.stop()
        ms.pass_card.hide()
        ms.loop_btn.setChecked(False)
        ms._toggle_loop_panel()
    win.resize(1040, 740)
    app.processEvents()
    ms._render_at(0.3)
    ms._render_at(tl.segments[1].start_sec + 0.1)
    ms.on_midi_note(64, True)
    ms.on_midi_note(64, False)
    # 코드 레인(C안): 타임라인 연결 + 위치 추적 + 클릭=구간 점프 + 드래그=시킹
    assert ms.lane._timeline is tl
    ms.lane.set_position(1.0)
    assert ms.lane._pos == 1.0
    ms.lane.resize(900, 92)
    seg1 = tl.segments[1]
    ms.lane.setGraphicsEffect(None)  # 입장 애니메이션 투명도와 무관하게 실제 위젯 렌더 검사
    lane_img = QImage(ms.lane.size(), QImage.Format.Format_ARGB32)
    ms.lane.render(lane_img)
    fx0 = int(ms.lane._sec_to_x(seg1.start_sec)) + 8
    fx1 = int(ms.lane._sec_to_x(seg1.end_sec)) - 4
    name_color = QColor(_T.TEXT_MUTED).name()
    name_rows = [
        y for y in range(4, ms.lane.height() - 4)
        if any(lane_img.pixelColor(x, y).name() == name_color
               for x in range(fx0, fx1))
    ]
    assert len(name_rows) >= 18, f"다음 코드명이 작음: {len(name_rows)}px"
    scale_color = QColor(_T.TEXT_DIM).name()
    scale_rows = [
        y for y in range(4, ms.lane.height() - 4)
        if any(lane_img.pixelColor(x, y).name() == scale_color
               for x in range(fx0, fx1))
    ]
    assert scale_rows, "다음 코드 아래 스케일명이 사라짐"
    text_rows = name_rows + scale_rows
    text_mid = (min(text_rows) + max(text_rows)) / 2
    assert abs(text_mid - ms.lane.height() / 2) <= 4, \
        f"코드 트랙 텍스트 세로 중앙 불일치: {text_mid:.1f}"
    key_fill = QColor(_T.KEY_W_FILL).name()
    mini_key_pixels = sum(
        lane_img.pixelColor(x, y).name() == key_fill
        for x in range(fx0, fx1) for y in range(58, 84)
    )
    assert mini_key_pixels == 0, "다음 코드에 미니 건반이 남아 있음"
    seeks = []
    ms.lane.seekRequested.connect(seeks.append)

    class _P:                                         # 최소 마우스 이벤트 대역
        def __init__(self, x): self._x = x
        def x(self): return self._x

    class _Ev:
        def __init__(self, x): self._p = _P(x)
        def position(self): return self._p

    x1 = ms.lane._sec_to_x(seg1.start_sec + 0.1)     # 구간1 블록 위 클릭
    ms.lane.mousePressEvent(_Ev(x1))
    ms.lane.mouseReleaseEvent(_Ev(x1))                # 이동 없음 = 클릭 → 점프
    assert seeks and abs(seeks[-1] - seg1.start_sec) < 1e-6, seeks
    ms.lane.mousePressEvent(_Ev(x1))
    ms.lane.mouseMoveEvent(_Ev(x1 + 60.0))            # 오른쪽 드래그 = 과거로 시킹
    assert seeks[-1] < ms.lane._press_sec, seeks[-1]
    n_seek = len(seeks)
    ms.lane.mouseReleaseEvent(_Ev(x1 + 60.0))         # 드래그 후 release = 점프 없음
    assert len(seeks) == n_seek
    ms.lane.seekRequested.disconnect(seeks.append)
    ms.lane.set_position(1.0)
    # 곡 전체 재생바 + 레인 연동: 한 틱에 둘 다 같은 위치로 이동
    ms._on_tick(2.5)
    assert ms.lane._pos == 2.5 and ms.scrub._pos == 2.5

    # 리프연습 ON/OFF 토글 + 리프 뷰 표시 연동
    ms._toggle_riff(); assert ms._mode == "practice" and not ms.riff.isHidden()
    ms._toggle_riff(); assert ms._mode == "guide" and ms.riff.isHidden()

    # ML 리프: 스케일 '종류당 1개' (코드 등장마다가 아님, §8)
    assert tl.scale_riffs, "scale_riffs 미생성"
    assert set(tl.scale_riffs) == set(tl.available_scales), \
        f"종류당 1개 아님: {set(tl.scale_riffs)} vs {set(tl.available_scales)}"
    dorian_segs = [s for s in tl.segments if s.scale and s.scale.kind == "도리안"]
    assert len(dorian_segs) >= 2 and dorian_segs[0].example == dorian_segs[1].example, \
        "같은 종류·근음인데 리프가 다름(종류당 1개 위반)"
    assert all(s.example for s in tl.segments), "구간 이조 example 미생성"

    # 리프 구성 — 보장 불변식만 검증(나머지는 분포 soft bias, 하드 강제 아님):
    #   1마디 / 스케일 안의 음만 / 밀도 하한(≥3음) / 마지막 음 코드톤 해결 / 음역 안.
    #   (첫박 코드톤·스케일음 3연속 억제·같은음 억제는 soft라 통계적 경향만 — 하드 검증 X)
    for kind, d in tl.scale_riffs.items():
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
    ms._toggle_riff()                       # 연습 ON → 이벤트 생성
    assert ms._riff_events and ms._riff_times == sorted(ms._riff_times), "리프 이벤트 정렬"
    mid = tl.segments[1].start_sec
    ms._seek_riff_idx(mid)
    assert all(t < mid for t in ms._riff_times[:ms._riff_idx]), "시킹 커서 오류(앞)"
    assert all(t >= mid for t in ms._riff_times[ms._riff_idx:]), "시킹 커서 오류(뒤)"
    ms._toggle_riff()                       # OFF

    # §1 수동 코드 수정: 박자 조정 화면 코드 목록에서 바꾸면 스케일·리프 재계산
    win.beat.set_timeline(tl, ms._ml_model)
    s0 = tl.segments[0]                      # Dm7 → Fmaj7로 수정
    win.beat._apply_chord(s0, "Fmaj7")
    assert s0.chord.name == "Fmaj7" and s0.scale_name == "F 리디안", \
        f"수동 수정 실패: {s0.chord.name}/{s0.scale_name}"
    assert s0.example, "수정 후 리프 미생성"
    assert "리디안" in tl.scale_riffs, "새 스케일 종류 리프 미생성"
    print(f"  scale_riffs: {list(tl.scale_riffs)}  riff_events={len(ms._riff_events)}  "
          f"(모델 {'O' if ms._ml_model else 'X'})")

    # §7.5 채점: 엔진 생성 + 배지 + 패스 요약 카드
    from player.scoring import PassSummary
    assert ms.scorer is not None, "set_timeline 후 scorer 미생성"
    eng = ms.scorer
    assert eng.windows, "패스 창 미생성"
    eng.tick(eng.windows[0][0] + 0.01)          # 패스 진입(유효)
    eng.note_on(72, eng.windows[0][0] + 0.5)    # 오른손 존
    ms._update_badge()
    assert "오른손" in ms.acc_lbl.text(), ms.acc_lbl.text()
    summary = PassSummary(number=1, right_hits=3, right_total=4,
                          left_hits=1, left_total=2, landing_hits=1,
                          landing_opps=2, out_counts={1: 2})
    eng.trend = [62, 75]
    ms._on_pass_done(summary)
    assert not ms.pass_card.isHidden(), "패스 카드 미표시"
    body = ms.pass_card.body_lbl.text()
    assert "75%" in body and "스케일 밖" in body and "틀림" not in body, body
    assert "62 → 75" in body, body
    assert ms.acc_lbl.text() == "", "패스 후 배지 리셋 안 됨"
    # 모드 전환 → 진행 중 패스 무효화(리프연습 무채점, §7.5 1차)
    eng.note_on(72, eng.windows[0][0] + 0.6)
    ms._toggle_riff()
    assert eng.cur.right_total == 0, "모드 전환 시 패스 리셋 안 됨"
    ms._toggle_riff()

    # §3.5 분석 보정: 루프 override → 연습 재진입 시 채점에 반영(스플릿 C4 고정)
    tl.loop_override = 4                         # (UI 콤보 제거 — 값 경로만 검증)
    assert tl.split_point == 60                  # 왼손 C3~B3 / 오른손 C4~B5
    win.score.practiceRequested.emit()           # → 메인 재진입 = 엔진 재생성
    assert win.stack.currentWidget() is win.main_screen
    eng2 = ms.scorer
    assert eng2 is not eng, "재진입 시 엔진 미재생성"
    assert all(w[3] == 4 for w in eng2.windows) or len(eng2.windows) == 1, \
        eng2.windows
    w0 = eng2.windows[0]
    eng2.tick(w0[0] + 0.01)
    eng2.note_on(50, w0[0] + 0.1)                # C3~B3 → 왼손 존
    eng2.note_on(72, w0[0] + 0.15)               # C4~B5 → 오른손 존
    assert (eng2.cur.right_total, eng2.cur.left_total) == (1, 1)
    # 보정값은 타임라인 JSON에 영속
    from player.timeline import Timeline as _TL2
    d = _TL2.from_dict(tl.to_dict())
    assert d.loop_override == 4 and d.split_point == 60

    # §7.5 난이도: 선택 → 채점 기준 교체 + 건반 목표음 필터
    ms.diff_combo.setCurrentIndex(1)             # Lv1: 왼손 근음 + 오른손 코드톤
    assert ms.scorer.level == 1
    seg = ms._current_segment()
    assert ms.piano._split == tl.split_point
    assert ms.piano._right_targets == set(seg.chord_tones()), "Lv1 오른손 ≠ 코드톤"
    assert ms.piano._left_targets == {seg.chord.root % 12}, "Lv1 왼손 ≠ 근음"
    # 리프연습 진입 → 난이도 비활성(§7: 리프연습은 난이도 미적용)
    ms._toggle_riff()
    assert not ms.diff_combo.isEnabled()
    ms._toggle_riff()
    assert ms.diff_combo.isEnabled()
    # 해제 → 필터 해제
    ms.diff_combo.setCurrentIndex(0)
    assert ms.scorer.level == 0
    assert ms.piano._split == 0

    # §7.5 2차: 리프연습 = 리프 일치도 채점
    ms._toggle_riff()                            # 연습 ON → 채점 기준 교체
    eng3 = ms.scorer
    assert eng3.mode == "practice" and eng3._riff, "리프 이벤트 미전달"
    w0 = eng3.windows[0]
    riff_in = [(t, m) for t, m in eng3._riff if w0[0] <= t < w0[1]]
    assert riff_in, "첫 패스 창에 리프 음 없음"
    eng3.tick(w0[0] + 0.01)
    eng3.note_on(riff_in[0][1], riff_in[0][0])   # 첫 리프 음 정시 연주 → 일치
    s3 = eng3.tick(w0[1] + 0.01)
    assert s3 and (s3.riff_hits, s3.riff_total) == (1, len(riff_in)), \
        (s3.riff_hits, s3.riff_total)
    ms._on_pass_done(s3)
    body = ms.pass_card.body_lbl.text()
    assert "리프 일치율" in body and "추이" not in body, body
    ms._toggle_riff()                            # OFF → 가이드 복귀
    assert ms.scorer.mode == "guide"

    # §3.5 2차: 박자 조정 화면 — 좌(시작박)/우(BPM) 드래그 반응형 → 확정 시 재격자화
    from build.real_builder import regrid_timeline
    assert not regrid_timeline(tl, ms._ml_model, 1.0), "원자료 없이 재격자화됨"
    tl3 = _TL(audio_ref="", bpm=120, time_sig="4/4", key="C major", key_root=0,
              loop_len=0, segments=[], content_span=(0.0, 8.0),
              bar_times=[0.0, 2.0, 4.0, 6.0, 8.0],
              beat_times=[i * 0.5 for i in range(17)],
              chord_spans=[[0.0, 4.0, "C"], [4.0, 8.0, "F"]])
    bs = win.beat
    bs.set_timeline(tl3, ms._ml_model)
    assert bs.anchor == 0.0 and abs(bs.bar_len - 2.0) < 1e-9
    assert bs.bpm_edit.text() == "120.0"
    bs._on_drag(1, 2.7)               # 왼쪽 창: 마디1 선을 2.7s로 → 시작박 0.7s
    assert abs(bs.anchor - 0.7) < 1e-9
    bs._on_drag(4, 8.5)               # 끝박 드래그 → BPM 불변, 시작박만 당겨짐(0.5s)
    assert abs(bs.anchor - 0.5) < 1e-9 and abs(bs.bar_len - 2.0) < 1e-9
    bs._on_drag(0, -0.7)              # 0초 앞으로 나가면 한 마디 안으로 되접기
    assert abs(bs.anchor - 1.3) < 1e-9
    bs._on_drag(1, 2.5)               # 시작박 0.5s로 복귀
    # BPM(간격) 직접 입력 — 시작박 유지
    bs.bpm_edit.setText("96")
    bs._on_bpm_edited()
    assert abs(bs.bar_len - 2.5) < 1e-9 and bs.bpm_edit.text() == "96.0"
    bs.bpm_edit.setText("120")
    bs._on_bpm_edited()
    assert abs(bs.bar_len - 2.0) < 1e-9 and abs(bs.anchor - 0.5) < 1e-9
    # 드래그를 놓으면 그 마디선 위치부터 재생
    bs._on_drag_end(1)
    assert bs.playhead.is_playing(), "드래그 종료 후 재생 안 됨"
    assert abs(bs.playhead.position_sec() - 2.5) < 0.05, bs.playhead.position_sec()
    bs.pause()
    bars_before = list(tl3.bar_times)
    assert tl3.bar_times == bars_before, "드래그만으로 재격자화됨"
    bs._on_confirm()                  # 확정 → 멈춤+재격자화+잠금, 화면 유지
    assert not bs.playhead.is_playing()
    assert bs._locked and not bs.zoom_l.isEnabled(), "확정 후 편집부 잠금 안 됨"
    assert tl3.bpm == 120.0 and tl3.bar_times == [0.5, 2.5, 4.5, 6.5, 8.0], \
        (tl3.bpm, tl3.bar_times)
    assert [s.chord.name for s in tl3.segments] == ["C", "F"]
    assert tl3.segments[1].start_sec == 4.5 and tl3.segments[1].scale_name == "F 리디안"
    assert all(s.example for s in tl3.segments), "재격자화 후 리프 미굽기"
    assert bs.grid.count() > 0, "확정 후 코드 목록 미갱신"

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
    assert tl3.loops == [{"name": "인트로", "start_bar": 0, "end_bar": 2, "on": True}]
    assert bs.loops_row.count() == 1
    bs._loop_press(1)                         # 1마디 루프: 나갔다 복귀
    bs._loop_drag_to(0)
    bs._loop_drag_to(1)
    assert bs._drag_loop and bs._highlight_bars() == {1}
    bs._loop_release()
    app.processEvents()
    assert tl3.loops[1] == {"name": "인트로", "start_bar": 1, "end_bar": 1, "on": True}
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

    # 확정 후 코드 수정 → 조정 완료가 잠금 상태면 재격자화 생략(수정 보존)
    bs._apply_chord(tl3.segments[0], "Am")
    assert tl3.segments[0].chord.name == "Am"
    bs._on_done()
    assert win.stack.currentWidget() is win.score
    assert tl3.segments[0].chord.name == "Am", "조정 완료가 코드 수정을 덮어씀"

    # 메인 화면 루프 사이드바(§6): 루프 리스트 + 루프별 ON/OFF + 재생 루프백
    win.score.practiceRequested.emit()
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

    # 건반 중앙 간격 — 왼손(C3~B3)|오른손(C4~B5) 시각 분리(B3|C4)
    pw = ms.piano
    pw.resize(900, 220)
    _wm, _x0, _y0, _kw, _kh = pw._geometry()
    assert _wm[0] == 48 and _wm[-1] == 83          # C3~B5
    _i = _wm.index(60)                              # C4 앞에 간격
    _gap = pw._wx(_i, _wm, _x0, _kw) - (pw._wx(_i - 1, _wm, _x0, _kw) + _kw)
    assert _gap > 0.5 * _kw, _gap
    # 보정 결과는 캐시 JSON에 영속(원자료 포함)
    d3 = _TL.from_dict(tl3.to_dict())
    assert d3.beat_times == tl3.beat_times and d3.bar_times == tl3.bar_times

    # 파형 피크(분석 WAV → 박자 조정 확대바)
    import wave as _wv, struct as _st, os as _os, tempfile as _tmp
    from gui.beat_screen import _wave_peaks
    fd, wavp = _tmp.mkstemp(suffix=".wav"); _os.close(fd)
    with _wv.open(wavp, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
        f.writeframes(_st.pack("<h", 12000) * 22050)     # 1초, 일정 진폭
    peaks = _wave_peaks(wavp, 0.0, 1.0)
    assert peaks and all(-1.0 <= lo <= hi <= 1.0 for lo, hi in peaks)
    assert abs(peaks[0][1] - 12000 / 32768) < 1e-6, peaks[0]
    assert _wave_peaks("no_such.wav", 0.0, 1.0) == []    # 캐시 유실 → 파형 생략
    _os.remove(wavp)

    # 세션 저장/불러오기 — 분석 1회 결과를 링크 화면 파일입력으로 즉시 로드(재분석 없음)
    fd, sess = _tmp.mkstemp(suffix=".json"); _os.close(fd)
    tl3.save_json(sess)
    win._start_build(sess)
    assert win.stack.currentWidget() is win.beat, "세션 로드 후 박자 화면 아님"
    assert win._timeline is not tl3 and win._timeline.bpm == tl3.bpm
    assert len(win._timeline.segments) == 2 and win._timeline.scale_riffs
    assert win._timeline.chord_spans == tl3.chord_spans   # 원자료도 복원 → 재보정 가능
    _os.remove(sess)

    # §6 라이브러리: 저장 폴더의 세션(.json) 카드 — 클릭 한 번 재개
    lib_dir = _tmp.mkdtemp()
    win.link_screen.set_save_dir(lib_dir)
    win.link_screen.refresh_library()
    assert win.link_screen._lib_list.count() == 1        # "저장된 세션 없음"
    tl3.save_json(_os.path.join(lib_dir, "demo.json"))
    win.link_screen.refresh_library()
    assert win.link_screen._lib_list.count() == 1
    card = win.link_screen._lib_list.itemAt(0).widget()
    assert tl3.key.split()[0] in card.text() and "BPM" in card.text()
    for i in range(1, 8):
        tl3.save_json(_os.path.join(lib_dir, f"demo_{i}.json"))
    win.link_screen.refresh_library()
    win.resize(1040, 740)
    win.link_screen.stack.setCurrentWidget(win.link_screen._input)
    win.stack.setCurrentWidget(win.link_screen)
    app.processEvents()
    assert win.link_screen._lib_list.count() == 8
    assert all(
        win.link_screen._lib_list.itemAt(i).widget().height()
        >= win.link_screen._lib_list.itemAt(i).widget().sizeHint().height()
        for i in range(8)
    ), "최근 세션이 많을 때 카드 높이가 눌림"
    link_content = win.link_screen.findChild(QWidget, "compactContent")
    assert win.link_screen._input.height() <= link_content.height(), \
        "최근 세션이 많을 때 링크 입력 화면이 콘텐츠 영역을 넘음"

    # §6 연습하며 기다리기: 분석은 백그라운드, 링크 화면은 세션 열기만 활성
    win.analyzing._set_steps(50)                          # 단계 체크리스트 매핑
    st = [l.text()[0] for l in win.analyzing._step_lbls]
    assert st == ["✓", "●", "○", "○"], st
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
    assert not win._pill.play_btn.isHidden() and tl_bg.scale_riffs
    win._play_pending()                                   # → 그 곡의 박자 조정
    assert win.stack.currentWidget() is win.beat and win._timeline is tl_bg
    assert not win._bg_wait and win._pill.isHidden()
    assert win.link_screen.url_edit.isEnabled()

    # 입장 애니메이션 헬퍼 — 헤드리스에서 예외 없이 동작
    from gui.anim import stagger as _stagger
    _stagger([ms.play_btn, ms.lane])

    print("\nSMOKE OK — 스케일/악보+수동수정/리프동기재생/리프불변식(1마디·스케일안·밀도·해결·음역)/채점UI/보정/난이도/리프일치/마디선+확정잠금/루프정의·사이드바/건반간격/파형·세션/애니메이션 정상")


if __name__ == "__main__":
    main()
