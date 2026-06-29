# 정보 품질 감사 (2026-06-28)

발행 아티팩트(`web/public/data/*.json`)에 **실제로 도달하는** 정보적 결함만 추림.
8개 차원 병렬 탐색 → 모든 발견을 반론(adversarial) 검증 → 측정 증거로 뒷받침.
원시 37건 중 검증 통과 27건 (high 8 / medium 12 / low 7). "critical" 주장 4건은 검증 후
전부 high로 하향(실제 결함이나 드릴다운 하위노드·단일 뷰에 국한, 주 화면을 오염시키진 않음).

---

## 1. 핵심 진단

지배적 결함은 **시간(bi-temporal) 모델의 붕괴**다. `config.py:130`의
`AS_OF_NOW="2026-06-23T00:00:00"`가 하드코딩(env 오버라이드·자동전진 없음)된 채,
`news_pull.py`/`kr_pull.py`가 모든 Claim의 `knowledge_time`를 이 상수로 강제 스탬프한다
(`skg/sources/news.py`에서 `ingest_time=knowledge_time`). 그 결과:

- 오늘(06-28) 수집한 06-24~06-27 기사가 `WHERE knowledge_time <= $as_of` 가드를 그대로 통과.
- **방향에 주의:** 데이터가 "안 보이게 얼어붙은" 게 아니라 그 반대다 — knowledge_time이
  상수 06-23으로 고정돼 가드가 *전부* 통과하므로, 최신 뉴스가 **새어 들어와 보인다**.
  즉 **라벨은 06-23인데 내용은 06-28까지 신선**하다(라벨 거짓, 내용은 오히려 더 신선).
- 발행물은 "06-23 스냅샷" 라벨을 달고도 내용은 06-28까지의 최신 뉴스를 담음.
  `themes.json`(표시 헤드라인)의 **54%(836/1534)** 가 06-23 이후, `graph.json`(이슈어)의
  **87%(333/384)** 가 06-23 이후 날짜의 최신 헤드라인을 표시. (둘은 서로 다른 파일·분모.)
- 같은 뿌리가 (a) freshness 라벨 거짓, (b) 시간감쇠 `now=06-23` 고정으로 최근 4일이 전부
  weight 1.0 클램프, (c) 요약(06-24)과 헤드라인(06-27) 날짜 불일치를 동시에 유발.

2차 축은 **gazetteer 키워드 오염**(테마 오배정): `조정`/`overvalued`/`수주`/`구축`/`소재`/
`통합`/`통상` 같은 다의어가 한글 substring 매칭되어 `ai_bubble`≈95%, `dc_build`≈89% 거짓양성.

3차 축은 **영어 편향 lexicon**: stance 질량의 **92%가 회색(중립)** — 한글 방향성 동사
(수주/계약/공급/사망/제재…)가 사전에 없어, 프로젝트 간판 신호(개발 vs 거품)가 사실상 붕괴.

---

## 2. 결함 랭킹 (심각도 × 사용자 도달 × blast-radius, 검증 후 보정 심각도)

