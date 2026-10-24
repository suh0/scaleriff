# ScaleRiff AI 평가

재현 명령: `.venv/Scripts/python.exe -m ml.evaluate --out document/AI_EVALUATION.md`

평가 버전 `progression-reference-v1`, 곡 분리 seed=42. 고정 수작업 진행 5개 × 3도/7도 목표 × 변주 4개.

이 진행은 WJazzD의 홀드아웃 정답 프레이즈가 아닌 독립적인 규칙 점검용 기준이다.

| 생성 방식 | 프레이즈/음 수 | 스케일 게이트 | 경계 위반 | 지원 목표 착지 | 재현성 | 변주 변화 | 희박→조밀 음/박 |
|---|---:|---:|---:|---:|---:|---:|---:|
| rule | 40/456 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | 0.868→2.132 |
| bootstrap | 40/456 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | 0.868→2.132 |
| trained_legacy | 40/456 | 100.0% | 0 | 100.0% | 100.0% | 100.0% | 0.868→2.132 |

목표 착지는 코드 변화 첫 음과 마지막 음으로 판정한다. 실제 코드와 배정 스케일에 없는 3도/7도는 지원 목표 분모에서 제외한다. C6의 6도를 7도로 취급하지 않는다.

- rule: source=`rule`, phrases=0, artifact=`None`, SHA256=`None`; 미지원 착지 12건, 밀도 증가 20/20, 유효하지 않은 음 0건.
- bootstrap: source=`theory_prior`, phrases=3600, artifact=`C:\Users\ggkh1\Desktop\scaleriff\models\default_markov.json`, SHA256=`91009331bf848b5d57bf12b9e320931902927d144a483517e90e9e3dad604b4d`; 미지원 착지 12건, 밀도 증가 20/20, 유효하지 않은 음 0건.
- trained_legacy: source=`train_markov`, phrases=15512, artifact=`C:\Users\ggkh1\Desktop\scaleriff\models\markov.json`, SHA256=`6f58127c2060421a1ad53528e02d87d85a8f701049399ed4b8a7b6b6155c492e`; 미지원 착지 12건, 밀도 증가 20/20, 유효하지 않은 음 0건.

## 곡 단위 재학습 평가

WJazzD 읽기 전용 원본 SHA256: `af6a0d9debf042c3581565bd75baad591d32e166cd2ec7298519883de614bf12`.

준비 버전 `wjazzd-tune-v2`; 14492개 4/4 프레이즈, 437개 솔로. 동일 composition ID의 모든 솔로·프레이즈를 한쪽에만 배치한다. 곡 229개 학습/57개 검증, 겹침 0개. 프레이즈 11671개 학습/2821개 검증.

준비 데이터 SHA256: `4bd62542265fc6b8e43642d93ddacbde58f95b5baabd126aff58e9587e16a388`; 재학습 모델 SHA256: `a5d92e700d4d9024c99f4c40d23f092a7d661958f9e46edc744cd410d29dd7f0`.

| 확률 모델 | 검증 토큰 수 | 조건부 토큰 log loss (nats) | 온셋 수 | 온셋 log loss (nats) |
|---|---:|---:|---:|---:|
| uniform_reference | 90272 | 2.639057 | 33133 | 2.639057 |
| bootstrap | 90272 | 2.275409 | 33133 | 4.673578 |
| tune_holdout_retrained | 90272 | 1.721698 | 33133 | 3.210281 |

모든 수치는 정답 이전 토큰과 코드군·스케일·박 위치를 조건으로 계산한 평균 음의 로그확률이며 낮을수록 좋다. BOS를 제외한 14개 토큰에 0.001 평활화를 사용한다. uniform_reference는 규칙 생성기의 확률이 아닌 균등 확률 기준이다.

기존 15,512개 학습 모델은 원래 곡 분리 정보가 없어 일반화 log loss를 보고하지 않았다. 위 재학습 모델은 cache에 별도로 저장했으며 models/markov.json을 교체하지 않았다.

## 해석과 한계

- 스케일 게이트·목표 착지·밀도·경계 준수는 생성 제약의 검사다. 세 방식의 음악적 우열, 자연스러움, 학습 효과를 증명하지 않는다.
- 실연자 청취 평가와 학습자 전후 비교, 실제 MIDI 기기 검증은 수행하지 않았다.
- 재학습은 4/4의 16분음표 양자화다. 3/4·가변 템포는 런타임 배치만 점검했으며 해당 미터의 학습 품질과 스윙은 검증하지 않았다.
- WJazzD j7/o/- 표기를 지원 코드로 축약한다. altered/확장 화성 전체와 미세 리듬을 보존하지 않는다.
- 스케일 라벨은 해당 프레이즈의 관측 음에서 유도한다. 조건부 log loss는 자동 스케일 추정이나 실제 앱 전체의 성능이 아니다.
- 곡 분리는 제공된 composition ID에 의존한다. 동일 진행·인용구·곡명 변형을 넘어서는 음악적 유사성까지 제거한 것은 아니다.

기계 판독 결과: `C:\Users\ggkh1\Desktop\scaleriff\cache\ai_evaluation\results.json`. 원본 data/phrases.jsonl과 models/*.json은 읽기만 했다.
