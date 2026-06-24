# 아키텍처 (Architecture)

주식 시장 정보를 그래프로 구조화하는 지식그래프 시스템. 사용자의 3계층 멘탈 모델
(**대시보드 / 백엔드 로직 / 데이터베이스**)에 맞춰 정리됨.

```
2606-vibe-stock/
├─ config.py                # 단일 calibration 표면 (모든 매직넘버·경로·env)
├─ run.py                   # 주 진입점 ① 오프라인 데모 파이프라인 (fixtures → SQLite/vault)
├─ loop_build.py            # 주 진입점 ② 무인 누적 루프 (EDGAR/DART → Neo4j)
│
├─ pipelines/               # ▶ 실행 스크립트. [Q]=정량(자동화 가능) [S]=의미(세션) [V]=렌더
│   ├─ news_pull.py         # [Q] 미국 뉴스 수집 (규칙기반 stance/risk, 멱등 sha1 doc_id)
│   ├─ kr_pull.py           # [Q] 한국 기업(DART) + 한국 뉴스 (규칙기반)
│   ├─ market_state_pull.py # [Q] 52주 위치(시장폭) + 원자재/메모리 (yfinance, 덮어쓰기)
│   ├─ build_themes.py      # [Q] 테마 연관망 (고정 사전 — 규칙)
│   ├─ build_emergent.py    # [Q] :Term 키워드망 (DF필터 — 규칙)
│   ├─ reanalyze.py         # [Q] 랭킹 재계산(PPR) + graph.html
│   ├─ dedup_news.py        # [Q] 일회성 중복정리 (파괴적 — 승인 필요)
│   ├─ ── 의미 레이어 (세션이 작성, 무인 자동화 X) ──
│   ├─ (data/theme_summaries.json)  # [S] 테마/연결 의미 요약 — 세션의 Claude가 작성
│   ├─ (data/edgar/extractions/)    # [S] 세션 작성 풍부한 추출 (supplies/competes 등)
│   ├─ ── 렌더(아티팩트→React) ──
│   ├─ build_theme_view.py  # [V] themes.html + themes.json (드릴다운/감쇠/추세)
│   ├─ build_emergent_view.py # [V] emergent.html
│   ├─ build_dashboard.py   # [V] dashboard.html
│   ├─ export_artifacts.py  # [V] 모든 뷰 → web/public/data/*.json + 백업
│   ├─ artifact_views.py    # [V] 뷰별 데이터 추출 헬퍼
│   └─ comovement_trial.py  # [Q] 거시↔주가 동조(상관) (실험, 기본 비활성)
│
│   # 2-tier 자동화 모델: [Q]는 무인 cron 가능(규칙·멱등). [S]는 세션이 가끔 갱신
│   #   (무키 원칙). [V]는 [Q]/[S] 갱신 후 돌려 아티팩트 생성. 자세히: DATA_STRATEGY.md
│
├─ skg/                     # ▶ 핵심 패키지
│   ├─ models.py            #   도메인 dataclass (Issuer, Claim, Theme, ...)
│   ├─ ingest.py            #   코퍼스 리더
│   ├─ prefilter.py         #   근접중복 클러스터링 (통신사 기사 묶기)
│   ├─ resolve.py           #   엔티티 해소 (ID앵커 + 퍼지) — Repository ABC에 의존
│   │
│   ├─ database/  ◀ 데이터베이스 계층
│   │   ├─ repository.py    #   Repository ABC (백엔드 교체 seam)
│   │   ├─ sqlite_repo.py   #   SQLite 구현 (데모/conformance 기준)
│   │   ├─ neo4j_repo.py    #   Neo4j 구현 (프로덕션, 라이브 그래프)
│   │   └─ __init__.py      #   make_repo(cfg) 팩토리
│   │
│   ├─ sources/   ◀ 백엔드: 데이터 수집
│   │   edgar · dart · news · market   (전부 키 없거나 무료 키)
│   ├─ extract/   ◀ 백엔드: 추출 (헤드라인/공시 → Claim)
│   │   edgar_rules · news_rules · fixture_extractor (+ base seam)
│   ├─ analyze/   ◀ 백엔드: 관계망·로직
│   │   pagerank · detectors · lexicon · themes · emergent · market_state · graph_builder
│   │
│   └─ export/    ◀ 대시보드 계층 (시각화 산출물)
│       dashboard · force_graph · emergent_graph · obsidian
│
├─ data/   (gitignore) EDGAR 코퍼스 37k + 상태 + 세션작성 요약
├─ out/    (gitignore) 생성물: dashboard/themes/emergent/graph.html, vault, skg.db
├─ fixtures/  오프라인 데모 합성 데이터
└─ tests/  test_core(8) + test_neo4j_conformance(28, 라이브 Neo4j+플래그 시만)
```

