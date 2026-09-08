# ScaleRiff — 시스템 정의서 (2026-07 재작성)

> 이 문서가 **단일 출처**다. 코드 주석의 §번호는 이 문서를 가리키므로 절 번호는 유지한다.
> 이전 정의서·README의 콜앤리스폰스/우도 표시 서술은 폐기되었다(§10 제외 항목).

## 0. 한 줄 요약
좋아하는 곡(링크/파일) 위에서 코드에 맞는 스케일을 익히는 데스크톱 앱.
빌드 단계에서 곡을 분석해 타임라인을 굽고, WJazzD로 학습한 모델이 스케일 종류당
1개의 리프를 생성한다. 사용자는 가이드/리프연습 모드로 연주하고, 패스(루프 1주기)마다
채점 요약을 받는다. 연습 성적은 기록되어 다음 리프 재생성의 난이도에 반영된다(학습 루프).

## 1. 목표 & 타겟
- **타겟**: 양손으로 곡은 치지만 즉흥은 못 하는 중급자
- **문제**: 이론(스케일·코드) 지식과 실시간 적용 사이의 갭
- **해결**: 실제 곡 위에서 "언제 어떤 스케일이 통하는지"를 직접 쳐보며 학습.
  "외워서 다른 데 써먹을 수 있는" 반복 구조의 리프를 예시로 제공
- **기술 핵심(졸업작품)**: 채점→재생성으로 이어지는 **학습 루프**(§7.5↔§8)

## 2. 전체 워크플로우

### 2.1 화면 흐름 (`gui/app.py`, QStackedWidget)
```
[0] 링크 입력(+라이브러리) → [1] 분석 중 → [2a] 박자 조정 → [2] 악보(스케일·리프)
                                     ↓                            ↕ (←박자조정 / 연습시작→)
                          "연습하며 기다리기"(상단 알약)      [3] 메인 플레이어
```
- 저장 세션(.json) 선택 시 분석 생략, 바로 [2a]로 (§4 "한 번 구운 건 다시 안 굽는다").
- 분석은 QThread 백그라운드(`analyzing_screen.BuildWorker`). "연습하며 기다리기"를
  누르면 링크 화면(세션 열기만 활성)으로 복귀, 상단 알약이 진행률 → 완료 시 "연주하기".
- [2]→[3] 진입 시마다 세션 JSON 재저장(보정·재생성 반영) 후 `MainScreen.set_timeline`.

### 2.2 내부 파이프라인 (빌드 1회, `ml/real_builder.build_real_timeline`)
```
소스(링크/파일)
 → 오디오 확보     ingest/audio_source  (yt-dlp + 동봉 ffmpeg → 모노 WAV 22050Hz, cache/)
 → MIR             ingest/mir_extract   (코드·키·BPM·비트·다운비트·content_span)
 → 구조 분석       analyze/structure    (다운비트 마디격자, 루프 주기·위상 감지)
 → 화성 분석       analyze/harmony      (홈 키·전조·디투어 → 코드별 note_set)
 → 스케일 배정     analyze/theory       (다이아토닉→키의 모드 / 비다이아토닉→코드-스케일)
 → Timeline        player/timeline      (★세션 타임라인 — 이후 재분석 없음)
 → 리프 굽기       ml/generate.bake_examples (스케일 종류당 1개, [2] 진입 전 1회)
```

## 3. 분석 파이프라인 상세

### 3.1 MIR (`ingest/mir_extract.py`)
- **코드**: madmom 학습 모델(CNN 특징 + CRF 디코딩). 미설치 시 librosa 크로마 +
  maj/min 템플릿 argmax 폴백. Windows에서 madmom은 Py3.11 venv 빌드 필요.
- **비트·다운비트**: madmom RNN/DBN(`DBNDownBeatTrackingProcessor`, 박자 후보 3/4)
  → librosa beat_track + onset 위상 추정 폴백. **마디선은 다운비트 앵커**(t=0 가정 금지).
- **BPM**: 비트 간격 중앙값 + 옥타브 sanity(70–185로 배수 보정).
- **키**: Krumhansl–Schmuckler 프로파일, 실패 시 코드 다이아토닉 적합도 폴백.
- **content_span**: HPSS 하모닉 RMS가 임계를 지속적으로 넘는 첫 지점(드럼 인트로 통과)
  → 최근접 다운비트 스냅. 재생·패스는 이 구간 안에서만.

