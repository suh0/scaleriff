# 즉흥연주 트레이너 — 음악과 대화하기

초보자가 좋아하는 곡(링크/파일) 위에서 **콜 앤 리스폰스**로 즉흥연주를 배우는 데스크톱 앱.
앱이 짧은 프레이즈를 "부르면(콜)" 사용자가 MIDI 키보드로 "받아친다(리스폰스)".
어떤 음이 잘 통하는지는 **데이터로 학습한 ML 모델의 우도**로 안내한다.

> 설계 근거: `../claude_code_build_brief.md` (이 구현은 그 브리프대로 처음부터 작성됨)

## 아키텍처 (핵심: 빌드 → 플레이어)
모든 분석을 **앞에서 한 번에 굽고(pre-bake)** 세션 타임라인을 만든 뒤,
메인 화면은 그 타임라인의 **플레이어로만** 동작한다. 재생/스크럽 시 ML·재분석 없음.

```
[링크/파일] → 오디오 확보 → 코드/키/BPM·비트/다운비트(MIR) → 구조분석(루프·턴)
   → 화성분석(note_set) → ML 1회(콜 생성 + 우도 테이블) → ★세션 타임라인★
   → 메인 화면(플레이어): 재생 · 스크럽=인덱스 점프 · 친 음 우도 룩업만
```

### 비트·마디 격자 (다운비트 앵커)
마디선은 BPM 고정 간격이 아니라 **다운비트 트래킹**으로 앵커링한다(첫 다운비트 기준, t=0 가정 안 함).
코드 변경 시각은 비트 격자에 스냅, BPM은 옥타브 오류 sanity check(70–185 범위로 보정).
- **madmom `DBNDownBeatTrackingProcessor`** 가 설치돼 있으면 자동 사용(비트+다운비트).
  Windows는 C 컴파일에 *Microsoft C++ Build Tools* 필요(requirements.txt 주석 참고).
- 미설치 시 **librosa 비트 + onset 기반 다운비트 위상 추정**으로 폴백.
- **`content_span` 시작 = 하모닉 에너지 온셋**: `librosa` HPSS 하모닉 성분 RMS가 임계를
  지속적으로 넘는 첫 지점(드럼만 있는 인트로 통과) → 가장 가까운 다운비트 스냅 +
  "코드가 ≥1마디 안정 유지" 보강. '첫 코드 라벨'을 시작점으로 쓰지 않는다. 끝은 RMS 꼬리.
  콜 격자·재생 모두 `content_span` 안에서만, 끝에서 자동 정지. (감지 시작 시각·인트로 코드 라벨 디버그 로그)

규칙(구조·키·음집합·턴)이 "언제·어떤 화성"을, ML(콜·우도)이 "어떤 음이 얼마나 잘 통하나"를 담당.

## 설치 (Windows, Python 3.11 고정)
> python-rtmidi가 3.14와 비호환이라 **3.11 고정** (브리프 §2).

```powershell
py -3.11 -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```
시스템 ffmpeg는 불필요(`imageio-ffmpeg` 동봉 바이너리로 yt-dlp 추출/디코딩 처리).

## 실행
```powershell
venv\Scripts\python.exe main.py
```
- **링크/파일**을 넣고 *분석 시작* → 분석 후 플레이어로 이동.
- 오디오 없이 둘러보려면 *데모 타임라인으로 둘러보기*.
- MIDI 키보드가 있으면 자동 연결(mido). **없으면 피아노를 마우스로 클릭**해 받아칠 수 있다.

## 화면
- **링크 입력**: 온보딩 3카드 + 링크/파일 + 장르·난이도(빌드 입력)
- **분석 중**: 타임라인 빌드 진행
- **메인(플레이어)**: 상단바(곡명·패턴·키) · 컨트롤(장르/난이도/BPM) ·
  턴박스(차례·프레이즈 길이 카운트다운·진행) · 피아노(우도 명도 그라데이션·콜 번호·반투명 콜) ·
  피드백(우도·기능·코멘트, **채점 없음**) · 스크럽바(루프 경계) · 재생
