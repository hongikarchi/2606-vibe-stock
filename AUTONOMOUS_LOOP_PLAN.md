# 자율 개발 루프 알고리즘 (오늘 밤 ~ 내일 08:00)

> 목표: 무인으로 KR+US 지식그래프를 **개선**하되, 사람 감독 없는 master 자동배포에서
> **품질이 나빠진 걸 배포하는 일은 절대 없게**. 핵심 안전 모델 한 문장:
> **"객관적 non-regression 게이트가 존재하는 변경만 자동배포. 없으면 브랜치+아침 제안."**

## 0. 안전 모델 — 작업을 2개 클래스로 가른다

| | Class 1 (게이트 가능) | Class 2 (판단 의존) |
|---|---|---|
| 무엇 | 신선도(news→dedup→rebuild→reanalyze→export), 감사 재실행, 메트릭 계측 | lexicon/subtheme/stoplist 편집, **EDGAR 새 레이어** |
| 정답 판정 | "불변식이 성립" — 루프가 **객관 검증 가능** | "더 나아졌나" — 루프가 **검증 불가** (= 이번 세션 내내 사람에게 미룬 큐레이션 판단) |
| 처리 | **게이트 통과 시 master 자동 push·배포** | 측정만 자동, 수정은 **메트릭 개선 입증 시에만**. EDGAR는 baseline 자체가 없어 **브랜치+제안만** |

→ "전부 자동 push"는 **"객관 게이트를 통과한 전부 자동 push"**로 해석. 사람 리뷰를 대체하는 게
아니라, 자동 검증 가능한 것만 내보내는 것. EDGAR 새 surface는 회귀 대조 baseline이 없어 유일한 예외.

## 1. 게이트 스크립트 `verify_artifacts.py` (가장 가치 높은 산출물, 제일 먼저 작성)

종료코드 ≠0 이면 배포 차단. 다음 **전부** 성립해야 통과:

- **존재/규모**: 5개 아티팩트 파싱 OK; `graph.issuers ≥ 380`, `themes.nodes ≥ 50`,
  `emergent.terms ≥ 100`, `dashboard.{us,kr,hot,cold}` 비어있지 않음
- **retention (과잉제거 탐지)**: `SK하이닉스 ∈ graph`, 핵심 테마(반도체·인공지능·데이터센터·로봇·
  에너지) 전부 존재 — *제거만 보는 체크는 토픽 손실을 못 잡음*(emergent FAIL로 입증됨)
- **라벨==내용**: `meta.as_of == dashboard.as_of == run_date` AND `max(event_time) ≤ as_of`
- **오늘밤 그 버그**: `graph.issuers > 0` (= 해당 as_of에 AnalysisResult가 실제 존재)
- **pytest green**

→ **루프와 `run_pipeline.bat` 양쪽에 연결.** 현재 batch는 "데이터 바뀌면 커밋"만 하고 payload
검증이 0 → reanalyze가 실패하면 빈 graph가 cron으로도 나감. 이 스크립트가 "라벨≠내용 두 번
다시는 안 함"의 영속 형태.

## 2. baseline + 자동 롤백

- 루프 시작 시: last-good 스냅샷 = {SHA, 메트릭: stance_neut 77.2% / ai_bubble 1 / dc_build 5 /
  graph 400 / emergent 상위 hub 집합}
- 매 사이클 변경 후 재계측. 핵심 메트릭이 baseline 대비 **악화** → `git revert`로 last-good SHA
  복귀 → 재 push → 로그 크게 남김
- **배포 후 라이브 검증**: GitHub Pages에서 json 직접 fetch해 라벨·payload 재확인(오늘 수동으로
  한 걸 매 사이클 표준 마감으로). 라이브가 깨졌으면 즉시 롤백.

## 3. 수렴 / 진동 방지

- 우선순위 큐. **Class 2 변경은 사이클당 1개, 밤 전체 상한**(예: 최대 4개)
- 각 변경은 **커밋된 상태 기준**으로 측정 — 타깃 메트릭을 *엄격히* 개선하고 다른 메트릭 회귀
  없을 때만 keep. 아니면 폐기
- loop-until-dry: 게이트 통과 변경이 없는 사이클 → 큐 다음으로 or idle. (lexicon이 앞뒤로 churn하는 것 방지)

