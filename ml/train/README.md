# ML 학습 파이프라인 (리듬+멜로디 공동 생성)

코드 구간 위에서 **자연스러운 즉흥 라인(example_phrase)**을 만드는 모델.
규칙(theory)은 "어떤 음이 되는지", ML은 "그 음들로 어떤 리듬·라인을 만드는지".

## 표현 (확정)
- 한 마디 16칸(16분음표), 프레이즈 2마디 = 32칸 (`ml/representation.py`)
- 토큰: `REST` / `HOLD`(앞 음 지속) / `ONSET_0..11`(코드 근음 기준 도수)
  → onset 위치=리듬, HOLD=음 길이, 도수=멜로디(키 독립)
- 음높이는 도수만 학습 → 디코드 때 직전 음과 가까운 옥타브로 배치(보이스리딩)
- 스윙은 학습엔 안 넣고 **재생 때 비율 적용**(16칸 직선 유지)
- 칸별 조건: 코드 품질군(maj/dom/min/dim) · 스케일(메이저/마이너/도리안) · 박위치(0–15)

## 1단계 — 로컬 베이스라인 (지금 바로, torch 불필요)

```powershell
# 부트스트랩(이론 프라이어) 기본 모델 생성
venv\Scripts\python.exe -m ml.train.make_default_model
# → models/default_markov.json

# 생성 확인
venv\Scripts\python.exe -m ml.generate
```

### 실데이터(Weimar Jazz DB)로 학습
1. WJazzD `wjazzd.db` 다운로드: https://jazzomat.hfm-weimar.de/dbformat/dboverview.html
2. 토큰 변환 → 학습:
```powershell
venv\Scripts\python.exe -m ml.train.prepare_phrases --wjazzd wjazzd.db --out data\phrases.jsonl
venv\Scripts\python.exe -m ml.train.train_markov --data data\phrases.jsonl --out models\markov.json
```
(파이프라인만 점검하려면 `--demo 200` 으로 합성 데이터 사용)

## 2단계 — LSTM (Colab GPU, 품질↑) [예정]
- 같은 토큰 표현 + 위치 임베딩을 Transformer/LSTM로 학습
- Colab에서 학습 → `.pt` 가중치만 받아 앱이 로드(런타임 torch는 선택)
- 로컬은 torch 미설치/설치난이도 때문에 Colab 권장

## 3단계 — 앱 통합 [예정]
- 빌드 시 segment마다 `generate_phrase`로 `example_phrase` 굽기
- 메인 화면에 "듣기 / 같이 연주" 버튼(정의서 §8)

## 데이터 소스
- **Weimar Jazz DB (WJazzD)** — 재즈 솔로 채보, 음마다 onset/duration/beat·코드 주석(1순위, 리듬 학습 최적)
- **Lakh MIDI** — 단성 멜로디 트랙 추출 + 비트 양자화(확장)
