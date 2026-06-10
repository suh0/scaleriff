# ScaleRiff — 디자인 스펙 v4 (Claude Code 핸드오프)

> 단일 출처(single source of truth). 색·타이포·로고·키보드 상태색을 여기 정의된 값 그대로 구현.
> 대상 스택: **Python 3.11 · PyQt6**.

---

## 1. 아이덴티티

| 항목 | 값 |
|---|---|
| 앱 이름 | **ScaleRiff** |
| 표기 | `ScaleRiff` (카멜케이스, 공백 없음) |
| 태그라인 | *"Improvise your way through any song"* |
| 비주얼 컨셉 | **Black & White Minimal** — 검정 배경 + 흰 텍스트, 기능색만 사용 |
| 무드 키워드 | clean, minimal, functional, high-contrast, no-decoration |

디자인 철학: **기능만 남긴다.** 장식 없음. 색은 오직 "이 음이 지금 안전한가"를 알리는 신호로만 쓴다. 사용자가 키보드를 봤을 때 악보를 읽는 것이 아니라 신호등을 읽듯 즉각 반응할 수 있어야 한다.

---

## 2. 로고

기존 SVG 로고 형태(원형 링 + 건반 모티프 + 음표) 유지. 색만 변경:
- 링·음표: `#ffffff` (흰색)
- 건반 막대(흰 건반 모티프): `#ffffff`, opacity 단계 0.85/0.55/0.85/0.45
- 건반 막대(검은 건반 모티프): `#555555`
- 배경: 투명 (다크 배경 위 사용)

```svg
<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
  <circle cx="32" cy="32" r="30" fill="none" stroke="#ffffff" stroke-width="1.5"/>
  <rect x="20" y="26" width="4.5" height="14" rx="1" fill="#ffffff" opacity="0.85"/>
  <rect x="26" y="26" width="4.5" height="14" rx="1" fill="#ffffff" opacity="0.55"/>
  <rect x="32" y="26" width="4.5" height="14" rx="1" fill="#ffffff" opacity="0.85"/>
  <rect x="38" y="26" width="4.5" height="14" rx="1" fill="#ffffff" opacity="0.45"/>
  <rect x="23.5" y="26" width="3.5" height="9" rx="0.5" fill="#555555"/>
  <rect x="29.5" y="26" width="3.5" height="9" rx="0.5" fill="#555555"/>
  <rect x="35.5" y="26" width="3.5" height="9" rx="0.5" fill="#555555"/>
  <circle cx="43" cy="26" r="2.5" fill="#ffffff"/>
  <line x1="45.5" y1="26" x2="45.5" y2="21" stroke="#ffffff" stroke-width="1.5"/>
</svg>
```

워드마크: `ScaleRiff`, Inter 700, `#ffffff`.

---

## 3. 컬러 팔레트

> **가독성 원칙**: 모든 UI 텍스트 ≥ 6.9:1. light(300) 굵기 사용 금지.

### 3.1 표면 / 배경

| 토큰 | HEX | 용도 |
|---|---|---|
| `bg/base` | `#0a0a0a` | 앱 전체 배경 |
| `bg/surface` | `#141414` | 카드·패널 |
| `bg/surface-alt` | `#1e1e1e` | hover 상태·보조 패널 |
| `bg/inset` | `#0f0f0f` | 코드 HUD 안쪽 등 깊은 영역 |
| `border/subtle` | `#2a2a2a` | 내부 구분선 |
| `border/default` | `#555555` | 카드 테두리 |
| `border/active` | `#ffffff` | 선택·hover 강조 |

### 3.2 텍스트

| 토큰 | HEX | 대비비 | 용도 |
|---|---|---|---|
| `text/primary` | `#ffffff` | 21:1 | 제목·강조 |
| `text/body` | `#e0e0e0` | 16.1:1 | 본문 |
| `text/muted` | `#a0a0a0` | 11.0:1 | 보조 설명 |
| `text/dim` | `#666666` | 6.9:1 | 캡션·모노 라벨 |

### 3.3 기능색 (키보드 배지 전용)

UI 일반 영역에는 사용하지 않는다. 배지 동그라미 전용.

| 토큰 | HEX | 의미 |
|---|---|---|
| `badge/chord` | `#22c55e` | 코드톤 배지 배경 (초록) |
| `badge/scale` | `#4a4a4a` | 스케일음 배지 배경 (짙은 회색) |
| `badge/out` | `#ef4444` | 스케일 밖 배지 배경 (빨강) |
| `badge/text` | `#ffffff` | 배지 위 텍스트 (모든 배지 공통) |
| `badge/scale-text` | `#e0e0e0` | 스케일음 배지 텍스트 |

---

## 4. 타이포그래피

| 역할 | 폰트 | weight | 비고 |
|---|---|---|---|
| 제목·워드마크·코드명 | **Inter** | 700–900 | |
| 본문·UI | **Inter** | 500 | light(300) 금지 |
| 모노 라벨·도수·섹션 캡션 | **Space Mono** | 700 | letter-spacing 2–3px, 대문자 |
| 한글 본문 | **Noto Sans KR** | 500–700 | |

> PyQt6 배포: `.ttf` 리소스에 번들 + `QFontDatabase.addApplicationFont()`. 시스템 설치 의존 금지.

크기 가이드:
- 워드마크/메인 타이틀: 30–40px, 700–900
- 코드 HUD 코드명: 28–36px, 900
- 섹션 타이틀: 24px, 700
- 본문: 15–16px, 500
- 보조 설명: 14–15px, 500
- 모노 라벨/도수: 11–13px, 700

---

## 5. 키보드 UI — 배지(Badge) 시스템

