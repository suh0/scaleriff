# ML 학습·생성·평가

코드 품질군·스케일·박 위치와 직전 토큰을 조건으로 하는 order-2 Markov 모델이다.
구조 규칙이 리듬 셀·모티프·컨투어·착지를 만들고, 학습 통계가 후보 음과 리듬의 가중치에 개입한다.
실행 환경은 Windows/Python 3.12와 `.venv`다.

## 표현과 지원 범위

- 학습: 4/4 한 마디 16칸, 두 마디 32칸의 16분음표 양자화.
- 토큰: REST / HOLD / 코드 근음에 대한 ONSET_0..11. 옥타브는 생성 때 가까운 음역으로 배치한다.
- 칸별 조건: maj/dom/min/dim 품질군, 스케일 라벨, 마디 안 위치, 이전 토큰.
- 준비 데이터는 코드가 쉬는 칸에도 화성을 유지하고 `solo_id`, `tune_id`(composition ID), 원본 출처와 준비 버전을 보존한다.
- 스케일 라벨은 실제 프레이즈 음에서 유도한다. dim7/aug는 디미니시드/온음 라벨을 사용한다.
- 3/4·가변 템포는 생성 결과의 시간 배치를 지원한다. 해당 박자의 학습 품질과 스윙 미세 타이밍은 검증하지 않았다. 별도 스윙 재생 변환도 구현하지 않았다.

## WJazzD 재학습

데이터 형식은 [WJazzD 공식 설명](https://jazzomat.hfm-weimar.de/dbformat/dboverview.html)을 참조한다.
로컬 `data/wjazzd.db`를 읽는다. 다양한 악기의 재즈 단선율 솔로이며 피아노 양손 학습 자료로 간주하지 않는다.

기존 데이터/실행 모델과 구분해 새 결과를 cache에 만든다.

```powershell
& ./.venv/Scripts/python.exe -m ml.train.prepare_phrases --wjazzd data/wjazzd.db --out cache/phrases_identified.jsonl
& ./.venv/Scripts/python.exe -m ml.train.train_markov --data cache/phrases_identified.jsonl --out cache/markov_tune_holdout.json --seed 42 --test-fraction 0.2
```

같은 composition의 모든 솔로·프레이즈를 학습/검증 중 한쪽에만 배치한다. 모델에 두 그룹 ID, 겹침 수,
데이터 SHA256, 버전과 검증 로그손실을 저장한다. 곡 ID가 없는 옛 JSONL은 임의의 행 분할로 평가하지 않고 재준비를 요구한다.

`load_model()`은 기존 `models/markov.json` → `models/default_markov.json` → 규칙 순서로 로드한다.
평가용 재학습 모델은 자동으로 실행 모델을 교체하지 않는다. 기존 모델 15,512 프레이즈의 원래 곡 분리는 입증하지 못했다.
로드한 실제 파일의 경로와 SHA256을 세션 생성 정보에 남긴다.

## 기본 모델

외부 데이터 없이 이론 사전분포를 만드는 도구다. 명시적으로 실행하면 `models/default_markov.json`을 갱신한다.

```powershell
& ./.venv/Scripts/python.exe -m ml.train.make_default_model
```

기존 부트스트랩 파일의 버전/커버리지는 현재 생성 스크립트와 다를 수 있다. 실제 사용한 파일의 해시로 구분한다.

## 생성

- `bake_examples`: 스케일 종류별 기본 리프를 만들고 실제 구간 길이와 비트에 맞춰 배치한다.
- `bake_progression`: 선택한 실제 코드 진행·음 집합·착지 목표·밀도·변주 번호를 사용한다.
  코드 진입/마지막 음의 지원되는 목표 착지를 고정하고, 선택 구간 밖 예시는 유지한다.
- 생성 시 스케일 게이트와 음 길이/코드 경계를 적용한다. 지원되지 않는 3도/7도 목표는 메타데이터에 표시한다.
- 준비나 명시적 사용자 액션 때 계산하며 재생 틱에서는 생성하지 않는다.

## 평가 재현

```powershell
& ./.venv/Scripts/python.exe -m ml.evaluate --wjazzd data/wjazzd.db --out cache/ai_evaluation/report.md
```

규칙/부트스트랩/기존 학습 모델의 고정 진행 생성 제약을 비교하고, 곡 단위 재학습 결과는
`cache/ai_evaluation`에 별도 저장한다. 결과와 정확한 해석은 `cache/ai_evaluation/report.md`에 있다.

전체 토큰 log loss는 재학습이 균등 기준보다 낮았지만 **온셋만의 log loss는 균등 기준보다 높았다**.
관측 음에서 유도한 스케일과 정답 이전 토큰을 조건으로 한 확률 평가이며, 생성곡의 자연스러움이나 학습 효과의 입증이 아니다.
청취 평가·학습자 전후 비교, 스윙/altered 화성과 실제 피아노 입력 평가는 후속 과제다.