- 콜·사용자 연주음 모두 **피아노 음색**(음색 선택 없음). 친 음은 즉시 소리난다.

### 턴 모델 (프레이즈 단위 · 루프 인스턴스 동기화) — 브리프 v2
턴은 코드 구간 반쪽이 아니라 **프레이즈 단위(기본 2마디)의 연속 교대**다.
콜=현재 프레이즈, 리스폰스=다음 프레이즈. 콜/리스폰스가 서로 다른 코드를 포함할 수 있고,
한 프레이즈 안에서 코드가 바뀌면 **우도·note_set은 코드(segment) 따라 갱신**된다.
- **턴 격자는 각 루프 인스턴스 시작에 앵커링·재동기화** — 곡 처음부터 블라인드 연속
  카운트 금지(간주 등 offset 누적 방지). 각 인스턴스는 콜로 다시 시작.
- 카운트다운 점 = 턴 길이(2마디·4/4 → **8박**).
- **`free` = 구조상 콜앤리스폰스 안 하는 구간**(비루프 인트로·간주, `content_span` 밖 무음).
- **콜 번호는 콜 동안만** 표시, 리스폰스는 그 코드 우도 지도만(다른 코드라 옛 번호 무효).
- **2트랙 스키마**: `segments`(코드별 note_set/우도) / `turns`(role=call/response/free).
- 모듈: `analyze/structure.py`(루프 감지·인스턴스) · `analyze/turns.py`(턴 격자) ·
  `player/cr_engine.py`(위치→상태) · `ml/generate.py:generate_call_phrase`(멀티코드 콜).

## 난이도 = 다이얼, 장르 = 스타일
- **쉬움** 펜타토닉/코드톤 · **보통** 풀 다이아토닉 · **어려움** 게이트 해제(전체 우도, 크로마틱)
- **일반 / 재즈** — 곡과 독립적인 "콜의 즉흥 스타일" (팝 곡 위 재즈 콜 가능)
- 장르·난이도 변경 = **재빌드**(빌드 입력). 음색은 즉시 적용.

## 모듈 구성
```
ingest/   audio_source(yt-dlp/파일→WAV)  mir_extract(코드/키/BPM, 교체가능 백엔드)
analyze/  theory(코드파싱/도수)  structure(루프·턴)  harmony(note_set/디투어/전조)
ml/       representation(화성상대값)  model  generate(콜+우도+난이도게이트)
          real_builder(전체 파이프라인)  timeline_builder(라우터)  train/(오프라인 학습)
player/   timeline(§4 스키마)  playhead(재생/seek)  note_synth(연주/리프 음색)
          midi_input(mido)  dummy_timeline(데모/테스트)
gui/      app  link/analyzing/main_screen/score_screen
          widgets/(piano scrub_bar mini_guide riff_view countin)
```

## ML 모델
- 런타임 동봉: **Markov 베이스라인** `models/default_markov.json` (torch 불필요, 빌드 시 1회 추론).
- 데이터 학습/업그레이드(Weimar Jazz DB·Lakh MIDI, LSTM): **`ml/train/README.md`** 참고.
- 표현은 **코드 근음 기준 상대 음정(키 독립)** — 절대음 미사용.

## 자가 점검
```powershell
$env:QT_QPA_PLATFORM="offscreen"; venv\Scripts\python.exe tests_smoke.py   # UI/CR엔진
venv\Scripts\python.exe tests_mir.py        # 합성 오디오로 MIR
venv\Scripts\python.exe tests_analyze.py    # 구조/화성
```

## 스코프
**포함**: 링크 입력, 원본 반주, 코드/키/구조 분석, 하이브리드 우도 표시,
콜앤리스폰스(프레이즈 단위 2마디 연속 교대·프레이즈 길이 카운트다운),
난이도 다이얼, 장르 선택, 콜 음색, ML(콜+우도), 스크럽.
**비목표**: 녹음·저장, 구간반복, 왼손, 빠른 곡 콜앤리스폰스(→free), 벌스/코러스 감지, BPM 조절, 표현적 리듬, 음 단위 즉시반응, 절대음 ML.
