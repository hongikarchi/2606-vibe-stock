# 결정 필요: bi-temporal ingest_time 분리 (방향 확인 후 진행)

> 이건 **실행 안 한 결정 메모**입니다. 파괴적·되돌리기 어렵고, 깨끗한 정답이 없는 정책 선택이라
> 자율 진행에서 제외했습니다. 주무시는 동안 #2(KR 노드)·#3(emergent)는 완료·배포했습니다.

## 문제 (감사 #1, 지배적 결함의 뿌리)

`news.py`가 모든 Claim의 `ingest_time = knowledge_time`로 쓰고(`news.py:218`),
파이프라인이 `knowledge_time = cfg.AS_OF_NOW`를 넘긴다(`news_pull.py:62`, `kr_pull.py`).
읽기는 `WHERE knowledge_time <= $as_of`로 거른다(`neo4j_repo.py:415`, `sqlite_repo.py:209`).

→ **"언제 알게 됐나(knowledge_time)"가 "언제 질의하나(as_of)"와 같은 값으로 묶여 있음.**
이게 두 가지를 동시에 망가뜨림:
1. **freshness 라벨이 거짓** — 06-29 라벨인데 내용은 그 이전 전부. (지금은 `AS_OF_NOW`를
   매번 올려 *완화*만 한 상태. 상수를 안 올리면 매일 다시 벌어짐.)
2. **as-of 리플레이가 불성실** — "06-23 시점에 알던 것만 보기"가 불가능. 06-28에 수집한
   기사도 knowledge_time이 06-23이라 06-23 질의에 그대로 보임. survivorship 데모(`run.py:216`,
   `AS_OF_PAST`)의 신뢰성이 약해짐.

**측정된 현황:** 뉴스 Claim 23,128건이 **전부** `knowledge_time=2026-06-23`로 찍혀 있음.
이들의 실제 `event_time`은 2005년 ~ 2026-06-29에 걸침. 즉 **진짜 ingest 시각은 복원 불가**
(과거 실행이 언제였는지 기록이 없음). → 그래서 "올바른 마이그레이션"이란 게 없고, **정책 선택**만 있음.

## 올바른 종착 설계 (모두 동의하는 부분)

- `ingest_time`/`knowledge_time` = **실제 벽시계 시각**(그 기사를 *수집한* 순간). `news.py:218`을
  `knowledge_time` 대신 `datetime.now()` 류로.
- `as_of` = **읽기 필터 전용 파라미터**. 더 이상 스탬프에 안 쓰임.
- 시간감쇠 `now`(`build_theme_view._decay_weight`)도 실제 today / `max(event_time)`에서 계산.

논쟁 지점은 **"이미 06-23으로 찍힌 기존 23,128건을 어떻게 할 것인가"**.

## 선택지 (기존 데이터 처리)

| | 방식 | 장점 | 단점 / 위험 | 되돌리기 |
|---|---|---|---|---|
| **A0** | **라벨만 자동 전진 (이번 세션에서 이미 적용)** | 가장 가벼움. `AS_OF_NOW`를 env(`SKG_AS_OF_NOW`)로 빼고 `run_pipeline.bat`이 매 루프 run 날짜로 세팅 → 라벨이 더 이상 stale 안 됨. ingest_time 구조는 안 건드림 | as-of 리플레이의 불성실은 그대로(knowledge_time이 여전히 묶임). "라벨 거짓"만 해결, "리플레이 부정확"은 미해결 | 매우 쉬움 (env 제거) |
| **A** | **기존은 동결, 신규만 실제 ingest 시각** | A0 + `news.py:218`을 실제 now로 → 신규 데이터의 knowledge_time이 진짜 인지 시각이 됨. 무손실 | 기존 23k건은 영원히 "06-23에 알게 됨"으로 남음 → as-of 리플레이가 과거 구간에선 여전히 부정확. 신규가 쌓이며 자연 희석 | 쉬움 (코드만 revert) |
| **B** | **기존 knowledge_time을 event_time으로 백필** | as-of 리플레이가 기사 발행일 기준으로 그럴듯해짐. survivorship 데모가 의미 회복 | event_time ≠ 실제 알게 된 시각(기사는 6/20 발행이어도 우리가 6/28에 처음 봄). "knowledge"의 정의를 약간 왜곡. 대량 UPDATE(파괴적) | 중간 (백업에서 복구) |
| **C** | **기존 뉴스 Claim drop 후 재수집** | 모든 데이터가 실제 ingest 시각을 갖는 깨끗한 상태 | 무키 RSS는 보통 최근 N일치만 줌 → **과거 기사 영구 손실 위험**. 누적 자산(ARCHITECTURE.md의 핵심 가치)을 버림. 가장 파괴적 | 어려움 (원복 불가) |

## 추천

**A (동결+전진)을 기본으로.** 이유:
- 무손실·되돌리기 쉬움 — 창립 제약(1~2인, heavy-ingest)과 "누적이 자산"이라는 프로젝트 철학에 부합.
- as-of 리플레이의 부정확은 **과거 구간에만** 남고, 신규 데이터가 쌓이며 자연 희석됨.
- B는 "발행일=인지일" 근사를 받아들이면 매력적이지만, 그건 knowledge_time의 의미를 바꾸는
  별도 결정. **B를 원하면 그때 따로 진행**(event_time이 이미 있으니 백필 자체는 단순).
- C는 누적 자산을 버리므로 비추천.

→ **A0는 이번 자율 세션에서 이미 적용·배포함**(되돌리기 쉬운 라벨 수정 = 당신이 이미 고른 "오늘
날짜로 bump"의 영속 버전): `AS_OF_NOW`를 `SKG_AS_OF_NOW` env로 빼고 `run_pipeline.bat`이 매 루프
run 날짜로 세팅. 이제 라벨은 자동으로 안 stale해짐. 기본값(literal)은 테스트·수동 실행 결정성 유지.

→ A까지 마저 가려면(=신규의 knowledge_time을 진짜 인지 시각으로): `news.py:218`의
`ingest_time = knowledge_time`을 실제 now로, `_decay_weight`의 now를 실제 today로. 이게
"as-of 리플레이 불성실"의 신규분을 해결. **기존 23k건 처리(동결 A / 백필 B / 재수집 C)가
바로 위 표의 결정 지점** — 이 부분만 방향 주시면 됩니다.

## 곁다리로 같이 결정하면 좋은 것 (감사 잔여, 모두 reversible지만 "더 나은가?"는 사람 눈 필요)

- **emergent 랭킹을 raw degree → 동시출현 집중도(PMI류)로**: generic이 degree로 상위에 뜨는
  구조적 원인. stoplist parity(#3)로 지금 hub는 깨끗하지만, 점수 자체를 바꾸면 더 견고.
  "결과가 더 나은지"는 봐야 알 수 있어 자율 적용 안 함.
- **meta 카운트 이원화**: `meta.json` nodes/rels가 full-dump(127k)라 view(~400)와 ~300배 괴리.
  `backup_nodes` vs `as_of_nodes` 2개로 분리하면 헤더가 정직해짐. (낮은 우선순위, 안전)
- **lexicon 부정/밸류에이션 엔진**: 순 토큰 카운트라 'overvalued'·'리스크 해소' 같은 역설 못 잡음.
  지금은 토큰 추가로 정밀도만 올린 상태. 진짜 해결은 negation-flip 로직 = 모델 변경급.

---
*작성: 자율 세션 2026-06-29~30. 관련 감사: `INFO_AUDIT_2026-06-28.md`. 핸드오프 메모리: `autonomous-session-2026-06-29`.*
