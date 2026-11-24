# ScaleRiff

좋아하는 곡의 코드·키·박자를 분석하고, Markov 모델 리프로 **자유연습·리프연습**을 하는 Windows 피아노 앱.
대상: 곡은 치지만 즉흥이 낯선 중급자. 입력: MIDI 피아노 또는 화면 건반.

> **문서 규칙** — 이 파일이 프로젝트의 유일한 문서다. 키워드 중심으로 짧게 유지한다.
> 작업 로그·검증 수치·날짜별 기록·변경 이력은 쓰지 않는다(커밋 메시지에 남긴다). 끝난 Todo는 지운다.
> 상세 동작은 코드와 `tests_*.py`가 기준이다. 코드 주석의 `정의서 §N`은 삭제된 구 문서 번호다(git 이력).

## 실행

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   # uv 처음 한 번(Python 3.12도 uv가 받음)
./setup.bat                                   # .venv + 의존성(requirements-tested.txt 고정), 다시 실행해도 됨
& ./.venv/Scripts/python.exe main.py
```

- 다른 PC에서도 같게: 폰트(영문 Segoe UI = Windows 기본, 한글 = `assets/fonts/` Pretendard 동봉, [OFL 1.1](assets/fonts/OFL.txt)), madmom·Deno·ffmpeg도 `setup.bat`이 설치·동봉분 사용. `assets/backdrop.webp`·`assets/stage_backdrop.webp`(연주 무대)·`assets/fonts/`·`wheels/`는 저장소에 포함해야 한다.
- madmom(학습 모델 비트·코드 인식, librosa보다 정확하지만 분석이 수 배 느림): `wheels/`의 미리 빌드·패치한 휠(Python 3.12 x64)로 빌드 도구 없이 설치, 휠이 없으면 Visual Studio C++ 빌드 도구로 소스 빌드, 둘 다 없으면 librosa. 모델은 비상업 CC BY-NC-SA 4.0(휠 안 `madmom/models/LICENSE`). 건너뛰기: `set SCALERIFF_NO_MADMOM=1`.
- YouTube 링크 입력용 Deno는 의존성(`yt-dlp[deno]`)으로 `.venv`에 함께 설치된다. 로컬 음원은 불필요.
- 리프 모델 `models/markov.json`은 저장소에 포함 — [Weimar Jazz Database](https://jazzomat.hfm-weimar.de)(Jazzomat Research Project, HfM Weimar)에서 만든 통계표로, 원본과 같은 [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)을 따른다. 재학습은 `ml/train/`.
- 연주음 `assets/piano/*.flac`은 [Salamander Grand Piano](https://github.com/sfzinstruments/SalamanderGrandPiano)(Alexander Holm, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/))를 음역·포맷만 바꿔 만든 것 — `tools/build_piano_samples.py`.
- 건반 소리 `assets/piano/`는 [Salamander Grand Piano](https://github.com/sfzinstruments/SalamanderGrandPiano)(Alexander Holm, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/))의 v10 샘플을 변형(모노·44.1kHz·6초, 사이 음 리샘플)한 것. 재생성은 `tools/build_piano_samples.py`.

검사: `$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'; & ./.venv/Scripts/python.exe tools/run_checks.py` (`--network`: YouTube 포함)
평가: `& ./.venv/Scripts/python.exe -m ml.evaluate`, `& ./.venv/Scripts/python.exe tools/evaluate_music.py`(librosa 고정) → 보고서는 `cache/`에 생성.

## 사용 흐름과 기술

| 단계 | 기능 | 기술 · 모듈 |
|---|---|---|
| 1. 곡 입력 | YouTube 링크 / 로컬 오디오 / 세션 JSON, 최근 저장경로, 세션 캐시 재사용 | yt-dlp(+Deno), imageio-ffmpeg · `ingest/audio_source`, `gui/link_screen` |
| 2. 분석 | 비트·다운비트·키·코드(장/단 3화음) 추정, 별도 프로세스·취소 | madmom(설치 시) → librosa 폴백 · `ingest/mir_extract`, `analyze/*`, `gui/analysis_job` |
| 3. 학습 설정 | 곡 전체 스케일 1개(펜타토닉·키 7음·블루스, 추천 = 부딪히는 음(코드톤 반음 위 어보이드) 최소·동률은 펜타 우선, 코드톤이 하나도 안 걸리는 코드가 있으면 비활성, 키 밖 코드는 로컬 스케일)만 고른다 — 연습은 자유연습으로 시작 | `Timeline.apply_song_scale`·`practice` · `gui/setup_screen` |
| 4. 연습 | 자유연습(기본)·리프연습, 리프모드(리프는 이때만 생성 — 분석·박자·코드 수정 중엔 안 굽는다. 곡 처음~끝 4마디마다 1마디 리프(리프당 5~6음 고정)를 프로그램·나·프로그램·나로 같은 음 그대로 주고받음, 블록 안 코드 스케일 공통음 사용(4개 미만이면 코드별 스케일), 정박·긴 음은 반복 마디 코드톤과 반음 충돌 피함, 리프 생성 창의 '3도 착지 섞기'·'7도 착지 섞기' 체크 = 블록이 기본 → 3도 → 7도 리프로 순환(켠 것만, 목표음이 스케일에 없는 코드는 코드톤 착지, 3화음의 7도 = 스케일 안 단7·장7, 착지음은 프로그램 마디 기준, 그 블록에서만 건반 목표음 초록), 설정 조건으로 생성·재생성·확정 → 리프연습, 진입·해제 시 곡 처음으로), 오른손 2옥타브(C4~B5, 밖의 MIDI 음은 소리만), 원근 하이웨이 무대(참고 이미지 실측 비율, 3D 건반·레인, 내 차례 노드 = 제 색 유리판+밝은 모서리+은은한 번짐·근음 별빛(앞면 윗모서리, 서서히 밝아졌다 잦아듦), 네온 레일선+박자에 맞춰 흐르는 바깥 점선, 건반 아래 원근 받침 패널 안 재생바(재생/일시정지·마디 눈금), 리프모드만 낙하 노드(프로그램 차례 = 늘 소리·판정 없음·노드 어둡고 투명·레인 어둡게, 내 차례 = 리프음 무음(친 음만 소리)·노드 불투명 선명), 정적 레이어 캐시, 실제 화면은 OpenGL 창(셰이더·vsync)+HUD 투명 창·안 되면 CPU(`SCALERIFF_STAGE=cpu`))·상단 현재/다음 코드·왼쪽 위 <·제목·키|BPM, 오른쪽 위 ⚙·리프모드(배경 없는 흰 아이콘 — 모든 화면 ←·⚙ 공통, 리프모드는 AI를 순환 화살표가 감쌈·켜지면 보라)·스페이스=재생+재생바·건반 번호(곡 스케일 주음=1 곡 내내 고정, 예외 구간 ♭/♯, 예비박에도 표시)·지금 코드 근음·코드톤 강조(진한 파랑+원 숫자, 고른 스케일 밖 근음·코드톤은 강조·번호 없음 — 펜타면 5음만)·연주화면 진입마다 단계별 화면 가이드(건너뛰기) | order-2 백오프 Markov(WJazzD 학습 → 부트스트랩 → 규칙) `bake_progression`, Qt FFmpeg, mido/python-rtmidi, 내장 신스 · `gui/main_screen`, `gui/riff_dialog`, `gui/widgets/play_guide`, `gui/widgets/gl_stage`, `player/` |
| 5. 박자 조정(⚙) | 연주화면 설정(⚙)에서 연다(분석 직후엔 생략·자동 추정 격자), 확인 → 학습 설정, ← = 적용 없이 연주화면. 한 화면 세로 3단계(코드시작 → 코드종료(끝 핸들, 마디선 스냅, 이후는 재생만·파형 흐리게) → 예비박 1~N마디), 다음 단계는 흐리게·비활성, Enter 다음·Backspace 이전·이전 단계 조작 시 아랫단계 재비활성. 상단 박자·BPM·자동추정값 초기화(BPM Enter 시 커서 해제). 초기 격자 = 보정 비트(±8박 국소 회귀, 점선과 동일), BPM 지정 시 균등 격자, 비트 자석 스냅, 1단계 마디선 드래그 = 음원을 끌기(선은 제자리, 창 밖까지), 끝 핸들은 놓으면 창이 끝선 기준으로 이동, 격자는 음원 앞뒤 5초 이내, 파형은 곡별 크기 정규화(상위 0.5% 진폭), 재생은 스페이스(1마디부터)·드래그 후 놓을 때(끄는 동안 정지), 재격자화 | QSoundEffect · `build/real_builder`, `gui/beat_screen` |
| 6. 코드 편집(⚙) | 연주화면 설정의 '코드 수정' 창: 마디 내 다중 코드, 시간 기반 수정, 키 변경 — 확인=반영 후 키 재추정(직접 고른 키 제외, 나란한조는 으뜸화음 길이로)·새로고침한 학습 설정으로, 취소=되돌림(연주화면 유지) | `Timeline.chord_overrides` · `gui/beat_screen` |
| 7. 저장 | 세션 JSON v2 + 원본 음원만 남김(파형 피크는 JSON, 분석 WAV는 분석 후 삭제), 원자 저장, 구버전 호환, 미디어 재연결 | `player/timeline` |

## 원칙

- `Timeline`이 단일 상태. 모든 시각은 원본 오디오 초.
- 재생 틱에서 분석·생성 금지(준비/사용자 액션 시 수행).
- 자동 분석은 추정 → 사용자 수정이 우선.
- UI: 남색 그라데이션 배경(창 공통 `Backdrop`)·파랑 그라데이션 주 버튼·둥근 카드, 토큰은 `gui/theme.py`. 지금 코드 근음 진한 파랑·코드톤 파랑·스케일 연한 파랑, 번호는 곡 스케일 주음 기준.

## Todo

- 테스트 갱신: `tests_play_guide`(가이드가 커튼 뒤에 뜸·4단계·근음 색), `tests_smoke`(학습 설정 제목), `tests_falling_notes`(건반 프레임 예산) — 현재 코드와 어긋나 실패