### 3.2 구조 (`analyze/structure.py`)
- 마디 격자 = 다운비트 시각 리스트(+곡 끝). 다운비트 부족 시 비트 격자 폴백.
- 루프 감지: 주기 후보 {1,2,4,8,16}마디, 마디별 코드 시퀀스 일치율 ≥0.8인 가장 짧은
  주기 + 시작 위상(loop_phase). 벌스/코러스 섹션 감지는 하지 않는다.

### 3.3 화성·스케일 배정 (`analyze/harmony.py`, `analyze/theory.py`)
- 홈 키는 **루프 단위로 재평가**(±1점 히스테리시스로 전조 과민 방지). 새 키 2회 연속
  일관 시 전환.
- 다이아토닉 코드 → 키의 해당 모드(C장조 Dm7→D도리안, G7→G믹솔리디안…).
  비다이아토닉 고립 → 그 코드 품질의 코드-스케일(로컬 디투어, `is_detour`) 후 홈 복귀.
- 결과: Segment마다 단일 ScaleOption(candidates[0]) + 곡 전체 등장 스케일 종류 집계.

## 3.5 사용자 보정 — 박자 조정 화면 [2a] (`gui/beat_screen.py`)
원칙: **MIR 재실행 없음, 구조 재계산만** (`ml/real_builder.regrid_timeline`).
- **마디 격자**: 처음/마지막 10초 확대 파형바 2개에서 마디선 드래그 = 격자 평행이동
  (BPM 불변). BPM은 숫자 입력으로만. 박자 3/4↔4/4 전환. **확정 시에만 재격자화** —
  anchor부터 BPM 균등 격자(템포 가변 곡은 madmom 가변 마디 정보 유실, 알려진 한계),
  구조→화성→Segment→리프 재굽기(수동 코드 수정은 유실).
- **코드표**: 칸 클릭 = 코드 수정(quality 선택지) → 해당 구간만 `bake_segment` 재굽기.
  칸 드래그 = 사용자 루프 지정(이름 입력, `Timeline.loops`에 저장, [3] 사이드바에서 ON/OFF).
- 스플릿 포인트 설정 없음 — `split_point=60(C4)` 고정.

## 4. 아키텍처 불변식
1. **빌드 → 플레이어**: 모든 분석·생성은 빌드(+보정) 시점에 굽는다. 재생·스크럽 중
   재분석·재추론 없음. 스크럽 = 인덱스 점프.
2. 리프 재생성(§8)은 사용자 액션(버튼)으로만, 그 종류의 리프·타일링만 다시 굽는다.
3. 세션은 JSON으로 저장(라이브러리) — 다시 열면 분석 생략.
4. 화면은 타임라인의 뷰일 뿐 상태를 소유하지 않는다(타임라인이 단일 상태).

## 5. 타임라인 스키마 (`player/timeline.py`, 실제 필드)
```
Timeline:
  audio_ref(재생용 경로)  wav_ref(분석 WAV, 파형용)  title  bpm  time_sig  key  key_root
  content_span[s,e]  bar_times[마디 시작 시각+끝]  beat_times  chord_spans[[s,e,name]…]
  loop_len  loop_phase  loop_override(사용자 보정, 0=감지값)
  loops: [{name, start_bar, end_bar(포함), on}…]        # 사용자 정의 루프
  split_point: 60                                        # 왼손/오른손 존 경계(C4)
  available_scales: [스케일 종류…]
  scale_riffs: { 종류: {notes:[{midi,beat_pos,dur_beats}…],   # C(루트0) 기준 상대값
                        note_set, chord_tones, quality, n_bars, variant} }
  segments: [Segment]

Segment:
  idx  start/end_sec  start/end_bar  chord(Chord)  degree("ii" 등)  is_detour
  candidates:[ScaleOption]  active                       # 현재는 후보 1개
  example: [{midi,beat_pos,dur_beats}…]                  # 리프를 근음 이조+타일링한 결과
```
- 직렬화: `to_dict/from_dict` + `save_json/load_json`. beat_times·chord_spans는
  마디선 보정의 재격자화 재료(원자료 없는 구 캐시는 보정 불가 처리).

