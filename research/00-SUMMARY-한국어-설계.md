# 주식 정보 지식그래프 시스템 — 통합 설계 결론

> 두 개의 다중 에이전트 리서치(아키텍처 / LLM 편향 방어)와 각각의 적대적 검토를 종합.
> 원본 근거: `01-architecture-workflow-raw.json`, `01b/01c`(아키텍처 종합·공격), `02b/02c`(편향 통합·공격).

---

## 0. 한 문단 요약 (먼저 이것만)

수집(크롤링)은 **코드**로, 가공은 **LLM**으로 하되, **AI는 정보를 구조화만 하고 판단은 사람이 한다**는 당신의 스탠스를 *구조로* 강제하는 단일 노드 스택입니다. 핵심은 세 가지입니다. ① 저장은 "Obsidian vs Neo4j vs vectorDB" 택일이 아니라 **계층 스택**(그래프+벡터+표현)이다. ② 수학적 엄밀성은 DB가 아니라 **분석·방어 방법론**에 있다(신뢰도 가중 PageRank, Leiden, 전이엔트로피, 그리고 편향 방어). ③ LLM 편향("AI가 편향적으로 정리한다")의 진짜 해법은 *여러 AI를 토론시키는 것이 아니라* **불일치·이견·불확실성을 뭉개지 말고 사람에게 그대로 노출**하는 구조다. 단, 두 리서치의 적대적 검토가 공통으로 잡아낸 가장 큰 위험은 **과설계**다 — 1~2명을 위해 연구팀급 운영·평가 부담을 세우면 안 된다. 그래서 결론은 "최대주의 설계"가 아니라 **정직하게 단계화된 MVP**다.

---

## 1. 가장 중요한 결정 한 가지 (유일하게 열린 포크)

**저장 엔진의 spine: bi-temporal(이중시간) 코어를 살 것인가, 직접 만들 것인가.**

- 리서치 종합안은 **all-Postgres**(Postgres + pgvector + Apache AGE, bi-temporal을 SQL 컬럼으로 직접 구현)를 골랐다.
- 그런데 적대적 검토가 그 선택의 **간판 근거를 사실 오류로 판정**했다: "Graphiti가 모순 시 자동 무효화해서 *루머→부인→확정* 추적을 지운다"는 주장은 **틀렸다**. Graphiti는 bi-temporal이라 superseded edge를 `invalid_at`으로 닫고 **보존**한다(시점 조회 가능).
- 남는 진짜 근거는 둘뿐이다: (a) 어차피 엔티티 해소·provenance·신뢰도·비용 테이블 때문에 Postgres가 필요하니 Graphiti를 쓰면 *2개 엔진 + 동기화 어긋남 위험*, (b) 명시적 SQL 컬럼은 *감사 가능*하다.
- **그러나** 같은 검토가 "직접 만든 validity-interval supersession은 *엄밀성이 조용히 깨지는 가장 쉬운 자리*"라고 경고하고, no-lookahead 증명(frozen-as-of-T 스냅샷 테스트)을 **load-bearing**으로 만든다.

**→ 권고:** greenfield·1~2인 탐색 단계에서 첫날부터 bi-temporal SQL을 손으로 짜고 no-lookahead를 증명하는 것은 과한 베팅이다. **루머 추적 소실 우려가 반증된 지금**, 두 갈래 중 하나로 *단순하게* 시작하라:
- **(권장) 옵션 A:** Graphiti(무료 incremental + 검증된 bi-temporal supersession)를 코어로 쓰고, Postgres는 해소·provenance·신뢰도 테이블만. 단점은 2엔진이지만 가장 어려운 시간 정합성을 *증명된 코드로* 얻는다.
- **옵션 B:** all-Postgres이되 bi-temporal은 *의도적으로 최소* 스키마로 시작하고, frozen-as-of-T 테스트를 Phase 1에 반드시 둔다.

이건 두 리서치를 통틀어 **유일하게 진짜 미결인 결정**이다. 나머지는 아래처럼 수렴했다.

---

## 2. 수렴한 아키텍처 (계층 스택)