| # | 심각도 | 결함 | 사용자가 보는 증상 | 측정 증거 | 원인(hop) |
|---|--------|------|--------------------|-----------|-----------|
| 1 | **High** | **bi-temporal 붕괴 + freshness 라벨 거짓** | "06-23 기준" 라벨인데 카드는 06-24~28 뉴스 | themes.json 헤드라인 54%(836/1534)·이슈어 87%(333/384)가 06-23 이후 | store: knowledge_time=as_of 강제 |
| 2 | **High** | **stance bar 92% 회색 (KR 방향성 동사 누락)** | 'ai' 노드가 bull5%/bear3%/neut92% — 신호 소실 | 52노드 neut=3459.7/3754.6=92.1%; 중립 KR head의 36%가 실제 방향성 보유 | extract: lexicon.py KR 공백, dead phrase '수주는 호재' |
| 3 | **High** | **emergent.json ≈48% 비주제 보일러플레이트** | 최대 허브 노드가 '밝혔다'(보도 동사) | 120노드 중 58~69 잡음; '밝혔다' df=306/deg=66(1위); 'hits' df=352 | analyze: emergent.py stoplist에 '했다'만, '밝혔다' 없음; df_hi=0.02가 1.7% 보일러플레이트 못 잡음 |
| 4 | **High** | **graph.json KR 노드가 상위 KOSPI 누락** | SK하이닉스(HBM 벨웨더)·NAVER·삼성바이오·POSCO 부재; 6뉴스 DB하이텍은 포함 | backup엔 303 DART 존재; 선택키 `ppr_naive DESC LIMIT 120`(시총·뉴스 무시) | export: artifact_views.py:118-122 |
| 5 | **High** | **lexicon KR 중립화율이 EN의 1.4~2.3배** | KR-heavy 테마가 EN보다 "미정"으로 보여 시장별 확신 왜곡 | 노드 head: KR 중립 57% vs EN 25%(2.3x); 전체 코퍼스 1.4x | extract: 동일 KR lexicon 공백 |
| 6 | **High** | **ai_bubble 노드 ≈95% 거짓양성** | 'AI 거품/과열' 근거 8건 중 0건이 실제 AI 버블 (Sandisk Overvalued, 롯데리츠 담보대출 조정) | 170회 발화 중 overvalued=114·조정=51, 진짜 3건; 95%가 AI앵커 없음 | analyze: subthemes.json bare overvalued/조정 |
| 7 | **High** | **dc_build ≈89% 거짓양성, freq가 부모 초과** | '데이터센터 건설' 자식 freq=191 > 부모 datacenter 117 | 수주=88·구축=67·프로젝트=45; 89%가 datacenter 앵커 없음; 패널 '뉴스 191건' | analyze: bare 수주/구축/프로젝트, child<parent 가드 없음 |
| 8 | **High** | **요약(06-24)에 헤드라인 없는 인물 'Warsh' 명시** | rates 요약 "연준 의장 교체(Warsh)" — 282 head 중 0건; 패널은 Hassett만 | grep Warsh=0, Hassett=1; 최신 head는 전부 hike/hold | semantic: 세션작성 요약이 head 코퍼스와 불일치 (단 '인하 방향 오류' 주장은 검증서 반박됨) |
| 9 | **Medium** | **중복 헤드라인 / freq ≈22% 인플레** | 한 이슈어 6칸 중 동일 헤드라인 2회; '뉴스 N건' 과대 | graph.json 117/400(29%) byte-identical 중복; 코퍼스 ratio 1.223; earnings freq +23% | store/export: run_pipeline.bat에 dedup_news.py 부재 |
| 10 | **Medium** | **semi_material 소재 다의어 ≈80% 거짓양성** | 반도체 자식인데 화장품·식품포장·배터리 소재 혼입; 표시 엔티티 절반만 진짜 | 209건 중 130 bare 소재, 80% 반도체 앵커 없음 | analyze: 소재 substring |
| 11 | **Medium** | **ma_merger 통합 다의어 ≈44% 거짓양성** | '합병/통합'에 ESG 통합공시·통합플랫폼 혼입 | freq=94, 통합-only의 80%가 합병 앵커 없음 → 전체 ~44% off-topic | analyze: 통합 substring |
| 12 | **Medium** | **trade 통상이 회사명 매칭** | '관세/무역'에 대림통상(욕실)·산업통상부 | 발행 8 head 중 3건이 통상 substring 사고(전부 잡음) | analyze: 통상이 고유명사 내부 매칭 |
| 13 | **Medium** | **stance 부정/역설 미처리** | '리스크 해소'·'overvalued after surge'가 반대 색 | 1084건 중 ~12건 부정/밸류에이션, 3-4건 명백 반전(발행 확인) | extract: stance_of 순 키워드 카운트 |
| 14 | **Medium** | **beat/record가 하락 주식 덮어씀** | 최대 노출 'earnings' 노드 8 head 중 2건(25%) 방향 오류 (FedEx '폭락'이 녹색) | bullish 105건 중 3-4건이 하락 동사 포함 | extract: BEARISH에 fall/decline/drop 부재 |
| 15 | **Medium** | **edge 요약이 사용자 thesis 검증** | "당신이 말한 …급등의 데이터 근거" — 중립 co-occurrence를 인과 확정으로 reframe | semiconductor\|supply는 stance 0/0/28(장비출시), '급등' 근거 아님; 49엣지 중 2개 | semantic: _note 서술전용 위반 |
| 16 | **Medium** | **요약 staleness 불투명** | 06-23 헤더 / 06-24 요약 / 06-27 헤드라인 3날짜가 경고 없이 공존 | 요약 보유 10노드 전부 요약일 이후 헤드라인 보유; edge 요약은 날짜 없음; web/src에 stale 비교 없음 | semantic: summary_date가 경고 아닌 단순 라벨 |
| 17 | **Low** | **node 120자 절단이 매칭 키워드 숨김** | 근거 헤드라인이 왜 그 테마인지 안 보임 | 410 head 중 37(9%)이 자기 키워드 미포함, 37/37 전부 len==120 | analyze→export: _clean()[:120] |
| 18 | **Low** | **시장상태 패널 가격 날짜 혼재** | 06-26 구리와 06-18~23 유가/금리가 같은 날인 듯 나란히 | STATE set=06-26, MACRO=06-23, ^TNX=06-18; 행별 날짜 키 없음 | export: market_state.py as_of 미고정 |
| 19 | **Low** | **meta 카운트가 view의 ~245~300배** | 헤더 "127,780 노드·173,306 관계·06-23 기준" (실제 view 412/583) | dump_full_graph(무필터) 카운트를 meta에 그대로; App.jsx:45 렌더 | export |
| 20 | **Low** | **16개 대형주가 뉴스 0건 점** | BofA·Amgen·CSX 등이 '뉴스 0건' 빈 패널, 타 뷰엔 부재 | 280 US 중 16(5.7%) news_count=0, 누적 코퍼스 기준 0; (단 sector 엣지는 있어 '고립'은 과장) | source: 인덱스 노드화하나 US 뉴스 소스 미커버 |
| 21 | **Low** | **시간감쇠 as_of 고정 → 최근 4일 weight 1.0** | 06-24~27 동일 신선도, heat ~1.29x 인플레 | 410 head 중 278(68%)이 age<=0; 단 정규화로 순위·크기·stance 비율 보존 | analyze: _decay_weight now=AS_OF_NOW |
| 22 | **Low** | **요약 인과/예측 framing** | 'A→B→C' 화살표·'기대' 톤이 중립 설명란에 | geopolitics '휴전 기대→유가 하락→항공주 상승' 등; 단 헤드라인에 근거는 있음 | semantic |
| 23 | **Low** | **trend 스파크라인 raw 미dedup** | AI trend [59,31,71,107,16] 미세 인플레 | dedup 시 0~11% 감소, 피크일 거의 불변 | duplication |
| 24 | **Low** | **ai 요약이 최대 하위버킷 ai_robot(208) 누락** | AI 요약이 인프라 중심, 로봇 미언급 (단 '세부 이슈' 칩 1순위로 노출, stance는 중립이라 '약세 편향' 주장은 반박됨) | ai_robot freq=208 > ai_infra 103 | semantic |