## 6. 화면 & UI
디자인 시스템 단일 출처: `gui/theme.py` (+ `document/SCALERIFF_DESIGN_SPEC.md`).
- **[0] 링크 입력**: 로고 + 링크/파일 + 라이브러리(세션 카드) + 첫 실행 온보딩 3카드.
  백그라운드 분석 중엔 제한 모드(세션 열기만).
- **[1] 분석 중**: 단계 체크리스트(오디오 42% → 비트·코드 78% → 구조·화성 99% → 굽기)
  + 진행바 + "연습하며 기다리기".
- **[2a] 박자 조정**: §3.5. 마스터-디테일(좌 고정 편집부/우 코드표 스크롤), 확정=편집부 잠금.
- **[2] 악보**: 곡맥락 리스트(스케일 종류별 행 — 사용 코드) + 선택 종류의 **리프 피아노롤**
  (`RiffRoll`: 좌측 세로 건반 거터 C4~B5, 도수 배지 = 코드톤 초록·근음 파랑·스케일음 회색)
  + **리프 듣기**(신스 미리듣기, 리드인 250ms) + **리프 재생성 ↻**(§8 변주).
- **[3] 메인 플레이어**:
  - 코드 레인(고정 플레이헤드 34%, 블록 흐름, 다음 블록 미니 건반 미리보기, 드래그 시킹)
  - 곡 전체 스크럽 바 · 리프 뷰(리프연습 시, 도수 번호+박자 알약) · 피아노(C3–B6,
    스케일 가이드 배지, 존 분리 시각화, 친 음 호박색)
  - 하단 한 줄: 리프연습 토글 · 난이도 선택기(없음/Lv1/Lv2/Lv3) · 루프 사이드바(ON/OFF,
    켜진 루프 끝→시작 반복) · 실시간 적중률 배지 · 카운트인(다음 코드 4박 전 점등) · 재생
  - 패스 요약 카드: 패스 경계에서 수 초 표시 후 페이드아웃

## 7. 모드
- **가이드**: 스케일 가이드 풀 표시, 존별 채점 + 난이도 Lv 적용.
- **리프연습(practice)**: 리프 뷰 표시 + **리프가 재생 헤드에 동기로 재생**되고,
  채점은 리프 일치도만(난이도 선택기 비활성).
- 모드와 난이도는 직교. 채점 기준은 모드를 따라가고, 전환 시 진행 중 패스 무효화.
- 리프 재생 구현: `MainScreen._build_riff_events`가 모든 seg.example을 (절대초, midi)로
  펼쳐 정렬해 "곡에 구움" → 매 틱 재생 헤드가 지난 이벤트만 note-on (일시정지·시킹과
  함께 멈추고 따라감, 과거 음 몰아치기 방지 bisect 커서).

## 7.5 연주 채점 & 학습 루프 (`player/scoring.py`, Qt 비의존)
- **입력**: MIDI(mido) + 화면 건반. note-on만 판정(길이 무시). 재생 중에만 채점.
- **존**: midi < split_point(60) = 왼손 → **코드톤 판정** / 이상·화면건반 = 오른손 →
  **스케일 판정**. 스케일 밖 음은 "틀림"이 아니라 **"스케일 밖"**(중립 표현).
- **패스** = 루프 1주기 창(감지 loop_len·phase, 사용자 override 우선). 루프 미검출 시
  곡 전체 = 1패스. 창 시작 0.3초 이내 진입한 패스만 유효(스크럽 진입 배제).
- **판정**: 스케일 적중(pc ∈ note_set) / 코드톤 착지(마디 첫박 ±0.25박 내 코드톤,
  마디당 1회) / 리프 일치(같은 음높이 ±0.25박 최근접 매칭, practice 모드).
- **난이도**(가이드): 존별 목표음 교체 — Lv1 왼손근음+오른손코드톤 / Lv2 왼손근음+
  오른손스케일 / Lv3(=기본) 왼손코드톤+오른손스케일. 통과·실패·잠금 없음.
- **피드백**: 패스 요약 카드 + 세션 내 추이(right_pct 나열) + 실시간 배지.
- **영속화**: 패스 완료마다 `data/practice_log.jsonl`에 1줄 append
  ({ts, kind, mode, level, right_pct, left_pct, riff_pct}).
- **학습 루프 폐회로**: `rebake_kind`(리프 재생성)가 그 종류 최근 20패스 평균
  right_pct < 60이면 `density_penalty=0.15`로 **성긴(쉬운) 변주**를 선택한다.

