# ScaleRiff 학습 시스템 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 승인된 개선안 1~6과 과제별 점수제를 기존 앱에 통합하고 개선/검증 기록을 유지한다.

**Architecture:** Timeline에 원자료·시간 기반 수정과 비트 변환을 유지한다. MIDI 이벤트와 연주 기록/채점은 Qt에 독립적인 모듈에 두고 MainScreen이 재생 상태와 연결한다. 학습 모델은 준비 시 실제 코드 진행에 맞춘 프레이즈를 생성한다.

**Tech Stack:** Python 3.12, PyQt6, numpy/scipy/librosa/soundfile, mido/python-rtmidi, yt-dlp, imageio-ffmpeg. 기존 의존성을 사용한다.

**Spec:** `document/IMPROVEMENTS.md`와 2026-10-20 사용자 승인.

## Global Constraints

- 사용자 수정 파일과 박자 조정→코드 편집 흐름, 최근 저장경로 표시 보존.
- 재생 틱에서 MIR/모델 생성/느린 오디오 변환 금지.
- 실제 기기/학습자 검증과 자동 테스트를 구분해 보고.
- 모든 변경은 `.venv/Scripts/python.exe`로 검증. .git 변경/커밋 없이 파일 변경으로 제공.
- 개선·추가 문제 및 잔여 한계는 `IMPROVEMENTS.md`에 먼저 기록하고 갱신.

## Review Focus

- 같은 마디 여러 코드, 한 코드가 여러 마디 지속하는 구간 편집.
- 가변 템포, 3/4, 음수 프리롤, 마지막 음의 구간 경계.
- note-off가 늦게 도착한 시킹/루프/장치 변경, 무연주 및 추가음 도배.
- 손상/구버전 세션, 저장 실패, 원본 오디오 경로 이동.
- 평가 데이터 곡 누출과 모델 미설치/부트스트랩 폴백.

## Task 1: 음악 시간축과 보정 보존 (MUS-01/02/04)
Files: analyze/structure.py, player/timeline.py, build/real_builder.py, gui/beat_screen.py, ml/generate.py, tests_music_integrity.py.
Interfaces: Timeline.beat_at(sec), time_at_beat(beat), beats_between(start,end); chord_overrides=[start,end,name]; bar chord 편집은 실제 시간 범위에 적용.
- [x] 같은 마디 두 코드/수정 후 재격자화/비트 왕복/구간 길이 테스트 RED.
- [x] 코드 시점 유지, 수동 오버라이드 합성, 루프 원본 시간 보존, 3/4 및 가변 박자 리프 배치 구현.
- [x] tests_music_integrity + 기존 smoke/key/countin GREEN.

## Task 2: 이론 일관성 (MUS-03)
Files: analyze/theory.py, analyze/harmony.py, ml/representation.py, ml/generate.py, gui/beat_screen.py, tests_music_integrity.py.
Interfaces: 코드 품질별 지원 스케일명/음 집합은 전역 정의를 공유한다.
- [x] dim7/aug의 안내·리프 일치 RED.
- [x] 디미니시드/온음 스케일 명시 및 현재 기본 추천 설명 구현.
- [x] dim7/aug와 기존 코드 회귀 GREEN.

## Task 3: 저장·문서·환경 (SYS-01/02)
Files: player/timeline.py, gui/app.py, README.md, requirements.txt, .vscode/*.json, document/scaleriff_system_definition.md, tests_session_storage.py.
Interfaces: schema_version, analysis_info/model_info; save_json atomic; load_json 구세션 호환; 사용자 저장 상태 표시.
- [x] 저장 실패 시 이전 파일 보존·버전/미디어 재연결·구세션 RED.
- [x] 원자 저장·메타데이터·저장 실패 알림·실행설정 구현.
- [x] 세션 회귀 GREEN; 실제 설치 환경 문서 갱신.

## Task 4: MIDI와 재생 (IO-01/02)
Files: player/midi_input.py, player/note_synth.py, player/playhead.py, player/audio_stretch.py, gui/app.py, gui/main_screen.py, player/performance.py, tests_midi_audio.py.
Interfaces: note_event(dict) pitch/on/velocity/channel/time/pedal; 기존 note_received 호환; NotePlayer.note_on/note_off/set_pedal/stop_all; Playhead.set_rate(rate), set_volume(volume), source time 유지.
- [x] 이벤트 강약/페달/음길이·0.75배 원본 시각·정지/seek 안전 RED.
- [x] 장치 선택/재연결·독립 음량·음정 유지 재생·연주 캡처 구현.
- [x] 입출력/시간축 GREEN; 실제 기기 가능 여부 기록.

## Task 5: 연습 흐름·점수 (EDU-01/SCORE-01/02)
Files: player/performance.py, player/scoring.py, player/timeline.py, gui/main_screen.py, tests_scoring.py, tests_learning_flow.py.
Interfaces: PerformanceRecorder handles note events/source sec, score_performance(timeline,notes,mode,level,start,end,goal); practice history with notes/summary; 단계 listen/copy/vary/free/review.
- [x] 리프 1:1 매칭·누락/추가·무연주·경과음·시킹 무효화 RED.
- [x] 연습구간/단계 UI, 녹음/재청취, 점수/근거/다음 목표, 기록 저장 구현.
- [x] UI 연습→채점→저장/복원 통합 GREEN.

## Task 6: 진행 조건 생성·평가 (AI-01/02)
Files: ml/generate.py, ml/model.py, ml/train/prepare_phrases.py, ml/train/train_markov.py, ml/evaluate.py, gui/main_screen.py, tests_ml_context.py.
Interfaces: bake_progression(timeline,model,start,end,goal,variant,density); 원곡/솔로 ID와 안정적 곡 단위 split, 평가 보고 JSON/MD.
- [x] 2마디 진행·목표 착지·스케일게이트·출처/곡 분리 RED.
- [x] 실제 진행 프레이즈·변주/밀도 조건·모델 메타·세 모델 비교 구현.
- [x] 고정 평가셋 실행/보고서 저장, 재현성 GREEN.

## Task 7: 전체 검증·검토·잔여 한계 (QA-01/MUS-05)
- [x] 전체 오프라인 테스트 실행기와 실제 오디오→세션→편집→연주→점수 경로 실행.
- [x] 저장소 코드와 UI 렌더를 별도 검토. 독립 리뷰로 중요한 문제 수정.
- [x] 실제 분석기를 실행한 합성 음원 지표·모델 비교와 미검증 실기기/학습 효과를 기록.
- [x] 문서 목록의 상태·완료 근거·잔여 항목 갱신 후 결과 전달.

## Execution ledger

- 2026-10-20: 사용자 실행 승인이 있으므로 추가 승인 없이 현재 브랜치에서 순서대로 구현. 기존 수정 보존, 커밋 없이 변경 파일로 제공.

- 2026-10-21: Task 1~6 구현 및 Task 7 자동 검증 완료. 오프라인 스크립트 22/22, 최종 unittest 70/70 통과. 실제 WAV→편집→0.75배 변환→MIDI 이벤트→채점→자동 저장/복원→재청취 통합 검증.
- 독립 코드 리뷰 지적을 회귀로 재현해 수정했다. 기존 사용자 수정은 보존했으며 .git 변경/커밋은 수행하지 않았다.
- 음악 분석/AI 평가의 정확도 한계와 실기기·청감·학습 효과·네트워크·새 설치 미검증은 IMPROVEMENTS.md의 FOLLOW-01~09로 남긴다. 이 체크리스트의 완료는 해당 외부 검증까지 통과했다는 뜻이 아니다.
