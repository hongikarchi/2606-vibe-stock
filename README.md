# 주식 지식그래프 — 시연 파이프라인 (오프라인/합성)

크롤링한 주식 정보를 **node 그래프로 구조화**하고, 그 사이의 연관성·위계·중요성을 뽑아
사람이 판단할 수 있는 형태로 정리하는 시스템의 **작동하는 시연**입니다.

> **핵심 스탠스:** AI는 정보를 **구조화**할 뿐, 매수/매도 판단은 **사람**이 합니다.
> 이 파이프라인은 어떤 매매 신호도 내지 않습니다(구조적 가드레일로 강제).

리서치 두 건(아키텍처 + LLM 편향 방어)과 각 적대적 검토의 결론을 구현했습니다.
설계 문서는 `research/00-SUMMARY-한국어-설계.md`, 계획은 `.claude/plans/`에 있습니다.

---

## 빠른 시작

```bash
pip install -r requirements.txt   # networkx, rapidfuzz, scipy
python run.py
```

끝나면 **`out/vault/`** 가 생성됩니다. Obsidian으로 그 폴더를 열거나, `out/vault/_index.md`
를 직접 보세요. `out/skg.db`(SQLite)에 전체 그래프가 들어있습니다.

콘솔에 한글이 깨지면(Windows cp949) 데이터 문제가 아니라 콘솔 인코딩 문제입니다 —
**vault 파일은 UTF-8로 정상**입니다. `set PYTHONIOENCODING=utf-8` 후 실행하면 콘솔도 정상입니다.

---

## 무엇을 보게 되나 (4가지 핵심 차별화, 합성 데이터로 시연)

`out/vault/_index.md`(대시보드)와 `entities/`, `minority/` 폴더에서:

1. **교차언어 엔티티 해소** — `삼성전자` = `Samsung Electronics` = `삼전` = `005930`이 한 노드로
   합쳐집니다. 권위 ID(DART corp_code/CIK/ISIN) 앵커 + 시간범위 별칭. 모호한 `Samsung`(삼성전자
   vs 삼성SDI)은 **억지로 합치지 않고 보류(provisional)** 하여 중요도 계산에서 제외합니다.
   *대조:* naive 문자열매칭이면 더 많은 노드로 쪼개집니다(콘솔의 `naive vs canonical`).

2. **신뢰도가중 중요도 (TRUE over LOUD)** — 원시 PageRank는 펌프(`테마주Z`)를 **#1**로 올리지만,
   신뢰도가중 PPR + TrustRank는 출처 신뢰도를 접어 **#6으로 강등**합니다. 대시보드에 두 랭킹이
   나란히(`⬇` = 강등). 50개 복붙 펌프 글은 1개 유효독립 소스로 collapse됩니다(`K eff / M raw`).

3. **편향 방어 탐지기 4종** (LLM이 "편향적으로 정리"하는 것을 구조적으로 잡음):
   - **누락(omission)** — 비-LLM 베이스라인으로 본문을 전수 훑어, 추출이 빠뜨린 **material 이벤트**
     (예: `중소제약` 분식회계 제보)를 복원. 누락 질량은 **하한**으로 보고(두 추출기가 맹점을
     공유하면 낮게 편향되므로). → `minority/`
   - **유효독립 corroboration** — "K effective of M raw"로 표시. K는 **독립성의 상한**(good-source
     복사는 과소계수)임을 명시.
   - **grounding (closed-book)** — 추출이 본문 근거 span에 추적되는지 검증. "파산 우려는 **사실무근**"
     이라는 span에서 "파산 리스크"를 사실로 추출하면 **극성 반전**으로 격리(단순 substring 검사가
     놓치는 케이스).
   - **선택 편향 (stance-dispersion, grounded ≠ unbiased)** — 신중한 공시(신중 6:강세 1)에서
     **강세 문장만 elevate**하면, 각 추출이 개별적으로 참이어도 *선택*이 편향됐음을 JS divergence로
     포착. → `minority/skew_*`

4. **시점 정합성 (bi-temporal) — 생존편향 방지** — 과거 랭킹을 *그때 존재했던 우주*로 재구성합니다.
   `퇴출기업X`는 2023년 분석엔 나오지만 현재 분석엔 없습니다(look-ahead 차단). 티커 재사용도
   처리: `$V`는 2007년 Vivendi, 2026년 Visa로 시점별 다른 엔티티에 해소됩니다.

