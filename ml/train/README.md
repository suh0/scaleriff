# ML 학습 파이프라인 (리듬+멜로디 공동 생성)

코드 구간 위에서 **자연스러운 리프(example_phrase)**를 만드는 모델.
규칙(theory)은 "어떤 음이 되는지", ML은 "그 음들로 어떤 리듬·라인을 만드는지".

## 표현 (확정)
- 한 마디 16칸(16분음표), 프레이즈 2마디 = 32칸 (`ml/representation.py`)
- 토큰: `REST` / `HOLD`(앞 음 지속) / `ONSET_0..11`(코드 근음 기준 도수)
  → onset 위치=리듬, HOLD=음 길이, 도수=멜로디(키 독립)
- 음높이는 도수만 학습 → 디코드 때 직전 음과 가까운 옥타브로 배치(보이스리딩)
- 스윙은 학습엔 안 넣고 **재생 때 비율 적용**(16칸 직선 유지)
- 칸별 조건: 코드 품질군(maj/dom/min/dim) · 스케일 라벨 · 박위치(0–15)
- 스케일 라벨(7종): 메이저 / 리디안(#4 빈도) / 믹솔리디안 / 마이너 / 도리안(♮6) /
  프리지안(♭2) / 로크리안 — `prepare_phrases._scale_for`가 실제 사용 음으로 판별

## 학습 (Weimar Jazz DB)
1. WJazzD `wjazzd.db` 다운로드 → `data/`:
   https://jazzomat.hfm-weimar.de/dbformat/dboverview.html
2. 토큰 변환 → 학습:
```powershell
venv\Scripts\python.exe -m ml.train.prepare_phrases --wjazzd data\wjazzd.db --out data\phrases.jsonl
venv\Scripts\python.exe -m ml.train.train_markov --data data\phrases.jsonl --out models\markov.json
```

## 부트스트랩 (데이터 없이)
`models/markov.json`이 없을 때의 폴백 모델(git 추적):
```powershell
venv\Scripts\python.exe -m ml.train.make_default_model   # → models/default_markov.json
```

## 생성에서 모델이 개입하는 곳 (`ml/generate.py`)
- 멜로디: `blended`(보간 백오프) 분포를 도수 사전분포로 곱함(floor 0.03)
- 리듬: 학습된 칸별 온셋 확률(`_onset_probs`)로 리듬 셀 가중치 보정
- 후보 랭킹: `_riff_score` = 모델 평균 로그우도 + 정박 코드톤 적중률
- 구조(리듬 셀 어휘·AA' 모티프·컨투어·앵커·스케일 게이트)는 항상 하한 유지

## 데이터 소스 결정
- **WJazzD** — 재즈 솔로 채보, 음마다 onset/duration/비트·코드 주석. 단일 소스.
- Lakh MIDI / POP909는 검토 후 제외(코드 라벨 부재/자동추출 노이즈,
  카운트 병합 시 재즈 통계 희석 — 2026-07 분석).
