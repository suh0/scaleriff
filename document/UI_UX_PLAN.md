# ScaleRiff UI/UX Implementation Plan

> 실행: 현재 작업 폴더에서 직접 구현한다. 기존 미커밋 수정을 보존하고, UI 관련 파일은 `cache/ui_ux/source_before`에 복사한다. Git 커밋/브랜치 변경은 포함하지 않는다.

**Goal:** 다크 스튜디오 방향으로 전체 화면 구성과 상호작용을 일관되게 개선한다.

**Architecture:** 기존 PyQt6 화면과 데이터/신호 연결을 유지한다. 공통 theme/anim과 진행 표시를 공유하고 화면별 레이아웃·그리기를 조정한다.

**Tech Stack:** Python 3.12, PyQt6, 기존 `.venv`; 새 의존성 없음.

**Spec:** [UI_UX.md](UI_UX.md)

## 공통 제약

- 최근 경로 읽기 전용, 박자→코드 순서, 현재 피아노 배지/하단 예고 유지.
- 음악/채점/세션 알고리즘은 수정하지 않는다.
- `PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen`, `.venv/Scripts/python.exe` 사용.

## 검토 중점

- 반복 화면 전환 시 삭제된 Qt 효과 참조나 잠금 opacity 손실.
- 긴 제목/경로/오류문과 많은 스케일이 컨트롤을 창 밖으로 밀어내는 경우.
- 창 크기 변경 후 낙하 노트와 실제 건반 x/y 정렬.
- 효과 축소 상태에서도 안내/선택/분석 상태 식별.
- 기존 코드/루프/학습/채점/저장 복원 동작.

## 1. 공통 토큰·전환·단계 안내

- [x] `tests_ui_ux.py`: 효과 중복, 효과 축소, 좁은 입력, 전체 연주 공간의 회귀 검사 RED 확인.
- [x] `gui/theme.py`, `gui/anim.py`, `gui/widgets/flow_header.py`: 화면 폭·폰트·상태 스타일, 소유권이 안전한 180ms 전환, 저장 가능한 효과 축소.
- [x] 같은 회귀 검사 GREEN 확인.

## 2. 준비·편집 화면

- [x] `gui/link_screen.py`, `gui/analyzing_screen.py`, `gui/beat_screen.py`: 입력·분석 단계·박자 안내·코드 표 개선.
- [x] `gui/score_screen.py`: 목록/피아노롤 분리, 많은 항목 스크롤·빈 상태.
- [x] 스모크의 과거 75% 비율 단언을 새 공간 사용 계약으로 갱신. 저장/박자 흐름 단언은 유지.

## 3. 연주와 세부 상호작용

- [x] `gui/main_screen.py`, `gui/app.py`: 공간 배분·범례·피드백·설정·팝업 일관성.
- [x] `gui/widgets/falling_notes.py`, `chord_lane.py`, `scrub_bar.py`: 시간 기반 안내선·음표 명암·hover/시킹 피드백.
- [x] 기존 낙하/스케일 예고/학습 흐름 검사 통과.

## 4. 렌더·검증·관리 기록

- [x] `tools/capture_ui.py`: 사용자 설정/세션을 건드리지 않는 더미 렌더와 크기별 사진.
- [x] 주요 화면·설정·실패·많은 스케일의 실제 PNG 확인 및 잘림 수정.
- [x] 전체 오프라인 검사, compileall, diff 공백 검사.
- [x] 결과·미검증 한계를 `UI_UX.md`, `IMPROVEMENTS.md`에 기록하고 README에서 연결.

## 완료 기록 — 2026-10-21

- 전체 unittest 84/84, 실제 진입점 오프라인 검사 23/23 통과.
- 960×700~1600×1000의 4종 창, 11개 상태의 PNG 44개 생성 및 대표 화면 확인.
- 독립 검토의 실제 박선 정렬·스크롤 내부 배경·숫자 입력 화살표 문제 수정 및 재확인.
- 새 UI 회귀 14건, compileall과 diff 공백 검사 통과. 근거·사진·남은 실사용 검증은 UI_UX.md 참조.