흐름: **수집 → 추출 → 엔티티 해소 → 저장(그래프+벡터, bi-temporal, 신뢰도 가중) → 분석 → 표현**. 어느 계층도 매수/매도/목표가를 내지 않는다.

| 계층 | 선택 | 핵심 이유 | 버린 대안 |
|---|---|---|---|
| **수집** | 단일 노드 Dagster(또는 cron+큐), **2-tier 소스 전략** | 비대칭(수집 큼/소비 1-2명)→단일 노드. 크롤 시점에 provenance·신뢰도·event/ingest 시각 *스탬프*(나중에 복원 불가) | Kafka/Spark/분산 — **제외**(쓰지 않을 규모). Reddit — 코어 제외(’25.11 AI학습 금지 정책) |
| **추출** | **스키마 강제**(function-calling JSON) 트리플. 고정 핵심 온톨로지 | KR·EN이 *같은 edge 타입*에 떨어져야 노드가 합쳐짐. 위법 술어·provenance 누락을 구조적으로 불가능하게 | Open IE(자유 트리플) — **제외**(비정규 술어→노드 분열). 모든 항목 LLM — 제외(비용) |
| **해소** ★#1 빌드 | **Issuer→Security→Listing 3단계** 정규 저장소, 권위 ID(LEI/DART corp_code/CIK/ISIN/FIGI) 앵커. 티커·은어는 *시간 범위 별칭* | 삼성전자=Samsung=005930이 안 합쳐지면 그래프는 노이즈. 상장 우주는 *유한*하므로 백만건 dedup이 아니라 **gazetteer 링킹** | 평면 "회사당 1노드" — 제외(보통주/우선주 표현 불가). LLM 자유생성 — 제외(ID 환각) |
| **저장** | **§1의 포크 결정** | 하나의 트랜잭션 경계 vs 검증된 시간 코어 | 독립 벡터DB(Qdrant 등) — 제외(2명에 무의미한 속도/운영비). MS GraphRAG 정적 인덱스 — 제외(배치/정적) |
| **분석** | **신뢰도 가중 Personalized-PageRank + TrustRank** teleport(규제기관/공시 노드 seed), truth-discovery, **독립성 인식** 보강. 군집은 **Leiden**(Louvain 아님) + BERTopic 융합 | *원시 중심성은 LOUD를 TRUE 위에 올린다*(펌핑/루머). 신뢰도를 가중치·teleport에 접어야 TRUE가 위로 | 원시 PageRank/eigenvector — 제외(공동언급량 랭킹). Louvain — 제외(분리된 커뮤니티 버그) |
| **표현** | DB→**Obsidian** 단방향 생성 마크다운. 매수/매도 어휘 *금지*, caveat 그대로 | 1-2명이 탐색·판단하는 감사 가능한 표면 | Obsidian을 백엔드로 — 제외(쿼리·시간 로직 없음) |

---

## 3. LLM 편향 문제 — 당신 질문의 직접 답

> "AI에게 가공을 맡기면 편향적으로 정리한다. 상호 비판하는 모델로 막을 수 있나?"

**직관과 다른 핵심 결론: 당신이 우려한 세 편향에 대해, 단순한 다중-AI 토론(debate)은 약하거나 역효과다.** 이유는 모두 **상관된 오류(correlated error)** — *같은 base 모델을 공유한 "독립" 비평가는 같은 맹점을 공유한다*. 그래서 1차 방어는 변증법이 아니라 **구조**(비-LLM)다.