---

## 3. 지금 당장 (데이터/설정만 고치면 발행물 즉시 개선)

- **`dedup_news.py`를 `run_pipeline.bat`에 삽입** — #9·#23 동시 해결. freq 22% 인플레와 29%
  중복 헤드라인이 매 refresh마다 누적 중. 한 줄 추가로 멈춤. (또는 export 시 head 텍스트 dedup.)
- **`data/subthemes.json` bare 키워드 제거 + AI/datacenter 앵커 co-occurrence 요구** — #6·#7·#10·
  #11·#12를 한 파일 편집으로: `조정`·`overvalued`(ai_bubble), `수주`·`구축`·`프로젝트`(dc_build),
  `소재`·`기판`(semi_material), `통합`(ma_merger), `통상`(trade). child<parent freq 가드 추가.
- **`skg/analyze/lexicon.py` KR 극성 동사 추가** + dead phrase '수주는 호재' 삭제 — #2·#5·#14.
  bull: 수주/수출/계약/공급/출시/신고가/돌파; bear: 사망/사기/제재/횡령/중단/하향/적자전환/하락/약세.
  추가 후 `build_theme_view.py` 재실행으로 92% 회색 즉시 재계산.
- **`skg/analyze/emergent.py` stoplist 보강** — #3. KR 보일러플레이트(밝혔다/있다/따르면/위한/규모/
  억원) + EN scaffolding(tikr/barchart/stocktwits/hits/form/june/valuation). df_hi 하향 또는 min-degree gate.