## 4. 운영 위험 (무인 master-push에서 반드시 터지는 것)

- **⚠️ cron 충돌 (최우선)**: `\StockKG\refresh-08/14/20` 작업이 **활성(Ready)**.
  **refresh-20(오늘 20:00)·refresh-08(내일 08:00)이 루프와 동시에 Neo4j 쓰기+master push →
  레이스/non-fast-forward**. → **밤 동안 이 작업들 일시정지**(`Disable-ScheduledTask`),
  08:00 직전 루프 종료하며 **재활성화**. (또는 둘 다 지키는 lockfile, 단 batch도 수정 필요라 일시정지가 단순)
- **push 거부**: non-fast-forward는 `pull --rebase → 재검증 → 재push`. **blind force 금지.**
- **Neo4j/Docker off**: batch처럼 컨테이너 체크, 없으면 그 사이클 skip(중단 아님)

## 5. 케이던스 & 복구

- `ScheduleWakeup`으로 진행 (sleeping bash loop 아님). 무거운 신선도 패스 ~2-3h마다,
  싼 회귀 tick 더 자주
- 매 사이클 큐 상태·진행을 핸드오프 메모리에 기록 → 밤중 크래시해도 복구 가능

## 6. 사이클 알고리즘 (의사코드)

```
[부팅 1회]
  StockKG refresh-08/14/20 Disable        # cron 충돌 차단
  write verify_artifacts.py               # 게이트
  baseline = snapshot(SHA, metrics)
  queue = [ freshness, regression_watch, quality_probes..., edgar_layer(branch-only) ]

[매 사이클 — ScheduleWakeup]
  if now >= 07:30: goto SHUTDOWN          # 08:00 전 안전 종료
  if Neo4j down: log+skip; reschedule
  git pull --rebase; if conflict→resolve or skip

  task = queue.next()
  if task.class == 1:                     # 신선도/계측/회귀
     run task (news_pull→dedup→build*→reanalyze→export, 동일 SKG_AS_OF_NOW)
     if verify_artifacts.py FAIL → revert to last-good SHA, push, log; continue
     metrics_now = measure()
     if regressed vs baseline → revert, push, log
     else → commit+push; live-fetch verify; baseline=metrics_now
  elif task.class == 2 (quality):         # lexicon/subtheme/stoplist, 1개씩
     apply ONE change
     rebuild affected + verify_artifacts.py
     keep ONLY if target metric strictly↑ AND no other regression; else discard
     if kept → commit+push; live verify
  elif task == edgar_layer:               # baseline 없음 = 자동검증 불가
     work on BRANCH only; write measured proposal for 08:00; never push to master

  ScheduleWakeup(next, write progress→memory)

[SHUTDOWN ~07:30-08:00]
  final live-fetch verify of master
  StockKG refresh-08/14/20 Re-enable      # cron 복원 (08:00 정시 정상 동작)
  write wrap-up→memory + summary for user
```

## 7. 큐 초기 내용 (감사 잔여 기준, 우선순위순)

1. **freshness** (Class1) — news_pull+kr → dedup → rebuild → reanalyze → export. 매 무거운 패스.
2. **regression_watch** (Class1) — 핵심 메트릭 재계측, baseline 대비 드리프트 감지. 매 싼 tick.
3. **quality: stance 오류율** (Class2) — KR neut 비율 더 내릴 정밀-안전 토큰 1개씩, 입증 시만.
4. **quality: emergent 잔여 generic** (Class2) — 기반/기술/나선다 등, 정밀도 편향으로 신중히.
5. **quality: 테마 오배정 잔여** (Class2) — subtheme bare 키워드 추가 정리.
6. **edgar_layer** (BRANCH ONLY) — supplies/competes 엣지를 graph.json에 실어보기. baseline 없어
   자동검증 불가 → 측정된 제안만, master 미반영.

## 제외 (루프가 절대 안 건드림)
- bi-temporal 마이그레이션 (lossy+비가역, 사용자 결정 대기 — `DECISION_bitemporal.md`)
- emergent PMI 랭킹 ("더 나은가" 사람 눈 필요)
- 스키마/destructive 작업, 보존정책 prune

---
*이건 계획서입니다. 승인하시면 §1 게이트 스크립트부터 구현 → cron 일시정지 → 루프 시작.*
