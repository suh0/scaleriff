# ScaleRiff

좋아하는 곡(YouTube 링크/로컬 파일) 위에서 **코드에 맞는 스케일을 익히는** 데스크톱 앱.
곡을 분석해 코드·키·스케일을 배정하고, WJazzD로 학습한 모델이 스케일마다 짧은 **리프**를
생성한다. 사용자는 가이드/리프연습 모드로 연주하고, 루프 1주기(패스)마다 채점 요약을 받는다.
연습 성적은 다음 리프 재생성의 난이도에 반영된다(학습 루프).

> **전체 사양은 [`document/scaleriff_system_definition.md`](document/scaleriff_system_definition.md)가 단일 출처.**
> 코드 주석의 `§`번호는 그 문서를 가리킨다.

## 아키텍처: 빌드 → 플레이어
모든 분석·생성을 **빌드 단계에서 한 번에 굽고**(pre-bake) 세션 타임라인을 만든 뒤,
화면들은 그 타임라인의 **뷰/플레이어로만** 동작한다. 재생·스크럽 중 재분석·재추론 없음(§4).

```
소스 → 오디오 확보 → MIR(코드·키·BPM·다운비트) → 구조(루프) → 화성(스케일 배정)
     → Timeline → 리프 굽기(스케일 종류당 1개) → ★세션★ → 플레이어(재생·채점·룩업만)
```

## 설치 (Windows, Python 3.11 고정)
> python-rtmidi가 3.14와 비호환 → **3.11 고정**.
```powershell
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```
시스템 ffmpeg 불필요(`imageio-ffmpeg` 동봉 바이너리 사용). madmom(비트·코드 학습모델)은
선택 — 미설치 시 librosa 폴백. 설치 절차는 `requirements.txt` 주석 참고.

## 실행
```powershell
venv\Scripts\python.exe main.py
```
링크/파일을 넣고 분석 → 박자 조정 → 악보 → 메인 플레이어. 소스 없이 *데모 타임라인*으로
둘러보기 가능. MIDI 키보드는 자동 연결(mido), 없으면 화면 피아노를 마우스로 클릭.

## 모듈 구성 (기능별)
```
build/    빌드 파이프라인 — 소스 → 세션 타임라인 (§2.2)
          timeline_builder(라우터)  real_builder(실제 파이프라인 + 마디선 재격자화)

ingest/   오디오·MIR 입력 (§3.1)
          audio_source(yt-dlp/파일→모노 WAV)  mir_extract(코드·키·BPM·비트·다운비트)
          _madmom_compat(numpy/collections 옛 별칭 셰임 — madmom import 전 필수)

analyze/  음악 이론·분석 (§3.2–3.3)
          theory(pc·코드파싱·스케일·도수 — 전역 이론층)  structure(마디격자·루프감지)
          harmony(홈키·전조·디투어 → note_set)

ml/       리프 생성 (§8)
          representation(16분 그리드 토큰, 코드 근음 상대 도수)  model(백오프 Markov)
          generate(구조 생성기 + 모델 prior + PMI 랭킹, bake/rebake)
          practice_log(연습기록 — 학습 루프 폐회로)  train/(오프라인 WJazzD 학습)

player/   재생·상태·채점 (§5, §7.5, §9)
          timeline(세션 스키마 = 단일 상태)  playhead(오디오 재생/seek)
          scoring(존 판정·패스 집계, Qt 비의존)  note_synth(연주/리프 신스)
          midi_input(mido)  dummy_timeline(데모)

gui/      PyQt6 화면 (§6, 디자인 단일출처 theme.py)
          app(화면 흐름)  link/analyzing/beat/score/main_screen  theme  anim
          widgets/(piano chord_lane scrub_bar riff_roll riff_view mini_guide
                   pass_card countin)
```

## ML 모델
- 런타임: **order-2 백오프 Markov**(`models/markov.json`, torch 불필요). 없으면 부트스트랩
  `models/default_markov.json`(git 추적) 폴백 — 무데이터에도 앱 동작.
- 표현은 **코드 근음 기준 상대 도수**(키 독립). 생성은 구조(리듬 셀·AA'·컨투어·앵커)가
  품질 하한, 모델이 도수 prior + 리듬 통계 + PMI 후보 랭킹.
- 데이터 학습/재학습: **`ml/train/README.md`** 참고 (WJazzD 단일 소스).

## 자가 점검
```powershell
$env:PYTHONUTF8="1"; $env:QT_QPA_PLATFORM="offscreen"
venv\Scripts\python.exe tests_smoke.py      # UI/타임라인/흐름 + 리프 불변식
venv\Scripts\python.exe tests_ml.py         # 표현/학습/게이트/폴백
venv\Scripts\python.exe tests_scoring.py    # 존 판정·패스·밀도페널티
venv\Scripts\python.exe tests_mir.py        # 합성 오디오 MIR
venv\Scripts\python.exe tests_analyze.py    # 구조·화성
```