## 8. ML — 리프 생성 (`ml/`)

### 8.1 표현 (`ml/representation.py`, 확정)
- 1마디 = 16칸(16분), 학습 프레이즈 = 2마디 = 32칸. 스윙 없음(직선 그리드).
- 토큰(어휘 15): `REST` / `HOLD`(지속) / `ONSET_0..11`(**코드 근음 기준 도수** — 키 독립).
- 칸별 조건: 코드 품질군(maj/dom/min/dim) · 스케일 라벨 · 박위치(0–15).
- 디코드: 도수→pc→직전 음과 가까운 옥타브(보이스리딩), 음역 60–83(C4–B5) 고정.

### 8.2 모델 (`ml/model.py`)
- **order-2 백오프 Markov 카운트 테이블**(JSON, torch 불필요). 컨텍스트 키 =
  `품질군|스케일|박위치|직전2토큰`, 백오프 6단계(구체→`*|*|*`).
- 추론은 `blended()`: 첫 히트 절벽 대신 **단계별 정규화 분포를 감쇠(0.5) 혼합**.
- 로드 우선순위: `models/markov.json`(WJazzD 학습본) → `models/default_markov.json`
  (부트스트랩, git 추적) → None(규칙 생성 폴백). 부트스트랩은 `rule_based_grid`(이론
  프라이어)로 합성한 프레이즈를 학습한 것 — **무데이터에도 앱이 동작**하는 안전망.

### 8.3 학습 파이프라인 (`ml/train/`, 오프라인)
```
data/wjazzd.db → prepare_phrases(토큰화) → data/phrases.jsonl → train_markov → models/markov.json
```
- WJazzD 솔로 채보(onset/duration/pitch + 비트별 코드 주석)를 2마디 창으로 절단.
  코드는 **비트 단위 bisect 룩업**(마디 중간 코드 체인지 정확 반영).