## 데이터 흐름

```
수집(sources) → 추출(extract) → 해소(resolve) → 저장(database)
            → 분석(analyze: PPR·테마·감쇠) → 시각화(export: HTML)
```

## 데이터베이스 — 노드/관계 + 시계열

**노드(13+1):** Source, Issuer, Security, Listing, Alias, Claim, Mention, AnalysisResult,
Sector, MacroIndicator, PriceSeries, Theme, Term, **ThemeDay(신규)**.

**시계열 저장 방식:**
- 가격/거시: 노드 1개에 `recent_closes_json`(90일 윈도우) — 대시보드 스파크라인.
- **테마: `:ThemeDay {theme_id, day, count, w_bull/bear/neut}`** — 일별 버킷.
  `theme_id@day`로 MERGE(멱등). 이것이 **시간감쇠(가중합) · 추세차트 · 실시간 누적**을
  동시에 받치는 그릇. 향후 crawling/websocket 데이터는 day-버킷만 추가하면 됨.
- bi-temporal: 모든 fact가 `event_time`+`knowledge_time`, as-of 읽기는 렉시컬 비교.

**멱등성:** 모든 write는 MERGE(CREATE 금지). 뉴스 doc_id는 `hashlib.sha1`(프로세스 무관
안정 — 이전 `hash()`는 재실행마다 달라져 중복 생성하던 버그였음, 수정됨).

> ⚠️ **정직한 주의:** 현재 테마 수치(ThemeDay 카운트·감쇠 열기·추세차트의 "6/22에 245건"
> 등)는 옛 `hash()` 버그로 생긴 **기존 중복 뉴스(비율 ~1.54) 위에서 계산됨.** doc_id는
> fix-forward 완료라 더 나빠지진 않지만, 아래 "깨어서 할 일 ④" 일회성 정리 후에야 정확해짐.

## 검증
- `pytest tests/` → 8 pass / 28 skip (conformance는 라이브 Neo4j + `SKG_ALLOW_NEO4J_WIPE=1`일 때만).
- 4개 HTML 재생성: `pipelines/reanalyze.py`(graph), `pipelines/build_theme_view.py`(themes),
  emergent/dashboard는 `skg.export`의 함수.
- 회귀: `python run.py`(오프라인 SQLite) 정상.

## ✅ 완료된 정리 (2026-06-24)
- 루트 11개 스크립트 → `pipelines/` 8개 + 루트 3개(run/loop_build/config).
- `skg/store/` → **`skg/database/` rename 완료** (13개 import 전부 수정·검증).
- 결합 위반: `resolve.py`→`Repository` ABC, `graph_builder.py` `store/`→`analyze/`.
- 뉴스 doc_id 멱등성 버그 수정, Theme/Term/ThemeDay 제약, per-day 버킷.

## ⏳ 남은 할 일 (파괴적/대규모 — 방향 정하면 진행)
1. **export/ 디커플링**: `repo._read(raw Cypher)` → Repository 메서드(`get_issuer_breadth` 등)로.
   시각화가 Neo4j에 하드결합돼 있음. 다수 파일.
2. **보존/가지치기 정책**: Claim/Mention 무한 증가. 옵션(1년 후 prune / 콜드 아카이브 /
   as_of 스냅샷 압축) — 파괴적이라 방향 확인 후 실행.
3. **기존 뉴스 중복 일회성 정리**: 옛 `hash()` 버그로 생긴 중복(비율 ~1.54). doc_id는
   fix-forward 완료(신규는 중복 0). 기존 중복은 DETACH DELETE 필요 — 방향 확인 후.
4. **news_pull/kr_pull 공통 로직 추출**: `_register_news_sources`/claim 빌드 중복 → `skg/sources/news.py`.