**대시보드는 "정리된 지식"으로 읽히게** 설계됐습니다 — 소수·이견 리포트가 **최상단**(각주 아님),
그 아래 중요도 랭킹. 모든 페이지는 출처와 as-of 날짜를 인용하고 매매 어휘를 담지 않습니다.

---

## 합성 데이터 (`fixtures/`)

| 파일군 | 시나리오 | 발화하는 차별화 |
|---|---|---|
| `f1_*` | 삼성 다중 별칭 + 보통/우선주 + 모호한 `Samsung` | 엔티티 해소, abstain→provisional |
| `f2_*` | DART 공시 1 vs 테마주Z 펌프 5 | TRUE-over-LOUD, K-of-M |
| `f3_*` | 내부고발(분식회계)이 강세 잡담에 묻힘 | 누락 복원, 소수보고서 |
| `f4_*` | 신중 공시에서 강세 문장만 추출 | stance-skew |
| `f6_*` | 부정된 span을 사실로 추출 | grounding 극성 반전 |
| `issuer_master.json` | 상장폐지 + $V 티커 재사용 | 생존편향, bi-temporal |

**의도적으로 "나쁜 추출"을 작성**했습니다(`fixtures/extractions/`). 편향 탐지기는 LLM 추출을
비-LLM 베이스라인과 대조해 잡으므로, 추출이 "정확"하면 탐지기가 발화하지 않아 시연이 빕니다 —
왜곡 추출이 시연의 핵심입니다.

---

## 실데이터로 전환하는 두 지점 (스왑 seam)

지금은 오프라인 합성이지만, 두 인터페이스만 교체하면 실데이터로 갑니다(나머지 불변):

- **LLM 추출** (`skg/extract/base.py`의 `LLMExtractor`): 지금은 `FixtureExtractor`(JSON).
  나중에 `AnthropicExtractor`가 동일 프로토콜로 **claude-opus-4-8** strict function-calling 호출.
- **저장소** (`skg/store/repository.py`의 `Repository`): 지금은 `SqliteRepository`. 모든 읽기가
  `as_of`를 받으므로 bi-temporal 계약이 인터페이스에 있습니다. 나중에 `PostgresRepository`(AGE)나
  Graphiti로 교체 — 리서치의 "열린 저장 spine 포크"를 코드 구조로 보존했습니다.

수집(크롤러)은 `skg/ingest.py`의 `SampleReader`를 DART/EDGAR/GDELT/커뮤니티 크롤러로 교체하면
됩니다. 같은 `Document` 계약(provenance + bi-temporal 스탬프)을 emit하면 끝.

---

## 의도적으로 미포함 (DEFERRED — 정직하게 명시)

두 적대적 검토의 #1 발견은 **과설계**였습니다(1~2명에게 연구팀급 부담 금지). 그래서 다음은
의도적으로 뺐습니다:

- **info-flow / 전이엔트로피 (리드랙)** — 사용자의 "신호 금지" 스탠스를 위반(FDR 통과 리드랙
  edge는 실질적 신호)하고, 일봉 데이터로는 검정력 부족. 실데이터 + 명시적 게이트 후에만.
- **군집화** (Leiden/BERTopic), **교차계열 NLI**, **full CIB(coordinated cluster)**, **entity-swap
  probe**, **실시간 LLM 호출**, 무거운 평가 장치(골드셋/심은-공시 감사/가격회귀).

이것들을 빼서 의존성이 `networkx + rapidfuzz + scipy`로 최소화됐습니다 — 의존성 목록이 곧 범위 결정입니다.

---

## 구조

```
run.py                  오케스트레이터 (ingest→prefilter→extract→resolve→store→analyze→export)
config.py               신뢰도 prior, 임계값, 데모 as-of 날짜 (단일 캘리브레이션 표)
skg/
  ingest.py             합성 코퍼스 reader
  prefilter.py          근접중복 collapse + origin-vs-amplifier
  extract/              LLMExtractor 프로토콜 + FixtureExtractor(오프라인)
  resolve.py            ID앵커 + rapidfuzz + abstain→provisional + naive 대조군
  store/                Repository 인터페이스 + SqliteRepository + graph_builder(networkx)
  analyze/              pagerank(신뢰도가중 PPR), detectors(4종), lexicon
  export/obsidian.py    분포 보존형 마크다운 vault
fixtures/               합성 데이터 + 의도적 왜곡 추출
tests/                  핵심 알고리즘 단위 테스트 (pytest)
research/               설계 근거 (두 리서치 + 적대적 검토)
```

테스트: `pip install pytest && pytest` (또는 `python -m pytest`).