| 편향 | 토론이 실패하는 이유 | 진짜(구조적) 방어 | 측정 |
|---|---|---|---|
| **선택/누락** | 두 토론자가 *이미 걸러진 같은 후보집합*에서 논쟁 → "없는 것"은 영영 못 봄(recall 문제에 precision 도구) | 비-LLM으로 **먼저 전수 열거**(NER+게이저티어+GDELT+이벤트렉시콘=C), LLM은 순위만(E). `C\E`·`S\L`을 *누락 후보*로 노출 | recall-at-span, RBO/recall@k, **omitted-mass(하한)** |
| **동조/합의** | 같은 prior 공유 모델은 *더* 수렴 → *가짜 합의* 제조(backfire) | **소스 독립성**: 200개 언급이 한 뿌리면 "1 effective of 200 raw". 출처 추적(origin vs amplifier), copy-dependency, 소수의견을 **1급 노드로 보존** | K-effective(M raw 병기), dissent 커버리지 테스트 |
| **학습/사전지식** | 같은 계열끼리 토론은 *공유 맹점* → 무의미 | **closed-book 추출**: 모든 주장은 *본문 span+timestamp*에 추적. 본문에 없는 걸 끌어오면 "parametric-suspected" 격리. 컷오프 누출 테스트 | span-존재 검증, NER set-difference |

**관통하는 답:** 편향의 진짜 해법은 "AI가 더 중립적으로 판단"이 아니라 **분포를 뭉개지 않고 사람에게 노출**하는 것 — 이것이 "AI는 구조화, 판단은 사람"과 정확히 일치. 토론은 폐기가 아니라 **2차·비싼·교차계열(cross-provider)·이견 보존형** 옵션으로, *고-salience 논쟁 항목에만* 강등.

---

## 4. 두 검토가 공통으로 잡은 결함 = 적용해야 할 수정

1. **휴먼 병목(가장 깊은 위험).** 아키텍처: ER abstain 큐를 1-2명이 못 비움 → 그래프 분열. 편향: 12개 플래그를 2명이 못 봄 → **분포가 화면과 눈 사이 마지막 15cm에서 다시 붕괴**.
   - **수정:** 플래그 12개 → **복합 배지 2~3개**(grounding / corroboration[K-of-M] / dispersion→소수보고서 링크). ER abstain은 *임시 노드*로 그래프에 넣되 중요도 계산에서 제외, 큐 드레인율 < 도착률이면 알림. **minority-section-open-rate를 진짜 anti-bias KPI로 추적.**
2. **grounded ≠ unbiased (체리피킹).** 모든 검사를 통과해도 *어떤 grounded 사실을 elevate하느냐*의 편향엔 탐지기가 없음.
   - **수정:** **within-document stance-dispersion 탐지기**(싼 계층). 원문 stance 분포 vs elevate된 집합 stance 분포가 벌어지면(예: 70% 신중한 공시 → 80% 강세 추출) "selection-skew" 플래그.
3. **상관된 포획.** omitted-mass의 capture-recapture가 LLM·비-LLM 같은 맹점 공유 → omission을 *낮게* 편향(거짓 안심).
   - **수정:** **하한으로만 보고**("최소 X% 누락, 두 추출기가 맹점 공유 시 낮게 편향"). KR 스트림에 *진짜 비상관* 2번째 채널 추가.
4. **NLI는 독립적이지 않다.** lexical-overlap 단축 때문에 extractor가 가장 쉽게 조작하는(본문 복붙) 케이스를 통과시킴.
   - **수정:** "독립" 표기 강등. 고-overlap 쌍은 HANS형 hard-subset로. 싼 계층에 부정/헤지/인용 렉시콘 체크(극성 반전 차단).
5. **생존편향(delisting).** 시점 정합성을 *사실*에만 걸고 *우주*엔 안 걸면, 과거 랭킹/리드랙이 *생존자만* 대상 → look-ahead.
   - **수정:** **issuer master 자체를 bi-temporal**(상장폐지·합병·파산 보존, "T시점에 존재했던 우주" 재구성).
6. **K-effective 방향성.** 독립성 추정은 *독립성의 상한*(공모 과소계수)이라 *합의를 믿는 쪽*으로 편향.
   - **수정:** 사람에게 "K (독립성 상한; good-source 복사 공모는 과소계수)"로 *방향성 명시*.

---

## 5. 과설계 경고 → 정직한 단계화 (가장 중요)

> 두 검토 모두 최강 발견: **per-item 런타임 비용은 줄였지만, 비용이 사라진 게 아니라 상시 운영·평가 부담으로 이동**했다. 1-2명에게 연구팀급 eval(골드셋, 심은-공시 감사, 가격회귀, 6개 임계값 튜닝)은 가치를 압도한다.