> **핵심 원칙**: 건반 자체의 색/테두리는 절대 바꾸지 않는다.
> 오직 **라벨 위 작은 동그라미(배지)**만으로 상태를 표시한다 — 당구공처럼.
> 건반을 봤을 때: 🟢초록 배지 = 안정, ⚫회색 배지 = 가능, 🔴빨간 배지 = 피할 것.

### 5.1 건반 기본색 (상태와 무관하게 항상 동일)

| 종류 | fill | border |
|---|---|---|
| 흰 건반 | `#f2f2f2` | `#c8c8c8` 1px |
| 검은 건반 | `#1c1c1c` | 없음 |
| 친 건반(흰) | `#eeeee8` (아주 미세한 변화만) | `#c8c8c8` 1px |
| 친 건반(검) | `#2a2a2a` | 없음 |

### 5.2 배지 스펙 (라벨 동그라미)

배지는 건반 하단(흰 건반) 또는 건반 하단 내부(검은 건반)에 중앙 배치.

| 상태 | 배지 배경 | 배지 텍스트색 | 내용 | 흰 건반 크기 | 검은 건반 크기 |
|---|---|---|---|---|---|
| 코드톤 | `#22c55e` | `#ffffff` | 도수(R, 3, 5, 7 …) | 26×26px | 20×20px |
| 스케일음 | `#4a4a4a` | `#e0e0e0` | 도수(2, 4, 6, b3 …) | 26×26px | 20×20px |
| 스케일 밖 | `#ef4444` | `#ffffff` | `×` | 26×26px | 20×20px |
| 기본(스케일 미포함) | 없음 | — | — | — | — |

배지 폰트: Space Mono 700. 원형 `border-radius: 50%`.

### 5.3 친 건반 표시

배지는 **그대로 유지**. 추가로 **건반 테두리 색**만 해당 음의 상태를 알린다. 별도 텍스트 없음.

| 음 상태 | 테두리 색 | 흰 건반 두께 | 검은 건반 두께 | fill 변화 |
|---|---|---|---|---|
| 코드톤 | `#22c55e` | 2.5px | 2px | `#eeeee8` / `#2a2a2a` (미세) |
| 스케일음 | `#888888` | 2.5px | 2px | `#eeeee8` / `#2a2a2a` |
| 스케일 밖 | `#ef4444` | 2.5px | 2px | `#eeeee8` / `#2a2a2a` |
| DEFAULT | `border/default` | 1.5px | 1px | 동일 |

### 5.4 모드별 적용

- **가이드 모드**: 모든 건반에 배지 표시. 친 건반 = 배지 유지 + 상태 테두리 추가.
- **퀴즈 모드**: 배지 전부 숨김 → 친 건반만 상태 테두리 + 배지 동시 공개 → **코드 바뀌면 전체 리셋**.

---

## 6. 화면별 적용

### 6.1 메인 플레이어 영역

- **코드 HUD(상단)**: `bg/inset`. 코드명 Inter 900 32–36px `text/primary`. 스케일명 Inter 600 14px `text/muted`. 도수 Space Mono 700 12px `text/dim`. 다음 코드는 `text/dim`으로 흐리게.
- **피아노 키보드(C2–B5)**: §5 상태색. MIDI 손 구분 없음.
- **모드 토글(가이드↔퀴즈)**: 활성 = `#ffffff` 배경 + `#0a0a0a` 텍스트. 비활성 = `border/default` 외곽 + `text/muted`.
- **ML 예시 버튼**: 외곽선 버튼. 테두리 `border/active`, 텍스트 `text/primary`, hover fill `rgba(255,255,255,0.08)`.
- **스크럽 바**: 트랙 `border/subtle`, 코드 눈금 `text/dim`, 헤드 `#ffffff`.
- **재생/일시정지**: 흰 원형 `#ffffff`, 아이콘 `#0a0a0a`.

---

## 7. 구현 체크리스트 (Claude Code용)

- [ ] 폰트 3종(Inter, Space Mono, Noto Sans KR) `.ttf` 번들 + `QFontDatabase.addApplicationFont()`
- [ ] §3 컬러 토큰 단일 상수 모듈(`theme.py`)로 정의
- [ ] 키보드 상태 enum: `DEFAULT, SCALE, CHORD, OUT` → 건반 fill/border 불변, **배지만** 상태별 렌더
- [ ] 배지: 원형 `QPainter` 타원. Space Mono 700. 흰/검 건반 각각 26px/20px
- [ ] 친 건반: **배지 그대로 유지** + 상태별 컬러 border 추가(초록/회색/빨강). 건반 fill은 미세하게만 변화
- [ ] 배지(`badge/*`)는 키보드 위젯 외부 UI에 절대 사용 금지
- [ ] light(300) 굵기 사용 금지 — Inter 최소 500, Space Mono 700

---

## 8. 변경 이력

- v1 — 이름 ScaleRiff / Ivory & Soul 빈티지 골드 / 키보드 Scheme A++
- v2 — 텍스트·테두리 명도 상향, 키보드 라벨 솔리드화
- v3 — light(300) 폐기, 폰트 크기 전반 상향
- v4 — 컨셉 전환: Black & White Minimal. 기능색(초록/빨강)만 키보드에 사용.
- v5 — **배지 시스템 도입**: 건반 fill/border 불변. 라벨 동그라미(배지)만으로 상태 표시.
- v6 — 친 건반 피드백: 배지 없음 + `#f5c842` 도수 텍스트 + 상태별 테두리 (일시적 방향).
- v7 — **친 건반 동작 최종 확정**: 배지 항상 유지. 친 건반 = 배지 그대로 + 상태별 컬러 border만 추가. 노란색(`#f5c842`) 완전 제거.
