# 데이터 전략 결정 메모

자동화 전에 "무엇을·어디서·얼마나 자주" 가져올지 정리. 자동화는 **마지막에 잠그는 나사**.

## 1. 자동화 가능성은 두 갈래로 갈린다 (전부 기다릴 필요 없음)

| 레이어 | 자동화 지금 가능? | 이유 |
|---|---|---|
| **시세·거시·시장폭** (yfinance) | ✅ 지금 OK | 멱등(덮어쓰기), 세션 불필요, 무한누적 아님 |
| **뉴스 → Claim/Mention** | ⏸️ 구조 먼저 | 유일한 무한 누적, 중복부채(1.54), 세션 없으면 품질↓ |

→ 시세 레이어만이라도 자동 갱신하면 "지금 시장 상태"는 매일 신선해짐. 빠른 승리.

## 2. 척추 결정 ✅ → **(a) 2-tier (무키 유지)** [2026-06-24 확정]

무인 실행 시 뉴스 신선도 유지 방식:
- **정량 레이어** (자동 실행, 무인 OK): 뉴스량·ThemeDay·시세·시장폭·거시 — 규칙기반/멱등.
- **의미 레이어** (세션 패스): 테마 요약·관계 추출 — "세션의 Claude"가 주기적으로 갱신.
- **무키(no-API-key) 원칙 유지.** 요약은 날짜 박혀있고(이미 구현) 패스 사이엔 약간 stale — 허용.
- LLM API 도입(방향 전환)은 **보류.** websocket/실시간도 보류(창립 제약과 충돌).

→ 이 결정에 따라: 보존은 정량 레이어 위주로 누적, 의미 레이어는 세션이 관리.

## 3. websocket/실시간 현실 점검
창립 제약(1~2인, heavy-ingest/tiny-serving)과 충돌. (a)와도 충돌. 거의 확실히 과잉.
→ 일별/시간별 배치로 충분. 실시간은 보류 권장.

## 4. 순서 (척추 정해진 뒤)
1. ✅ 추출 tier 확정 → 2-tier (위 §2)
2. ✅ 기존 뉴스 중복 일회성 정리 (1.54→1.02, `dedup_news.py`)
3. ⏳ 보존 규칙 (Claim/Mention 무한증가 — 아래 §5)
4. ⏳ **자동화 (마지막)** — 아래 레시피를 N시간마다

### 자동화 레시피 (2-tier, 구조 정해지면 cron/Actions로)
```
# [정량 패스] 무인 가능 — 규칙기반·멱등. 예: 6시간마다
SKG_STORAGE_BACKEND=neo4j python pipelines/news_pull.py        # 뉴스 (sha1 멱등)
                                  pipelines/market_state_pull.py # 시세·시장폭
                                  pipelines/build_themes.py      # 테마 카운트·ThemeDay
                                  pipelines/build_emergent.py    # 키워드망
                                  pipelines/reanalyze.py         # 랭킹
                                  pipelines/export_artifacts.py  # → 아티팩트
git add web/public/data && git commit && git push              # → 자동 재배포

# [의미 패스] 세션(Claude)이 가끔 — 무키. 예: 주 1~2회
#   세션이 새 헤드라인 읽고 data/theme_summaries.json 갱신 (날짜 박음)
#   필요시 data/edgar/extractions/ 에 풍부한 관계 추출
```
→ 정량은 매일 신선, 의미는 세션 패스 사이엔 약간 stale(날짜 표시됨). 무키 유지.

## 5. 보존 규칙 (다음 작업)
**핵심 통찰: ThemeDay(일별 집계)가 영속 자산이고, raw 뉴스 Claim은 윈도우링 가능.**
- ThemeDay/시세/랭킹 = 작고 집계됨 → 영구 보존.
- raw 뉴스 Claim/Mention = 무한증가 → ThemeDay에 집계된 뒤엔 N일 윈도우만 유지(prune 가능).
- 옵션: (a) N일 지난 뉴스 Claim prune (집계는 ThemeDay에 남음), (b) 콜드 아카이브(gz),
  (c) as_of 스냅샷. **파괴적이라 승인 후 실행.** 기본은 비활성(누적 유지).

## 데이터 소스 현황 (확정된 것)
- **미국 기업**: SEC EDGAR (키 없음) ✅
- **한국 기업**: DART (무료 키, `.env`) ✅
- **뉴스**: Google News RSS (미/한) + 언론사 RSS ✅ — 본문요약까지
- **시세·거시·원자재**: yfinance (키 없음) ✅
- **시총 랭킹**: FinanceDataReader (KRX 일괄) ✅
- saveticker/stockeasy: robots/JS렌더로 수집 불가 → 참고만
