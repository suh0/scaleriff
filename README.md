# ScaleRiff

좋아하는 곡의 코드·키·박자를 분석하고, Markov 모델 리프로 **자유연습·리프연습**을 하는 Windows 피아노 앱.
대상: 곡은 치지만 즉흥이 낯선 중급자. 입력: MIDI 피아노 또는 화면 건반.

> **문서 규칙** — 이 파일이 프로젝트의 유일한 문서다. 키워드 중심으로 짧게 유지한다.
> 작업 로그·검증 수치·날짜별 기록·변경 이력은 쓰지 않는다(커밋 메시지에 남긴다). 끝난 Todo는 지운다.
> 상세 동작은 코드와 `tests_*.py`가 기준이다. 코드 주석의 `정의서 §N`은 삭제된 구 문서 번호다(git 이력).

## 실행

```powershell
py -3.12 -m venv .venv
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt -c requirements-tested.txt
& ./.venv/Scripts/python.exe main.py
```

검사: `$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'; & ./.venv/Scripts/python.exe tools/run_checks.py` (`--network`: YouTube 포함)
평가: `python -m ml.evaluate`, `python tools/evaluate_music.py` → 보고서는 `cache/`에 생성.

## 사용 흐름과 기술

| 단계 | 기능 | 기술 · 모듈 |
|---|---|---|
| 1. 곡 입력 | YouTube 링크 / 로컬 오디오 / 세션 JSON, 최근 저장경로, 세션 캐시 재사용 | yt-dlp(+Deno), imageio-ffmpeg · `ingest/audio_source`, `gui/link_screen` |
| 2. 분석 | 비트·다운비트·키·코드(장/단 3화음) 추정, 별도 프로세스·취소 | librosa(madmom 선택) · `ingest/mir_extract`, `analyze/*`, `gui/analysis_job` |
| 3. 박자 조정 | 한 화면 세로 3단계(코드시작 → 코드종료(끝 핸들, 마디선 스냅, 이후는 재생만·파형 흐리게) → 예비박 1~N마디), 다음 단계는 흐리게·비활성, Enter 다음·Backspace 이전·이전 단계 조작 시 아랫단계 재비활성. 상단 박자·BPM·자동추정값 초기화(BPM Enter 시 커서 해제). 초기 격자 = 보정 비트(±8박 국소 회귀, 점선과 동일), BPM 지정 시 균등 격자, 비트 자석 스냅, 1단계 마디선 드래그 = 음원을 끌기(선은 제자리, 창 밖까지), 끝 핸들은 놓으면 창이 끝선 기준으로 이동, 격자는 음원 앞뒤 5초 이내, 파형은 곡별 크기 정규화(상위 0.5% 진폭), 재생은 스페이스(1마디부터)·드래그 후 놓을 때(끄는 동안 정지), 재격자화 | QSoundEffect · `build/real_builder`, `gui/beat_screen` |
| 4. 코드 편집 | 마디 내 다중 코드, 시간 기반 수정, 키 변경, 루프 | `Timeline.chord_overrides` · `gui/beat_screen` |
| 5. 학습 설정 | 곡 전체 스케일 1개(펜타토닉 추천·키 7음·블루스, 키 밖 코드는 로컬 스케일), 자유연습/착지음(1·3·7도·코드톤 중 곡 전체에서 가능한 것만), 코드당 음 개수(사용안함·고정·범위) | `Timeline.apply_song_scale`·`practice` · `gui/setup_screen` |
| 6. 연습 | 자유연습·리프연습, 착지음 방식은 목표음만 초록, 리프학습모드(루프 또는 현재 마디부터 4마디, 설정 조건으로 생성·재생성·확정 → 리프연습), 오른손 2옥타브(C4~B5, 밖의 MIDI 음은 소리만), 낙하 가이드·건반 배지·코드 레인 | order-2 백오프 Markov(WJazzD 학습 → 부트스트랩 → 규칙) `bake_progression`, Qt FFmpeg, mido/python-rtmidi, 내장 신스 · `gui/main_screen`, `gui/riff_dialog`, `player/` |
| 7. 저장 | 세션 JSON v2 + 원본 음원만 남김(파형 피크는 JSON, 분석 WAV는 분석 후 삭제), 원자 저장, 구버전 호환, 미디어 재연결 | `player/timeline` |

## 원칙

- `Timeline`이 단일 상태. 모든 시각은 원본 오디오 초.
- 재생 틱에서 분석·생성 금지(준비/사용자 액션 시 수행).
- 자동 분석은 추정 → 사용자 수정이 우선.
- UI: 다크 스튜디오, 토큰은 `gui/theme.py`. 근음 파랑·코드톤 초록·스케일 회색.

## Todo

- [ ] 다운비트 위상 정확도(합성 타악 음원에서도 실패)
- [ ] 템포 ½·2배 오인식 자동 판단 없음(BPM = 비트 간격 그대로) — 박자 화면에서 사용자가 BPM으로 보정
- [ ] 연습 화면 예비박 시작점은 BPM 균등 외삽(검출 비트 격자와 수 ms 차이)
- [ ] 박자 조정: 메트로놈 실제 출력 지연 미측정
- [ ] 코드 인식: 3화음 어휘 한계, 7th·altered 확장 — 그 전까지 7도 착지는 항상 비활성
- [ ] 착지 부담 완화(착지 간격·짧은 코드 제외·다음 목표 미리보기) 미정
- [ ] 곡 스케일은 키 하나 기준 — 전조 구간(디투어 아님)에도 같은 스케일 적용
- [ ] 메인 화면 실시간 채점(작업 중)
- [ ] `bake_examples`(코드 근음 이조)는 박자/코드 화면에서 여전히 굽지만 곡 스케일 적용 시 버려짐 — 정리 판단
- [ ] 한 마디 한 코드(최다 점유) — 마디 중간 코드 변경 소실, 2코드/마디 곡 대응
- [ ] 실제 MIDI 기기: 지연·페달·재연결·청감
- [ ] 연주음 note-off 팝: 80ms 페이드로 완화(청감 미확인), 페이드 중 같은 음 재타건 팝은 남음 — 키당 보이스 2개 교대
- [ ] 재학습 모델 리듬(온셋) 품질 개선 후 교체 판단
- [ ] 스윙·3/4·복합박자 데이터와 검증
- [ ] 실제 모니터 DPI 배율(100~200%) 확인
- [ ] 새 환경 설치 재현
- [ ] 전환·확정 로딩 오버레이(흐림+스피너): 실제 창에서 흐림 품질·스피너 끊김 확인