- 스케일 라벨 7종은 실제 사용 음으로 판별(maj의 #4 빈도→리디안, min의 ♭2→프리지안 등).
  현 학습본: 15,512 프레이즈 / 18,880 컨텍스트 / 라벨 분포 메이저 42%·믹솔 28%·마이너
  10%·리디안 9%·도리안 7%·프리지안 3%·로크리안 1.5%.
- **데이터 소스는 WJazzD 단일**: Lakh MIDI(코드 라벨 부재)·POP909(자동 코드 노이즈,
  카운트 병합 시 재즈 통계 희석)는 검토 후 제외. 겹침 윈도 증량도 기각(같은 전이의
  중복 카운트 — 정규화로 상쇄, depth-0 컨텍스트 히트율 이미 99.8%).

### 8.4 생성 (`ml/generate.py`) — 구조가 하한, 모델이 통계
스케일 종류당 1개, 종류명 시드로 **결정적**(같은 종류=같은 리프, variant로 변주).
```
후보 24개 생성 → 밀도 하한(<3음/마디) 기각 → PMI 랭킹 argmax
후보 1개 = melodic_grid:
  리듬: 박 단위 셀 어휘(정박 위주 8종, 손 가중치) × 학습 온셋 확률(_onset_probs) 보정
        → 반 마디 모티프 ×2 = AA'(외워 써먹는 반복 구조)
  멜로디(온셋마다): blended 분포를 스케일 안 도수로 재정규화한 prior(+floor 0.03)
        × 스텝모션(도약 억제) × 같은음 억제 × 컨투어 목표선(아치/상행/하행/웨이브)
        × 정박 코드톤 앵커 ×2.5 × 비코드톤 3연속 금지 → 마지막 음 코드톤 해결
```
- **스케일 게이트(하드 불변식)**: 출력은 항상 배정 스케일 안의 음만.
- **랭킹 `_riff_score` = PMI + 정박 코드톤 적중률**: 스텝별 `log p(토큰|컨텍스트) −
  log p(토큰)`. (순수 로그우도는 온셋 희소성 때문에 "음 적은 후보"로 기울어
  density_penalty까지 무력화했던 것을 2026-07 수정.)
- `bake_examples`: 종류당 1회 생성 → 각 구간에 코드 근음 이조(+위/−아래 최근접)
  + 구간 길이만큼 반복 타일링 → `seg.example`.
- `rebake_kind`: variant+1 재생성 + 그 종류 구간 재타일링(§7.5 density_penalty 반영).
  `bake_segment`: 수동 코드 수정 후 해당 구간만.
- **현 측정치**(모델 on/off 동일 시드 대조): 음 단위 개입 37%, 그리드 80%.
  평균 6.9음/마디, 정박 코드톤 앵커 99%, 스케일 밖 0, 정박 온셋 51%.
- 알려진 설계 한계: order-2라 마디 넘는 전개(질문-응답 등)는 표현 불가 — 컨투어·AA'가
  그 자리를 구조로 채운다. 시퀀스 모델 도입 전까지는 의도된 트레이드.

## 9. 오디오 입출력
- **곡 재생**: `player/playhead.py` — QMediaPlayer + 25ms 틱. 오디오 없으면(데모)
  가상 클럭. 시킹/일시정지는 채점·리프 커서와 동기.
- **연주음/리프 신스**: `player/note_synth.py` — 음별 가산합성 피아노 WAV(PCM16,
  44.1kHz, 1.1s 감쇠)를 `cache/notes/`에 렌더-캐시, 음별 QSoundEffect 재생(폴리포니).
  앱 전역 공유 1인스턴스(`shared_player`), C3~B5(48–84) 프리웜 + 무음 WAV 예열
  (첫 재생 몰림 방지). 범위 밖은 preload로 지연 생성.
- **백엔드**: Qt 기본 FFmpeg 백엔드가 반복 재생 후 전체 무음에 빠지는 문제로
  `main.py`에서 `QT_MEDIA_BACKEND=windows`(네이티브) 강제 — QtMultimedia 임포트 전 설정.
- **MIDI 입력**: `player/midi_input.py` — mido+rtmidi 스레드, 첫 가용 포트 자동 연결.

## 10. 스코프
**포함**: 링크/파일 입력, 코드·키·BPM·다운비트 분석, 박자·코드 보정, 사용자 루프,
스케일 자동 배정, 리프 생성·재생성·미리듣기, 가이드/리프연습 모드, 존별 채점 + 난이도,
패스 요약·추이, 연습 기록 영속화 + 재생성 난이도 반영(학습 루프), 세션 저장·라이브러리,
MIDI·화면 건반, 데모 타임라인.
**제외**: 벌스/코러스 감지, 장르 선택, 콜앤리스폰스, 우도 히트맵, 퀴즈, 녹음,
자동 손 분리, BPM 변속 재생, 스윙 재생, 진행 패턴 네이밍, Claude 설명 코치(보류).

## 11. 기술 스택 & 실행
- Python **3.11 고정**(python-rtmidi 호환) · PyQt6 6.11 · yt-dlp + imageio-ffmpeg ·
  madmom(비트·코드, 선택적— venv 빌드) · librosa(폴백·HPSS) · numpy · soundfile · mido.
  **torch 불필요**(Markov JSON).
- 실행: `venv\Scripts\python.exe main.py`
- 학습 재실행: §8.3 명령 두 줄 (`ml/train/README.md`).

## 12. 테스트 (루트, 프레임워크 없는 assert 스크립트)
| 파일 | 대상 |
|---|---|
| `tests_smoke.py` | 헤드리스 UI/타임라인/화면 흐름 + 리프 불변식(밀도·정박·게이트) |
| `tests_ml.py` | 표현 라운드트립 / 부트스트랩 학습 / 게이트 생성 / 무학습 폴백 |
| `tests_scoring.py` | 존 판정·착지·패스·루프 override·밀도 페널티(§7.5) |
| `tests_mir.py` / `tests_analyze.py` | 합성 오디오로 MIR·구조·화성 |
| `tests_mir_real.py` | 실제 백킹트랙 ground-truth 코드 일치율 |

## 13. 데이터·아티팩트 지도
```
models/markov.json          WJazzD 학습본(미추적) — 없으면 default_markov.json(추적) 폴백
data/wjazzd.db              WJazzD 원본(미추적)
data/phrases.jsonl          토큰화 학습 데이터(미추적)
data/practice_log.jsonl     연습 기록(패스 요약 append)
cache/*.json                세션 타임라인(라이브러리)
cache/*_22050.wav           분석용 WAV 캐시
cache/notes/piano_*.wav     신스 음별 렌더 캐시
```