### MVP (이것만으로도 충분히 엄밀한 시스템)
- Tier-1 **구조화 소스만**: DART/OpenDART(+corp_code), SEC EDGAR(+CIK), GDELT(전역 뉴스 그래프, 엔티티/테마 *무료* 추출), Alpaca + CCXT/Upbit.
- 엔티티 해소(권위 ID 앵커) → 그라운딩 스키마 추출 → **싼 상시 구조 탐지기**(S0–S6: span 검증, recall, RBO, origin-vs-amplifier, effective-independent, dissent 보존) → Obsidian 뷰.
- 신뢰도 가중 PPR + Leiden 군집.

### 명시적 DEFER / 선택 (검토의 "나중에" 판정 그대로)
- **전이엔트로피/info-flow 엔진** — §6 참조. 가장 과설계 + 사용자 스탠스 위반 + 데이터 부족.
- 전체 CIB/coordinated-cluster(S10, 최고 false-positive), 2x entity-swap probe(싼 name-masking 임베딩 거리 프록시로 대체).
- 무거운 eval 장치(심은-공시 감사, 가격회귀) — 싼 스택이 부족함을 입증한 뒤에.

### 권장 빌드 순서
**P0** Postgres+pgvector(+§1 그래프 결정) · Issuer→Security→Listing 해소 · Tier-1만 · event/ingest 스탬프 →
**P1** 스키마 추출 + bi-temporal + frozen-as-of-T 테스트 + 싼 pre-filter 캐스케이드(trafilatura→lingua→Kiwi→MinHash→BGE-M3) + Haiku→Opus 티어링 →
**P2** 신뢰도 가중 PPR+TrustRank+truth-discovery(*그 다음에야* Tier-2 커뮤니티를 낮은 신뢰도로 투입) + 싼 편향 탐지기(S0–S6) + 복합 배지 표현 →
**P3** Leiden+BERTopic 군집 + 분기 요약 + 실제 종토방/Reddit 샘플로 검증 →
**P4(선택, 마지막·게이트)** info-flow.

---

## 6. info-flow(전이엔트로피) — 별도 경고

리드랙(정보→가격) 분석은 가장 비싼 분석이자 **유일하게 사용자 스탠스를 위반하는 계층**이다: FDR을 통과한 방향성 리드랙 edge는 *어휘를 금지해도 실질적으로 신호다*. 게다가 몇 년치 일봉으로는 조건부/다변량 전이엔트로피에 **표본이 부족**(유한표본 상향 편향)해, 절차가 완벽해도 *과소검정력의 인공물*을 FDR-생존자로 내놓을 수 있다.
- **권고:** 코어 엄밀성으로 제시하지 말 것. *나중·선택*, 그리고 "이 복잡성이 2명에게 값하는가?" 명시 게이트 뒤에. 만든다면 ADF+KPSS(가격 아님 *수익률*)→MI→Granger→공통동인 조건부 effective TE→IAAFT surrogate→Benjamini-**Yekutieli** FDR + **쌍별 최소표본 게이트**, 그리고 가격 시계열의 *조정 vintage*(분할/배당 소급조정의 look-ahead) 처리.

---

## 7. 미결 질문 (사람이 결정/캘리브레이션 필요)
- **§1 저장 포크** (가장 중요): Graphiti vs 최소 bitemporal — greenfield엔 Graphiti 권장.
- 소스 신뢰도 prior 분류 체계의 초기값과 감사 루프.
- KR+EN 클레임 정규화(실적 서프라이즈=earnings beat) 품질 — D3/D4의 load-bearing 의존성. *언어 내 먼저*, 교차언어는 별도 저신뢰 신호.
- escalation 게이트 임계값(너무 빡빡→이견 재붕괴, 너무 느슨→비용 폭발).
- OpenDART 일일 호출 쿼터(공식 페이지에서 확정 못 함 — 스케일 전 확인).
- KR 포털 스크래핑 TOS와 Reddit 제외 기준의 일관성.