- **요약 텍스트 정리** — #8·#15·#22: rates에서 Warsh 제거, edge 요약 '당신이 말한'/'급등 근거'/
  화살표 제거, 현재 head 기준 재작성.

## 4. 구조적 (방향 결정 필요 — 파이프라인/모델 변경)

- **bi-temporal 분리** (#1·#21·#16 공통 뿌리): `ingest_time`/`knowledge_time`를 실제 벽시계로
  스탬프하고 `as_of`는 read 필터 전용으로. **또는** 매 루프 `AS_OF_NOW`를 run 날짜로 전진.
  시간감쇠 `now`도 실제 today/`max(event_time)`로. → freshness 라벨·감쇠·요약 staleness 3개 동시 해결.
- **KR 노드 선정 재설계** (#4): `ppr_naive` → 시총/뉴스 degree 기반. KOSPI top-30 대조 export check.
- **요약 재생성을 refresh 루프에 통합** (#8·#16): 세션 수작업 요약이 head 코퍼스와 표류. 자식
  freq/stance에서 파생하고, newest head > summary_date 시 'stale' 배너.
- **lexicon KR/EN parity + 부정/밸류에이션 처리** (#2·#5·#13·#14): 단순 토큰 카운트 모델 한계.
- **meta 카운트 이원화 + 신선도 라벨 정합** (#18·#19): full-dump vs as_of-gated 2개 카운트, 패널 행별 event_time 노출.

---

## 5. 범위 메모 — EDGAR 관계 레이어는 발행물에 도달하지 않음

`graph.json`의 top-level 키는 `issuers`와 `macros` **뿐**이고 edges 배열이 아예 없다(n=0).
즉 EDGAR 공시에서 추출하는 이슈어↔이슈어 관계([S] supplies/competes 등)는 **발행 아티팩트에
전혀 도달하지 않는다** — GraphView는 sector 멤버십 엣지를 클라이언트에서 그릴 뿐이다.
"사용자가 보는 정보" 기준 감사에선 정당히 범위 밖이지만, **KG에서 가장 풍부한 의미 엣지가
대시보드에 안 보인다**는 사실 자체가 별도로 짚어둘 만하다(향후: graph.json에 관계 엣지를
실어 보낼지 결정 필요).

---

*감사 방법: 8차원 병렬 finder(freshness·extraction-noise·theme-assignment·stance·resolution·
semantic·bitemporal·duplication) → 발견별 반론 검증(reproduce-or-reject) → 측정증거 기반 종합.
모든 수치는 실제 `web/public/data/*.json` 및 라이브 Neo4j 코퍼스에서 재현 확인됨.*
